import sys
from PyQt6.QtWidgets import (
    QMainWindow, QCheckBox, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QIcon
from ImageEditorScreen import ImageEditor
from ffmpegVE import VideoEditor


class OptionPane(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SNIPIX – Editing Studio")
        self.setWindowIcon(QIcon("resources/icons/SnipixLogo.png"))
        self.resize(1200, 768)
        self.setMinimumSize(800, 600)

        self.center_on_screen()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)
        self.main_layout.setContentsMargins(40, 40, 40, 40)

        self.initUI()

    def initUI(self):
        # Dark mode checkbox
        checkbox_container = QWidget()
        checkbox_layout = QHBoxLayout(checkbox_container)
        checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dark_mode = QCheckBox("Dark Mode")
        self.dark_mode.setChecked(False)
        checkbox_layout.addWidget(self.dark_mode)
        self.main_layout.addWidget(checkbox_container)

        # Welcome
        welcome_label = QLabel("Welcome to SNIPIX")
        welcome_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_label.setObjectName("welcome")
        self.main_layout.addWidget(welcome_label)

        # Subtitle
        subtitle_label = QLabel("Choose your editing project type")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle_label.setObjectName("subtitle")
        self.main_layout.addWidget(subtitle_label)

        # Options container
        options_container = QWidget()
        options_layout = QHBoxLayout(options_container)
        options_layout.setContentsMargins(0, 40, 0, 40)
        options_layout.setSpacing(40)
        options_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        options_layout.addWidget(self.create_option_box(
            "Photo Editing",
            "resources/icons/photo.png",
            "Edit, enhance, and transform your photos",
            ImageEditor
        ))
        options_layout.addWidget(self.create_option_box(
            "Video Editing",
            "resources/icons/video.png",
            "Create stunning videos with editing capabilities",
            VideoEditor
        ))

        self.main_layout.addWidget(options_container)
        self.main_layout.addStretch()

        # Footer
        footer = QLabel("© 2025 SNIPIX Studio. All rights reserved.")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setObjectName("footer")
        self.main_layout.addWidget(footer)

        # Mode toggle
        self.dark_mode.stateChanged.connect(self.apply_styles)
        self.apply_styles()

    def create_option_box(self, title, icon_path, description, target_class=None):
        box = QFrame()
        box.setFixedSize(300, 300)
        box.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(box)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Icon
        icon_label = QLabel()
        icon = QPixmap(icon_path)
        if icon.isNull():
            icon_label.setText("📷" if "Photo" in title else "🎬")
            icon_label.setStyleSheet("font-size: 72px;")
        else:
            icon_label.setPixmap(icon.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        # Title
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setObjectName("title")
        layout.addWidget(title_label)

        # Description
        if description:
            desc_label = QLabel(description)
            desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            desc_label.setWordWrap(True)
            desc_label.setObjectName("description")
            layout.addWidget(desc_label)

        # Start button
        start_btn = QPushButton("Start Editing")
        start_btn.setFixedSize(200, 40)
        if target_class:
            start_btn.clicked.connect(lambda: self.open_editor(target_class))
        else:
            start_btn.setEnabled(False)
            start_btn.clicked.connect(self.show_unavailable_message)
        layout.addWidget(start_btn)

        return box

    def show_unavailable_message(self):
        QMessageBox.warning(self, "Feature Unavailable", "Video editing is not available.")

    def center_on_screen(self):
        screen_geometry = QApplication.primaryScreen().geometry()
        x = (screen_geometry.width() - self.width()) // 2
        y = (screen_geometry.height() - self.height()) // 2
        self.move(x, y)

    def apply_styles(self):
        if self.dark_mode.isChecked():
            # Dark mode
            self.setStyleSheet("""
                QMainWindow { background: #18181b; }
                QLabel { color: #e5e7eb; }
                #welcome { font-size: 36px; font-weight: bold; }
                #subtitle { font-size: 18px; }
                #title { font-size: 24px; font-weight: bold; }
                #description { font-size: 16px; }
                #footer { padding: 10px; }
                QFrame {
                    background-color: #23232a;
                    border: 1px solid #44444c;
                    border-radius: 10px;
                }
                QFrame:hover { background-color: #292933; }
                QPushButton {
                    background: #cab4f5;
                    color: #18181b;
                    border: none;
                    border-radius: 8px;
                    font-size: 16px;
                    font-weight: bold;
                }
                QPushButton:hover { opacity: 0.95; }
                QPushButton:pressed { background: #44444c; }
            """)
        else:
            # Light mode
            self.setStyleSheet("""
                QMainWindow { background: #e5f0fd; }
                QLabel { color: #111827; }
                #welcome { font-size: 36px; font-weight: bold; }
                #subtitle { font-size: 18px; }
                #title { font-size: 24px; font-weight: bold; }
                #description { font-size: 16px; }
                #footer { padding: 10px; }
                QFrame {
                    background-color: #ffffff;
                    border: 1px solid #e5e7eb;
                    border-radius: 10px;
                }
                QFrame:hover { background-color: #f8fafc; }
                QPushButton {
                    background: #cab4f5;
                    color: #111827;
                    border: none;
                    border-radius: 8px;
                    font-size: 16px;
                    font-weight: bold;
                }
                QPushButton:hover { opacity: 0.95; }
                QPushButton:pressed { background: #e5e7eb; }
            """)

    def open_editor(self, editor_class):
        try:
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
