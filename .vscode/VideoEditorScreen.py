# snipix_video_editor.py
# Simplified PyQt6 video editor using FFmpeg
# Operations: Open, Save As, Undo/Redo, Reset, Trim, Speed Change, Rotate, Remove Audio, Grayscale, Export MP4
# Requires: FFmpeg on PATH

import sys, os, shutil, tempfile, threading, subprocess
from datetime import datetime
from PyQt6.QtCore import Qt, QTimer, QEvent, QUrl
from PyQt6.QtGui import QIcon, QKeySequence, QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QCheckBox,
    QSlider, QGroupBox, QFormLayout, QFileDialog, QMessageBox, QDialog, QDoubleSpinBox, QDialogButtonBox
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from styles.styles import SnipixStyles 

class OpCompleteEvent(QEvent):
    TYPE = QEvent.Type(QEvent.registerEventType())
    def __init__(self, ok: bool, msg: str, out_path: str | None = None):
        super().__init__(OpCompleteEvent.TYPE)
        self.ok, self.msg, self.out_path = ok, msg, out_path

class VideoEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SNIPIX – Video Editor")
        self.setWindowIcon(QIcon(".vscode/resources/icons/SnipixLogo.png"))
        self.resize(1200, 768)

        # Dark mode state
        self.is_dark_mode = False
        self.setStyleSheet(SnipixStyles.get_stylesheet(self.is_dark_mode))

        # State
        self.temp_dir = tempfile.mkdtemp(prefix=f"snipix_edit_{os.getpid()}_")
        self.original_path = None
        self.current_path = None
        self.history = []
        self.redo_stack = []
        self.playing = False
        self.is_processing = False

        self.center_on_screen()

        # Media player
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.positionChanged.connect(self._on_position_changed)
        self.media_player.durationChanged.connect(self._on_duration_changed)
        self.media_player.playbackStateChanged.connect(self._on_playback_changed)

        # UI Layout
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        root.addLayout(self._build_left_panel(), 1)
        root.addWidget(self._build_canvas(), 4)
        root.addLayout(self._build_right_panel(), 1)

        # Status bar
        self.status = self.statusBar()
        self._status("Ready")

        # Menu bar
        self._build_menubar()

        # Canvas
        self.video_widget.setStyleSheet("background-color: #E8ECEF;")

        # Player guard
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._player_guard)
        self.timer.start(100)

        # FFmpeg check
        if not self._which_ffmpeg():
            QMessageBox.critical(self, "FFmpeg Not Found", 
                "FFmpeg is required. Install it and add to PATH. Visit https://ffmpeg.org/download.html.")

    def center_on_screen(self):
        screen_geometry = QApplication.primaryScreen().geometry()
        x = (screen_geometry.width() - self.width()) // 2
        y = (screen_geometry.height() - self.height()) // 2
        self.move(x, y)
    def _build_left_panel(self):
        left = QVBoxLayout()

        # Dark mode toggle
        mode_group = QGroupBox("Display")
        m = QVBoxLayout()
        self.dark_mode_check = QCheckBox("Dark Mode")
        self.dark_mode_check.setChecked(self.is_dark_mode)
        self.dark_mode_check.stateChanged.connect(self.toggle_dark_mode)
        m.addWidget(self.dark_mode_check)
        mode_group.setLayout(m)
        left.addWidget(mode_group)

        file_group = QGroupBox("File")
        f = QVBoxLayout()
        self.btn_open = QPushButton(QIcon(".vscode/resources/icons/video.png"), "Open Video", clicked=self.open_video)
        self.btn_save_as = QPushButton(QIcon(".vscode/resources/icons/save.png"), "Save As…", clicked=self.save_as)
        f.addWidget(self.btn_open)
        f.addWidget(self.btn_save_as)
        file_group.setLayout(f)
        left.addWidget(file_group)

        bops_group = QGroupBox("Basic Operations")
        b = QFormLayout()
        self.btn_trim = QPushButton(QIcon(".vscode/resources/icons/trim.png"), "Trim", clicked=self.trim_video)
        self.btn_speed = QPushButton(QIcon(".vscode/resources/icons/speed.png"), "Change Speed", clicked=self.change_speed)
        self.btn_rotate = QPushButton(QIcon(".vscode/resources/icons/rotate.png"), "Rotate 90° CW", clicked=lambda: self.rotate_video(transpose=1))
        b.addRow(self.btn_trim)
        b.addRow(self.btn_speed)
        b.addRow(self.btn_rotate)
        bops_group.setLayout(b)
        left.addWidget(bops_group)

        edit_group = QGroupBox("Edit")
        e = QVBoxLayout()
        self.btn_undo = QPushButton(QIcon(".vscode/resources/icons/undo.png"), "Undo", clicked=self.undo)
        self.btn_redo = QPushButton(QIcon(".vscode/resources/icons/redo.png"), "Redo", clicked=self.redo)
        self.btn_reset = QPushButton(QIcon(".vscode/resources/icons/reset.png"), "Reset", clicked=self.reset_to_original)
        e.addWidget(self.btn_undo)
        e.addWidget(self.btn_redo)
        e.addWidget(self.btn_reset)
        edit_group.setLayout(e)
        left.addWidget(edit_group)
        left.addStretch()
        return left

    def toggle_dark_mode(self):
        self.is_dark_mode = self.dark_mode_check.isChecked()
        self.setStyleSheet(SnipixStyles.get_stylesheet(self.is_dark_mode))

    def back_to_menu(self):
        from optionPane import OptionPane  # Local import to avoid circular dependency
        try:
            option_pane = OptionPane()
            option_pane.show()
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to return to menu: {e}")


    def _build_right_panel(self):
        right = QVBoxLayout()
        aops_group = QGroupBox("Adv. Operations")
        o = QFormLayout()
        self.btn_remove_audio = QPushButton(QIcon(".vscode/resources/icons/rmSound.png"), "Remove Audio", clicked=self.remove_audio)
        o.addRow(self.btn_remove_audio)
        aops_group.setLayout(o)
        right.addWidget(aops_group)

        filters_group = QGroupBox("Filters")
        f = QFormLayout()
        self.btn_grayscale = QPushButton(QIcon(".vscode/resources/icons/grayscale.png"), "Grayscale", clicked=self.apply_grayscale)
        f.addRow(self.btn_grayscale)
        filters_group.setLayout(f)
        right.addWidget(filters_group)

        export_group = QGroupBox("Export")
        ef = QFormLayout()
        self.btn_export_mp4 = QPushButton(QIcon(".vscode/resources/icons/export.png"), "Export MP4", clicked=lambda: self.export_as(ext="mp4"))
        ef.addRow(self.btn_export_mp4)
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
        self.play_btn = QPushButton(QIcon(".vscode/resources/icons/play.png"), "Play", clicked=self.toggle_play)
        self.seek = QSlider(Qt.Orientation.Horizontal, sliderMoved=self._on_seek_slider)
        self.time_label = QLabel("00:00 / 00:00")
        bar.addWidget(self.play_btn)
        bar.addWidget(self.seek, 1)
        bar.addWidget(self.time_label)
        vbox.addLayout(bar)
        return container

    def _build_menubar(self):
        menubar = self.menuBar()

        # File
        m_file = menubar.addMenu("&File")
        act_open = QAction(QIcon("resources/icons/video.png"), "Open", self)
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

        act_menu = QAction("Back to Home Screen", self)
        act_menu.triggered.connect(self.back_to_menu)
    
        for a in (act_open, act_save_as, act_export, act_menu):
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
        m_tools.addAction("Rotate 90° CW", lambda: self.rotate_video(transpose=1))
        m_tools.addAction("Remove Audio", self.remove_audio)
        m_tools.addAction("Grayscale", self.apply_grayscale)

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

    def _fmt_time(self, ms: int) -> str:
        t = max(0, ms // 1000)
        return f"{t // 60:02d}:{t % 60:02d}"

    def _on_position_changed(self, pos: int):
        if not self.seek.isSliderDown():
            self.seek.setValue(pos)
        self.time_label.setText(f"{self._fmt_time(pos)} / {self._fmt_time(self.media_player.duration())}")

    def _on_duration_changed(self, dur: int):
        self.seek.setRange(0, dur)
        self._on_position_changed(self.media_player.position())

    def _on_playback_changed(self, state):
        self.play_btn.setText("Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "Play")
        self.playing = state == QMediaPlayer.PlaybackState.PlayingState

    def toggle_play(self):
        if not self.current_path:
            return
        self.media_player.play() if not self.playing else self.media_player.pause()

    def _on_seek_slider(self, value: int):
        if self.current_path:
            self.media_player.setPosition(value)
            self._on_position_changed(value)

    def _player_guard(self):
        if self.is_processing:
            self.media_player.pause()

    def _load_into_player(self, path: str, autoplay: bool = False):
        try:
            if not os.path.exists(path):
                raise FileNotFoundError(f"Video file not found: {path}")
            self.current_path = path
            self.media_player.setSource(QUrl.fromLocalFile(path))
            if autoplay:
                self.media_player.play()
        except Exception as ex:
            QMessageBox.critical(self, "Playback Error", str(ex))

    def _reset_history(self):
        self.history.clear()
        self.redo_stack.clear()

    def _push_history(self, new_path: str):
        self.history.append(new_path)
        if len(self.history) > 50:
            old = self.history.pop(0)
            if os.path.exists(old) and old != self.current_path:
                os.remove(old)
        self.redo_stack.clear()
        self.btn_undo.setEnabled(len(self.history) > 1)
        self.btn_redo.setEnabled(bool(self.redo_stack))

    def undo(self):
        if len(self.history) <= 1:
            self._status("Nothing to undo")
            return
        self.redo_stack.append(self.history.pop())
        self._load_into_player(self.history[-1], autoplay=True)
        self._status("Undid last action")
        self.btn_undo.setEnabled(len(self.history) > 1)
        self.btn_redo.setEnabled(bool(self.redo_stack))

    def redo(self):
        if not self.redo_stack:
            self._status("Nothing to redo")
            return
        self.history.append(self.redo_stack.pop())
        self._load_into_player(self.history[-1], autoplay=True)
        self._status("Redid last action")
        self.btn_undo.setEnabled(len(self.history) > 1)
        self.btn_redo.setEnabled(bool(self.redo_stack))

    def reset_to_original(self):
        if not self.original_path:
            return
        fresh = self._mk_working_copy(self.original_path)
        self._reset_history()
        self._push_history(fresh)
        self._load_into_player(fresh, autoplay=True)
        self._status("Reset to original")

    def open_video(self):
        if self.is_processing:
            QMessageBox.warning(self, "Please wait", "Operation in progress.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open Video", "", "Video Files (*.mp4 *.mov *.mkv *.avi *.wmv *.flv)")
        if not path or not os.path.exists(path):
            return
        if not os.access(self.temp_dir, os.W_OK):
            QMessageBox.critical(self, "Error", "Cannot write to temp directory.")
            return
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
        out, _ = QFileDialog.getSaveFileName(self, "Save As", f"edited_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4", "MP4 (*.mp4)")
        if out:
            try:
                shutil.copy2(self.current_path, out)
                self._status(f"Saved: {os.path.basename(out)}")
            except Exception as ex:
                QMessageBox.critical(self, "Save Failed", str(ex))

    def export_as(self, ext="mp4"):
        if not self.current_path:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        out, _ = QFileDialog.getSaveFileName(self, "Export", f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}", f"{ext.upper()} (*.{ext})")
        if out:
            ff = ["-y", "-i", self.current_path, "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]
            self._run_ffmpeg_async(ff, f"Exported: {os.path.basename(out)}", out)

    def closeEvent(self, event):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        super().closeEvent(event)

    def trim_video(self):
        if not self.current_path:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Trim Video")
        layout = QFormLayout()
        start_spin = QDoubleSpinBox(maximum=10**7, decimals=2, value=0.0)
        end_spin = QDoubleSpinBox(maximum=10**7, decimals=2, value=self.media_player.duration() / 1000.0 or 5.0)
        layout.addRow("Start time (s):", start_spin)
        layout.addRow("End time (s):", end_spin)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        dialog.setLayout(layout)
        if dialog.exec() == QDialog.DialogCode.Accepted and end_spin.value() > start_spin.value():
            start_time, end_time = start_spin.value(), end_spin.value()  # Capture values before dialog closes
            out_file = self._temp_name("trim", "mp4")
            ff_try_copy = ["-y", "-ss", f"{start_time}", "-to", f"{end_time}", "-i", self.current_path, "-c", "copy", "-movflags", "+faststart", out_file]
            def worker():
                ok, _ = self._run_ffmpeg_blocking(ff_try_copy)
                if not ok:
                    ff_reencode = ["-y", "-ss", f"{start_time}", "-to", f"{end_time}", "-i", self.current_path, "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out_file]
                    ok, err = self._run_ffmpeg_blocking(ff_reencode)
                    if not ok:
                        self._post_event(False, f"Trim failed: {err}")
                        return
                self._post_event(True, f"Trimmed {start_time:.2f}s → {end_time:.2f}s", out_file)
            self._start_worker(worker, "Trimming...")
        elif end_spin.value() <= start_spin.value():
            QMessageBox.critical(self, "Invalid Range", "End must be greater than Start.")

    def change_speed(self):
        if not self.current_path:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Change Speed")
        layout = QFormLayout()
        factor_spin = QDoubleSpinBox(minimum=0.25, maximum=4.0, decimals=2, value=1.0)
        layout.addRow("Speed factor:", factor_spin)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        dialog.setLayout(layout)
        if dialog.exec() == QDialog.DialogCode.Accepted and factor_spin.value() != 1.0:
            factor = factor_spin.value()
            setpts = f"setpts={1.0/factor}*PTS"
            a_filters = []
            remaining = factor
            while remaining > 2.0 + 1e-6:
                a_filters.append("atempo=2.0")
                remaining /= 2.0
            while remaining < 0.5 - 1e-6:
                a_filters.append("atempo=0.5")
                remaining *= 2.0
            a_filters.append(f"atempo={remaining:.6f}")
            out_file = self._temp_name(f"speedx{factor}", "mp4")
            ff = ["-y", "-i", self.current_path, "-filter:v", setpts, "-filter:a", ",".join(a_filters), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out_file]
            self._run_ffmpeg_async(ff, f"Speed x{factor}", out_file)

    def rotate_video(self, transpose=1):
        if not self.current_path:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        out_file = self._temp_name("rotate", "mp4")
        ff = ["-y", "-i", self.current_path, "-vf", f"transpose={transpose}", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "copy", "-movflags", "+faststart", out_file]
        self._run_ffmpeg_async(ff, "Rotated 90° CW", out_file)

    def remove_audio(self):
        if not self.current_path:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        out_file = self._temp_name("mute", "mp4")
        ff = ["-y", "-i", self.current_path, "-c:v", "copy", "-an", "-movflags", "+faststart", out_file]
        self._run_ffmpeg_async(ff, "Audio removed", out_file)

    def apply_grayscale(self):
        if not self.current_path:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        out_file = self._temp_name("grayscale", "mp4")
        ff = ["-y", "-i", self.current_path, "-vf", "hue=s=0", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "copy", "-movflags", "+faststart", out_file]
        self._run_ffmpeg_async(ff, "Applied Grayscale", out_file)

    @staticmethod
    def _which_ffmpeg() -> str | None:
        exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        for p in os.environ.get("PATH", "").split(os.pathsep):
            cand = os.path.join(p, exe)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return exe
        return None

    def _run_ffmpeg_blocking(self, args: list[str]) -> tuple[bool, str]:
        ff = self._which_ffmpeg()
        if not ff:
            return False, "FFmpeg not found. Install it and add to PATH. Visit https://ffmpeg.org/download.html."
        try:
            subprocess.run([ff] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True, encoding='utf-8')
            return os.path.exists(args[-1]), ""
        except subprocess.CalledProcessError as ex:
            return False, ex.stderr.strip()[-1000:] or "FFmpeg error"
        except FileNotFoundError:
            return False, "FFmpeg not found in PATH."
        except Exception as ex:
            return False, str(ex)

    def _run_ffmpeg_async(self, ff_args: list[str], success_msg: str, final_out: str):
        def worker():
            ok, err = self._run_ffmpeg_blocking(ff_args)
            self._post_event(ok, success_msg if ok else err, final_out if ok else None)
        self._start_worker(worker, "Processing...")

    def _start_worker(self, target, busy_msg: str):
        if self.is_processing:
            QMessageBox.warning(self, "Please wait", "Operation in progress.")
            return
        if not self._which_ffmpeg():
            QMessageBox.critical(self, "FFmpeg Not Found", "FFmpeg is required. Install it and add to PATH. Visit https://ffmpeg.org/download.html.")
            return
        self.is_processing = True
        self._status(busy_msg, ms=0)
        threading.Thread(target=target, daemon=True).start()

    def _post_event(self, ok: bool, msg: str, out_path: str | None = None):
        QApplication.instance().postEvent(self, OpCompleteEvent(ok, msg, out_path))

    def _temp_name(self, tag: str, ext: str) -> str:
        return os.path.join(self.temp_dir, f"{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{os.getpid()}.{ext}")

    def _mk_working_copy(self, src: str) -> str:
        ext = os.path.splitext(src)[1].lstrip(".").lower() or "mp4"
        dst = self._temp_name("working", ext)
        shutil.copy2(src, dst)
        return dst

if __name__ == "__main__":
    app = QApplication(sys.argv)
    editor = VideoEditor()
    editor.show()
    sys.exit(app.exec())
