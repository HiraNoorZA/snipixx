# snipix_video_editor.py
# PyQt6 video editor skeleton using FFmpeg for processing and Whisper (English) for captions.
# - Operations: Open, Save As, Undo/Redo, Reset, Trim, Speed Change, Add Text (drawtext), Rotate, Remove Audio, Generate+Burn Captions (Whisper)
# - Playback: QMediaPlayer + QVideoWidget
# - Processing: FFmpeg subprocess (no MoviePy)
# - History: versioned temp files for safe Undo/Redo
# - Notes:
#     * Requires FFmpeg installed and available on PATH.
#     * Captions use Whisper (English only). Install via: pip install openai-whisper
#     * Windows users may need a TTF font path when adding text (FFmpeg drawtext). The UI lets you pick a font file.

import sys
import os
import shutil
import tempfile
import threading
import subprocess
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, QEvent, QUrl
from PyQt6.QtGui import QIcon, QKeySequence, QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSlider, QGroupBox, QFormLayout, QFileDialog, QInputDialog, QMessageBox
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

# Optional: Whisper for captions (English only)
try:
    import whisper
except Exception:
    whisper = None


# ----------------------------- Utility Events (for thread-safe UI updates) -----------------------------

class OpCompleteEvent(QEvent):
    """Generic operation completion event used to hop results back to the UI thread."""
    TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, ok: bool, msg: str, out_path: str | None = None):
        super().__init__(OpCompleteEvent.TYPE)
        self.ok = ok
        self.msg = msg
        self.out_path = out_path


# ------------------------------------------ Main Window -----------------------------------------------

