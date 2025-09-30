import sys
import numpy as np
from scipy import ndimage
from concurrent.futures import ThreadPoolExecutor, as_completed

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

        if mods & Qt.ControlModifier:  # ズーム
            factor = 1.25 if angle > 0 else 0.8
            self.scale(factor, factor)
            self.scale_factor *= factor
            event.accept()
        elif mods & Qt.ShiftModifier:  # 横スクロール
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
        self.setWindowTitle("SVG比較ツール（大画像安定版）")
        self.setGeometry(100, 100, 1200, 900)

        # Scene & View
        self.scene = QGraphicsScene(self)
        self.view = GraphicsView()
        self.view.setScene(self.scene)

        # ピクスマップ
        self.left_pixmap_item = None
        self.right_pixmap_item = None

        # 差分矩形
        self.diff_items = []

        # 状態
        self.left_renderer = None
        self.right_renderer = None
        self.left_img = None
        self.right_img = None
        self.left_arr = None
        self.right_arr = None
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

    # -------------------- SVG読み込み --------------------
    def load_left(self):
        path, _ = QFileDialog.getOpenFileName(self, "左SVGを選択", "", "SVG Files (*.svg)")
        if path:
            self.left_renderer = QSvgRenderer(path)
            self.left_img = self.svg_to_qimage(self.left_renderer)
            self.left_arr = self.qimage_to_numpy_safe(self.left_img)
            self.update_scene_pixmaps()
            self.compute_diff()

    def load_right(self):
        path, _ = QFileDialog.getOpenFileName(self, "右SVGを選択", "", "SVG Files (*.svg)")
        if path:
            self.right_renderer = QSvgRenderer(path)
            self.right_img = self.svg_to_qimage(self.right_renderer)
            self.right_arr = self.qimage_to_numpy_safe(self.right_img)
            self.update_scene_pixmaps()
            self.compute_diff()

    # -------------------- UI更新 --------------------
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

    # -------------------- SVG → QImage --------------------
    def svg_to_qimage(self, renderer):
        size = renderer.defaultSize()
        img = QImage(size, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        renderer.render(p)
        p.end()
        return img

    # -------------------- 安全に QImage → NumPy --------------------
    def qimage_to_numpy_safe(self, img: QImage):
        img = img.convertToFormat(QImage.Format_ARGB32)
        # copy() して安全にメモリ確保
        img_copy = img.copy()
        ptr = img_copy.bits()
        arr = np.array(ptr).reshape(img_copy.height(), img_copy.width(), 4)
        return arr

    # -------------------- Scene 更新 --------------------
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

        self.view.setSceneRect(0, 0,
                               max(self.left_img.width(), self.right_img.width()),
                               max(self.left_img.height(), self.right_img.height()))

    # -------------------- タイル差分 --------------------
    def _diff_tile_worker(self, arr_l_tile, arr_r_tile, x0, y0):
        diff_tile = np.any(arr_l_tile != arr_r_tile, axis=2)
        return x0, y0, diff_tile

    def compute_diff(self):
        if self.left_arr is None or self.right_arr is None:
            return

        h, w, _ = self.left_arr.shape
        tile_size = 512

        # 差分矩形クリア
        for item in self.diff_items:
            self.scene.removeItem(item)
        self.diff_items.clear()

        diff_mask = np.zeros((h, w), dtype=bool)

        # タイル分割
        tasks = []
        for y0 in range(0, h, tile_size):
            for x0 in range(0, w, tile_size):
                h_tile = min(tile_size, h - y0)
                w_tile = min(tile_size, w - x0)
                arr_l_tile = self.left_arr[y0:y0+h_tile, x0:x0+w_tile, :]
                arr_r_tile = self.right_arr[y0:y0+h_tile, x0:x0+w_tile, :]
                tasks.append((arr_l_tile, arr_r_tile, x0, y0))

        # ThreadPoolExecutorで差分計算
        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(self._diff_tile_worker, *t) for t in tasks]
            for future in as_completed(futures):
                x0, y0, diff_tile = future.result()
                diff_mask[y0:y0+diff_tile.shape[0], x0:x0+diff_tile.shape[1]] = diff_tile

        # ラベリングして矩形作成
        labeled, num_features = ndimage.label(diff_mask, structure=np.ones((3,3), dtype=int))
        for label_id in range(1, num_features+1):
            ys, xs = np.nonzero(labeled == label_id)
            min_x, max_x = xs.min(), xs.max()
            min_y, max_y = ys.min(), ys.max()
            rect = QGraphicsRectItem(min_x, min_y, max_x-min_x+1, max_y-min_y+1)
            pen = QPen(QColor(255,0,0,200))
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
