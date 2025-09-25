import sys
import numpy as np  # <= 必須
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QSlider, QLabel, QScrollArea, QColorDialog
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QPainter, QPixmap, QImage, QColor
from PySide6.QtCore import Qt, QSize, QEvent
from PySide6.QtGui import QPainter, QPen, QColor
from scipy import ndimage

class SVGOverlayCompare(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SVG比較ツール（重ね＋差分＋スクロール）")
        self.setGeometry(100, 100, 1000, 800)

        # ラベルに画像を表示し、スクロール可能にする
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.image_label)

        self.left_renderer = None
        self.right_renderer = None
        self.alpha = 0.5
        self.diff_enabled = False

        self.left_path = None
        self.right_path = None

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
        layout.addWidget(self.scroll_area)

        self.setLayout(layout)
        self.background_color = QColor(Qt.white)

        self.scale_factor = 1.0
        self.scroll_area.viewport().installEventFilter(self)

    def load_left(self):
        path, _ = QFileDialog.getOpenFileName(self, "左SVGを選択", "", "SVG Files (*.svg)")
        if path:
            self.left_path = path
            self.left_renderer = QSvgRenderer(path)
            self.update_display()

    def load_right(self):
        path, _ = QFileDialog.getOpenFileName(self, "右SVGを選択", "", "SVG Files (*.svg)")
        if path:
            self.right_path = path
            self.right_renderer = QSvgRenderer(path)
            self.update_display()

    def update_alpha(self, value):
        self.alpha = value / 100.0
        self.alpha_label.setText(f"透過度: {value}%")
        self.update_display()

    def toggle_diff(self):
        self.diff_enabled = not self.diff_enabled
        self.diff_toggle_btn.setText(f"差分ハイライト {'ON' if self.diff_enabled else 'OFF'}")
        self.update_display()

    # 背景色変更のメソッド
    def change_background_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.background_color = color
            self.update_display()

    def qimage_to_numpy_uint32(self, img: QImage):
        """
        QImage を numpy uint32 配列 (H, W) に変換する。
        QImage は QImage.Format_ARGB32 を前提。
        """
        if img.format() != QImage.Format_ARGB32:
            img = img.convertToFormat(QImage.Format_ARGB32)

        width = img.width()
        height = img.height()
        ptr = img.bits()

        # バイト数を height × bytesPerLine で計算
        byte_count = height * img.bytesPerLine()

        # memoryview → numpy
        arr = np.frombuffer(ptr, dtype=np.uint8, count=byte_count)

        row_bytes = img.bytesPerLine()
        arr = arr.reshape((height, row_bytes))

        # 幅分だけ取り出して 4byte/px → uint32 に再解釈
        arr = arr[:, :width * 4]
        arr32 = arr.view(dtype=np.uint32).reshape((height, width))

        return arr32, arr
    

    # def create_diff_overlay(self, left_img: QImage, right_img: QImage) -> tuple[QImage, int, int]:
    #     """
    #     差分領域を赤枠で囲む QImage を返す。
    #     戻り値: (diff_qimg, offset_x, offset_y)
    #     """
    #     w = max(left_img.width(), right_img.width())
    #     h = max(left_img.height(), right_img.height())

    #     l = left_img.convertToFormat(QImage.Format_ARGB32)
    #     r = right_img.convertToFormat(QImage.Format_ARGB32)

    #     l32, _ = self.qimage_to_numpy_uint32(l)
    #     r32, _ = self.qimage_to_numpy_uint32(r)

    #     diff_mask = (l32 != r32)

    #     if not diff_mask.any():
    #         return None, 0, 0

    #     # 差分矩形を計算
    #     ys, xs = np.nonzero(diff_mask)
    #     min_x, max_x = xs.min(), xs.max()
    #     min_y, max_y = ys.min(), ys.max()

    #     rect_w = max_x - min_x + 1
    #     rect_h = max_y - min_y + 1

    #     # 差分矩形サイズの QImage を作成
    #     diff_qimg = QImage(rect_w, rect_h, QImage.Format_ARGB32)
    #     diff_qimg.fill(Qt.transparent)

    #     # QPainter で赤枠を描画
    #     painter = QPainter(diff_qimg)
    #     pen = QPen(QColor(255, 0, 0, 180))  # 半透明赤
    #     pen.setWidth(3)                     # 枠線の太さ
    #     painter.setPen(pen)
    #     painter.drawRect(0, 0, rect_w - 1, rect_h - 1)
    #     painter.end()

    #     return diff_qimg, min_x, min_y
    def create_diff_overlay(self, left_img: QImage, right_img: QImage) -> tuple[QImage, int, int]:
        """
        差分領域ごとに赤枠を描画する QImage を返す。
        戻り値: (diff_qimg, offset_x, offset_y)
        """
        w = max(left_img.width(), right_img.width())
        h = max(left_img.height(), right_img.height())

        l = left_img.convertToFormat(QImage.Format_ARGB32)
        r = right_img.convertToFormat(QImage.Format_ARGB32)

        l32, _ = self.qimage_to_numpy_uint32(l)
        r32, _ = self.qimage_to_numpy_uint32(r)

        diff_mask = (l32 != r32)

        if not diff_mask.any():
            return None, 0, 0

        # 連結成分ラベリング（8近傍）
        labeled, num_features = ndimage.label(diff_mask, structure=np.ones((3, 3), dtype=int))

        # 出力画像（全体サイズで透明）
        diff_qimg = QImage(w, h, QImage.Format_ARGB32)
        diff_qimg.fill(Qt.transparent)

        painter = QPainter(diff_qimg)
        pen = QPen(QColor(255, 0, 0, 180))  # 半透明赤
        pen.setWidth(2)
        painter.setPen(pen)

        # 各領域ごとに矩形を描画
        for label_id in range(1, num_features + 1):
            ys, xs = np.nonzero(labeled == label_id)
            min_x, max_x = xs.min(), xs.max()
            min_y, max_y = ys.min(), ys.max()
            rect_w = max_x - min_x + 1
            rect_h = max_y - min_y + 1
            painter.drawRect(min_x, min_y, rect_w, rect_h)

        painter.end()

        return diff_qimg, 0, 0
    def update_display(self):
        if not self.left_renderer or not self.right_renderer:
            return

        # SVGサイズ（大きい方に合わせる）
        left_size = self.left_renderer.defaultSize()
        right_size = self.right_renderer.defaultSize()
        size = left_size.expandedTo(right_size)

        # 左と右の画像を描画（スケーリング考慮せずに原寸描画）
        left_img = QImage(size, QImage.Format_ARGB32)
        left_img.fill(Qt.transparent)
        painter = QPainter(left_img)
        self.left_renderer.render(painter)
        painter.end()

        right_img = QImage(size, QImage.Format_ARGB32)
        right_img.fill(Qt.transparent)
        painter = QPainter(right_img)
        self.right_renderer.render(painter)
        painter.end()

        # 合成結果を生成（背景色で初期化）
        final_img = QImage(size, QImage.Format_ARGB32)
        final_img.fill(self.background_color)
        painter = QPainter(final_img)
        painter.drawImage(0, 0, left_img)
        painter.setOpacity(self.alpha)
        painter.drawImage(0, 0, right_img)
        painter.setOpacity(1.0)

        # 差分を numpy で作成して一度に描画
        if self.diff_enabled:
            diff_overlay, ox, oy = self.create_diff_overlay(left_img, right_img)
            if diff_overlay is not None:
                painter.drawImage(ox, oy, diff_overlay)

        painter.end()

        # 表示
        pixmap = QPixmap.fromImage(final_img)
        scaled_pixmap = pixmap.scaled(pixmap.size() * self.scale_factor, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled_pixmap)
        self.image_label.resize(scaled_pixmap.size())

    def eventFilter(self, obj, event):
        if obj == self.scroll_area.viewport() and event.type() == QEvent.Wheel:
            mods = event.modifiers()
            angle = event.angleDelta().y()

            if mods & Qt.ControlModifier:
                factor = 1.25 if angle > 0 else 0.8
                self.scale_factor *= factor
                self.scale_factor = max(0.1, min(10.0, self.scale_factor))
                self.update_display()
                return True  # イベントを処理済みにする

            elif mods & Qt.ShiftModifier:
                delta = -angle
                h_scrollbar = self.scroll_area.horizontalScrollBar()
                h_scrollbar.setValue(h_scrollbar.value() + delta)
                return True  # イベントを処理済みにする

        # それ以外のイベントは親に渡す
        return super().eventFilter(obj, event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SVGOverlayCompare()
    window.show()
    sys.exit(app.exec())
