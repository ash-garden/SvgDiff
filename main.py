import sys
import numpy as np
from scipy import ndimage

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QSlider, QLabel, QColorDialog,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QPainter, QPixmap, QImage, QColor, QPen
from PySide6.QtCore import Qt


class GraphicsView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scale_factor = 1.0

    def wheelEvent(self, event):
        mods = event.modifiers()
        angle = event.angleDelta().y()

        if mods & Qt.ControlModifier:
            factor = 1.25 if angle > 0 else 0.8
            self.scale(factor, factor)
            self.scale_factor *= factor
            event.accept()
        elif mods & Qt.ShiftModifier:
            delta = -angle
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() + delta
            )
            event.accept()
        else:
            super().wheelEvent(event)


class SVGOverlayCompare(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SVG比較ツール（大画像対応・GPU版）")
        self.setGeometry(100, 100, 1200, 900)

        # Scene & View
        self.scene = QGraphicsScene(self)
        self.view = GraphicsView()
        self.view.setScene(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setRenderHint(QPainter.SmoothPixmapTransform)

        # ピクスマップアイテム
        self.left_pixmap_item = None
        self.right_pixmap_item = None

        # 差分矩形
        self.diff_items = []

        # 状態
        self.left_renderer = None
        self.right_renderer = None
        self.left_img = None
        self.right_img = None
        self.alpha = 0.5
        self.diff_enabled = False
        self.background_color = QColor(Qt.white)

        # UI
        load_left_btn = QPushButton("左SVGを読み込む")
        load_right_btn = QPushButton("右SVGを読み込む")
        bg_color_btn = QPushButton("背景色を変更")

        self.alpha_slider = QSlider(Qt.Horizontal)
        self.alpha_slider.setRange(0, 100)
        self.alpha_slider.setValue(50)
        self.alpha_slider.valueChanged.connect(self.update_alpha)

        self.alpha_label = QLabel("透過度: 50%")

        self.diff_toggle_btn = QPushButton("差分ハイライト ON")
        self.diff_toggle_btn.clicked.connect(self.toggle_diff)

        load_left_btn.clicked.connect(self.load_left)
        load_right_btn.clicked.connect(self.load_right)
        bg_color_btn.clicked.connect(self.change_background_color)

        layout = QVBoxLayout()
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(load_left_btn)
        btn_layout.addWidget(load_right_btn)
        btn_layout.addWidget(bg_color_btn)

        slider_layout = QHBoxLayout()
        slider_layout.addWidget(self.alpha_label)
        slider_layout.addWidget(self.alpha_slider)
        slider_layout.addWidget(self.diff_toggle_btn)

        layout.addLayout(btn_layout)
        layout.addLayout(slider_layout)
        layout.addWidget(self.view)
        self.setLayout(layout)

    def load_left(self):
        path, _ = QFileDialog.getOpenFileName(self, "左SVGを選択", "", "SVG Files (*.svg)")
        if path:
            self.left_renderer = QSvgRenderer(path)
            self.left_img = self.svg_to_qimage(self.left_renderer)
            self.update_scene_pixmaps()
            self.compute_diff()

    def load_right(self):
        path, _ = QFileDialog.getOpenFileName(self, "右SVGを選択", "", "SVG Files (*.svg)")
        if path:
            self.right_renderer = QSvgRenderer(path)
            self.right_img = self.svg_to_qimage(self.right_renderer)
            self.update_scene_pixmaps()
            self.compute_diff()

    def update_alpha(self, value):
        self.alpha = value / 100.0
        self.alpha_label.setText(f"透過度: {value}%")
        if self.right_pixmap_item:
            self.right_pixmap_item.setOpacity(self.alpha)

    def toggle_diff(self):
        self.diff_enabled = not self.diff_enabled
        self.diff_toggle_btn.setText(f"差分ハイライト {'ON' if self.diff_enabled else 'OFF'}")
        for item in self.diff_items:
            item.setVisible(self.diff_enabled)

    def change_background_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.background_color = color
            self.scene.setBackgroundBrush(self.background_color)

    def svg_to_qimage(self, renderer):
        size = renderer.defaultSize()
        img = QImage(size, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        renderer.render(p)
        p.end()
        return img

    def update_scene_pixmaps(self):
        if not self.left_img or not self.right_img:
            return

        left_pix = QPixmap.fromImage(self.left_img)
        right_pix = QPixmap.fromImage(self.right_img)

        if not self.left_pixmap_item:
            self.left_pixmap_item = QGraphicsPixmapItem(left_pix)
            self.scene.addItem(self.left_pixmap_item)
        else:
            self.left_pixmap_item.setPixmap(left_pix)

        if not self.right_pixmap_item:
            self.right_pixmap_item = QGraphicsPixmapItem(right_pix)
            self.right_pixmap_item.setOpacity(self.alpha)
            self.scene.addItem(self.right_pixmap_item)
        else:
            self.right_pixmap_item.setPixmap(right_pix)
            self.right_pixmap_item.setOpacity(self.alpha)

        self.view.setSceneRect(0, 0, max(self.left_img.width(), self.right_img.width()),
                               max(self.left_img.height(), self.right_img.height()))

    def qimage_to_numpy_tile_safe(self, img: QImage, tile_size=1024):
        """大画像対応。タイル単位でNumPy配列を生成するジェネレーター"""
        img = img.convertToFormat(QImage.Format_ARGB32)
        h, w = img.height(), img.width()
        for y0 in range(0, h, tile_size):
            for x0 in range(0, w, tile_size):
                y1 = min(y0 + tile_size, h)
                x1 = min(x0 + tile_size, w)
                tile = img.copy(x0, y0, x1 - x0, y1 - y0)
                ptr = tile.bits()
                arr = np.asarray(ptr).reshape((tile.height(), tile.bytesPerLine() // 4, 4))
                arr = arr[:, :tile.width(), :]
                yield x0, y0, arr

    def compute_diff(self):
        if not self.left_img or not self.right_img:
            return

        h, w = self.left_img.height(), self.left_img.width()
        diff_mask = np.zeros((h, w), dtype=bool)

        # タイル単位で差分計算
        for x0, y0, arr_l_tile in self.qimage_to_numpy_tile_safe(self.left_img):
            tile_r = self.right_img.copy(x0, y0, arr_l_tile.shape[1], arr_l_tile.shape[0])
            ptr_r = tile_r.bits()
            arr_r_tile = np.asarray(ptr_r).reshape((tile_r.height(), tile_r.bytesPerLine() // 4, 4))
            arr_r_tile = arr_r_tile[:, :tile_r.width(), :]
            diff_tile = np.any(arr_l_tile != arr_r_tile, axis=2)
            diff_mask[y0:y0+arr_l_tile.shape[0], x0:x0+arr_l_tile.shape[1]] = diff_tile

        # 差分矩形を更新
        for item in self.diff_items:
            self.scene.removeItem(item)
        self.diff_items.clear()

        labeled, num_features = ndimage.label(diff_mask, structure=np.ones((3, 3), dtype=int))
        for label_id in range(1, num_features + 1):
            ys, xs = np.nonzero(labeled == label_id)
            min_x, max_x = xs.min(), xs.max()
            min_y, max_y = ys.min(), ys.max()
            rect = QGraphicsRectItem(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
            pen = QPen(QColor(255, 0, 0, 200))
            pen.setWidth(3)
            rect.setPen(pen)
            rect.setBrush(Qt.NoBrush)
            rect.setVisible(self.diff_enabled)
            self.scene.addItem(rect)
            self.diff_items.append(rect)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SVGOverlayCompare()
    window.show()
    sys.exit(app.exec())