class VideoEditor(QMainWindow):
    """
    SNIPIX – Video Editor (FFmpeg edition)
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SNIPIX – Video Editor")
        self.setWindowIcon(QIcon("resources/icons/SnipixLogo.png"))
        self.resize(1200, 800)

        # --- App style (light) ---
        self.COLOR_BG = "#e5f0fd"
        self.COLOR_SURF = "#ffffff"
        self.COLOR_ACCENT = "#cab4f5"
        self.COLOR_TEXT = "#111827"
        self.COLOR_MUTED = "#e5e7eb"

        self.setStyleSheet(f"""
            QMainWindow {{ background: {self.COLOR_BG}; }}
            QMenuBar {{ background: {self.COLOR_SURF}; color: {self.COLOR_TEXT}; border-bottom: 1px solid {self.COLOR_MUTED}; }}
            QMenuBar::item:selected {{ background: {self.COLOR_MUTED}; }}
            QLabel {{ color: {self.COLOR_TEXT}; }}
            QGroupBox {{ color: {self.COLOR_TEXT}; background: {self.COLOR_SURF}; border: 1px solid {self.COLOR_MUTED}; border-radius: 10px; margin-top: 12px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; }}
            QPushButton {{
                background: {self.COLOR_ACCENT}; color: black; border: none; padding: 8px 10px; border-radius: 8px;
            }}
            QPushButton:hover {{ opacity: 0.95; }}
            QPushButton:disabled {{ background: #cbd5e1; color: #6b7280; }}
            QSlider::groove:horizontal {{ height: 6px; background: {self.COLOR_MUTED}; border-radius: 3px; }}
            QSlider::handle:horizontal {{ width: 16px; background: {self.COLOR_ACCENT}; border-radius: 8px; margin: -6px 0; }}
        """)

        # --- State ---
        self.temp_dir = tempfile.mkdtemp(prefix="snipix_edit_")
        self.original_path: str | None = None      # path of the file opened by the user
        self.current_path: str | None = None       # active working file (in temp dir)
        self.history: list[str] = []               # stack of working versions (paths)
        self.redo_stack: list[str] = []            # redo stack (paths)
        self.playing = False
        self.is_processing = False
        self.last_fontfile: str | None = None      # cached TTF path for drawtext

        # --- Media player ---
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.positionChanged.connect(self._on_position_changed)
        self.media_player.durationChanged.connect(self._on_duration_changed)
        self.media_player.playbackStateChanged.connect(self._on_playback_changed)

        # --- UI Layout ---
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # Left: File / Edit actions
        root.addLayout(self._build_left_panel(), 1)

        # Center: Canvas + transport
        root.addWidget(self._build_canvas(), 4)

        # Right: Operations (no filters/adjustments/crop)
        root.addLayout(self._build_right_panel(), 1)

        # Status bar
        self.status = self.statusBar()
        self._status("Welcome to SNIPIX – Ready")

        # Menu bar
        self._build_menubar()

        # Background welcome
        self.video_widget.setStyleSheet("background-color: #f8fafc;")

        # Keep player responsive if any background work is running
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._player_guard)
        self.timer.start(100)

    # -------------------------------------- UI Builders --------------------------------------

    def _build_left_panel(self):
        left = QVBoxLayout()
        left.setSpacing(12)

        file_group = QGroupBox("File")
        f = QVBoxLayout()
        self.btn_open = QPushButton(QIcon("resources/icons/open.png"), "Open Video")
        self.btn_open.clicked.connect(self.open_video)
        f.addWidget(self.btn_open)

        self.btn_save_as = QPushButton(QIcon("resources/icons/save.png"), "Save As…")
        self.btn_save_as.clicked.connect(self.save_as)
        f.addWidget(self.btn_save_as)
        file_group.setLayout(f)
        left.addWidget(file_group)

        bops_group = QGroupBox("Basic Operations")
        b = QFormLayout()

        self.btn_trim = QPushButton(QIcon("resources/icons/crop.png"), "Trim…")
        self.btn_trim.clicked.connect(self.trim_video)
        b.addRow(self.btn_trim)

        self.btn_speed = QPushButton(QIcon("resources/icons/speed.png"), "Change Speed…")
        self.btn_speed.clicked.connect(self.change_speed)
        b.addRow(self.btn_speed)

        self.btn_add_text = QPushButton(QIcon("resources/icons/addText.png"), "Add Text Overlay…")
        self.btn_add_text.clicked.connect(self.add_text_overlay)
        b.addRow(self.btn_add_text)

        self.btn_rotate = QPushButton(QIcon("resources/icons/rotate.png"), "Rotate 90° CW")
        self.btn_rotate.clicked.connect(lambda: self.rotate_video(transpose=1))  # 1 = 90° CW
        b.addRow(self.btn_rotate)
        bops_group.setLayout(b)
        left.addWidget(bops_group)

        edit_group = QGroupBox("Edit")
        e = QVBoxLayout()
        self.btn_undo = QPushButton(QIcon("resources/icons/undo.png"), "Undo")
        self.btn_undo.clicked.connect(self.undo)
        e.addWidget(self.btn_undo)

        self.btn_redo = QPushButton(QIcon("resources/icons/redo.png"), "Redo")
        self.btn_redo.clicked.connect(self.redo)
        e.addWidget(self.btn_redo)

        self.btn_reset = QPushButton(QIcon("resources/icons/reset.png"), "Reset")
        self.btn_reset.clicked.connect(self.reset_to_original)
        e.addWidget(self.btn_reset)
        edit_group.setLayout(e)
        left.addWidget(edit_group)

        left.addStretch()
        return left

    def _build_right_panel(self):
        right = QVBoxLayout()
        right.setSpacing(12)

        aops_group = QGroupBox("Adv. Operations")
        o = QFormLayout()

        self.btn_remove_audio = QPushButton(QIcon("resources/icons/mute.png"), "Remove Audio")
        self.btn_remove_audio.clicked.connect(self.remove_audio)
        o.addRow(self.btn_remove_audio)

        self.btn_captions = QPushButton(QIcon("resources/icons/captions.png"), "Generate English Captions")
        self.btn_captions.clicked.connect(self.generate_and_burn_captions)
        o.addRow(self.btn_captions)

        aops_group.setLayout(o)
        right.addWidget(aops_group)

        export_group = QGroupBox("Export")
        ef = QFormLayout()
        self.btn_export_mp4 = QPushButton(QIcon("resources/icons/export.png"), "Export MP4")
        self.btn_export_mp4.clicked.connect(lambda: self.export_as(ext="mp4"))
        ef.addRow(self.btn_export_mp4)
        export_group.setLayout(ef)
        right.addWidget(export_group)

        right.addStretch()
        return right

    def _build_canvas(self):
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setSpacing(10)

        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background-color: black;")
        self.media_player.setVideoOutput(self.video_widget)
        vbox.addWidget(self.video_widget, 1)

        bar = QHBoxLayout()
        self.play_btn = QPushButton(QIcon("resources/icons/play.png"), "Play")
        self.play_btn.clicked.connect(self.toggle_play)
        bar.addWidget(self.play_btn)

        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)  # set after load
        self.seek.sliderMoved.connect(self._on_seek_slider)
        bar.addWidget(self.seek, 1)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setStyleSheet("color: #111827;")
        bar.addWidget(self.time_label)

        vbox.addLayout(bar)
        return container

    def _build_menubar(self):
        menubar = self.menuBar()

        # File
        m_file = menubar.addMenu("&File")
        act_open = QAction(QIcon("resources/icons/open.png"), "Open…", self)
        act_open.setShortcut(QKeySequence("Ctrl+O"))
        act_open.triggered.connect(self.open_video)

        act_save_as = QAction(QIcon("resources/icons/save.png"), "Save As…", self)
        act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        act_save_as.triggered.connect(self.save_as)

        act_export = QAction(QIcon("resources/icons/export.png"), "Export MP4…", self)
        act_export.setShortcut(QKeySequence("Ctrl+E"))
        act_export.triggered.connect(lambda: self.export_as(ext="mp4"))

        act_exit = QAction("Exit", self)
        act_exit.setShortcut(QKeySequence("Ctrl+Q"))
        act_exit.triggered.connect(self.close)

        for a in (act_open, act_save_as, act_export):
            m_file.addAction(a)
        m_file.addSeparator()
        m_file.addAction(act_exit)

        # Edit
        m_edit = menubar.addMenu("&Edit")
        act_undo = QAction(QIcon("resources/icons/undo.png"), "Undo", self)
        act_undo.setShortcut(QKeySequence("Ctrl+Z"))
        act_undo.triggered.connect(self.undo)

        act_redo = QAction(QIcon("resources/icons/redo.png"), "Redo", self)
        act_redo.setShortcut(QKeySequence("Ctrl+Y"))
        act_redo.triggered.connect(self.redo)

        act_reset = QAction(QIcon("resources/icons/reset.png"), "Reset to Original", self)
        act_reset.setShortcut(QKeySequence("Ctrl+R"))
        act_reset.triggered.connect(self.reset_to_original)

        for a in (act_undo, act_redo, act_reset):
            m_edit.addAction(a)

        # Tools
        m_tools = menubar.addMenu("&Tools")
        m_tools.addAction("Trim…", self.trim_video)
        m_tools.addAction("Change Speed…", self.change_speed)
        m_tools.addAction("Add Text Overlay…", self.add_text_overlay)
        m_tools.addAction("Rotate 90° CW", lambda: self.rotate_video(transpose=1))
        m_tools.addAction("Remove Audio", self.remove_audio)
        m_tools.addAction("Generate English Captions", self.generate_and_burn_captions)

    # -------------------------------------- Status helpers --------------------------------------

    def _status(self, msg: str, ms: int = 4000):
        self.status.showMessage(msg, ms)

    def customEvent(self, event):
        """Receive completion events from worker threads."""
        if isinstance(event, OpCompleteEvent):
            self.is_processing = False
            if event.ok and event.out_path:
                # Update current version + player
                self._push_history(event.out_path)
                self._load_into_player(event.out_path, autoplay=True)
                self._status(event.msg)
            else:
                QMessageBox.critical(self, "Operation Failed", event.msg)
                self._status("Ready")

    # -------------------------------------- Player/Transport --------------------------------------

    @staticmethod
    def _fmt_time(ms: int) -> str:
        t = max(0, ms // 1000)
        m = int(t // 60)
        s = int(t % 60)
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
            self.playing = True
        else:
            self.play_btn.setText("Play")
            self.playing = False

    def _update_time_label(self):
        self.time_label.setText(f"{self._fmt_time(self.media_player.position())} / {self._fmt_time(self.media_player.duration())}")

    def toggle_play(self):
        if not self.current_path:
            return
        if self.playing:
            self.media_player.pause()
        else:
            self.media_player.play()

    def _on_seek_slider(self, value: int):
        if not self.current_path:
            return
        self.media_player.setPosition(value)
        self._update_time_label()

    def _player_guard(self):
        # Prevent playback during long operations
        if self.is_processing:
            self.media_player.pause()

    def _load_into_player(self, path: str, autoplay: bool = False):
        self.current_path = path
        self.media_player.setSource(QUrl.fromLocalFile(path))
        if autoplay:
            self.media_player.play()

    # -------------------------------------- History Management --------------------------------------

    def _reset_history(self):
        self.history.clear()
        self.redo_stack.clear()

    def _push_history(self, new_path: str):
        """Push a new version into history and clear redo."""
        self.history.append(new_path)
        if len(self.history) > 50:
            # Clean oldest to manage disk usage
            old = self.history.pop(0)
            try:
                if os.path.exists(old) and old != self.current_path:
                    os.remove(old)
            except Exception:
                pass
        self.redo_stack.clear()

    def undo(self):
        if len(self.history) <= 1:
            self._status("Nothing to undo")
            return
        # Move top to redo, load previous
        last = self.history.pop()
        self.redo_stack.append(last)
        prev = self.history[-1]
        self._load_into_player(prev, autoplay=True)
        self._status("Undid last action")

    def redo(self):
        if not self.redo_stack:
            self._status("Nothing to redo")
            return
        nxt = self.redo_stack.pop()
        self.history.append(nxt)
        self._load_into_player(nxt, autoplay=True)
        self._status("Redid last action")

    def reset_to_original(self):
        if not self.original_path:
            return
        # Create a fresh working copy of the original
        fresh = self._mk_working_copy(self.original_path)
        self._reset_history()
        self._push_history(fresh)
        self._load_into_player(fresh, autoplay=True)
        self._status("Reset to original")

    # -------------------------------------- File I/O --------------------------------------

    def open_video(self):
        if self.is_processing:
            QMessageBox.warning(self, "Please wait", "Another operation is running.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open Video", "", "Video Files (*.mp4 *.mov *.mkv *.avi *.wmv *.flv)")
        if not path:
            return
        if not os.path.exists(path):
            QMessageBox.critical(self, "Error", "File does not exist.")
            return

        # Make a working copy inside temp dir so we never modify the original directly
        self.original_path = path
        working = self._mk_working_copy(path)
        self._reset_history()
        self._push_history(working)
        self._load_into_player(working, autoplay=True)
        self._status(f"Loaded: {os.path.basename(path)}")

    def save_as(self):
        if not self.current_path:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        default = f"edited_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        out, _ = QFileDialog.getSaveFileName(self, "Save As", default, "MP4 (*.mp4);;All Files (*.*)")
        if not out:
            return
        try:
            shutil.copy2(self.current_path, out)
            self._status(f"Saved: {os.path.basename(out)}")
        except Exception as ex:
            QMessageBox.critical(self, "Save Failed", str(ex))

    def export_as(self, ext="mp4"):
        if not self.current_path:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        default = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
        out, _ = QFileDialog.getSaveFileName(self, "Export", default, f"{ext.upper()} (*.{ext});;All Files (*.*)")
        if not out:
            return
        # Re-mux/re-encode to standard H.264/AAC MP4 for compatibility
        self._run_ffmpeg_async(
            ff_args=[
                "-y",
                "-i", self.current_path,
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                out
            ],
            success_msg=f"Exported: {os.path.basename(out)}",
            final_out=out
        )

    def closeEvent(self, event):
        """Clean temp dir on close."""
        try:
            if os.path.isdir(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass
        super().closeEvent(event)

    # -------------------------------------- Operations (FFmpeg) --------------------------------------

    def trim_video(self):
        if not self.current_path:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return

        # Ask for start/end in seconds
        start, ok = QInputDialog.getDouble(self, "Trim", "Start time (seconds):", 0.0, 0.0, 10**7, 2)
        if not ok:
            return
        end, ok = QInputDialog.getDouble(self, "Trim", "End time (seconds):", start, start, 10**7, 2)
        if not ok:
            return
        if end <= start:
            QMessageBox.critical(self, "Invalid Range", "End must be greater than Start.")
            return

        # Fast path: stream copy (if cut points are on keyframes it’s perfect; otherwise may be approximate)
        out_file = self._temp_name("trim", "mp4")
        ff_try_copy = [
            "-y",
            "-ss", f"{start}",
            "-to", f"{end}",
            "-i", self.current_path,
            "-c", "copy",
            out_file
        ]

        def worker():
            ok1, _ = self._run_ffmpeg_blocking(ff_try_copy)
            if not ok1:
                # Fallback: re-encode to get precise cut
                ff_reencode = [
                    "-y",
                    "-ss", f"{start}",
                    "-to", f"{end}",
                    "-i", self.current_path,
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                    "-c:a", "aac", "-b:a", "192k",
                    out_file
                ]
                ok2, err2 = self._run_ffmpeg_blocking(ff_reencode)
                if not ok2:
                    self._post_event(False, f"Trim failed: {err2}")
                    return
            self._post_event(True, f"Trimmed {start:.2f}s → {end:.2f}s", out_file)

        self._start_worker(worker, "Trimming...")

    def change_speed(self):
        if not self.current_path:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        factor, ok = QInputDialog.getDouble(self, "Change Speed",
                                            "Speed factor (0.25–4.0)\n0.5 = half speed, 2.0 = double speed:", 1.0, 0.25, 4.0, 2)
        if not ok or factor == 1.0:
            return

        # Video timing filter: setpts=PTS/Factor
        setpts = f"setpts={1.0/factor}*PTS"

        # Audio: atempo supports 0.5–2.0; chain if outside
        def atempo_chain(x: float) -> list[str]:
            # Break factor into 0.5–2.0 steps
            chain = []
            remaining = x
            # Normalize to 1.0..4.0 range by multiplying or dividing in steps
            while remaining > 2.0 + 1e-6:
                chain.append("atempo=2.0")
                remaining /= 2.0
            while remaining < 0.5 - 1e-6:
                chain.append("atempo=0.5")
                remaining *= 2.0
            chain.append(f"atempo={remaining:.6f}")
            return chain

        a_filters = atempo_chain(factor)
        afilter = ",".join(a_filters)

        out_file = self._temp_name(f"speedx{factor}", "mp4")
        ff = [
            "-y",
            "-i", self.current_path,
            "-filter:v", setpts,
            "-filter:a", afilter,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            out_file
        ]
        self._run_ffmpeg_async(ff, success_msg=f"Speed x{factor}", final_out=out_file)

    def add_text_overlay(self):
        if not self.current_path:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return

        text, ok = QInputDialog.getText(self, "Add Text", "Text to overlay:")
        if not ok or not text.strip():
            return

        size, ok = QInputDialog.getInt(self, "Text Size", "Font size (px):", 48, 10, 200, 1)
        if not ok:
            return

        # Choose font file once (recommended for Windows); optional on Linux/macOS with fontconfig
        if self.last_fontfile is None:
            msg = QMessageBox.question(self, "Font File (Optional)",
                                       "FFmpeg drawtext often needs a TTF font file on Windows.\n"
                                       "Do you want to select a .ttf font file now?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if msg == QMessageBox.StandardButton.Yes:
                fpath, _ = QFileDialog.getOpenFileName(self, "Choose Font (.ttf)", "", "Fonts (*.ttf *.otf);;All Files (*.*)")
                if fpath:
                    self.last_fontfile = fpath

        # Drawtext: white text with subtle black shadow, centered horizontally near bottom
        # Position (x,y): x centered, y = h - text_h - margin
        draw = f"drawtext="
        if self.last_fontfile:
            draw += f"fontfile='{self.last_fontfile}':"
        # Escape single quotes inside text for FFmpeg
        safe_text = text.replace("'", r"\'")
        draw += (
            f"text='{safe_text}':"
            f"fontsize={size}:fontcolor=white:"
            f"shadowcolor=black:shadowx=2:shadowy=2:"
            f"x=(w-text_w)/2:y=h-text_h-40"
        )

        out_file = self._temp_name("text", "mp4")
        ff = [
            "-y",
            "-i", self.current_path,
            "-vf", draw,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "copy",
            out_file
        ]
        self._run_ffmpeg_async(ff, success_msg="Text overlay added", final_out=out_file)

    def rotate_video(self, transpose=1):
        """
        transpose:
          1 = 90° clockwise,
          2 = 90° counterclockwise,
          0 = 90° clockwise and vertical flip,
          3 = 90° counterclockwise and vertical flip
        """
        if not self.current_path:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        out_file = self._temp_name("rotate", "mp4")
        ff = [
            "-y",
            "-i", self.current_path,
            "-vf", f"transpose={transpose}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "copy",
            out_file
        ]
        self._run_ffmpeg_async(ff, success_msg="Rotated 90° CW", final_out=out_file)

    def remove_audio(self):
        if not self.current_path:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        out_file = self._temp_name("mute", "mp4")
        ff = [
            "-y",
            "-i", self.current_path,
            "-c:v", "copy",
            "-an",
            out_file
        ]
        self._run_ffmpeg_async(ff, success_msg="Audio removed", final_out=out_file)

    def generate_and_burn_captions(self):
        """
        English-only captions:
          1) Extract mono 16 kHz WAV via FFmpeg
          2) Transcribe with Whisper (tiny/base/small – tiny used here for speed)
          3) Save .srt
          4) Burn into video with FFmpeg subtitles filter
        """
        if not self.current_path:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        if whisper is None:
            QMessageBox.critical(self, "Whisper not installed",
                                 "Please install Whisper first:\n    pip install openai-whisper")
            return

        # Choose model size (tiny/base/small/medium/large). Tiny is fastest; you can change this default.
        model_name = "tiny"

        wav_path = os.path.join(self.temp_dir, "audio_16k_mono.wav")
        srt_path = os.path.join(self.temp_dir, "captions.srt")
        out_file = self._temp_name("captioned", "mp4")

        def worker():
            # 1) Extract WAV
            ok_wav, err_wav = self._run_ffmpeg_blocking([
                "-y",
                "-i", self.current_path,
                "-vn",
                "-ac", "1",             # mono
                "-ar", "16000",         # 16 kHz
                wav_path
            ])
            if not ok_wav:
                self._post_event(False, f"Audio extract failed: {err_wav}")
                return

            # 2) Whisper (English only)
            try:
                model = whisper.load_model(model_name)
                # Force English to avoid language detection overhead
                result = model.transcribe(wav_path, language="en", task="transcribe", verbose=False)
            except Exception as ex:
                self._post_event(False, f"Whisper failed: {ex}")
                return

            # 3) Write SRT
            try:
                def srt_timestamp(t):
                    h = int(t // 3600)
                    m = int((t % 3600) // 60)
                    s = int(t % 60)
                    ms = int((t - int(t)) * 1000)
                    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

                lines = []
                idx = 1
                for seg in result.get("segments", []):
                    start = float(seg["start"])
                    end = float(seg["end"])
                    text = (seg.get("text") or "").strip()
                    if not text:
                        continue
                    lines.append(f"{idx}")
                    lines.append(f"{srt_timestamp(start)} --> {srt_timestamp(end)}")
                    lines.append(text)
                    lines.append("")  # blank line
                    idx += 1

                if not lines:
                    self._post_event(False, "No captions generated from audio.")
                    return

                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
            except Exception as ex:
                self._post_event(False, f"Failed to write SRT: {ex}")
                return

            # 4) Burn SRT using FFmpeg
            # Note: On Windows, paths must be escaped; simplest approach is to use absolute path and wrap in quotes.
            ff = [
                "-y",
                "-i", self.current_path,
                "-vf", f"subtitles='{srt_path}'",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                out_file
            ]
            ok_burn, err_burn = self._run_ffmpeg_blocking(ff)
            if not ok_burn:
                self._post_event(False, f"Burning captions failed: {err_burn}")
                return

            self._post_event(True, "Captions generated & burned in", out_file)

        self._start_worker(worker, "Generating captions...")

    # -------------------------------------- FFmpeg plumbing --------------------------------------

    @staticmethod
    def _which_ffmpeg() -> str | None:
        """Return ffmpeg executable path if available."""
        exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        for p in os.environ.get("PATH", "").split(os.pathsep):
            cand = os.path.join(p, exe)
            if os.path.isfile(cand):
                return exe  # name is fine if on PATH
        return None

    def _run_ffmpeg_blocking(self, args: list[str]) -> tuple[bool, str]:
        """
        Execute FFmpeg synchronously.
        Returns (ok, stderr_text_on_error).
        """
        ff = self._which_ffmpeg()
        if not ff:
            return False, "FFmpeg not found on PATH."
        try:
            proc = subprocess.run(
                [ff] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                text=True
            )
            ok = proc.returncode == 0
            if not ok:
                return False, proc.stderr.strip() or "Unknown FFmpeg error"
            return True, ""
        except Exception as ex:
            return False, str(ex)

    def _run_ffmpeg_async(self, ff_args: list[str], success_msg: str, final_out: str):
        """Run FFmpeg in a worker thread and send result back via event."""
        def worker():
            ok, err = self._run_ffmpeg_blocking(ff_args)
            if ok:
                self._post_event(True, success_msg, final_out)
            else:
                self._post_event(False, err)
        self._start_worker(worker, "Processing...")

    def _start_worker(self, target, busy_msg: str):
        if self.is_processing:
            QMessageBox.warning(self, "Please wait", "Another operation is running.")
            return
        self.is_processing = True
        self._status(busy_msg, ms=0)
        t = threading.Thread(target=target, daemon=True)
        t.start()

    def _post_event(self, ok: bool, msg: str, out_path: str | None = None):
        QApplication.instance().postEvent(self, OpCompleteEvent(ok, msg, out_path))

    # -------------------------------------- Temp / Naming helpers --------------------------------------

    def _temp_name(self, tag: str, ext: str) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return os.path.join(self.temp_dir, f"{tag}_{ts}.{ext}")

    def _mk_working_copy(self, src: str) -> str:
        ext = os.path.splitext(src)[1].lstrip(".").lower() or "mp4"
        dst = self._temp_name("working", ext)
        shutil.copy2(src, dst)
        return dst


# ------------------------------------------ Entrypoint -----------------------------------------------

if __name__ == "__main__":
    app = QApplication(sys.argv)
    editor = VideoEditor()
    editor.show()
    sys.exit(app.exec())
