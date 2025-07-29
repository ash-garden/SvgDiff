import sys 
from PySide6.QtWidgets import ( QApplication, QWidget, QVBoxLayout, QPushButton, QFileDialog, QHBoxLayout, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QSlider, QCheckBox ) 
from PySide6.QtSvg import QSvgRenderer 
from PySide6.QtGui import QImage, QPainter, QPixmap, QColor, QWheelEvent 
from PySide6.QtCore import QRectF, Qt

class SvgTileComparer(QWidget): 
    def __init__(self): 
        super().__init__()
        self.setWindowTitle("SVGピクセル分割比較ツール")

        self.svg1_path = None
        self.svg2_path = None
        self.tile_x = 0
        self.tile_y = 0
        self.tile_width = 400
        self.tile_height = 400
        self.scale = 1.0
        self.opacity = 0.5
        self.show_diff = True

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        btn_layout = QHBoxLayout()
        self.load_btn1 = QPushButton("SVG1を選択")
        self.load_btn2 = QPushButton("SVG2を選択")
        self.compare_btn = QPushButton("比較")
        self.prev_x_btn = QPushButton("←")
        self.next_x_btn = QPushButton("→")
        self.prev_y_btn = QPushButton("↑")
        self.next_y_btn = QPushButton("↓")
        btn_layout.addWidget(self.load_btn1)
        btn_layout.addWidget(self.load_btn2)
        btn_layout.addWidget(self.compare_btn)
        btn_layout.addWidget(self.prev_x_btn)
        btn_layout.addWidget(self.next_x_btn)
        btn_layout.addWidget(self.prev_y_btn)
        btn_layout.addWidget(self.next_y_btn)
        self.layout.addLayout(btn_layout)

        opacity_layout = QHBoxLayout()
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(int(self.opacity * 100))
        self.diff_checkbox = QCheckBox("差分を表示")
        self.diff_checkbox.setChecked(True)
        opacity_layout.addWidget(self.opacity_slider)
        opacity_layout.addWidget(self.diff_checkbox)
        self.layout.addLayout(opacity_layout)

        self.view = GraphicsViewWithZoom()
        self.scene = QGraphicsScene(self)
        self.view.setScene(self.scene)
        self.layout.addWidget(self.view)

        self.load_btn1.clicked.connect(self.load_svg1)
        self.load_btn2.clicked.connect(self.load_svg2)
        self.compare_btn.clicked.connect(self.compare_svgs)
        self.next_x_btn.clicked.connect(self.next_tile_x)
        self.prev_x_btn.clicked.connect(self.prev_tile_x)
        self.next_y_btn.clicked.connect(self.next_tile_y)
        self.prev_y_btn.clicked.connect(self.prev_tile_y)
        self.opacity_slider.valueChanged.connect(self.change_opacity)
        self.diff_checkbox.stateChanged.connect(self.toggle_diff)

    def load_svg1(self):
        file, _ = QFileDialog.getOpenFileName(self, "SVG1を選択", "", "SVG Files (*.svg)")
        if file:
            self.svg1_path = file

    def load_svg2(self):
        file, _ = QFileDialog.getOpenFileName(self, "SVG2を選択", "", "SVG Files (*.svg)")
        if file:
            self.svg2_path = file

    def render_tile(self, path, x, y, w, h):
        renderer = QSvgRenderer(path)
        image = QImage(w, h, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        renderer.render(painter, QRectF(x, y, w, h))
        painter.end()
        return image

    def compare_images(self, img1, img2):
        result = QImage(img1.size(), QImage.Format_ARGB32)
        for x in range(img1.width()):
            for y in range(img1.height()):
                c1 = img1.pixel(x, y)
                c2 = img2.pixel(x, y)
                if c1 != c2:
                    result.setPixel(x, y, QColor("red").rgb())
                else:
                    result.setPixel(x, y, QColor(c1).rgb())
        return result

    def compare_svgs(self):
        if not self.svg1_path or not self.svg2_path:
            return
        img1 = self.render_tile(self.svg1_path, self.tile_x, self.tile_y, self.tile_width, self.tile_height)
        img2 = self.render_tile(self.svg2_path, self.tile_x, self.tile_y, self.tile_width, self.tile_height)

        self.scene.clear()
        pixmap1 = QGraphicsPixmapItem(QPixmap.fromImage(img1))
        pixmap2 = QGraphicsPixmapItem(QPixmap.fromImage(img2))
        pixmap2.setOpacity(self.opacity)

        self.scene.addItem(pixmap1)
        self.scene.addItem(pixmap2)

        if self.show_diff:
            diff = self.compare_images(img1, img2)
            diff_item = QGraphicsPixmapItem(QPixmap.fromImage(diff))
            self.scene.addItem(diff_item)

        self.view.resetTransform()
        self.view.scale(self.scale, self.scale)

    def next_tile_x(self):
        self.tile_x += self.tile_width
        self.compare_svgs()

    def prev_tile_x(self):
        self.tile_x = max(0, self.tile_x - self.tile_width)
        self.compare_svgs()

    def next_tile_y(self):
        self.tile_y += self.tile_height
        self.compare_svgs()

    def prev_tile_y(self):
        self.tile_y = max(0, self.tile_y - self.tile_height)
        self.compare_svgs()

    def change_opacity(self, value):
        self.opacity = value / 100.0
        self.compare_svgs()

    def toggle_diff(self, state):
        self.show_diff = bool(state)
        self.compare_svgs()

class GraphicsViewWithZoom(QGraphicsView): 
    def wheelEvent(self, event: QWheelEvent): 
        if event.modifiers() == Qt.ControlModifier: 
            delta = event.angleDelta().y() 
            if delta > 0:
                self.scale(1.1, 1.1) 
            else:
                    self.scale(0.9, 0.9) 
        else:
            super().wheelEvent(event)

if __name__ == "__main__": 
    app = QApplication(sys.argv) 
    viewer = SvgTileComparer() 
    viewer.resize(800, 600) 
    viewer.show() 
    sys.exit(app.exec())