import sys
import time
from PyQt6.QtWidgets import (
    QApplication, QSplashScreen, QLabel, QVBoxLayout, QWidget, QProgressBar
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QFont, QIcon
from optionPane import OptionPane  # Updated to launch OptionPane

class SnipixSplashScreen(QSplashScreen):
    def __init__(self):
        super().__init__()
        
        # Use same color scheme as ImageEditor
        self.COLOR_BG = "#e5f0fd"
        self.COLOR_SURF = "#ffffff"
        self.COLOR_ACCENT = "#cab4f5"
        self.COLOR_TEXT = "#111827"
        self.COLOR_MUTED = "#e5e7eb"

        # Set up the splash screen widget
        self.setFixedSize(800, 450)
        self.setWindowFlags(Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        
        # Apply stylesheet
        self.setStyleSheet(f"""
            QSplashScreen {{
                background: {self.COLOR_SURF};
                border: 1px solid {self.COLOR_MUTED};
                border-radius: 10px;
            }}
            QLabel {{
                color: {self.COLOR_TEXT};
            }}
            QWidget {{
                background: {self.COLOR_BG};
            }}
            QProgressBar {{
                border: 1px solid {self.COLOR_MUTED};
                border-radius: 5px;
                background: {self.COLOR_BG};
                text-align: center;
            }}
            QProgressBar::chunk {{
                background: {self.COLOR_ACCENT};
                border-radius: 3px;
            }}
        """)

        # Layout
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Logo
        logo_label = QLabel()
        logo_pixmap = QPixmap("resources/icons/SnipixLogo.png").scaled(
            80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        logo_label.setPixmap(logo_pixmap)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo_label)

        # Welcome text
        title = QLabel("SNIPIX – Smart Editing Studio")
        title.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Your all-in-one solution for photo and video editing")
        subtitle.setFont(QFont("Arial", 12))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(20)
        layout.addWidget(self.progress)

        # Set widget as splash screen content
        self.setPixmap(QPixmap(self.size()))
        widget.setGeometry(0, 0, self.width(), self.height())

        # Timer for progress animation
        self.progress_value = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_progress)
        self.timer.start(90)

    def update_progress(self):
        self.progress_value += 2
        self.progress.setValue(self.progress_value)
        if self.progress_value >= 100:
            self.timer.stop()
            self.close()
            self.main_window = OptionPane()
            self.main_window.show()

    def showEvent(self, event):
        super().showEvent(event)
        screen = QApplication.primaryScreen().geometry()
        size = self.geometry()
        self.move(
            (screen.width() - size.width()) // 2,
            (screen.height() - size.height()) // 2
        )

if __name__ == "__main__":
    app = QApplication(sys.argv)
    splash = SnipixSplashScreen()
    splash.show()
    sys.exit(app.exec())