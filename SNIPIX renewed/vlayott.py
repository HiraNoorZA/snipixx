import sys
import os
from datetime import datetime
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSlider, QScrollArea, QMessageBox, QGroupBox, QComboBox, QFormLayout,
    QFileDialog, QInputDialog, QColorDialog, QApplication
)
from PyQt6.QtCore import Qt, QTimer, QEvent, QUrl
from PyQt6.QtGui import QIcon, QKeySequence, QAction, QColor
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
from moviepy.video.VideoClip import ColorClip, TextClip
from moviepy.video.fx.all import speedx, blackwhite, colorx, lum_contrast, crop, rotate
from moviepy.audio.io.AudioFileClip import AudioFileClip
import threading
try:
    import whisper
except ImportError:
    whisper = None

class VideoEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SNIPIX – Video Editor")
        self.setWindowIcon(QIcon("resources/icons/SnipixLogo.png"))
        self.resize(1200, 800)

        # Styling
        self.COLOR_BG = "#e5f0fd"
        self.COLOR_SURF = "#ffffff"
        self.COLOR_ACCENT = "#cab4f5"
        self.COLOR_TEXT = "#111827"
        self.COLOR_MUTED = "#e5e7eb"

        self.setStyleSheet(f"""
            QMainWindow {{
                background: {self.COLOR_BG};
            }}
            QMenuBar {{
                background: {self.COLOR_SURF};
                color: {self.COLOR_TEXT};
                border-bottom: 1px solid {self.COLOR_MUTED};
            }}
            QMenuBar::item:selected {{
                background: {self.COLOR_MUTED};
            }}
            QLabel {{
                color: {self.COLOR_TEXT};
            }}
            QGroupBox {{
                color: {self.COLOR_TEXT};
                background: {self.COLOR_SURF};
                border: 1px solid {self.COLOR_MUTED};
                border-radius: 10px;
                margin-top: 12px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }}
            QPushButton {{
                background: {self.COLOR_ACCENT};
                color: black;
                border: none;
                padding: 8px 10px;
                border-radius: 8px;
            }}
            QPushButton:hover {{ opacity: 0.95; }}
            QPushButton:disabled {{ background: #cbd5e1; color: #6b7280; }}
            QSlider::groove:horizontal {{
                height: 6px;
                background: {self.COLOR_MUTED};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                width: 16px;
                background: {self.COLOR_ACCENT};
                border-radius: 8px;
                margin: -6px 0;
            }}
            QComboBox {{
                background: {self.COLOR_SURF};
                border: 1px solid {self.COLOR_MUTED};
                padding: 6px 8px;
                border-radius: 6px;
            }}
        """)

        # Video state
        self.original_video = None
        self.current_video = None
        self.history = []
        self.redo_stack = []
        self.playing = False
        self.is_processing = False
        self.saving_thread = None
        self.temp_file = None

        # Media player for video and audio playback
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.positionChanged.connect(self.update_slider)
        self.media_player.durationChanged.connect(self.update_duration)
        self.media_player.playbackStateChanged.connect(self.update_play_button)

        # Central layout
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # Left panel
        root.addLayout(self.create_left_panel(), 1)

        # Canvas
        root.addWidget(self.create_canvas(), 4)

        # Right panel
        root.addLayout(self.create_right_panel(), 1)

        # Status bar
        self.status = self.statusBar()
        self.status.showMessage("Welcome to SNIPIX Video Editor – Ready")

        # Menu bar
        self.create_menu_bar()

        # Welcome message
        self.show_welcome()

        # Timer for processing updates
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.player_loop)
        self.timer.start(100)

    def _status(self, msg: str, ms: int = 4000):
        self.status.showMessage(msg, ms)

    def create_left_panel(self):
        left = QVBoxLayout()
        left.setSpacing(12)

        # File operations
        file_group = QGroupBox("File")
        f = QVBoxLayout()
        self.btn_open = QPushButton(QIcon("resources/icons/open.png"), "Open Video")
        self.btn_open.clicked.connect(self.open_video)
        f.addWidget(self.btn_open)
        self.btn_save = QPushButton(QIcon("resources/icons/save.png"), "Save Video")
        self.btn_save.clicked.connect(self.save_video)
        f.addWidget(self.btn_save)
        file_group.setLayout(f)
        left.addWidget(file_group)

        # Filters
        filter_group = QGroupBox("Filters")
        f = QVBoxLayout()
        self.btn_grayscale = QPushButton(QIcon("resources/icons/grayscale.png"), "Grayscale")
        self.btn_grayscale.clicked.connect(self.apply_grayscale)
        f.addWidget(self.btn_grayscale)
        self.btn_brightness = QPushButton(QIcon("resources/icons/brightness.png"), "Brightness")
        self.btn_brightness.clicked.connect(self.adjust_brightness)
        f.addWidget(self.btn_brightness)
        self.btn_contrast = QPushButton(QIcon("resources/icons/contrast.png"), "Contrast")
        self.btn_contrast.clicked.connect(self.adjust_contrast)
        f.addWidget(self.btn_contrast)
        filter_group.setLayout(f)
        left.addWidget(filter_group)

        # Edit
        edit_group = QGroupBox("Edit")
        e = QVBoxLayout()
        self.btn_undo = QPushButton(QIcon("resources/icons/undo.png"), "Undo")
        self.btn_undo.clicked.connect(self.undo)
        e.addWidget(self.btn_undo)
        self.btn_redo = QPushButton(QIcon("resources/icons/redo.png"), "Redo")
        self.btn_redo.clicked.connect(self.redo)
        e.addWidget(self.btn_redo)
        self.btn_reset = QPushButton(QIcon("resources/icons/reset.png"), "Reset")
        self.btn_reset.clicked.connect(self.reset_video)
        e.addWidget(self.btn_reset)
        edit_group.setLayout(e)
        left.addWidget(edit_group)

        left.addStretch()
        return left

    def create_right_panel(self):
        right = QVBoxLayout()
        right.setSpacing(12)

        # Operations
        ops_group = QGroupBox("Operations")
        o = QVBoxLayout()
        self.btn_trim = QPushButton(QIcon("resources/icons/crop.png"), "Trim")
        self.btn_trim.clicked.connect(self.trim_video)
        o.addWidget(self.btn_trim)
        self.btn_add_text = QPushButton(QIcon("resources/icons/addText.png"), "Add Text")
        self.btn_add_text.clicked.connect(self.add_text)
        o.addWidget(self.btn_add_text)
        self.btn_captions = QPushButton(QIcon("resources/icons/captions.png"), "Generate Captions")
        self.btn_captions.clicked.connect(self.generate_captions)
        o.addWidget(self.btn_captions)
        self.btn_rotate = QPushButton(QIcon("resources/icons/rotate.png"), "Rotate 90°")
        self.btn_rotate.clicked.connect(self.rotate_video)
        o.addWidget(self.btn_rotate)
        self.btn_speed = QPushButton(QIcon("resources/icons/speed.png"), "Speed Change")
        self.btn_speed.clicked.connect(self.change_speed)
        o.addWidget(self.btn_speed)
        self.btn_bg = QPushButton(QIcon("resources/icons/bgColor.png"), "Set Background")
        self.btn_bg.clicked.connect(self.set_background)
        o.addWidget(self.btn_bg)
        self.btn_crop = QPushButton(QIcon("resources/icons/crop.png"), "Crop")
        self.btn_crop.clicked.connect(self.crop_video)
        o.addWidget(self.btn_crop)
        self.btn_remove_audio = QPushButton(QIcon("resources/icons/mute.png"), "Remove Audio")
        self.btn_remove_audio.clicked.connect(self.remove_audio)
        o.addWidget(self.btn_remove_audio)
        ops_group.setLayout(o)
        right.addWidget(ops_group)

        # Export Options
        export_group = QGroupBox("Export Options")
        form = QFormLayout()
        self.combo_format = QComboBox()
        self.combo_format.addItems(["MP4", "AVI"])
        form.addRow("Format", self.combo_format)
        self.btn_export = QPushButton(QIcon("resources/icons/export.png"), "Export")
        self.btn_export.clicked.connect(self.save_video)
        form.addRow(self.btn_export)
        export_group.setLayout(form)
        right.addWidget(export_group)

        right.addStretch()
        return right

    def create_canvas(self):
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setSpacing(10)

        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background-color: black;")
        self.media_player.setVideoOutput(self.video_widget)
        vbox.addWidget(self.video_widget, 1)

        # Transport bar
        bar = QHBoxLayout()
        self.play_btn = QPushButton(QIcon("resources/icons/play.png"), "Play")
        self.play_btn.clicked.connect(self.toggle_play)
        bar.addWidget(self.play_btn)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.valueChanged.connect(self.on_seek)
        bar.addWidget(self.seek, 1)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setStyleSheet("color: #111827;")
        bar.addWidget(self.time_label)
        vbox.addLayout(bar)

        return container

    def create_menu_bar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        act_open = QAction(QIcon("resources/icons/open.png"), "Open Video", self, shortcut=QKeySequence("Ctrl+O"), triggered=self.open_video)
        act_save = QAction(QIcon("resources/icons/save.png"), "Save Video", self, shortcut=QKeySequence("Ctrl+S"), triggered=self.save_video)
        act_exit = QAction(QIcon("resources/icons/exit.png"), "Exit", self, triggered=self.close)
        file_menu.addAction(act_open)
        file_menu.addAction(act_save)
        file_menu.addSeparator()
        file_menu.addAction(act_exit)

        edit_menu = menubar.addMenu("Edit")
        act_undo = QAction(QIcon("resources/icons/undo.png"), "Undo", self, shortcut=QKeySequence("Ctrl+Z"), triggered=self.undo)
        act_redo = QAction(QIcon("resources/icons/redo.png"), "Redo", self, shortcut=QKeySequence("Ctrl+Y"), triggered=self.redo)
        act_reset = QAction(QIcon("resources/icons/reset.png"), "Reset", self, shortcut=QKeySequence("Ctrl+R"), triggered=self.reset_video)
        edit_menu.addAction(act_undo)
        edit_menu.addAction(act_redo)
        edit_menu.addAction(act_reset)

    def show_welcome(self):
        self.video_widget.setStyleSheet("background-color: #f8fafc;")
        self._status("Welcome to SNIPIX Video Editor – Ready")

    def fmt_time(self, ms):
        t = max(0, ms // 1000)
        m = int(t // 60)
        s = int(t % 60)
        return f"{m:02d}:{s:02d}"

    def update_time_label(self):
        position = self.media_player.position()
        duration = self.media_player.duration()
        self.time_label.setText(f"{self.fmt_time(position)} / {self.fmt_time(duration)}")

    def update_slider(self, position):
        if not self.seek.isSliderDown():
            self.seek.setValue(position)
        self.update_time_label()

    def update_duration(self, duration):
        self.seek.setMaximum(duration)
        self.update_time_label()

    def update_play_button(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setText("Pause")
            self.playing = True
        else:
            self.play_btn.setText("Play")
            self.playing = False

    def refresh_info(self):
        if self.current_video:
            w, h = self.current_video.size
            fps = getattr(self.current_video, "fps", 25)
            duration = self.current_video.duration
            self._status(f"Duration: {duration:.2f}s | FPS: {fps:.2f} | Size: {w}x{h}", 0)
        else:
            self._status("No video loaded")

    def push_history(self):
        if self.current_video:
            self.history.append(self.current_video)
            if len(self.history) > 15:
                self.history.pop(0)
            self.redo_stack.clear()

    def open_video(self):
        if self.is_processing:
            QMessageBox.warning(self, "Please wait", "An operation is already running.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open Video", "", "Video Files (*.mp4 *.avi *.mov *.mkv *.wmv *.flv)")
        if not path:
            return
        try:
            self._status(f"Loading {os.path.basename(path)} ...")
            clip = VideoFileClip(path)
            self.original_video = clip
            self.current_video = clip
            self.duration = float(clip.duration or 0.0)
            self.history.clear()
            self.redo_stack.clear()
            self.push_history()
            self.media_player.setSource(QUrl.fromLocalFile(path))
            self.playing = True
            self.media_player.play()
            self.refresh_info()
            self._status("Loaded")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load video: {e}")
            self._status("Ready")

    def save_video(self):
        if not self.current_video:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        if self.is_processing:
            QMessageBox.warning(self, "Please wait", "Another process is running.")
            return
        default_name = f"edited_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{self.combo_format.currentText().lower()}"
        path, _ = QFileDialog.getSaveFileName(self, "Save Video", default_name, "MP4 (*.mp4);;AVI (*.avi)")
        if not path:
            return
        self.is_processing = True
        self._status("Saving video...")
        def do_save():
            ok = True
            err = ""
            try:
                codec = "libx264" if path.endswith(".mp4") else "mpeg4"
                audio_codec = "aac" if self.current_video.audio else None
                self.current_video.write_videofile(path, codec=codec, audio_codec=audio_codec, threads=4, logger=None)
            except Exception as ex:
                ok = False
                err = str(ex)
            self.is_processing = False
            QApplication.instance().postEvent(self, SaveCompleteEvent(ok, err, path))
        self.saving_thread = threading.Thread(target=do_save, daemon=True)
        self.saving_thread.start()

    def customEvent(self, event):
        if isinstance(event, SaveCompleteEvent):
            self.on_save_complete(event.success, event.error, event.path)
        elif isinstance(event, CaptionCompleteEvent):
            self.on_caption_complete(event.success, event.error)

    def on_save_complete(self, ok, err, path):
        self.is_processing = False
        if ok:
            QMessageBox.information(self, "Saved", f"Video saved: {os.path.basename(path)}")
            self.media_player.setSource(QUrl.fromLocalFile(path))
        else:
            QMessageBox.critical(self, "Error", f"Failed to save video: {err}")
        self._status("Ready")

    def on_caption_complete(self, ok, err):
        self.is_processing = False
        if ok:
            temp_path = f"temp_captioned_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            self.current_video.write_videofile(temp_path, codec="libx264", audio_codec="aac" if self.current_video.audio else None, threads=4, logger=None)
            self.media_player.setSource(QUrl.fromLocalFile(temp_path))
            self.temp_file = temp_path
            self._status("Captions generated")
        else:
            QMessageBox.critical(self, "Error", f"Failed to generate captions: {err}")
            self._status("Ready")

    def toggle_play(self):
        if not self.current_video:
            return
        if self.playing:
            self.media_player.pause()
        else:
            self.media_player.play()

    def on_seek(self, value):
        if not self.current_video:
            return
        self.media_player.setPosition(value)
        self.update_time_label()

    def player_loop(self):
        if self.is_processing:
            self.media_player.pause()

    def undo(self):
        if len(self.history) > 1:
            last = self.history.pop()
            self.redo_stack.append(last)
            self.current_video = self.history[-1]
            self.duration = float(self.current_video.duration or 0.0)
            self.seek.setMaximum(int(self.duration * 1000))
            self.refresh_info()
            self._status("Undid last action")
            self.update_media_source()
        else:
            self._status("Nothing to undo")

    def redo(self):
        if self.redo_stack:
            self.push_history()
            self.current_video = self.redo_stack.pop()
            self.duration = float(self.current_video.duration or 0.0)
            self.seek.setMaximum(int(self.duration * 1000))
            self.refresh_info()
            self._status("Redid last action")
            self.update_media_source()
        else:
            self._status("Nothing to redo")

    def reset_video(self):
        if self.original_video:
            self.push_history()
            self.current_video = self.original_video
            self.duration = float(self.current_video.duration or 0.0)
            self.seek.setMaximum(int(self.duration * 1000))
            self.refresh_info()
            self._status("Reset to original")
            self.update_media_source()

    def update_media_source(self):
        if self.current_video:
            temp_path = f"temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            self.current_video.write_videofile(temp_path, codec="libx264", audio_codec="aac" if self.current_video.audio else None, threads=4, logger=None)
            self.media_player.setSource(QUrl.fromLocalFile(temp_path))
            self.temp_file = temp_path
            if self.playing:
                self.media_player.play()

    def trim_video(self):
        if not self.current_video:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        d = QInputDialog(self)
        d.setWindowTitle("Trim Video")
        d.setLabelText(f"Duration: {self.current_video.duration:.2f}s\nStart (s):")
        d.setInputMode(QInputDialog.InputMode.DoubleInput)
        d.setDoubleValue(0.0)
        d.setDoubleMinimum(0.0)
        if d.exec():
            start = d.doubleValue()
            d.setLabelText("End (s):")
            d.setDoubleValue(self.current_video.duration)
            d.setDoubleMaximum(self.current_video.duration)
            if d.exec():
                end = d.doubleValue()
                if start < 0 or end <= start or end > self.current_video.duration + 1e-6:
                    QMessageBox.critical(self, "Error", "Invalid trim range.")
                    return
                try:
                    self.push_history()
                    self.current_video = self.current_video.subclip(start, end)
                    self.duration = float(self.current_video.duration or 0.0)
                    self.seek.setMaximum(int(self.duration * 1000))
                    self.refresh_info()
                    self._status(f"Trimmed {start:.2f}s → {end:.2f}s")
                    self.update_media_source()
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Trim failed: {e}")

    def add_text(self):
        if not self.current_video:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        text, ok = QInputDialog.getText(self, "Add Text", "Enter text:")
        if not ok or not text:
            return
        try:
            duration = self.current_video.duration
            text_clip = TextClip(text, fontsize=48, color="white", font="Arial-Bold").set_duration(duration).set_position("center")
            self.push_history()
            self.current_video = CompositeVideoClip([self.current_video, text_clip])
            self.duration = float(self.current_video.duration or 0.0)
            self._status("Text added")
            self.update_media_source()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add text: {e}")

    def generate_captions(self):
        if not self.current_video:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        if whisper is None:
            QMessageBox.critical(self, "Error", "Whisper not installed. Install with `pip install openai-whisper`.")
            return
        if self.is_processing:
            QMessageBox.warning(self, "Please wait", "Another process is running.")
            return
        self.is_processing = True
        self._status("Generating captions...")
        def do_generate():
            ok = True
            err = ""
            try:
                if self.current_video.audio is None:
                    ok = False
                    err = "No audio in video."
                else:
                    temp_audio = "temp_audio.wav"
                    self.current_video.audio.write_audiofile(temp_audio, logger=None)
                    model = whisper.load_model("tiny")
                    result = whisper.transcribe(model, temp_audio, verbose=False)
                    captions = []
                    for segment in result["segments"]:
                        text = segment["text"].strip()
                        start = segment["start"]
                        end = segment["end"]
                        if text:
                            captions.append((text, start, end))
                    if captions:
                        text_clips = []
                        for text, start, end in captions:
                            text_clip = TextClip(
                                text, fontsize=32, color="white", font="Arial-Bold",
                                stroke_color="black", stroke_width=1
                            ).set_position(("center", "bottom")).set_start(start).set_end(end)
                            text_clips.append(text_clip)
                        self.push_history()
                        self.current_video = CompositeVideoClip([self.current_video] + text_clips)
                        self.duration = float(self.current_video.duration or 0.0)
                    else:
                        ok = False
                        err = "No captions generated from audio."
            except Exception as ex:
                ok = False
                err = str(ex)
            finally:
                if os.path.exists(temp_audio):
                    os.remove(temp_audio)
                self.is_processing = False
                QApplication.instance().postEvent(self, CaptionCompleteEvent(ok, err))
        threading.Thread(target=do_generate, daemon=True).start()

    def rotate_video(self):
        if not self.current_video:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        try:
            self.push_history()
            self.current_video = self.current_video.fx(rotate, 90)
            self.duration = float(self.current_video.duration or 0.0)
            self.refresh_info()
            self._status("Rotated 90°")
            self.update_media_source()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Rotate failed: {e}")

    def change_speed(self):
        if not self.current_video:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        factor, ok = QInputDialog.getDouble(self, "Speed", "Factor (0.5 = half, 2.0 = double):", 1.0, 0.1, 10.0, 1)
        if not ok:
            return
        try:
            self.push_history()
            self.current_video = self.current_video.fx(speedx, factor=factor)
            self.duration = float(self.current_video.duration or 0.0)
            self.seek.setMaximum(int(self.duration * 1000))
            self.refresh_info()
            self._status(f"Speed x{factor}")
            self.update_media_source()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Speed change failed: {e}")

    def set_background(self):
        if not self.current_video:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        color = QColorDialog.getColor(title="Choose Background Color", parent=self)
        if not color.isValid():
            return
        try:
            self.push_history()
            w, h = self.current_video.size
            bg = ColorClip(size=(w, h), color=(color.red(), color.green(), color.blue()), duration=self.current_video.duration)
            self.current_video = CompositeVideoClip([bg, self.current_video.set_position("center")])
            self.duration = float(self.current_video.duration or 0.0)
            self._status("Background applied")
            self.update_media_source()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Background failed: {e}")

    def crop_video(self):
        if not self.current_video:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        w, h = self.current_video.size
        x1, ok = QInputDialog.getInt(self, "Crop Video", f"Current size: {w}x{h}\nx1:", 0, 0, w)
        if not ok:
            return
        y1, ok = QInputDialog.getInt(self, "Crop Video", "y1:", 0, 0, h)
        if not ok:
            return
        width, ok = QInputDialog.getInt(self, "Crop Video", "width:", w // 2, 1, w - x1)
        if not ok:
            return
        height, ok = QInputDialog.getInt(self, "Crop Video", "height:", h // 2, 1, h - y1)
        if not ok:
            return
        x2 = x1 + width
        y2 = y1 + height
        if x1 < 0 or y1 < 0 or x2 > w or y2 > h or width <= 0 or height <= 0:
            QMessageBox.critical(self, "Error", "Invalid crop rectangle.")
            return
        try:
            self.push_history()
            self.current_video = self.current_video.fx(crop, x1=x1, y1=y1, x2=x2, y2=y2)
            self.duration = float(self.current_video.duration or 0.0)
            self.refresh_info()
            self._status(f"Cropped to {width}x{height}")
            self.update_media_source()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Crop failed: {e}")

    def apply_grayscale(self):
        if not self.current_video:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        try:
            self.push_history()
            self.current_video = self.current_video.fx(blackwhite)
            self._status("Applied grayscale")
            self.update_media_source()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Grayscale failed: {e}")

    def adjust_brightness(self):
        if not self.current_video:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        factor, ok = QInputDialog.getDouble(self, "Brightness", "Factor (1.0 = normal, 0.5 = darker, 2.0 = brighter):", 1.0, 0.1, 3.0, 1)
        if not ok:
            return
        try:
            self.push_history()
            self.current_video = self.current_video.fx(colorx, factor=factor)
            self._status(f"Brightness x{factor}")
            self.update_media_source()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Brightness failed: {e}")

    def adjust_contrast(self):
        if not self.current_video:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        factor, ok = QInputDialog.getDouble(self, "Contrast", "Factor (1.0 = normal, 0.5 = lower, 2.0 = higher):", 1.0, 0.1, 3.0, 1)
        if not ok:
            return
        try:
            contrast_delta = int((factor - 1.0) * 100)
            self.push_history()
            self.current_video = self.current_video.fx(lum_contrast, lum=0, contrast=contrast_delta, contrast_thr=128)
            self._status(f"Contrast {contrast_delta:+d}")
            self.update_media_source()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Contrast failed: {e}")

    def remove_audio(self):
        if not self.current_video:
            QMessageBox.warning(self, "No video", "Open a video first.")
            return
        if self.current_video.audio is None:
            self._status("No audio to remove")
            return
        try:
            self.push_history()
            self.current_video = self.current_video.without_audio()
            self._status("Audio removed")
            self.update_media_source()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to remove audio: {e}")

class SaveCompleteEvent(QEvent):
    def __init__(self, success, error, path):
        super().__init__(QEvent.Type.User)
        self.success = success
        self.error = error
        self.path = path

class CaptionCompleteEvent(QEvent):
    def __init__(self, success, error):
        super().__init__(QEvent.Type.User + 1)
        self.success = success
        self.error = error

if __name__ == "__main__":
    app = QApplication(sys.argv)
    editor = VideoEditor()
    editor.show()
    sys.exit(app.exec())