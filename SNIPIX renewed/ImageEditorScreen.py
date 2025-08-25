import sys
import os
import cv2
import numpy as np
from datetime import datetime
from PIL import (
    Image,
    ImageEnhance,
    ImageOps,
    ImageDraw,
    ImageFont,
    ImageFilter
)

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QFileDialog, QColorDialog,
    QHBoxLayout, QVBoxLayout, QSlider, QScrollArea, QMessageBox, QGroupBox, QInputDialog,
    QMenuBar, QToolBar, QComboBox, QFormLayout, QSizePolicy, QCheckBox
)
from PyQt6.QtCore import Qt, QRect, QPoint, QSize
from PyQt6.QtGui import QPixmap, QImage, QAction, QPainter, QPen, QIcon,QKeySequence
from styles.styles import SnipixStyles 


# ------------------------------
# Utility conversions
# ------------------------------

def pil_to_qimage(im: Image.Image) -> QImage:
    im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    qimg = QImage(data, im.size[0], im.size[1], QImage.Format.Format_RGBA8888)
    return qimg

def qimage_to_pixmap(qimg: QImage) -> QPixmap:
    return QPixmap.fromImage(qimg)


class ImageEditor(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("SNIPIX – Smart Image Editor")
        self.resize(1200, 800)
        self.setWindowIcon(QIcon("resources/icons/SnipixLogo.png"))
        
        # Dark mode state
        self.is_dark_mode = False
        self.setStyleSheet(SnipixStyles.get_stylesheet(self.is_dark_mode))
        
           # --- image state ---
        self.original_image: Image.Image | None = None
        self.current_image: Image.Image | None = None
        self.history: list[Image.Image] = []
        self.redo_stack: list[Image.Image] = []
        self.zoom_level: float = 1.0

        # For continuous adjustments
        self.baseline_image: Image.Image | None = None

        # Crop state
        self.cropping_mode = False
        self.crop_origin = QPoint()
        self.crop_rect = QRect()

        # Fit mode state
        self.fit_mode = False  # True when user chose "Fit to Window"

        # drag & drop
        self.setAcceptDrops(True)


        # central layout
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

        # Menus & top toolbar
        self.create_menu_and_toolbar()

        # Status bar
        self.status = self.statusBar()
        self.status.showMessage("Welcome to SNIPIX – Ready")

        # Welcome image
        self.show_welcome()

    # ------------------------------ helper: status ------------------------------
    def _status(self, msg: str, ms: int = 4000):
        self.status.showMessage(msg, ms)

    # ------------------------------ Drag & Drop ------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif")):
                self._load_image_path(path)
                break
    # ------------------------------ UI BUILDERS ------------------------------
    def create_left_panel(self):
        left = QVBoxLayout()
        left.setSpacing(12)

        # Dark mode toggle
        mode_group = QGroupBox("Display")
        m = QVBoxLayout()
        self.dark_mode_check = QCheckBox("Dark Mode")
        self.dark_mode_check.setChecked(self.is_dark_mode)
        self.dark_mode_check.stateChanged.connect(self.toggle_dark_mode)
        m.addWidget(self.dark_mode_check)
        mode_group.setLayout(m)
        left.addWidget(mode_group)


        # Basic tools
        basic_group = QGroupBox("Basic Tools")
        b = QVBoxLayout()

        self.btn_crop = QPushButton(QIcon("resources/icons/crop.png"), "Crop")
        self.btn_crop.clicked.connect(self.toggle_crop_mode)
        b.addWidget(self.btn_crop)

        self.btn_rotate = QPushButton(QIcon("resources/icons/rotate.png"), "Rotate 90°")
        self.btn_rotate.clicked.connect(self.rotate_90)
        b.addWidget(self.btn_rotate)

        self.btn_flip_h = QPushButton(QIcon("resources/icons/flipH.png"), "Flip Horizontal")
        self.btn_flip_h.clicked.connect(self.flip_horizontal)
        b.addWidget(self.btn_flip_h)

        self.btn_flip_v = QPushButton(QIcon("resources/icons/flipV.png"), "Flip Vertical")
        self.btn_flip_v.clicked.connect(self.flip_vertical)
        b.addWidget(self.btn_flip_v)

        self.btn_add_text = QPushButton(QIcon("resources/icons/addText.png"), "Add Text")
        self.btn_add_text.clicked.connect(self.add_text)
        b.addWidget(self.btn_add_text)
        
        basic_group.setLayout(b)
        left.addWidget(basic_group)

        # Adjustments
        adj_group = QGroupBox("Adjustments")
        a = QVBoxLayout()
        # Brightness
        a.addWidget(QLabel("Brightness"))
        self.slider_brightness = QSlider(Qt.Orientation.Horizontal)
        self.slider_brightness.setRange(0, 200)
        self.slider_brightness.setValue(100)
        self.slider_brightness.sliderPressed.connect(self._start_adjust_session)
        self.slider_brightness.valueChanged.connect(self._apply_live_adjustments)
        self.slider_brightness.sliderReleased.connect(self._commit_adjust_session)
        a.addWidget(self.slider_brightness)
        # Contrast
        a.addWidget(QLabel("Contrast"))
        self.slider_contrast = QSlider(Qt.Orientation.Horizontal)
        self.slider_contrast.setRange(0, 200)
        self.slider_contrast.setValue(100)
        self.slider_contrast.sliderPressed.connect(self._start_adjust_session)
        self.slider_contrast.valueChanged.connect(self._apply_live_adjustments)
        self.slider_contrast.sliderReleased.connect(self._commit_adjust_session)
        a.addWidget(self.slider_contrast)
        # Hue
        a.addWidget(QLabel("Hue"))
        self.slider_hue = QSlider(Qt.Orientation.Horizontal)
        self.slider_hue.setRange(-180, 180)
        self.slider_hue.setValue(0)
        self.slider_hue.sliderPressed.connect(self._start_adjust_session)
        self.slider_hue.valueChanged.connect(self._apply_live_adjustments)
        self.slider_hue.sliderReleased.connect(self._commit_adjust_session)
        a.addWidget(self.slider_hue)

        adj_group.setLayout(a)
        left.addWidget(adj_group)


        # reset
        reset_group = QGroupBox("Reset Changes")
        r = QVBoxLayout()
        self.btn_reset = QPushButton(QIcon("resources/icons/reset.png"), "Reset")
        self.btn_reset.clicked.connect(self.reset_image)
        r.addWidget(self.btn_reset)
        reset_group.setLayout(r)
        left.addWidget(reset_group)

        # History

        hist_group = QGroupBox("History")
        h = QVBoxLayout()
        self.btn_undo = QPushButton(QIcon("resources/icons/undo.png"), "Undo")
        self.btn_redo = QPushButton(QIcon("resources/icons/redo.png"), "Redo")
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo.clicked.connect(self.redo)
        h.addWidget(self.btn_undo)
        h.addWidget(self.btn_redo)
        hist_group.setLayout(h)
        left.addWidget(hist_group)

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

    def create_right_panel(self):
        right = QVBoxLayout()
        right.setSpacing(12)

        # Advanced Features
        adv_group = QGroupBox("Advanced Features")
        v = QVBoxLayout()
        self.btn_auto = QPushButton(QIcon("resources/icons/enhance.png"), "Auto Enhance")
        self.btn_auto.clicked.connect(self.auto_enhance)
        v.addWidget(self.btn_auto)

        self.btn_bg_remove = QPushButton(QIcon("resources/icons/bgremove.png"), "Remove Background")
        self.btn_bg_remove.clicked.connect(self.remove_background)
        v.addWidget(self.btn_bg_remove)

        self.btn_bg_set = QPushButton(QIcon("resources/icons/bgColor.png"), "Set Background Color")
        self.btn_bg_set.clicked.connect(self.set_custom_background)
        v.addWidget(self.btn_bg_set)

        adv_group.setLayout(v)
        right.addWidget(adv_group)

        # Filters
        filter_group = QGroupBox("Filters")
        f = QVBoxLayout()
        self.btn_gray = QPushButton(QIcon("resources/icons/grayscale.png"), "Grayscale")
        self.btn_gray.clicked.connect(self.apply_grayscale)
        f.addWidget(self.btn_gray)

        self.btn_sepia = QPushButton(QIcon("resources/icons/sepia.png"), "Sepia")
        self.btn_sepia.clicked.connect(self.apply_sepia)
        f.addWidget(self.btn_sepia)

        self.btn_blur = QPushButton(QIcon("resources/icons/blur.png"), "Blur…")
        self.btn_blur.clicked.connect(self.blur_image)
        f.addWidget(self.btn_blur)

        self.btn_invert = QPushButton(QIcon("resources/icons/invert.png"), "Invert")
        self.btn_invert.clicked.connect(self.apply_negative)
        f.addWidget(self.btn_invert)

        filter_group.setLayout(f)
        right.addWidget(filter_group)

        # Export Options
        export_group = QGroupBox("Export Options")
        form = QFormLayout()
        self.combo_format = QComboBox()
        self.combo_format.addItems(["PNG", "JPEG", "BMP"])
        form.addRow("Format", self.combo_format)

        self.slider_quality = QSlider(Qt.Orientation.Horizontal)
        self.slider_quality.setRange(1, 100)
        self.slider_quality.setValue(95)  # used for JPEG
        form.addRow("Quality", self.slider_quality)

        self.btn_export = QPushButton(QIcon("icons/export.png"), "Export")
        self.btn_export.clicked.connect(self.export_image)
        form.addRow(self.btn_export)

        export_group.setLayout(form)
        right.addWidget(export_group)

        right.addStretch()
        return right

    def create_canvas(self):
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setSpacing(10)

        # Canvas toolbar
        bar = QHBoxLayout()
        self.btn_fit_actual = QPushButton(QIcon("icons/actual_size.png"), "Actual Size")
        self.btn_fit_window = QPushButton(QIcon("icons/fit_window.png"), "Fit to Window")
        self.btn_custom_size = QPushButton(QIcon("icons/custom_zoom.png"), "Custom Size…")
        self.btn_fit_actual.clicked.connect(self.fit_actual)
        self.btn_fit_window.clicked.connect(self.fit_to_window)
        self.btn_custom_size.clicked.connect(self.custom_size)
        bar.addWidget(self.btn_fit_actual)
        bar.addWidget(self.btn_fit_window)
        bar.addWidget(self.btn_custom_size)
        bar.addStretch()
        vbox.addLayout(bar)

        # Image area
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(QSize(200, 200))
        self.image_label.setStyleSheet("background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 8px;")

        # install mouse events for cropping
        self.image_label.mousePressEvent = self._on_mouse_press
        self.image_label.mouseMoveEvent = self._on_mouse_move
        self.image_label.mouseReleaseEvent = self._on_mouse_release

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.image_label)
        vbox.addWidget(self.scroll, 1)

        return container

    def create_menu_and_toolbar(self):
        menubar = QMenuBar(self)
        self.setMenuBar(menubar)

        # --- File Menu ---
        file_menu = menubar.addMenu("File")

        act_open = QAction(QIcon("icons/open.png"), "Open…", self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self.open_image)
        file_menu.addAction(act_open)

        act_save = QAction(QIcon("icons/save.png"), "Save…", self)
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(self.save_image)
        file_menu.addAction(act_save)

        act_export = QAction(QIcon("icons/export.png"), "Export…", self)
        act_export.setShortcut("Ctrl+E")
        act_export.triggered.connect(self.export_image)
        file_menu.addAction(act_export)

        back_action = QAction(QIcon("resources/icons/back.png"), "Back to Menu", self)
        back_action.triggered.connect(self.back_to_menu)
        file_menu.addAction(back_action)

        # --- Edit Menu ---
        edit_menu = menubar.addMenu("Edit")
        act_undo = QAction(QIcon("resources/icons/undo.png"), "Undo", self, shortcut="Ctrl+Z", triggered=self.undo)
        act_redo = QAction(QIcon("resources/icons/redo.png"), "Redo", self, shortcut="Ctrl+Y", triggered=self.redo)
        edit_menu.addAction(act_undo)
        edit_menu.addAction(act_redo)

        # --- Tools Menu ---
        tools_menu = menubar.addMenu("Tools")
        tools_menu.addAction(QAction(QIcon("resources/icons/crop.png"), "Crop", self, triggered=self.toggle_crop_mode))
        tools_menu.addAction(QAction(QIcon("resources/icons/rotate.png"), "Rotate 90° CW", self, triggered=self.rotate_90))
        tools_menu.addAction(QAction(QIcon("resources/icons/flipH.png"), "Flip Horizontal", self, triggered=self.flip_horizontal))
        tools_menu.addAction(QAction(QIcon("resources/icons/flipV.png"), "Flip Vertical", self, triggered=self.flip_vertical))
        tools_menu.addAction(QAction(QIcon("resources/icons/addText.png"), "Add Text", self, triggered=self.add_text))
        tools_menu.addSeparator()
        tools_menu.addAction(QAction(QIcon("resources/icons/enhance.png"), "Auto Enhance", self, triggered=self.auto_enhance))
        tools_menu.addAction(QAction(QIcon("resources/icons/bgremove.png"), "Remove Background", self, triggered=self.remove_background))
        tools_menu.addAction(QAction(QIcon("resources/icons/bgColor.png"), "Set Background Color", self, triggered=self.set_custom_background))

        # --- Filters Menu ---
        filters_menu = menubar.addMenu("Filters")
        filters_menu.addAction(QAction(QIcon("resources/icons/grayscale.png"), "Grayscale", self, triggered=self.apply_grayscale))
        filters_menu.addAction(QAction(QIcon("resources/icons/sepia.png"), "Sepia", self, triggered=self.apply_sepia))
        filters_menu.addAction(QAction(QIcon("resources/icons/blur.png"), "Blur…", self, triggered=self.blur_image))
        filters_menu.addAction(QAction(QIcon("resources/icons/invert.png"), "Invert", self, triggered=self.apply_negative))

        # --- Help Menu ---
        help_menu = menubar.addMenu("Help")
        act_about = QAction(QIcon("icons/info.png"), "About SNIPIX", self)
        act_about.triggered.connect(self.show_about)
        help_menu.addAction(act_about)


    # ------------------------------ About ------------------------------
    def show_about(self):
        QMessageBox.information(
            self, "About SNIPIX",
            "SNIPIX – Smart Image Editor\n\nLightweight editor with essential tools, filters, exports, and a clean PyQt6 UI.\n© 2025"
        )

    # ------------------------------ CORE IMAGE OPS ------------------------------
    def show_welcome(self):
        w, h = 1000, 700
        welcome = Image.new("RGB", (w, h), color="#e5d7e9")
        d = ImageDraw.Draw(welcome)
        text = "Welcome to SNIPIX\nOpen an image to start"
        try:
            font = ImageFont.truetype("arial.ttf", 28)
        except Exception:
            font = ImageFont.load_default()
        bbox = d.multiline_textbbox((0, 0), text, font=font, align="center")
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.multiline_text(((w - tw) // 2, (h - th) // 2), text, font=font, fill="#111827", align="center")
        self.current_image = welcome
        self.history.clear()
        self.save_history()
        self._update_view()
        self._status("Welcome to SNIPIX – Ready")

    def _scaled_for_fit(self, pm: QPixmap) -> QPixmap:
        # Scale pixmap to fit viewport while keeping aspect ratio
        vw = self.scroll.viewport().width() - 16
        vh = self.scroll.viewport().height() - 16
        if vw <= 0 or vh <= 0:
            return pm
        return pm.scaled(vw, vh, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

    def _load_image_path(self, path: str):
        try:
            self.original_image = Image.open(path).convert("RGBA")
            self.current_image = self.original_image.copy()
            self.history.clear()
            self.save_history()
            self.zoom_level = 1.0
            self.fit_mode = False
            self._update_view()
            self._status(f"Loaded: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load image: {e}")
            self._status("Load failed", 4000)

    def _update_view(self):
        if not self.current_image:
            return
        # apply zoom by resizing unless in fit mode
        disp = self.current_image
        if self.zoom_level != 1.0 and not self.fit_mode:
            w = max(1, int(disp.width * self.zoom_level))
            h = max(1, int(disp.height * self.zoom_level))
            disp = disp.resize((w, h), Image.LANCZOS)

        qimg = pil_to_qimage(disp)
        pm = qimage_to_pixmap(qimg)

        if self.fit_mode:
            pm = self._scaled_for_fit(pm)

        self.image_label.setPixmap(pm)
        self.image_label.adjustSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # If in fit mode, keep image scaled to the viewport when window resizes
        if self.fit_mode and self.image_label.pixmap() is not None:
            self._update_view()

    def save_history(self):
        if self.current_image is None:
            return
        self.history.append(self.current_image.copy())
        if len(self.history) > 200:
            self.history.pop(0)
        self.redo_stack.clear()

    def undo(self):
        if len(self.history) > 1:
            self.redo_stack.append(self.history.pop())
            self.current_image = self.history[-1].copy()
            self._update_view()
            self._status("Undo performed")
        else:
            self._status("Nothing to undo", 2500)

    def redo(self):
        if self.redo_stack:
            self.history.append(self.redo_stack.pop())
            self.current_image = self.history[-1].copy()
            self._update_view()
            self._status("Redo performed")
        else:
            self._status("Nothing to redo", 2500)

     # ------------------------------ reset ------------------------------
    def reset_image(self):
        if not self.original_image:
            self._status("No original image to reset to", 2500)
            return
        self.current_image = self.original_image.copy()
        self.save_history()
        self._update_view()
        self._status("Reset to original image")


    # ------------------------------ File ops ------------------------------
    def open_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Image", "", "Image Files (*.png *.jpg *.jpeg *.bmp *.gif)")
        if not path:
            self._status("Open canceled", 2000)
            return
        try:
            self.original_image = Image.open(path).convert("RGB")
            self.current_image = self.original_image.copy()
            self.history.clear()
            self.save_history()
            self.zoom_level = 1.0
            self.fit_mode = False
            self._update_view()
            # reset sliders
            self.slider_brightness.setValue(100)
            self.slider_contrast.setValue(100)
            self.slider_hue.setValue(0)
            self._status(f"Opened: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load image: {e}")
            self._status("Failed to open image", 4000)

    def save_image(self):
        if not self.current_image:
            QMessageBox.warning(self, "Warning", "No image to save.")
            self._status("Save failed: no image", 4000)
            return
        default = f"edited_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        path, _ = QFileDialog.getSaveFileName(self, "Save Image", default,
                                              "PNG Files (*.png);;JPEG Files (*.jpg *.jpeg);;BMP Files (*.bmp)")
        if not path:
            self._status("Save canceled", 2000)
            return
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext in (".jpg", ".jpeg") and self.current_image.mode == "RGBA":
                self.current_image.convert("RGB").save(path, quality=95)
            else:
                self.current_image.save(path)
            QMessageBox.information(self, "Saved", f"Image saved: {os.path.basename(path)}")
            self._status(f"Saved: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save image: {e}")
            self._status("Save failed", 4000)

    def export_image(self):
        if not self.current_image:
            QMessageBox.warning(self, "Warning", "No image to export.")
            self._status("Export failed: no image", 4000)
            return

        fmt = self.combo_format.currentText().upper()
        quality = int(self.slider_quality.value())

        default_name = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{fmt.lower() if fmt!='JPEG' else 'jpg'}"
        filters = "PNG (*.png);;JPEG (*.jpg *.jpeg);;BMP (*.bmp)"
        path, _ = QFileDialog.getSaveFileName(self, "Export Image", default_name, filters)
        if not path:
            self._status("Export canceled", 2000)
            return

        try:
            img = self.current_image
            ext = os.path.splitext(path)[1].lower()

            if fmt == "JPEG" or ext in (".jpg", ".jpeg"):
                if img.mode == "RGBA":
                    img = img.convert("RGB")  # drop alpha for JPEG
                img.save(path, format="JPEG", quality=quality, optimize=True)
            elif fmt == "PNG" or ext == ".png":
                # Keep alpha if present
                img.save(path, format="PNG", optimize=True)
            elif fmt == "BMP" or ext == ".bmp":
                img.convert("RGB").save(path, format="BMP")
            else:
                # Fallback to PNG
                img.save(path, format="PNG", optimize=True)

            QMessageBox.information(self, "Exported", f"Exported: {os.path.basename(path)}")
            self._status(f"Exported ({fmt}) → {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export: {e}")
            self._status("Export failed", 4000)

    # ------------------------------ Zoom / Fit ------------------------------
    def fit_actual(self):
        self.fit_mode = False
        self.zoom_level = 1.0
        self._update_view()
        self._status("Actual size")

    def fit_to_window(self):
        self.fit_mode = True
        self._update_view()
        self._status("Fit to window")

    def custom_size(self):
        if not self.current_image:
            self._status("No image for custom zoom", 2500)
            return
        val, ok = QInputDialog.getInt(self, "Custom Zoom", "Zoom %:", 100, 10, 1000, 1)
        if ok:
            self.fit_mode = False
            self.zoom_level = max(0.1, val / 100.0)
            self._update_view()
            self._status(f"Zoom: {val}%")

    # ------------------------------ Adjustments ------------------------------
    def _start_adjust_session(self):
        if self.current_image is not None:
            self.baseline_image = self.current_image.copy()

    def _commit_adjust_session(self):
        if self.current_image is not None:
            self.save_history()
            self._status("Adjustments applied")

    def _apply_live_adjustments(self):
        if self.baseline_image is None:
            return
        img = self.baseline_image
        # brightness
        b_factor = self.slider_brightness.value() / 100.0
        img = ImageEnhance.Brightness(img).enhance(b_factor)
        # contrast
        c_factor = self.slider_contrast.value() / 100.0
        img = ImageEnhance.Contrast(img).enhance(c_factor)
        # hue shift
        h_shift = self.slider_hue.value()  # degrees
        img = self._hue_shift(img, h_shift)
        self.current_image = img
        self._update_view()
        self._status(f"Adjusting…  B:{self.slider_brightness.value()}  C:{self.slider_contrast.value()}  H:{self.slider_hue.value()}", 500)

    def _hue_shift(self, image: Image.Image, shift_deg: int) -> Image.Image:
        # Convert to HSV and shift hue
        base = image.convert("RGB")
        arr = np.array(base.convert("HSV"))
        h = arr[:, :, 0].astype(np.int16)
        # PIL HSV H channel is 0-255 (~0-360 deg). Map degrees to 0-255.
        shift = int((shift_deg / 360.0) * 255)
        h = (h + shift) % 255
        arr[:, :, 0] = h.astype(np.uint8)
        out = Image.fromarray(arr, mode="HSV").convert("RGB")
        return out

    # ------------------------------ Basic Tools ------------------------------
    def toggle_crop_mode(self):
        self.cropping_mode = not self.cropping_mode
        if self.cropping_mode:
            self.btn_crop.setText("✅ Cropping: drag to select")
            self._status("Crop mode enabled: drag to select region")
        else:
            self.btn_crop.setText("Crop")
            self._status("Crop mode disabled")

    def rotate_90(self):
        if not self.current_image: 
            self._status("No image to rotate", 2500)
            return
        self.save_history()
        self.current_image = self.current_image.rotate(-90, expand=True)
        self._update_view()
        self._status("Rotated 90° CW")

    def flip_horizontal(self):
        if not self.current_image: 
            self._status("No image to flip", 2500)
            return
        self.save_history()
        self.current_image = ImageOps.mirror(self.current_image)
        self._update_view()
        self._status("Flipped horizontally")

    def flip_vertical(self):
        if not self.current_image: 
            self._status("No image to flip", 2500)
            return
        self.save_history()
        self.current_image = ImageOps.flip(self.current_image)
        self._update_view()
        self._status("Flipped vertically")

    def add_text(self):
        if not self.current_image: 
            self._status("No image to add text", 2500)
            return
        text, ok = QInputDialog.getText(self, "Add Text", "Enter text:")
        if not ok or not text:
            self._status("Add text canceled", 2000)
            return
        self.save_history()
        img = self.current_image.convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        try:
            font = ImageFont.truetype("arial.ttf", 32)
        except Exception:
            font = ImageFont.load_default()
        bbox = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (img.width - tw) // 2
        y = (img.height - th) // 2
        d.text((x, y), text, font=font, fill=(0, 0, 0, 255))
        self.current_image = Image.alpha_composite(img if img.mode == "RGBA" else img.convert("RGBA"), overlay).convert("RGB")
        self._update_view()
        self._status(f'Text added: "{text}"')

    # ------------------------------ Advanced Features ------------------------------
    def auto_enhance(self):
        if not self.current_image: 
            self._status("No image to enhance", 2500)
            return
        self.save_history()
        img = self.current_image
        img = ImageEnhance.Color(img).enhance(1.15)
        img = ImageEnhance.Contrast(img).enhance(1.12)
        img = ImageEnhance.Sharpness(img).enhance(1.1)
        img = ImageEnhance.Brightness(img).enhance(1.05)
        self.current_image = img
        self._update_view()
        self._status("Auto enhance applied")

    def remove_background(self):
        if not self.current_image:
            QMessageBox.warning(self, "Warning", "No image loaded to remove background.")
            self._status("Remove BG failed: no image", 4000)
            return
        self.save_history()
        self._status("Removing background…")
        try:
            img_cv = cv2.cvtColor(np.array(self.current_image.convert("RGB")), cv2.COLOR_RGB2BGR)
            mask = np.zeros(img_cv.shape[:2], np.uint8)
            bgd_model = np.zeros((1, 65), np.float64)
            fgd_model = np.zeros((1, 65), np.float64)
            h, w = img_cv.shape[:2]
            rect = (10, 10, w - 20, h - 20)
            cv2.grabCut(img_cv, mask, rect, bgd_model, fgd_model, 5, cv2.GC_INIT_WITH_RECT)
            mask2 = np.where((mask == 2) | (mask == 0), 0, 1).astype('uint8')
            result = img_cv * mask2[:, :, np.newaxis]
            rgba = cv2.cvtColor(result, cv2.COLOR_BGR2RGBA)
            rgba[:, :, 3] = mask2 * 255
            self.current_image = Image.fromarray(rgba)
            self._update_view()
            self._status("Background removed")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to remove background: {e}")
            self._status("Remove background failed", 4000)

    def set_custom_background(self):
        if not self.current_image:
            self._status("No image loaded", 2500)
            return
        if self.current_image.mode != 'RGBA':
            QMessageBox.information(self, "Info", "Please remove background first (needs transparency).")
            self._status("Set BG: needs transparency", 4000)
            return
        color = QColorDialog.getColor(title="Select Background Color", parent=self)
        if not color.isValid():
            self._status("Set BG canceled", 2000)
            return
        bg_rgba = (color.red(), color.green(), color.blue(), 255)
        bg_img = Image.new("RGBA", self.current_image.size, bg_rgba)
        self.save_history()
        self.current_image = Image.alpha_composite(bg_img, self.current_image)
        self._update_view()
        self._status(f"Background set to #{color.name()[1:].upper()}")

    # ------------------------------ Filters ------------------------------
    def blur_image(self):
        if not self.current_image:
            self._status("No image to blur", 2500)
            return
        radius, ok = QInputDialog.getInt(self, "Blur", "Gaussian radius:", 2, 1, 50, 1)
        if not ok:
            self._status("Blur canceled", 2000)
            return
        self.save_history()
        self.current_image = self.current_image.filter(ImageFilter.GaussianBlur(radius))
        self._update_view()
        self._status(f"Blur applied (r={radius})")

    def apply_grayscale(self):
        if not self.current_image:
            self._status("No image to grayscale", 2500)
            return
        self.save_history()
        self.current_image = ImageOps.grayscale(self.current_image).convert("RGB")
        self._update_view()
        self._status("Grayscale applied")

    def apply_negative(self):
        if not self.current_image:
            self._status("No image to invert", 2500)
            return
        self.save_history()
        img = self.current_image
        if img.mode == "RGBA":
            rgb, a = img.convert("RGB"), img.split()[-1]
            inv = ImageOps.invert(rgb)
            self.current_image = Image.merge("RGBA", (*inv.split(), a))
        else:
            self.current_image = ImageOps.invert(img.convert("RGB"))
        self._update_view()
        self._status("Inverted colors")

    def apply_sepia(self):
        if not self.current_image:
            self._status("No image to sepia", 2500)
            return
        def sepia_filter(pil_img: Image.Image) -> Image.Image:
            img = np.array(pil_img.convert("RGB"))
            sepia_matrix = np.array([
                [0.393, 0.769, 0.189],
                [0.349, 0.686, 0.168],
                [0.272, 0.534, 0.131]
            ])
            sepia_img = cv2.transform(img, sepia_matrix)
            sepia_img = np.clip(sepia_img, 0, 255).astype('uint8')
            return Image.fromarray(sepia_img)
        self.save_history()
        self.current_image = sepia_filter(self.current_image)
        self._update_view()
        self._status("Sepia applied")

    # ------------------------------ Cropping Mouse Events ------------------------------
    def _on_mouse_press(self, event):
        if not self.cropping_mode or not self.current_image:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.crop_origin = event.position().toPoint()
            self.crop_rect = QRect(self.crop_origin, self.crop_origin)
            self._draw_overlay()

    def _on_mouse_move(self, event):
        if not self.cropping_mode or self.crop_rect.isNull():
            return
        self.crop_rect.setBottomRight(event.position().toPoint())
        self._draw_overlay()

    def _on_mouse_release(self, event):
        if not self.cropping_mode or not self.current_image:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            # map rect from label coordinates to image coordinates considering zoom / fit
            label_pixmap = self.image_label.pixmap()
            if not label_pixmap:
                return
            # Get top-left of image inside label
            lw, lh = self.image_label.width(), self.image_label.height()
            pw, ph = label_pixmap.width(), label_pixmap.height()
            offx = max(0, (lw - pw) // 2)
            offy = max(0, (lh - ph) // 2)
            rect = self.crop_rect.translated(-offx, -offy)
            rect = rect.intersected(QRect(0, 0, pw, ph))
            if rect.width() > 5 and rect.height() > 5:
                # scale back to real image size by current pixmap scale factor
                scale_x = self.current_image.width / pw
                scale_y = self.current_image.height / ph
                x = int(rect.x() * scale_x)
                y = int(rect.y() * scale_y)
                w = int(rect.width() * scale_x)
                h = int(rect.height() * scale_y)
                self.save_history()
                self.current_image = self.current_image.crop((x, y, x + w, y + h))
                self.fit_mode = False
                self.zoom_level = 1.0
                self._update_view()
                self._status(f"Cropped to {w}×{h}")
            # reset crop UI
            self.crop_rect = QRect()
            self._draw_overlay()
            self.cropping_mode = False
            self.btn_crop.setText("Crop (drag on image)")
            self._status("Crop mode disabled")

    def _draw_overlay(self):
        # draw the selection rect overlay on top of the current pixmap for feedback
        base_img = self.current_image if self.current_image else Image.new("RGB", (10, 10), "white")
        base_pm = qimage_to_pixmap(pil_to_qimage(base_img))
        if (self.zoom_level != 1.0 and not self.fit_mode) and self.current_image:
            w = max(1, int(self.current_image.width * self.zoom_level))
            h = max(1, int(self.current_image.height * self.zoom_level))
            base_pm = base_pm.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        elif self.fit_mode:
            base_pm = self._scaled_for_fit(base_pm)

        pm = QPixmap(base_pm)
        if not self.crop_rect.isNull():
            painter = QPainter(pm)
            pen = QPen(Qt.GlobalColor.black)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(self.crop_rect)
            painter.end()
        self.image_label.setPixmap(pm)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    editor = ImageEditor()
    editor.show()
    sys.exit(app.exec())
