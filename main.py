import sys
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QSlider, QLabel, QScrollArea
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QPainter, QPixmap, QImage, QColor, QBrush
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QColorDialog

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
            # self.scene.setBackgroundBrush(QBrush(color))
            self.background_color = color
            self.update_display()
            

    def update_display(self):
        if not self.left_renderer or not self.right_renderer:
            return

        # SVGサイズ（大きい方に合わせる）
        left_size = self.left_renderer.defaultSize()
        right_size = self.right_renderer.defaultSize()
        size = left_size.expandedTo(right_size)

        # 左と右の画像を描画
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

        # 合成結果を生成
        final_img = QImage(size, QImage.Format_ARGB32)
        final_img = QImage(size, QImage.Format_ARGB32)
        final_img.fill(self.background_color)
        final_img = QImage(size, QImage.Format_ARGB32)
        final_img.fill(self.background_color)
        painter = QPainter(final_img)
        painter.drawImage(0, 0, left_img)
        painter.setOpacity(self.alpha)
        painter.drawImage(0, 0, right_img)
        painter.setOpacity(1.0)

        # 差分を描画
        if self.diff_enabled:
            for y in range(size.height()):
                for x in range(size.width()):
                    if left_img.pixel(x, y) != right_img.pixel(x, y):
                        painter.setPen(Qt.NoPen)
                        painter.setBrush(QColor(255, 0, 0, 100))
                        painter.drawRect(x, y, 1, 1)

        painter.end()

        # 表示
        pixmap = QPixmap.fromImage(final_img)
        # self.image_label.setPixmap(pixmap)
        # self.image_label.resize(pixmap.size())
        scaled_pixmap = pixmap.scaled(pixmap.size() * self.scale_factor, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled_pixmap)
        self.image_label.resize(scaled_pixmap.size())

    # def wheelEvent(self, event):
    #     mods = event.modifiers()
    #     angle = event.angleDelta().y()

    #     if mods & Qt.ControlModifier:
    #         # Ctrlが押されていれば拡大/縮小
    #         factor = 1.25 if angle > 0 else 0.8
    #         self.scale_factor *= factor
    #         self.scale_factor = max(0.1, min(10.0, self.scale_factor))
    #         self.update_display()
    #         event.accept()
    #     elif mods & Qt.ShiftModifier:
    #         # Shiftが押されていれば左右スクロール
    #         delta = -angle
    #         h_scrollbar = self.scroll_area.horizontalScrollBar()
    #         h_scrollbar.setValue(h_scrollbar.value() + delta)
    #         event.accept()
    #     else:
    #         # 通常のスクロール
    #         super().wheelEvent(event)
    def eventFilter(self, obj, event):
        if obj == self.scroll_area.viewport() and event.type() == event.Type.Wheel:
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