# styles.py
# Shared stylesheet for SNIPIX editors

class SnipixStyles:
    # Light theme colors
    LIGHT_BG = "#e5f0fd"       # App background
    LIGHT_SURF = "#ffffff"     # Surface panels
    LIGHT_ACCENT = "#cab4f5"   # Primary accent
    LIGHT_TEXT = "#111827"     # Dark text
    LIGHT_MUTED = "#e5e7eb"    # Borders

    # Dark theme colors
    DARK_BG = "#18181b"        # App background
    DARK_SURF = "#23232a"      # Surface panels
    DARK_ACCENT = "#a78bfa"    # Brighter accent for contrast
    DARK_TEXT = "#e5e7eb"      # Light text
    DARK_MUTED = "#44444c"     # Borders

    @staticmethod
    def get_stylesheet(is_dark_mode: bool) -> str:
        """Return stylesheet string based on dark mode state."""
        colors = (
            SnipixStyles.DARK_BG, SnipixStyles.DARK_SURF, SnipixStyles.DARK_ACCENT,
            SnipixStyles.DARK_TEXT, SnipixStyles.DARK_MUTED
        ) if is_dark_mode else (
            SnipixStyles.LIGHT_BG, SnipixStyles.LIGHT_SURF, SnipixStyles.LIGHT_ACCENT,
            SnipixStyles.LIGHT_TEXT, SnipixStyles.LIGHT_MUTED
        )
        bg, surf, accent, text, muted = colors

        return f"""
            QMainWindow {{
                background: {bg};
                alignment: center;
            }}
            QMenuBar {{
                background: {surf};
                color: {text};
                border-bottom: 1px solid {muted};
            }}
            QMenuBar::item:selected {{
                background: {muted};
            }}
            QToolBar {{
                background: {surf};
                border: 0;
            }}
            QLabel {{
                color: {text};
            }}
            QGroupBox {{
                color: {text};
                background: {surf};
                border: 1px solid {muted};
                border-radius: 10px;
                margin-top: 12px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }}
            QPushButton {{
                background: {accent};
                color: black;
                border: none;
                qproperty-iconSize: 14px 14px;
                padding-left: 10px;
                padding: 8px 10px;
                border-radius: 8px;
            }}
            QPushButton:hover {{ opacity: 0.95; }}
            QPushButton:disabled {{ background: #cbd5e1; color: #6b7280; }}
            QSlider::groove:horizontal {{
                height: 6px;
                background: {muted};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                width: 16px;
                background: {accent};
                border-radius: 8px;
                margin: -6px 0;
            }}
            QScrollArea {{
                background: {surf};
                border: 1px solid {muted};
                border-radius: 10px;
            }}
            QComboBox {{
                background: {surf};
                border: 1px solid {muted};
                padding: 6px 8px;
                border-radius: 6px;
            }}
            QCheckBox {{
                color: {text};
            }}
            QDialog, QMessageBox, QFileDialog, QInputDialog, QColorDialog {{
                background: {surf};
                color: {text};
                border: 1px solid {muted};
                border-radius: 8px;
            }}
            QDialog QLabel, QMessageBox QLabel, QFileDialog QLabel, QInputDialog QLabel, QColorDialog QLabel {{
                color: {text};
                background: transparent;
            }}
            QDialog QPushButton, QMessageBox QPushButton, QFileDialog QPushButton, QInputDialog QPushButton, QColorDialog QPushButton {{
                background: {accent};
                color: black;
                border: none;
                padding: 6px 12px;
                border-radius: 6px;
            }}
            QDialog QPushButton:hover, QMessageBox QPushButton:hover, QFileDialog QPushButton:hover, QInputDialog QPushButton:hover, QColorDialog QPushButton:hover {{
                opacity: 0.80;
            }}
            QDialog QLineEdit, QInputDialog QLineEdit, QFileDialog QLineEdit, QColorDialog QLineEdit {{
                background: {surf};
                color: {text};
                border: 1px solid {muted};
                border-radius: 4px;
                padding: 4px;
            }}
            QDialog QDoubleSpinBox, QInputDialog QDoubleSpinBox {{
                background: {surf};
                color: {text};
                border: 1px solid {muted};
                border-radius: 4px;
                padding: 4px;
            }}
        """