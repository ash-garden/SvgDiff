import sys
import numpy as np
from scipy import ndimage
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QSlider, QLabel, QColorDialog,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
    QProgressDialog, QListWidget, QListWidgetItem, QSplitter,QSizePolicy
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
        self.setWindowTitle("SVG比較ツール（進捗キャンセル＋差分リスト対応）")
        self.setGeometry(100, 100, 1400, 900)

        # Scene & View
        self.scene = QGraphicsScene(self)
        self.view = GraphicsView()
        self.view.setScene(self.scene)

        # 差分リスト
        self.diff_list = QListWidget()
        # self.diff_list.itemClicked.connect(self.on_diff_item_selected)
        self.diff_list.itemSelectionChanged.connect(self.on_diff_selection_changed)

        # レイアウト：左にビュー、右にリスト
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.view)
        splitter.addWidget(self.diff_list)
        splitter.setStretchFactor(0, 9)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1260, 140]) 

        # ピクスマップ
        self.left_pixmap_item = None
        self.right_pixmap_item = None

        # 差分矩形
        self.diff_items = []
        self.diff_map = {}  # QListWidgetItem → QGraphicsRectItem

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

        # キャンセルフラグ
        self.cancel_requested = False

        # UIボタン群
        load_left_btn = QPushButton("左SVGを読み込む")
        load_right_btn = QPushButton("右SVGを読み込む")
        bg_color_btn = QPushButton("背景色を変更")

        self.ralpha_slider = QSlider(Qt.Horizontal)
        self.ralpha_slider.setRange(0, 100)
        self.ralpha_slider.setValue(50)
        self.ralpha_slider.valueChanged.connect(self.update_Ralpha)

        self.ralpha_label = QLabel("透過度: 50%")


        self.lalpha_slider = QSlider(Qt.Horizontal)
        self.lalpha_slider.setRange(0, 100)
        self.lalpha_slider.setValue(100)
        self.lalpha_slider.valueChanged.connect(self.update_Lalpha)

        self.lalpha_label = QLabel("透過度:100%")



        self.diff_toggle_btn = QPushButton("差分ハイライト ON")
        self.diff_toggle_btn.clicked.connect(self.toggle_diff)

        load_left_btn.clicked.connect(self.load_left)
        load_right_btn.clicked.connect(self.load_right)
        bg_color_btn.clicked.connect(self.change_background_color)

        # パス表示ラベル（透明度スライダー下、横並び）
        self.left_path_label = QLabel("左画像: 未選択")
        self.right_path_label = QLabel("右画像: 未選択")

        # 小さく固定してレイアウトを壊さない
        for lbl in (self.left_path_label, self.right_path_label):
            lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            lbl.setFixedHeight(20)
            lbl.setStyleSheet("font-size:11px;")  # 小さめフォント
            # 選択・コピーできるようにする
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)

        # レイアウト配置
        layout = QVBoxLayout()
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(bg_color_btn)
        btn_layout.addWidget(self.diff_toggle_btn)


        left_layout = QHBoxLayout()
        left_layout.addWidget(load_left_btn)
        left_layout.addWidget(self.left_path_label)
        left_layout.addWidget(self.lalpha_label)
        left_layout.addWidget(self.lalpha_slider)

        right_layout = QHBoxLayout()
        right_layout.addWidget(load_right_btn)
        right_layout.addWidget(self.right_path_label)
        right_layout.addWidget(self.ralpha_label)
        right_layout.addWidget(self.ralpha_slider)

        layout.addLayout(btn_layout)
        # layout.addLayout(Rslider_layout)
        # layout.addLayout(path_layout)   # ここをスライダーの下に配置
        layout.addLayout(left_layout)
        layout.addLayout(right_layout)
        layout.addWidget(splitter)
        self.setLayout(layout)

    # -------------------- SVG読み込み --------------------
    def load_left(self):
        path, _ = QFileDialog.getOpenFileName(self, "左SVGを選択", "", "SVG Files (*.svg)")
        if path:
            self.left_path_label.setText(f"左画像: {path}")
            self.left_path_label.setToolTip(path)
            self.left_renderer = QSvgRenderer(path)
            self.left_img = self.svg_to_qimage(self.left_renderer)
            self.left_arr = self.qimage_to_numpy_safe(self.left_img)
            self.update_scene_pixmaps()
            self.compute_diff()

    def load_right(self):
        path, _ = QFileDialog.getOpenFileName(self, "右SVGを選択", "", "SVG Files (*.svg)")
        if path:
            self.right_path_label.setText(f"右画像: {path}")
            self.right_path_label.setToolTip(path)
            self.right_renderer = QSvgRenderer(path)
            self.right_img = self.svg_to_qimage(self.right_renderer)
            self.right_arr = self.qimage_to_numpy_safe(self.right_img)
            self.update_scene_pixmaps()
            self.compute_diff()

    # -------------------- UI更新 --------------------
    def update_Ralpha(self, value):
        self.alpha = value / 100.0
        self.ralpha_label.setText(f"透過度: {value}%")
        if self.right_pixmap_item:
            self.right_pixmap_item.setOpacity(self.alpha)

    def update_Lalpha(self, value):
        self.alpha = value / 100.0
        self.ralpha_label.setText(f"透過度: {value}%")
        if self.left_pixmap_item:
            self.left_pixmap_item.setOpacity(self.alpha)

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
        self.diff_list.clear()
        self.diff_map.clear()

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

        total_tasks = len(tasks)

        # プログレスダイアログ
        self.cancel_requested = False
        progress = QProgressDialog("差分を計算中...", "キャンセル", 0, total_tasks, self)
        progress.setWindowTitle("進捗")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.canceled.connect(self._on_cancel)

        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(self._diff_tile_worker, *t) for t in tasks]
            for i, future in enumerate(as_completed(futures), 1):
                if self.cancel_requested:
                    break
                x0, y0, diff_tile = future.result()
                diff_mask[y0:y0+diff_tile.shape[0], x0:x0+diff_tile.shape[1]] = diff_tile
                progress.setValue(i)
                QApplication.processEvents()

        progress.setValue(total_tasks)

        if self.cancel_requested:
            return  # キャンセルされた場合は終了

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

            # リストに追加
            item = QListWidgetItem(f"差分 ({min_x}, {min_y})")
            item.setData(Qt.UserRole, rect)   # ← ここで矩形を埋め込む
            self.diff_list.addItem(item)
            # self.diff_map[item] = rect

    def _on_cancel(self):
        self.cancel_requested = True

    # -------------------- リスト選択処理 --------------------
    def on_diff_selection_changed(self):
        items = self.diff_list.selectedItems()
        if not items:
            return
        item = items[0]  # 複数選択対応ならループする
        data = item.data(Qt.UserRole)
        if isinstance(data, QGraphicsRectItem):
            center_point = data.sceneBoundingRect().center()
            self.view.centerOn(center_point)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SVGOverlayCompare()
    window.show()
    sys.exit(app.exec())
