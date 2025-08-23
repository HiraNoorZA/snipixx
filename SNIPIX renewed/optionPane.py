import sys
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame, QMessageBox, QApplication
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QFont, QIcon
from ImageEditorScreen import ImageEditor
from ffmpegVE import VideoEditor


class OptionBox(QFrame):
    def __init__(self, parent, title, icon_path, description="", target_class=None):
        super().__init__()
        self.parent = parent
        self.target_class = target_class
        self.setFixedSize(300, 300)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Styling matching Pyqt6ImageEditor.py
        self.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
            }
            QFrame:hover {
                background-color: #f8fafc;
            }
        """)

        # Layout
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Icon
        icon_label = QLabel()
        icon = QPixmap(icon_path)
        if icon.isNull():
            icon_label.setText("📷" if "Photo" in title else "🎬")
            icon_label.setStyleSheet("font-size: 72px; color: #111827;")
        else:
            icon_label.setPixmap(icon.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        # Title
        title_label = QLabel(title)
        title_label.setStyleSheet("color: #111827; font-size: 24px; font-weight: bold;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # Description
        if description:
            desc_label = QLabel(description)
            desc_label.setStyleSheet("color: #111827; font-size: 16px;")
            desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)

        # Start button
        start_btn = QPushButton("Start Editing")
        start_btn.setFixedSize(200, 40)
        start_btn.setStyleSheet("""
            QPushButton {
                background: #cab4f5;
                color: #111827;
                border: none;
                padding: 8px 10px;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover { opacity: 0.95; }
            QPushButton:pressed { background: #e5e7eb; }
        """)
        if target_class:
            start_btn.clicked.connect(self.open_editor)
        else:
            start_btn.setEnabled(False)
            start_btn.clicked.connect(self.show_unavailable_message)
        layout.addWidget(start_btn)

    def open_editor(self):
        if self.target_class:
            self.parent.open_editor(self.target_class)
        else:
            self.show_unavailable_message()

    def show_unavailable_message(self):
        QMessageBox.warning(self.parent, "Feature Unavailable", "Video editing is not available. Please check if VideoEdtr.py is correctly set up.")

class OptionPane(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SNIPIX – Editing Studio")
        self.setWindowIcon(QIcon("resources/icons/SnipixLogo.png"))
        self.resize(1200, 768)
        self.setMinimumSize(800, 600)

        # Apply stylesheet matching Pyqt6ImageEditor.py
        self.setStyleSheet("""
            QMainWindow {
                background: #e5f0fd;
            }
            QLabel {
                color: #111827;
            }
        """)

        # Center the window
        self.center_on_screen()

        # Initialize UI
        self.initUI()

    def initUI(self):
        # Central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(0)

        # Welcome message
        welcome_label = QLabel("Welcome to SNIPIX")
        welcome_label.setStyleSheet("color: #111827; font-size: 36px; font-weight: bold;")
        welcome_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(welcome_label)

        # Subtitle
        subtitle_label = QLabel("Choose your editing project type")
        subtitle_label.setStyleSheet("color: #111827; font-size: 18px;")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(subtitle_label)

        # Options container
        options_container = QWidget()
        options_layout = QHBoxLayout(options_container)
        options_layout.setContentsMargins(0, 40, 0, 40)
        options_layout.setSpacing(40)
        options_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Photo editing box
        photo_box = OptionBox(
            self,
            "Photo Editing",
            "resources/icons/photo.png",
            "Edit, enhance, and transform your photos",
            ImageEditor
        )

        # Video editing box
        video_box = OptionBox(
            self,
            "Video Editing",
            "resources/icons/video.png",
            "Create stunning videos with editing capabilities",
            VideoEditor
        )

        # Add boxes to layout
        options_layout.addWidget(photo_box)
        options_layout.addWidget(video_box)

        # Add to main layout
        main_layout.addWidget(options_container)
        main_layout.addStretch()

        # Footer
        footer = QLabel("© 2025 SNIPIX Studio. All rights reserved.")
        footer.setStyleSheet("color: #111827; padding: 10px;")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(footer)

    def center_on_screen(self):
        screen_geometry = QApplication.primaryScreen().geometry()
        x = (screen_geometry.width() - self.width()) // 2
        y = (screen_geometry.height() - self.height()) // 2
        self.move(x, y)

    def open_editor(self, editor_class):
        try:
            old_widget = self.centralWidget()
            if old_widget is not None:
                old_widget.deleteLater()
            editor = editor_class()
            editor.show()
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open editor: {e}")

    def sizeHint(self):
        return QSize(1200, 768)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = OptionPane()
    window.show()
    sys.exit(app.exec())