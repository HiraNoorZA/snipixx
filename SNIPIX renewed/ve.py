#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SNIPIX — BASIC VIDEO EDITOR (Single File, Final-Year Friendly)
===============================================================

Sections (readable for defense):
1) Imports & Data Models
2) Utility: FFprobe/FFmpeg helpers, Undo/Redo (max 4/4)
3) Player & Timeline mapping
4) UI Construction (PyQt6) + Styling
5) Basic Editing: add/remove clips, trim, speed preview
6) Manual Text Overlay dialog (system font, color, position)
7) Captions (Advanced): Whisper once → segments → live preview overlay (QLabel)
8) Export: per-clip render (trim/speed + captions if any) → concat → final mp4

Notes
-----
• Smooth playback: QMediaPlayer + QAudioOutput + playbackRate = speed slider.
• All heavy work (ffmpeg/whisper) is threaded; UI stays responsive.
• Windows-safe subtitle burning (paths converted to POSIX with forward slashes).
• Undo/Redo bounded to 4 items each (most recent edits only).
• No external .tiff files; system font picker is used for manual overlay.

Requirements
------------
    pip install PyQt6
    # optional for captions
    pip install openai-whisper
Ensure `ffmpeg` and `ffprobe` are available on PATH.

Run
---
    python snipix_final_singlefile.py
