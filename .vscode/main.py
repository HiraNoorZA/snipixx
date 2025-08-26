import sys
from PyQt6.QtWidgets import QApplication
from splash import SnipixSplashScreen

if __name__ == "__main__":
    app = QApplication(sys.argv)
    splash = SnipixSplashScreen()
    splash.show()
    sys.exit(app.exec())