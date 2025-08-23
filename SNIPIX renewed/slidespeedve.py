#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SNIPIX – Video Editor (Regenerated)
Changes from prior version:
 - Replaced "Change Speed…" dialog button with an inline speed slider + apply button.
 - Refined Export group: choose format (mp4/mkv), preset, CRF, audio encoding toggle, and Export button.
 - Maintains existing features: Open, Save As, Trim, Add Text Overlay, Rotate, Remove Audio, Generate captions (Whisper optional), Undo/Redo, Reset.
 - FFmpeg operations run in background threads; UI receives completion events.

Requirements:
 - Python 3.10+
 - PyQt6
 - FFmpeg on PATH
 - (Optional) whisper for auto captions: `pip install openai-whisper`

Run:
    python SNIPIX_regen_speed_slider_export_refined.py

"""
from __future__ import annotations

import os
import sys
import shutil
import tempfile
import threading
import subprocess
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, QEvent, QUrl
from PyQt6.QtGui import QIcon, QKeySequence, QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSlider, QGroupBox, QFormLayout, QFileDialog, QInputDialog, QMessageBox, QComboBox,
    QSpinBox, QCheckBox
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

# Optional whisper (for captions); keep optional
try:
    import whisper
except Exception:
    whisper = None


class OpCompleteEvent(QEvent):
    TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, ok: bool, msg: str, out_path: str | None = None):
        super().__init__(OpCompleteEvent.TYPE)
        self.ok = ok
        self.msg = msg
        self.out_path = out_path


class VideoEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SNIPIX – Video Editor")
        self.resize(1200, 800)

        # Styling (kept simple and consistent)
        self.COLOR_BG = "#e5f0fd"
        self.COLOR_SURF = "#ffffff"
        self.COLOR_ACCENT = "#cab4f5"
        self.COLOR_TEXT = "#111827"
        self.COLOR_MUTED = "#e5e7eb"

        self.setStyleSheet(f"""
            QMainWindow {{ background: {self.COLOR_BG}; }}
            QGroupBox {{ color: {self.COLOR_TEXT}; background: {self.COLOR_SURF}; border: 1px solid {self.COLOR_MUTED}; border-radius: 10px; margin-top: 12px; }}
            QPushButton {{ background: {self.COLOR_ACCENT}; color: black; border: none; padding: 8px 10px; border-radius: 8px; }}
            QPushButton:disabled {{ background: #cbd5e1; color: #6b7280; }}
            QSlider::groove:horizontal {{ height: 6px; background: {self.COLOR_MUTED}; border-radius: 3px; }}
            QSlider::handle:horizontal {{ width: 16px; background: {self.COLOR_ACCENT}; border-radius: 8px; margin: -6px 0; }}
        """)

        # state
        self.temp_dir = tempfile.mkdtemp(prefix="snipix_edit_")
        self.original_path: str | None = None
        self.current_path: str | None = None
        self.history: list[str] = []
        self.redo_stack: list[str] = []
        self.is_processing = False
        self.last_fontfile: str | None = None

        # media
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.positionChanged.connect(self._on_position_changed)
        self.media_player.durationChanged.connect(self._on_duration_changed)
        self.media_player.playbackStateChanged.connect(self._on_playback_changed)

        # layout
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        root.addLayout(self._build_left_panel(), 1)
        root.addWidget(self._build_canvas(), 4)
        root.addLayout(self._build_right_panel(), 1)

        self.status = self.statusBar()
        self._status("Ready")

        self._build_menubar()

        # guard timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._player_guard)
        self.timer.start(100)

    # ---------------- UI builders ---------------------------------------------
    def _build_left_panel(self):
        left = QVBoxLayout()
        left.setSpacing(12)

        file_group = QGroupBox("File")
        fg = QVBoxLayout()
        self.btn_open = QPushButton("Open Video")
        self.btn_open.clicked.connect(self.open_video)
        fg.addWidget(self.btn_open)
        self.btn_save_as = QPushButton("Save As…")
        self.btn_save_as.clicked.connect(self.save_as)
        fg.addWidget(self.btn_save_as)
        file_group.setLayout(fg)
        left.addWidget(file_group)

        ops_group = QGroupBox("Basic Operations")
        of = QFormLayout()

        # Trim
        self.btn_trim = QPushButton("Trim…")
        self.btn_trim.clicked.connect(self.trim_video)
        of.addRow(self.btn_trim)

        # Speed slider (replaces old dialog button)
        speed_container = QWidget()
        sc_layout = QHBoxLayout(speed_container)
        sc_layout.setContentsMargins(0, 0, 0, 0)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(25, 400)  # 0.25x .. 4.00x
        self.speed_slider.setValue(100)
        self.speed_slider.setSingleStep(5)
        self.speed_label = QLabel("Speed: 1.00x")
        self.btn_apply_speed = QPushButton("Apply Speed")
        self.btn_apply_speed.clicked.connect(self.apply_speed_from_slider)
        sc_layout.addWidget(self.speed_slider)
        sc_layout.addWidget(self.speed_label)
        sc_layout.addWidget(self.btn_apply_speed)
        of.addRow("Speed:", speed_container)

        # Add text overlay
        self.btn_add_text = QPushButton("Add Text Overlay…")
        self.btn_add_text.clicked.connect(self.add_text_overlay)
        of.addRow(self.btn_add_text)

        # Rotate
        self.btn_rotate = QPushButton("Rotate 90° CW")
        self.btn_rotate.clicked.connect(lambda: self.rotate_video(transpose=1))
        of.addRow(self.btn_rotate)

        ops_group.setLayout(of)
        left.addWidget(ops_group)

        edit_group = QGroupBox("Edit")
        ef = QVBoxLayout()
        self.btn_undo = QPushButton("Undo")
        self.btn_undo.clicked.connect(self.undo)
        ef.addWidget(self.btn_undo)
        self.btn_redo = QPushButton("Redo")
        self.btn_redo.clicked.connect(self.redo)
        ef.addWidget(self.btn_redo)
        self.btn_reset = QPushButton("Reset")
        self.btn_reset.clicked.connect(self.reset_to_original)
        ef.addWidget(self.btn_reset)
        edit_group.setLayout(ef)
        left.addWidget(edit_group)

        left.addStretch()
        # connect slider live preview
        self.speed_slider.valueChanged.connect(self._on_speed_slider_change)
        return left

    def _build_right_panel(self):
        right = QVBoxLayout()
        right.setSpacing(12)

        adv_group = QGroupBox("Advanced Ops")
        af = QFormLayout()
        self.btn_remove_audio = QPushButton("Remove Audio")
        self.btn_remove_audio.clicked.connect(self.remove_audio)
        af.addRow(self.btn_remove_audio)
        self.btn_captions = QPushButton("Generate English Captions")
        self.btn_captions.clicked.connect(self.generate_and_burn_captions)
        af.addRow(self.btn_captions)
        adv_group.setLayout(af)
        right.addWidget(adv_group)

        export_group = QGroupBox("Export")
        ef = QFormLayout()

        self.export_format = QComboBox(); self.export_format.addItems(["mp4", "mkv", "mov"])
        ef.addRow("Format:", self.export_format)

        self.export_preset = QComboBox(); self.export_preset.addItems(["ultrafast","superfast","veryfast","faster","fast","medium","slow"]) 
        self.export_preset.setCurrentText("medium")
        ef.addRow("Preset:", self.export_preset)

        self.export_crf = QSpinBox(); self.export_crf.setRange(0, 51); self.export_crf.setValue(18)
        ef.addRow("CRF (lower = better quality):", self.export_crf)

        self.export_audio_copy = QCheckBox("Copy audio (no re-encode)"); self.export_audio_copy.setChecked(False)
        ef.addRow(self.export_audio_copy)

        self.btn_export = QPushButton("Export…")
        self.btn_export.clicked.connect(self.export_dialog)
        ef.addRow(self.btn_export)

        export_group.setLayout(ef)
        right.addWidget(export_group)

        right.addStretch()
        return right

    def _build_canvas(self):
        container = QWidget()
        vbox = QVBoxLayout(container)
        self.video_widget = QVideoWidget()
        self.media_player.setVideoOutput(self.video_widget)
        vbox.addWidget(self.video_widget, 1)

        bar = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.toggle_play)
        bar.addWidget(self.play_btn)

        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.sliderMoved.connect(self._on_seek_slider)
        bar.addWidget(self.seek, 1)

        self.time_label = QLabel("00:00 / 00:00")
        bar.addWidget(self.time_label)
        vbox.addLayout(bar)
        return container

    def _build_menubar(self):
        menubar = self.menuBar()
        m_file = menubar.addMenu("&File")
        act_open = QAction("Open…", self); act_open.triggered.connect(self.open_video)
        act_save = QAction("Save As…", self); act_save.triggered.connect(self.save_as)
        act_export = QAction("Export…", self); act_export.triggered.connect(self.export_dialog)
        act_exit = QAction("Exit", self); act_exit.triggered.connect(self.close)
        for a in (act_open, act_save, act_export): m_file.addAction(a)
        m_file.addSeparator(); m_file.addAction(act_exit)

        m_edit = menubar.addMenu("&Edit")
        act_undo = QAction("Undo", self); act_undo.triggered.connect(self.undo)
        act_redo = QAction("Redo", self); act_redo.triggered.connect(self.redo)
        act_reset = QAction("Reset", self); act_reset.triggered.connect(self.reset_to_original)
        for a in (act_undo, act_redo, act_reset): m_edit.addAction(a)

    # ---------------- Status / Events ----------------------------------------
    def _status(self, msg: str, ms: int = 4000):
        self.status.showMessage(msg, ms)

    def customEvent(self, event):
        if isinstance(event, OpCompleteEvent):
            self.is_processing = False
            if event.ok and event.out_path:
                self._push_history(event.out_path)
                self._load_into_player(event.out_path, autoplay=True)
                self._status(event.msg)
            else:
                QMessageBox.critical(self, "Operation Failed", event.msg)
                self._status("Ready")

    # ---------------- Player controls ---------------------------------------
    @staticmethod
    def _fmt_time(ms: int) -> str:
        t = max(0, ms // 1000)
        m = int(t // 60); s = int(t % 60)
        return f"{m:02d}:{s:02d}"

    def _on_position_changed(self, pos: int):
        if not self.seek.isSliderDown():
            self.seek.setValue(pos)
        self._update_time_label()

    def _on_duration_changed(self, dur: int):
        self.seek.setRange(0, dur)
        self._update_time_label()

    def _on_playback_changed(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setText("Pause")
        else:
            self.play_btn.setText("Play")

    def _update_time_label(self):
        self.time_label.setText(f"{self._fmt_time(self.media_player.position())} / {self._fmt_time(self.media_player.duration())}")

    def toggle_play(self):
        if not self.current_path:
            return
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
        else:
            self.media_player.play()

    def _on_seek_slider(self, value: int):
        if not self.current_path: return
        self.media_player.setPosition(value)
        self._update_time_label()

    def _player_guard(self):
        if self.is_processing:
            self.media_player.pause()

    def _load_into_player(self, path: str, autoplay: bool = False):
        self.current_path = path
        self.media_player.setSource(QUrl.fromLocalFile(path))
        if autoplay:
            self.media_player.play()

    # ---------------- History -----------------------------------------------
    def _reset_history(self):
        self.history.clear(); self.redo_stack.clear()

    def _push_history(self, new_path: str):
        self.history.append(new_path)
        if len(self.history) > 50:
            old = self.history.pop(0)
            try: os.remove(old)
            except Exception: pass
        self.redo_stack.clear()

    def undo(self):
        if len(self.history) <= 1:
            self._status("Nothing to undo")
            return
        last = self.history.pop(); self.redo_stack.append(last)
        prev = self.history[-1]; self._load_into_player(prev, autoplay=True); self._status("Undid last action")

    def redo(self):
        if not self.redo_stack:
            self._status("Nothing to redo"); return
        nxt = self.redo_stack.pop(); self.history.append(nxt); self._load_into_player(nxt, autoplay=True); self._status("Redid")

    def reset_to_original(self):
        if not self.original_path: return
        fresh = self._mk_working_copy(self.original_path)
        self._reset_history(); self._push_history(fresh); self._load_into_player(fresh, autoplay=True); self._status("Reset to original")

    # ---------------- File I/O ------------------------------------------------
    def open_video(self):
        if self.is_processing:
            QMessageBox.warning(self, "Please wait", "Another operation is running."); return
        path, _ = QFileDialog.getOpenFileName(self, "Open Video", "", "Video Files (*.mp4 *.mov *.mkv *.avi *.wmv *.flv)")
        if not path: return
        if not os.path.exists(path): QMessageBox.critical(self, "Error", "File does not exist."); return
        self.original_path = path
        working = self._mk_working_copy(path)
        self._reset_history(); self._push_history(working); self._load_into_player(working, autoplay=True); self._status(f"Loaded: {os.path.basename(path)}")

    def save_as(self):
        if not self.current_path: QMessageBox.warning(self, "No video", "Open a video first."); return
        default = f"edited_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        out, _ = QFileDialog.getSaveFileName(self, "Save As", default, "MP4 (*.mp4);;All Files (*.*)")
        if not out: return
        try: shutil.copy2(self.current_path, out); self._status(f"Saved: {os.path.basename(out)}")
        except Exception as ex: QMessageBox.critical(self, "Save Failed", str(ex))

    def export_dialog(self):
        if not self.current_path: QMessageBox.warning(self, "No video", "Open a video first."); return
        ext = self.export_format.currentText()
        default = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
        out, _ = QFileDialog.getSaveFileName(self, "Export", default, f"{ext.upper()} (*.{ext});;All Files (*.*)")
        if not out: return
        # Build ffmpeg args per export settings
        args = ["-y", "-i", self.current_path]
        args += ["-c:v", "libx264", "-preset", self.export_preset.currentText(), "-crf", str(self.export_crf.value())]
        if self.export_audio_copy.isChecked():
            args += ["-c:a", "copy"]
        else:
            args += ["-c:a", "aac", "-b:a", "192k"]
        args += [out]
        self._run_ffmpeg_async(args, success_msg=f"Exported: {os.path.basename(out)}", final_out=out)

    def closeEvent(self, event):
        try:
            if os.path.isdir(self.temp_dir): shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass
        super().closeEvent(event)

    # ---------------- Operations (FFmpeg) ------------------------------------
    def trim_video(self):
        if not self.current_path: QMessageBox.warning(self, "No video", "Open a video first."); return
        start, ok = QInputDialog.getDouble(self, "Trim", "Start time (seconds):", 0.0, 0.0, 10**7, 2)
        if not ok: return
        end, ok = QInputDialog.getDouble(self, "Trim", "End time (seconds):", start, start, 10**7, 2)
        if not ok: return
        if end <= start: QMessageBox.critical(self, "Invalid Range", "End must be greater than Start."); return
        out_file = self._temp_name("trim", "mp4")
        ff_try = ["-y", "-ss", f"{start}", "-to", f"{end}", "-i", self.current_path, "-c", "copy", out_file]

        def worker():
            ok1, err1 = self._run_ffmpeg_blocking(ff_try)
            if not ok1:
                ff_re = ["-y", "-ss", f"{start}", "-to", f"{end}", "-i", self.current_path,
                         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k", out_file]
                ok2, err2 = self._run_ffmpeg_blocking(ff_re)
                if not ok2:
                    self._post_event(False, f"Trim failed: {err2}"); return
            self._post_event(True, f"Trimmed {start:.2f}s → {end:.2f}s", out_file)

        self._start_worker(worker, "Trimming...")

    def _on_speed_slider_change(self, val: int):
        factor = max(0.25, min(4.0, val/100.0))
        self.speed_label.setText(f"Speed: {factor:.2f}x")
        # live preview playback rate change
        try:
            self.media_player.setPlaybackRate(factor)
        except Exception:
            pass

    def apply_speed_from_slider(self):
        if not self.current_path: QMessageBox.warning(self, "No video", "Open a video first."); return
        val = self.speed_slider.value(); factor = max(0.25, min(4.0, val/100.0))
        out_file = self._temp_name(f"speedx{factor}", "mp4")

        # Build atempo chain
        def atempo_chain(x: float) -> list[str]:
            parts = []
            rem = x
            while rem > 2.0 + 1e-9:
                parts.append("atempo=2.0"); rem /= 2.0
            while rem < 0.5 - 1e-9:
                parts.append("atempo=0.5"); rem *= 2.0
            parts.append(f"atempo={rem:.6f}")
            return parts

        vfilter = f"setpts={1.0/factor}*PTS"
        afilters = atempo_chain(factor)
        # combine audio filters
        a_filter_arg = ",".join(afilters)
        ff = ["-y", "-i", self.current_path, "-filter:v", vfilter, "-filter:a", a_filter_arg,
              "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k", out_file]
        self._run_ffmpeg_async(ff, success_msg=f"Speed x{factor}", final_out=out_file)

    def add_text_overlay(self):
        if not self.current_path: QMessageBox.warning(self, "No video", "Open a video first."); return
        text, ok = QInputDialog.getText(self, "Add Text", "Text to overlay:")
        if not ok or not text.strip(): return
        size, ok = QInputDialog.getInt(self, "Text Size", "Font size (px):", 48, 10, 200, 1)
        if not ok: return
        if self.last_fontfile is None:
            msg = QMessageBox.question(self, "Font File (Optional)",
                                       "FFmpeg drawtext may need a TTF font file on Windows. Select one now?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if msg == QMessageBox.StandardButton.Yes:
                fpath, _ = QFileDialog.getOpenFileName(self, "Choose Font (.ttf)", "", "Fonts (*.ttf *.otf);;All Files (*.*)")
                if fpath: self.last_fontfile = fpath

        out_file = self._temp_name("text", "mp4")
        safe_text = text.replace("'", "\\'")
        draw = "drawtext="
        if self.last_fontfile:
            draw += f"fontfile='{self.last_fontfile}':"
        draw += f"text='{safe_text}':fontsize={size}:fontcolor=white:shadowcolor=black:shadowx=2:shadowy=2:x=(w-text_w)/2:y=h-text_h-40"
        ff = ["-y", "-i", self.current_path, "-vf", draw, "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "copy", out_file]
        self._run_ffmpeg_async(ff, success_msg="Text overlay added", final_out=out_file)

    def rotate_video(self, transpose=1):
        if not self.current_path: QMessageBox.warning(self, "No video", "Open a video first."); return
        out_file = self._temp_name("rotate", "mp4")
        ff = ["-y", "-i", self.current_path, "-vf", f"transpose={transpose}", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "copy", out_file]
        self._run_ffmpeg_async(ff, success_msg="Rotated", final_out=out_file)

    def remove_audio(self):
        if not self.current_path: QMessageBox.warning(self, "No video", "Open a video first."); return
        out_file = self._temp_name("mute", "mp4")
        ff = ["-y", "-i", self.current_path, "-c:v", "copy", "-an", out_file]
        self._run_ffmpeg_async(ff, success_msg="Audio removed", final_out=out_file)

    def generate_and_burn_captions(self):
        if not self.current_path: QMessageBox.warning(self, "No video", "Open a video first."); return
        if whisper is None:
            QMessageBox.critical(self, "Whisper not installed", "Install Whisper: pip install openai-whisper"); return
        model_name = "tiny"
        wav_path = os.path.join(self.temp_dir, "audio_16k_mono.wav")
        srt_path = os.path.join(self.temp_dir, "captions.srt")
        out_file = self._temp_name("captioned", "mp4")

        def worker():
            ok_wav, err_wav = self._run_ffmpeg_blocking(["-y", "-i", self.current_path, "-vn", "-ac", "1", "-ar", "16000", wav_path])
            if not ok_wav: self._post_event(False, f"Audio extract failed: {err_wav}"); return
            try:
                model = whisper.load_model(model_name)
                result = model.transcribe(wav_path, language="en", task="transcribe", verbose=False)
            except Exception as ex:
                self._post_event(False, f"Whisper failed: {ex}"); return
            try:
                def srt_timestamp(t):
                    h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60); ms = int((t - int(t)) * 1000)
                    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
                lines = []
                idx = 1
                for seg in result.get("segments", []):
                    start = float(seg["start"]); end = float(seg["end"]); text = (seg.get("text") or "").strip()
                    if not text: continue
                    lines.append(f"{idx}")
                    lines.append(f"{srt_timestamp(start)} --> {srt_timestamp(end)}")
                    lines.append(text); lines.append(""); idx += 1
                if not lines: self._post_event(False, "No captions generated."); return
                with open(srt_path, "w", encoding="utf-8") as f: f.write("\n".join(lines))
            except Exception as ex:
                self._post_event(False, f"Failed to write SRT: {ex}"); return
            ff = ["-y", "-i", self.current_path, "-vf", f"subtitles='{srt_path}'", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k", out_file]
            ok_burn, err_burn = self._run_ffmpeg_blocking(ff)
            if not ok_burn: self._post_event(False, f"Burn captions failed: {err_burn}"); return
            self._post_event(True, "Captions generated & burned", out_file)

        self._start_worker(worker, "Generating captions...")

    # ---------------- FFmpeg plumbing ---------------------------------------
    @staticmethod
    def _which_ffmpeg() -> str | None:
        exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        for p in os.environ.get("PATH", "").split(os.pathsep):
            cand = os.path.join(p, exe)
            if os.path.isfile(cand): return exe
        return None

    def _run_ffmpeg_blocking(self, args: list[str]) -> tuple[bool, str]:
        ff = self._which_ffmpeg()
        if not ff: return False, "FFmpeg not found on PATH."
        try:
            proc = subprocess.run([ff] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            ok = proc.returncode == 0
            if not ok: return False, proc.stderr.strip() or "Unknown FFmpeg error"
            return True, ""
        except Exception as ex:
            return False, str(ex)

    def _run_ffmpeg_async(self, ff_args: list[str], success_msg: str, final_out: str):
        def worker():
            ok, err = self._run_ffmpeg_blocking(ff_args)
            if ok: self._post_event(True, success_msg, final_out)
            else: self._post_event(False, err)
        self._start_worker(worker, "Processing...")

    def _start_worker(self, target, busy_msg: str):
        if self.is_processing:
            QMessageBox.warning(self, "Please wait", "Another operation is running."); return
        self.is_processing = True; self._status(busy_msg, ms=0)
        t = threading.Thread(target=target, daemon=True); t.start()

    def _post_event(self, ok: bool, msg: str, out_path: str | None = None):
        QApplication.instance().postEvent(self, OpCompleteEvent(ok, msg, out_path))

    def _temp_name(self, tag: str, ext: str) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return os.path.join(self.temp_dir, f"{tag}_{ts}.{ext}")

    def _mk_working_copy(self, src: str) -> str:
        ext = os.path.splitext(src)[1].lstrip(".") or "mp4"
        dst = self._temp_name("working", ext)
        shutil.copy2(src, dst); return dst


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = VideoEditor(); win.show(); sys.exit(app.exec())
