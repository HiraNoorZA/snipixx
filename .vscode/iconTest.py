from PyQt6.QtWidgets import QApplication, QPushButton
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QSize
import os

icon_path = "SNIPIX renewed/resources/icons/crop.png"  # Change to an icon you have

print("Icon exists:", os.path.exists(icon_path))  # Should print True if file exists

app = QApplication([])
btn = QPushButton(QIcon(icon_path), "Crop")
btn.setIconSize(QSize(24, 24))
btn.show()
app.exec()