"""
from __future__ import annotations

# 1) IMPORTS & DATA MODELS -----------------------------------------------------
import os
import sys
import json
import shutil
import tempfile
import threading
import subprocess
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, QTimer, QEvent
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QFormLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QSlider, QDoubleSpinBox,
    QFileDialog, QMessageBox, QGroupBox, QInputDialog, QFontDialog, QColorDialog,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

try:
    import whisper  # optional
except Exception:
    whisper = None


@dataclass
class CaptionSegment:
    start: float
    end: float
    text: str


@dataclass
class Clip:
    path: str
    duration: float = 0.0
    tin: float = 0.0
    tout: float = 0.0  # 0.0 means "use full duration"
    speed: float = 1.0
    # Manual Overlay
    text: str = ""
    font_family: str = ""
    font_size: int = 0
    color_rgb: tuple[int,int,int] | None = None
    pos: str = "bottom"  # 'bottom' or 'top'
    # Whisper captions (advanced)
    segments: list[CaptionSegment] = field(default_factory=list)

    # Derived helpers
    def end_effective(self) -> float:
        return self.tout if self.tout > 0 else self.duration

    def trimmed(self) -> float:
        return max(0.0, self.end_effective() - self.tin)

    def timeline(self) -> float:
        return self.trimmed() / max(1e-6, self.speed)


# 2) UTILITY: FFPROBE/FFMPEG, UNDO/REDO (MAX 4/4) -----------------------------
class UndoStack:
    def __init__(self, limit:int=4):
        self.limit = limit
        self.undo:list[str] = []
        self.redo:list[str] = []

    def snapshot(self, clips:list[Clip]):
        # store as json for deep copy
        data = [asdict(c) | {"segments":[asdict(s) for s in c.segments]} for c in clips]
        dump = json.dumps(data)
        self.undo.append(dump)
        if len(self.undo) > self.limit:
            self.undo.pop(0)
        self.redo.clear()

    def can_undo(self)->bool: return len(self.undo) > 0
    def can_redo(self)->bool: return len(self.redo) > 0

    def do_undo(self, current:list[Clip]) -> list[Clip] | None:
        if not self.undo: return None
        cur_dump = json.dumps([asdict(c) | {"segments":[asdict(s) for s in c.segments]} for c in current])
        self.redo.append(cur_dump)
        if len(self.redo) > self.limit:
            self.redo.pop(0)
        dump = self.undo.pop()
        return self._restore(dump)

    def do_redo(self, current:list[Clip]) -> list[Clip] | None:
        if not self.redo: return None
        cur_dump = json.dumps([asdict(c) | {"segments":[asdict(s) for s in c.segments]} for c in current])
        self.undo.append(cur_dump)
        if len(self.undo) > self.limit:
            self.undo.pop(0)
        dump = self.redo.pop()
        return self._restore(dump)

    def _restore(self, dump:str) -> list[Clip]:
        arr = json.loads(dump)
        clips: list[Clip] = []
        for d in arr:
            segs = [CaptionSegment(**s) for s in d.pop("segments", [])]
            clips.append(Clip(**d, segments=segs))
        return clips


def run_cmd(args:list[str]) -> tuple[bool,str]:
    """Run a subprocess, return (ok, stderr/head)."""
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if p.returncode == 0:
            return True, p.stderr
        return False, (p.stderr or p.stdout)
    except Exception as e:
        return False, str(e)


def ffprobe_duration(path:str) -> float:
    ffprobe = "ffprobe.exe" if os.name=='nt' else "ffprobe"
    ok, out = run_cmd([ffprobe, "-v","error", "-show_entries","format=duration", "-of","default=noprint_wrappers=1:nokey=1", path])
    try:
        if ok: return float(out.strip().splitlines()[-1])
    except Exception:
        pass
    return 0.0


def ffmpeg(args:list[str]) -> tuple[bool,str]:
    """Wrapper with safe flags for timestamps and Windows binary name."""
    ff = "ffmpeg.exe" if os.name=='nt' else "ffmpeg"
    base = [ff, "-fflags","+genpts","-avoid_negative_ts","make_zero"]
    return run_cmd(base + args)


# 3) PLAYER & TIMELINE MAPPING -------------------------------------------------
class TimelineMapper:
    @staticmethod
    def tl_total(clips:list[Clip]) -> int:
        return int(sum(c.timeline() for c in clips) * 1000)

    @staticmethod
    def tl_to_clip(clips:list[Clip], ms:int) -> tuple[int,float]:
        t = ms/1000.0
        acc = 0.0
        for i,c in enumerate(clips):
            dur = c.timeline()
            if t <= acc + dur + 1e-9:
                # within clip i
                sec = (t - acc) * c.speed + c.tin
                return i, max(0.0, sec)
            acc += dur
        return -1, 0.0

    @staticmethod
    def clip_to_tl(clips:list[Clip], idx:int, sec:float) -> int:
        acc = 0.0
        for i,c in enumerate(clips):
            if i == idx:
                return int((acc + (sec - c.tin)/max(1e-6,c.speed)) * 1000)
            acc += c.timeline()
        return 0


# 4) UI CONSTRUCTION (PyQt6) + STYLING ----------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SNIPIX – Video Editor (MVP + Captions)")
        self.resize(1200, 760)
        self.temp_dir = tempfile.mkdtemp(prefix="snipix_")
        self.clips: list[Clip] = []
        self.current = -1
        self.undo = UndoStack(limit=4)
        self.busy = False

        # Media
        self.player = QMediaPlayer()
        self.audio = QAudioOutput(); self.player.setAudioOutput(self.audio)
        self.video = QVideoWidget(); self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(lambda _: self._sync_time_label())

        # Build UI
        self._build_ui()
        self._style()

        # Overlay label for captions/overlay text
        self.overlay = QLabel(self.video)
        self.overlay.setStyleSheet("color:white; background:rgba(0,0,0,140); padding:6px; border-radius:8px;")
        self.overlay.setWordWrap(True)
        self.overlay.hide()

        # Timer to sync overlay
        self.timer = QTimer(self); self.timer.setInterval(120); self.timer.timeout.connect(self._sync_overlay)
        self.timer.start()

        # Captions availability
        if whisper is None:
            self.btn_gen_caps.setEnabled(False)
            self.btn_gen_caps.setToolTip("Install openai-whisper to enable")

    def _style(self):
        self.setStyleSheet(
            """
            QWidget { background:#eef6ff; font-family: Segoe UI, Arial; }
            QGroupBox { background:white; border:1px solid #e6eef9; border-radius:10px; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
            QPushButton { background:#d9b8ff; border:none; padding:8px 10px; border-radius:10px; }
            QPushButton:disabled { background:#ddd; }
            QListWidget { background:white; border:1px solid #dde7fb; border-radius:8px; }
            QSlider::groove:horizontal { height:6px; background:#e5dafb; border-radius:3px; }
            QSlider::handle:horizontal { background:#c6a7ff; width:16px; border-radius:8px; margin:-6px 0; }
            QLabel { color:#111; }
            """
        )

    def _build_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        h = QHBoxLayout(root); h.setContentsMargins(12,12,12,12); h.setSpacing(12)

        # Left – Clips & Edit
        left = QVBoxLayout()
        g1 = QGroupBox("Clips"); v1 = QVBoxLayout()
        self.btn_add = QPushButton("Add Clips…"); self.btn_add.clicked.connect(self.add_clips)
        self.btn_rm = QPushButton("Remove Clip"); self.btn_rm.clicked.connect(self.remove_clip)
        v1.addWidget(self.btn_add); v1.addWidget(self.btn_rm)
        self.list = QListWidget(); self.list.currentRowChanged.connect(self._on_select)
        v1.addWidget(self.list)
        g1.setLayout(v1); left.addWidget(g1)

        g2 = QGroupBox("Clip Settings"); f2 = QFormLayout()
        self.in_sp = QDoubleSpinBox(); self.in_sp.setDecimals(3); self.in_sp.setRange(0, 1e7)
        self.out_sp = QDoubleSpinBox(); self.out_sp.setDecimals(3); self.out_sp.setRange(0, 1e7)
        self.speed_sp = QDoubleSpinBox(); self.speed_sp.setRange(0.25, 4.0); self.speed_sp.setSingleStep(0.05); self.speed_sp.setValue(1.0)
        f2.addRow("In (s):", self.in_sp)
        f2.addRow("Out (s):", self.out_sp)
        f2.addRow("Speed:", self.speed_sp)
        self.btn_apply_clip = QPushButton("Apply Changes"); self.btn_apply_clip.clicked.connect(self.apply_changes)
        f2.addRow(self.btn_apply_clip)
        g2.setLayout(f2); left.addWidget(g2)

        g3 = QGroupBox("Manual Text Overlay"); v3 = QVBoxLayout()
        self.btn_text = QPushButton("Add / Edit Text…"); self.btn_text.clicked.connect(self.edit_text_overlay)
        v3.addWidget(self.btn_text)
        g3.setLayout(v3); left.addWidget(g3)

        # Undo/Redo
        g4 = QGroupBox("History (Undo/Redo up to 4)"); v4 = QHBoxLayout()
        self.btn_undo = QPushButton("Undo"); self.btn_undo.clicked.connect(self.on_undo)
        self.btn_redo = QPushButton("Redo"); self.btn_redo.clicked.connect(self.on_redo)
        v4.addWidget(self.btn_undo); v4.addWidget(self.btn_redo)
        g4.setLayout(v4); left.addWidget(g4)

        left.addStretch()
        h.addLayout(left, 1)

        # Center – Video + Transport
        center = QVBoxLayout()
        center.addWidget(self.video, 1)

        tbar = QHBoxLayout()
        self.btn_play = QPushButton("Play"); self.btn_play.clicked.connect(self.toggle_play)
        tbar.addWidget(self.btn_play)
        self.timeline = QSlider(Qt.Orientation.Horizontal); self.timeline.setRange(0,0)
        self.timeline.sliderMoved.connect(self.on_timeline_seek)
        tbar.addWidget(self.timeline, 1)
        self.lbl_time = QLabel("00:00 / 00:00"); tbar.addWidget(self.lbl_time)
        center.addLayout(tbar)

        srow = QHBoxLayout()
        srow.addWidget(QLabel("Preview Speed:"))
        self.speed_slider = QSlider(Qt.Orientation.Horizontal); self.speed_slider.setRange(25,400); self.speed_slider.setValue(100)
        self.speed_slider.valueChanged.connect(self.on_speed_change)
        srow.addWidget(self.speed_slider, 1)
        self.lbl_speed = QLabel("1.00x"); srow.addWidget(self.lbl_speed)
        center.addLayout(srow)

        h.addLayout(center, 3)

        # Right – Captions/Export
        right = QVBoxLayout()
        g5 = QGroupBox("Captions (Advanced)"); v5 = QVBoxLayout()
        self.btn_gen_caps = QPushButton("Generate Captions (Whisper)"); self.btn_gen_caps.clicked.connect(self.gen_caps)
        v5.addWidget(self.btn_gen_caps)
        self.btn_burn_clip = QPushButton("Export Current Clip + Captions"); self.btn_burn_clip.clicked.connect(self.export_current_with_captions)
        v5.addWidget(self.btn_burn_clip)
        g5.setLayout(v5); right.addWidget(g5)

        g6 = QGroupBox("Export Final"); f6 = QFormLayout()
        self.btn_export = QPushButton("Export All Clips…")
        self.btn_export.clicked.connect(self.export_all)
        f6.addRow(self.btn_export)
        g6.setLayout(f6); right.addWidget(g6)

        right.addStretch(); h.addLayout(right, 1)

        self.statusBar().showMessage("Ready")

    # 5) BASIC EDITING ---------------------------------------------------------
    def add_clips(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select clips", "", "Video Files (*.mp4 *.mov *.mkv *.avi)")
        if not files: return
        self.undo.snapshot(self.clips)
        for f in files:
            dur = ffprobe_duration(f)
            self.clips.append(Clip(path=f, duration=dur))
            self.list.addItem(QListWidgetItem(Path(f).name))
        if self.current == -1 and self.clips:
            self.list.setCurrentRow(0)
        self._rebuild_timeline()

    def remove_clip(self):
        idx = self.list.currentRow()
        if idx < 0: return
        self.undo.snapshot(self.clips)
        self.clips.pop(idx)
        self.list.takeItem(idx)
        self.current = -1 if not self.clips else min(idx, len(self.clips)-1)
        if self.current >= 0:
            self.list.setCurrentRow(self.current)
        else:
            self.player.stop(); self.timeline.setRange(0,0)
        self._rebuild_timeline()

    def _on_select(self, idx:int):
        if idx < 0 or idx >= len(self.clips):
            self.current = -1; return
        self.current = idx
        c = self.clips[idx]
        self.in_sp.setValue(c.tin); self.out_sp.setValue(c.tout); self.speed_sp.setValue(c.speed)
        self._load_clip(c.path, int(c.tin*1000))

    def apply_changes(self):
        if self.current < 0: return
        self.undo.snapshot(self.clips)
        c = self.clips[self.current]
        c.tin = float(self.in_sp.value()); c.tout = float(self.out_sp.value()); c.speed = float(self.speed_sp.value())
        self.list.item(self.current).setText(f"{Path(c.path).name} [{c.tin:.2f}-{(c.tout if c.tout>0 else c.duration):.2f}] @{c.speed:.2f}x")
        self._rebuild_timeline()

    def on_speed_change(self, val:int):
        f = max(0.25, min(4.0, val/100.0))
        self.lbl_speed.setText(f"{f:.2f}x")
        try:
            self.player.setPlaybackRate(f)  # smooth preview speed
        except Exception:
            pass

    # 6) MANUAL TEXT OVERLAY ---------------------------------------------------
    def edit_text_overlay(self):
        if self.current < 0: return
        c = self.clips[self.current]
        text, ok = QInputDialog.getText(self, "Text overlay", "Text:", text=c.text)
        if not ok: return
        font, ok = QFontDialog.getFont(QFont(c.font_family or 'Arial', c.font_size or 32), self)
        if not ok: return
        color = QColorDialog.getColor(QColor(*(c.color_rgb or (255,255,255))), self)
        if not color.isValid(): return
        pos, ok = QInputDialog.getItem(self, "Position", "Position:", ["bottom","top"], 0 if c.pos!="top" else 1, False)
        if not ok: return
        self.undo.snapshot(self.clips)
        c.text = text
        c.font_family, c.font_size = font.family(), font.pointSize()
        c.color_rgb = (color.red(), color.green(), color.blue())
        c.pos = pos
        self.statusBar().showMessage("Manual overlay saved", 3000)

    # 7) CAPTIONS (ADVANCED) ---------------------------------------------------
    def gen_caps(self):
        if whisper is None:
            QMessageBox.information(self, "Whisper not installed", "Run: pip install openai-whisper"); return
        if self.current < 0: return
        c = self.clips[self.current]
        tmp_wav = os.path.join(self.temp_dir, f"aud_{datetime.now().strftime('%H%M%S')}.wav")

        def worker():
            # Extract audio (respect trim if set)
            vf = []
            if c.tin>0 or c.tout>0:
                if c.tout>0: afr = ["-ss", str(c.tin), "-to", str(c.tout)]
                else: afr = ["-ss", str(c.tin)]
            else:
                afr = []
            ok, err = ffmpeg(["-y", *([*afr] if afr else []), "-i", c.path, "-vn", "-ac", "1", "-ar", "16000", tmp_wav])
            if not ok:
                self._notify(False, f"Audio extract failed: {err[:400]}"); return
            try:
                model = whisper.load_model("tiny")
                res = model.transcribe(tmp_wav, language="en")
                segs = [CaptionSegment(float(s['start']), float(s['end']), s.get('text','').strip()) for s in res.get('segments',[])]
                self.clips[self.current].segments = segs
                self._notify(True, f"Generated {len(segs)} segments")
            except Exception as e:
                self._notify(False, f"Whisper error: {e}")

        self._thread(worker, "Generating captions…")

    def _sync_overlay(self):
        # manual overlay has higher priority, else show current caption segment
        if self.current < 0 or not self.clips: return
        c = self.clips[self.current]
        # Manual overlay
        if c.text:
            self.overlay.setText(c.text)
            self.overlay.setFont(QFont(c.font_family or 'Arial', c.font_size or 32))
            r,g,b = c.color_rgb or (255,255,255)
            self.overlay.setStyleSheet(f"color: rgb({r},{g},{b}); background: rgba(0,0,0,140); padding:6px; border-radius:8px;")
            self._place_overlay(c.pos)
            self.overlay.show(); return
        # Auto captions
        pos_s = self.player.position()/1000.0
        for s in c.segments:
            if s.start <= pos_s <= s.end:
                self.overlay.setText(s.text)
                self.overlay.setFont(QFont('Segoe UI', 28))
                self.overlay.setStyleSheet("color:white; background:rgba(0,0,0,140); padding:6px; border-radius:8px;")
                self._place_overlay('bottom')
                self.overlay.show(); return
        self.overlay.hide()

    def _place_overlay(self, where:str):
        g = self.video.geometry(); self.overlay.adjustSize()
        w,h = self.overlay.width(), self.overlay.height()
        x = (g.width()-w)//2
        y = 10 if where == 'top' else g.height()-h-28
        self.overlay.move(x,y)

    # 8) EXPORT ---------------------------------------------------------------
    def export_current_with_captions(self):
        if self.current < 0: return
        c = self.clips[self.current]
        out, _ = QFileDialog.getSaveFileName(self, "Export clip", f"clip_{Path(c.path).stem}_{datetime.now().strftime('%H%M%S')}.mp4")
        if not out: return

        def worker():
            # Build filters for trim/speed
            vf = []
            af = []
            if c.tin>0 or c.tout>0:
                if c.tout>0:
                    vf += [f"trim=start={c.tin}:end={c.tout}", "setpts=PTS-STARTPTS"]
                    af += [f"atrim=start={c.tin}:end={c.tout}", "asetpts=PTS-STARTPTS"]
                else:
                    vf += [f"trim=start={c.tin}", "setpts=PTS-STARTPTS"]
                    af += [f"atrim=start={c.tin}", "asetpts=PTS-STARTPTS"]
            if abs(c.speed-1.0) > 1e-6:
                vf += [f"setpts={1.0/c.speed}*PTS"]
                rem = c.speed
                while rem>2.0: af.append("atempo=2.0"); rem/=2.0
                while rem<0.5: af.append("atempo=0.5"); rem*=2.0
                af.append(f"atempo={rem:.6f}")
            vf_str = ",".join(vf) if vf else "null"
            af_str = ",".join(af) if af else "anull"

            # If captions exist, write SRT and burn
            extra = []
            if c.segments:
                srt = os.path.join(self.temp_dir, "cap.srt")
                with open(srt,'w',encoding='utf-8') as f:
                    for i,s in enumerate(c.segments,1):
                        def ts(t):
                            h=int(t//3600); m=int((t%3600)//60); ss=int(t%60); ms=int((t-int(t))*1000)
                            return f"{h:02d}:{m:02d}:{ss:02d},{ms:03d}"
                        f.write(f"{i}\n{ts(s.start)} --> {ts(s.end)}\n{s.text}\n\n")
                srt_posix = Path(srt).as_posix()
                vf_str = f"{vf_str},{'subtitles=\''+srt_posix+'\'' if vf_str!='null' else 'subtitles=\''+srt_posix+'\''}"

            ok, err = ffmpeg(["-y","-i", c.path, "-filter:v", vf_str, "-filter:a", af_str,
                              "-c:v","libx264","-preset","medium","-crf","18",
                              "-c:a","aac","-b:a","192k", out])
            self._notify(ok, "Exported clip" if ok else f"Export failed: {err[:400]}")
        self._thread(worker, "Exporting clip…")

    def export_all(self):
        if not self.clips: return
        out, _ = QFileDialog.getSaveFileName(self, "Export final", f"final_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
        if not out: return

        def worker():
            # 2-step: render each clip to temp (apply trim/speed + burn captions if any), then concat demuxer.
            parts = []
            for idx,c in enumerate(self.clips):
                tmp = os.path.join(self.temp_dir, f"part_{idx}.mp4")
                vf = []
                af = []
                if c.tin>0 or c.tout>0:
                    if c.tout>0:
                        vf += [f"trim=start={c.tin}:end={c.tout}", "setpts=PTS-STARTPTS"]
                        af += [f"atrim=start={c.tin}:end={c.tout}", "asetpts=PTS-STARTPTS"]
                    else:
                        vf += [f"trim=start={c.tin}", "setpts=PTS-STARTPTS"]
                        af += [f"atrim=start={c.tin}", "asetpts=PTS-STARTPTS"]
                if abs(c.speed-1.0) > 1e-6:
                    vf += [f"setpts={1.0/c.speed}*PTS"]
                    rem = c.speed
                    while rem>2.0: af.append("atempo=2.0"); rem/=2.0
                    while rem<0.5: af.append("atempo=0.5"); rem*=2.0
                    af.append(f"atempo={rem:.6f}")
                # Manual overlay via drawtext if provided
                dvf = []
                if vf: dvf.append(",".join(vf))
                if c.text:
                    r,g,b = c.color_rgb or (255,255,255)
                    # Use system font family; escape colon/\ to avoid issues
                    family = c.font_family.replace(':','\\:') if c.font_family else 'Arial'
                    draw = f"drawtext=font='{family}':text='{c.text.replace(':','\\:').replace('\\','/').replace("'","\\\\'")}':fontsize={c.font_size or 32}:fontcolor=rgba({r},{g},{b},1):box=1:boxcolor=black@0.45:boxborderw=8:x=(w-text_w)/2:y={(10 if c.pos=='top' else '(h-text_h-30)')}"
                    dvf.append(draw)
                vf_str = ",".join(dvf) if dvf else "null"
                af_str = ",".join(af) if af else "anull"

                # If auto captions exist, burn via SRT
                extra_vf = None
                if self.clips[idx].segments:
                    srt = os.path.join(self.temp_dir, f"cap_{idx}.srt")
                    with open(srt,'w',encoding='utf-8') as f:
                        for i,s in enumerate(c.segments,1):
                            def ts(t):
                                h=int(t//3600); m=int((t%3600)//60); ss=int(t%60); ms=int((t-int(t))*1000)
                                return f"{h:02d}:{m:02d}:{ss:02d},{ms:03d}"
                            f.write(f"{i}\n{ts(s.start)} --> {ts(s.end)}\n{s.text}\n\n")
                    srt_posix = Path(srt).as_posix()
                    vf_str = f"{vf_str},{'subtitles=\''+srt_posix+'\'' if vf_str!='null' else 'subtitles=\''+srt_posix+'\''}"

                ok, err = ffmpeg(["-y","-i", c.path, "-filter:v", vf_str, "-filter:a", af_str,
                                   "-c:v","libx264","-preset","medium","-crf","18",
                                   "-c:a","aac","-b:a","192k", tmp])
                if not ok:
                    self._notify(False, f"Failed rendering part {idx}: {err[:300]}")
                    return
                parts.append(tmp)

            # Concat demuxer
            listfile = os.path.join(self.temp_dir, "concat.txt")
            with open(listfile,'w',encoding='utf-8') as f:
                for p in parts:
                    f.write(f"file '{Path(p).as_posix()}'\n")
            ok, err = ffmpeg(["-y","-f","concat","-safe","0","-i", listfile,
                               "-c","copy", out])
            if not ok:
                # fallback re-encode
                ok, err = ffmpeg(["-y","-f","concat","-safe","0","-i", listfile,
                                   "-c:v","libx264","-preset","medium","-crf","18",
                                   "-c:a","aac","-b:a","192k", out])
            self._notify(ok, "Exported final video" if ok else f"Concat failed: {err[:400]}")
        self._thread(worker, "Exporting final…")

    # --- Transport & Timeline ---
    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause(); self.btn_play.setText("Play")
        else:
            # ensure the correct clip/position based on timeline value
            if self.clips:
                idx, sec = TimelineMapper.tl_to_clip(self.clips, self.timeline.value())
                if idx >= 0:
                    self.list.setCurrentRow(idx)
                    self._load_clip(self.clips[idx].path, int(sec*1000))
            self.player.play(); self.btn_play.setText("Pause")

    def on_timeline_seek(self, ms:int):
        if not self.clips: return
        idx, sec = TimelineMapper.tl_to_clip(self.clips, ms)
        if idx >= 0:
            self.list.setCurrentRow(idx)
            self._load_clip(self.clips[idx].path, int(sec*1000))

    def _on_pos(self, pos_ms:int):
        if self.current >= 0 and self.clips:
            tl = TimelineMapper.clip_to_tl(self.clips, self.current, pos_ms/1000.0)
            if not self.timeline.isSliderDown():
                self.timeline.setValue(tl)
        self._sync_time_label()

    def _sync_time_label(self):
        def fmt(ms): s=ms//1000; m=s//60; s=s%60; return f"{m:02d}:{s:02d}"
        self.lbl_time.setText(f"{fmt(self.timeline.value())} / {fmt(self.timeline.maximum())}")

    def _rebuild_timeline(self):
        self.timeline.setRange(0, TimelineMapper.tl_total(self.clips))
        self._sync_time_label()

    def _load_clip(self, path:str, seek_ms:int=0):
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.setPosition(seek_ms)
        self.player.play()

    # --- Undo / Redo ---
    def on_undo(self):
        new = self.undo.do_undo(self.clips)
        if new is None: return
        self.clips = new
        self._repaint_list_from_clips()
        self._rebuild_timeline()

    def on_redo(self):
        new = self.undo.do_redo(self.clips)
        if new is None: return
        self.clips = new
        self._repaint_list_from_clips()
        self._rebuild_timeline()

    def _repaint_list_from_clips(self):
        self.list.clear()
        for c in self.clips:
            self.list.addItem(QListWidgetItem(Path(c.path).name))
        if self.clips:
            self.list.setCurrentRow(0)

    # --- Thread helpers & notifications ---
    def _thread(self, fn, msg:str):
        if self.busy:
            QMessageBox.warning(self, "Busy", "Another operation is running"); return
        self.busy = True; self.statusBar().showMessage(msg)
        t = threading.Thread(target=lambda: (fn(), self._set_idle()), daemon=True)
        t.start()

    def _set_idle(self):
        # called at end of worker thread
        def done():
            self.busy = False; self.statusBar().showMessage("Ready", 3000)
        QTimer.singleShot(0, done)

    def _notify(self, ok:bool, msg:str):
        def ui():
            if ok: self.statusBar().showMessage(msg, 4000)
            else: QMessageBox.critical(self, "Operation Failed", msg)
        QTimer.singleShot(0, ui)

    # --- Cleanup ---
    def closeEvent(self, e):
        try: shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception: pass
        super().closeEvent(e)


# ENTRY -----------------------------------------------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow(); w.show()
    sys.exit(app.exec())
