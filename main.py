import sys
import numpy as np
from scipy import ndimage
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QSlider, QLabel, QColorDialog,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
    QProgressDialog, QListWidget, QListWidgetItem, QSplitter,QSizePolicy,
    QDialog,QProgressBar,QDialogButtonBox
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QPainter, QPixmap, QImage, QColor, QPen
from PySide6.QtCore import Qt,QRectF, QThread, Signal, Slot
from scipy.ndimage import label
import time  
import cv2



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
            # プログレスダイアログ
            self.cancel_requested = False
            progress = QProgressDialog("...", "キャンセル", 0, 100, self)
            progress.setWindowTitle("進捗")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.canceled.connect(self._on_cancel)

            progress.setLabelText("左パスラベル更新")
            t0 = time.time()
            self.left_path_label.setText(f"左画像: {path}")
            print(f"[DEBUG] 左パスラベル更新: {time.time() - t0:.3f} 秒")
            progress.setValue(5)

            progress.setLabelText("左ツールチップ更新")
            t0 = time.time()
            self.left_path_label.setToolTip(path)
            print(f"[DEBUG] 左ツールチップ更新: {time.time() - t0:.3f} 秒")
            progress.setValue(10)

            progress.setLabelText("QSvgRenderer作成")
            t0 = time.time()
            self.left_renderer = QSvgRenderer(path)
            print(f"[DEBUG] QSvgRenderer作成: {time.time() - t0:.3f} 秒")
            progress.setValue(20)

            progress.setLabelText("svg_to_qimage")
            t0 = time.time()
            self.left_img = self.svg_to_qimage(self.left_renderer)
            print(f"[DEBUG] svg_to_qimage: {time.time() - t0:.3f} 秒")
            progress.setValue(30)

            progress.setLabelText("qimage_to_numpy_safe")
            t0 = time.time()
            self.left_arr = self.qimage_to_numpy_safe(self.left_img)
            print(f"[DEBUG] qimage_to_numpy_safe: {time.time() - t0:.3f} 秒")
            progress.setValue(40)

            progress.setLabelText("update_scene_pixmaps")
            t0 = time.time()
            self.update_scene_pixmaps()
            print(f"[DEBUG] update_scene_pixmaps: {time.time() - t0:.3f} 秒")
            progress.setValue(50)

            progress.setLabelText("compute_diff")
            t0 = time.time()
            self.compute_diff()
            print(f"[DEBUG] compute_diff: {time.time() - t0:.3f} 秒")
            progress.setValue(100)


    def load_right(self):
        path, _ = QFileDialog.getOpenFileName(self, "右SVGを選択", "", "SVG Files (*.svg)")
        if path:
            # プログレスダイアログ
            self.cancel_requested = False
            progress = QProgressDialog("...", "キャンセル", 0, 100, self)
            self.progress = progress
            progress.setWindowTitle("進捗")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.canceled.connect(self._on_cancel)

            progress.setLabelText("右パスラベル更新")
            t0 = time.time()
            self.right_path_label.setText(f"右画像: {path}")
            print(f"[DEBUG] 右パスラベル更新: {time.time() - t0:.3f} 秒")
            progress.setValue(5)

            progress.setLabelText("右ツールチップ更新")
            t0 = time.time()
            self.right_path_label.setToolTip(path)
            print(f"[DEBUG] 右ツールチップ更新: {time.time() - t0:.3f} 秒")
            progress.setValue(10)

            progress.setLabelText("QSvgRenderer作成")
            t0 = time.time()
            self.right_renderer = QSvgRenderer(path)
            print(f"[DEBUG] QSvgRenderer作成: {time.time() - t0:.3f} 秒")
            progress.setValue(20)

            progress.setLabelText("svg_to_qimage")
            t0 = time.time()
            self.right_img = self.svg_to_qimage(self.right_renderer)
            print(f"[DEBUG] svg_to_qimage: {time.time() - t0:.3f} 秒")
            progress.setValue(30)

            progress.setLabelText("qimage_to_numpy_safe")
            t0 = time.time()
            self.right_arr = self.qimage_to_numpy_safe(self.right_img)
            print(f"[DEBUG] qimage_to_numpy_safe: {time.time() - t0:.3f} 秒")
            progress.setValue(40)

            progress.setLabelText("update_scene_pixmaps")
            t0 = time.time()
            self.update_scene_pixmaps()
            print(f"[DEBUG] update_scene_pixmaps: {time.time() - t0:.3f} 秒")
            progress.setValue(50)

            progress.setLabelText("compute_diff")
            t0 = time.time()
            self.compute_diff()
            print(f"[DEBUG] compute_diff: {time.time() - t0:.3f} 秒")
            progress.setValue(100)
            
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

    # # -------------------- 安全に QImage → NumPy --------------------
    # def qimage_to_numpy_safe(self, img: QImage):    #11.6
    #     img = img.convertToFormat(QImage.Format_ARGB32)
    #     img_copy = img.copy()
    #     ptr = img_copy.bits()
    #     arr = np.array(ptr).reshape(img_copy.height(), img_copy.width(), 4)
    #     return arr
    def qimage_to_numpy_safe(self, img: QImage):    #9.7s
        """
        QImage → NumPy 配列 高速版（ゼロコピー + パディング対応）
        """
        # 形式をRGBAに統一
        if img.format() != QImage.Format_RGBA8888:
            img = img.convertToFormat(QImage.Format_RGBA8888)

        w, h = img.width(), img.height()
        ptr = img.bits()

        # memoryview を使って NumPy 配列を作成
        byte_count = img.bytesPerLine() * img.height()
        arr = np.frombuffer(ptr, dtype=np.uint8, count=byte_count)
        arr = arr.reshape((h, img.bytesPerLine() // 4, 4))

        # 不要な列をカット（bytesPerLineで余った分を除去）
        arr = arr[:, :w, :]

        return arr.copy()
        # return arr
    # -------------------- Scene 更新 --------------------
    def update_scene_pixmaps(self): #10s
        if not self.left_img or not self.right_img:
            return

        # left_pix = QPixmap.fromImage(self.left_img)
        # right_pix = QPixmap.fromImage(self.right_img)
        def make_pixmap(img):
            return QPixmap.fromImage(img)

        
        # 左右を別スレッドで QPixmap に変換
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_left = executor.submit(make_pixmap, self.left_img)
            future_right = executor.submit(make_pixmap, self.right_img)
            left_pix = future_left.result()
            right_pix = future_right.result()

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
    # def update_scene_pixmaps(self):     #13.9
    #     if self.left_img is None or self.right_img is None:
    #         return

    #     def make_pixmap(img):
    #         return QPixmap.fromImage(img)

    #     # 左右を別スレッドで QPixmap に変換
    #     with ThreadPoolExecutor(max_workers=2) as executor:
    #         future_left = executor.submit(make_pixmap, self.left_img)
    #         future_right = executor.submit(make_pixmap, self.right_img)
    #         left_pix = future_left.result()
    #         right_pix = future_right.result()

    #     # GUI スレッドで反映
    #     if self.left_pixmap_item is None:
    #         self.left_pixmap_item = QGraphicsPixmapItem(left_pix)
    #         self.scene.addItem(self.left_pixmap_item)
    #     else:
    #         self.left_pixmap_item.setPixmap(left_pix)

    #     if self.right_pixmap_item is None:
    #         self.right_pixmap_item = QGraphicsPixmapItem(right_pix)
    #         self.right_pixmap_item.setOpacity(self.alpha)
    #         self.scene.addItem(self.right_pixmap_item)
    #     else:
    #         self.right_pixmap_item.setPixmap(right_pix)
    #         self.right_pixmap_item.setOpacity(self.alpha)

    #     # シーンサイズをフル解像度に設定
    #     self.view.setSceneRect(0, 0,
    #                         max(self.left_img.width(), self.right_img.width()),
    #                         max(self.left_img.height(), self.right_img.height()))
    # -------------------- タイル差分 --------------------
    def _diff_tile_worker(self, arr_l_tile, arr_r_tile, x0, y0):
        diff_tile = np.any(arr_l_tile != arr_r_tile, axis=2)
        return x0, y0, diff_tile

    # def compute_diff(self):
    #     if self.left_arr is None or self.right_arr is None:
    #         return

    #     h, w, _ = self.left_arr.shape
    #     tile_size = 512

    #     # 差分矩形クリア
    #     for item in self.diff_items:
    #         self.scene.removeItem(item)
    #     self.diff_items.clear()
    #     self.diff_list.clear()
    #     self.diff_map.clear()

    #     diff_mask = np.zeros((h, w), dtype=bool)

    #     # タイル分割
    #     tasks = []
    #     for y0 in range(0, h, tile_size):
    #         for x0 in range(0, w, tile_size):
    #             h_tile = min(tile_size, h - y0)
    #             w_tile = min(tile_size, w - x0)
    #             arr_l_tile = self.left_arr[y0:y0+h_tile, x0:x0+w_tile, :]
    #             arr_r_tile = self.right_arr[y0:y0+h_tile, x0:x0+w_tile, :]
    #             tasks.append((arr_l_tile, arr_r_tile, x0, y0))

    #     total_tasks = len(tasks)

    #     # プログレスダイアログ
    #     self.cancel_requested = False
    #     progress = QProgressDialog("差分を計算中...", "キャンセル", 0, total_tasks, self)
    #     progress.setWindowTitle("進捗")
    #     progress.setWindowModality(Qt.WindowModal)
    #     progress.setMinimumDuration(0)
    #     progress.canceled.connect(self._on_cancel)

    #     with ThreadPoolExecutor() as executor:
    #         futures = [executor.submit(self._diff_tile_worker, *t) for t in tasks]
    #         for i, future in enumerate(as_completed(futures), 1):
    #             if self.cancel_requested:
    #                 break
    #             x0, y0, diff_tile = future.result()
    #             diff_mask[y0:y0+diff_tile.shape[0], x0:x0+diff_tile.shape[1]] = diff_tile
    #             progress.setValue(i)
    #             QApplication.processEvents()

    #     progress.setValue(total_tasks)

    #     if self.cancel_requested:
    #         return  # キャンセルされた場合は終了
    # def compute_diff(self):
    #     if self.left_arr is None or self.right_arr is None:
    #         return

    #     h, w, _ = self.left_arr.shape
    #     tile_size = 2048  # CPUなら大きめのタイルでもOK

    #     # 差分矩形クリア
    #     t0 = time.time()
    #     for item in self.diff_items:
    #         self.scene.removeItem(item)
    #     self.diff_items.clear()
    #     self.diff_list.clear()
    #     self.diff_map.clear()
    #     print(f"[DEBUG] 差分矩形クリア: {time.time() - t0:.3f} 秒")
    #     t0 = time.time()

    #     # タイルごとのタスク生成
    #     tasks = []
    #     for y0 in range(0, h, tile_size):
    #         for x0 in range(0, w, tile_size):
    #             h_tile = min(tile_size, h - y0)
    #             w_tile = min(tile_size, w - x0)
    #             arr_l_tile = self.left_arr[y0:y0+h_tile, x0:x0+w_tile, :]
    #             arr_r_tile = self.right_arr[y0:y0+h_tile, x0:x0+w_tile, :]
    #             tasks.append((arr_l_tile, arr_r_tile, x0, y0))
    #     print(f"[DEBUG] タイルごとのタスク生成: {time.time() - t0:.3f} 秒")
    #     t0 = time.time()

    #     total_tasks = len(tasks)

    #     # プログレスダイアログ
    #     self.cancel_requested = False
    #     progress = QProgressDialog("差分を計算中...", "キャンセル", 0, total_tasks, self)
    #     progress.setWindowTitle("進捗")
    #     progress.setWindowModality(Qt.WindowModal)
    #     progress.setMinimumDuration(0)
    #     progress.canceled.connect(self._on_cancel)

    #     diff_mask = np.zeros((h, w), dtype=bool)

    #     # タイルごとの差分計算を並列化
    #     def diff_tile_worker(arr_l, arr_r, x0, y0):
    #         diff_tile = np.any(arr_l != arr_r, axis=2)
    #         return x0, y0, diff_tile

    #     with ThreadPoolExecutor() as executor:
    #         futures = [executor.submit(diff_tile_worker, *t) for t in tasks]
    #         for i, future in enumerate(as_completed(futures), 1):
    #             if self.cancel_requested:
    #                 break
    #             x0, y0, diff_tile = future.result()
    #             diff_mask[y0:y0+diff_tile.shape[0], x0:x0+diff_tile.shape[1]] = diff_tile
    #             progress.setValue(i)
    #             QApplication.processEvents()
    #     print(f"[DEBUG] タイル差分計算完了: {time.time() - t0:.3f} 秒")
    #     t0 = time.time()

    #     progress.setValue(total_tasks)
    #     if self.cancel_requested:
    #         return

    #     # # ■ ラベリング
    #     # structure = np.ones((3,3), dtype=int)
    #     # labeled, num_features = ndimage.label(diff_mask, structure=structure)
    #     # print(f"[DEBUG] ラベリング完了: {time.time() - t0:.3f} 秒, num_features={num_features}")
    #     # t0 = time.time()

    #     # =============================
    #     # ■ 並列ラベリング処理
    #     # =============================
    #     structure = np.ones((3, 3), dtype=int)
    #     label_tiles = []
    #     label_offset = 0
    #     label_map = np.zeros((h, w), dtype=np.int32)

    #     tasks_label = []
    #     for y0 in range(0, h, tile_size):
    #         for x0 in range(0, w, tile_size):
    #             h_tile = min(tile_size, h - y0)
    #             w_tile = min(tile_size, w - x0)
    #             diff_tile = diff_mask[y0:y0+h_tile, x0:x0+w_tile]
    #             tasks_label.append((diff_tile, x0, y0))

    #     print(f"[DEBUG] ラベリング並列タスク数: {len(tasks_label)}")

    #     def label_worker(diff_tile, x0, y0):
    #         labeled_tile, num = ndimage.label(diff_tile, structure=structure)
    #         return x0, y0, labeled_tile, num

    #     total_features = 0
    #     with ThreadPoolExecutor() as executor:
    #         futures = [executor.submit(label_worker, *t) for t in tasks_label]
    #         for future in as_completed(futures):
    #             x0, y0, labeled_tile, num = future.result()
    #             if num > 0:
    #                 # ラベル値をグローバルIDに補正
    #                 labeled_tile[labeled_tile > 0] += label_offset
    #                 label_map[y0:y0+labeled_tile.shape[0], x0:x0+labeled_tile.shape[1]] = labeled_tile
    #                 label_offset += num
    #                 total_features += num

    #     print(f"[DEBUG] 並列ラベリング完了: {time.time() - t0:.3f} 秒, 総領域数={total_features}")
    #     t0 = time.time()
        
    #     # =============================
    #     # ■ ベクトル化で外接矩形算出
    #     # =============================
    #     ys, xs = np.nonzero(label_map)
    #     labels = label_map[ys, xs]
    #     rects = []

    #     # 各ラベルごとにmin/max座標を求める（ベクトル処理）
    #     if len(labels) > 0:
    #         unique_labels = np.unique(labels)
    #         for label_id in unique_labels:
    #             if label_id == 0:
    #                 continue
    #             mask = labels == label_id
    #             y_coords = ys[mask]
    #             x_coords = xs[mask]
    #             x0, x1 = x_coords.min(), x_coords.max()
    #             y0, y1 = y_coords.min(), y_coords.max()
    #             rects.append((x0, y0, x1, y1))

    #     print(f"[DEBUG] 外接矩形算出完了: {time.time() - t0:.3f} 秒, 矩形数={len(rects)}")
    #     t0 = time.time()

    #     # =============================
    #     # ■ Qt矩形生成
    #     # =============================
    #     for x0, y0, x1, y1 in rects:
    #         rect = QGraphicsRectItem(x0, y0, x1-x0+1, y1-y0+1)
    #         pen = QPen(QColor(255, 0, 0, 200))
    #         pen.setWidth(3)
    #         rect.setPen(pen)
    #         rect.setBrush(Qt.NoBrush)
    #         rect.setVisible(self.diff_enabled)
    #         self.scene.addItem(rect)
    #         self.diff_items.append(rect)

    #         item = QListWidgetItem(f"差分 ({x0}, {y0})")
    #         item.setData(Qt.UserRole, rect)
    #         self.diff_list.addItem(item)
    #         self.diff_map[(x0, y0)] = rect

    #     print(f"[DEBUG] Qt矩形作成完了: {time.time() - t0:.3f} 秒")
    def compute_diff(self):
        if self.left_arr is None or self.right_arr is None:
            return

        h, w, _ = self.left_arr.shape
        tile_size = 2048  # 高解像度比較時のタイルサイズ
        scale_factor = 0.125  # 低解像度比較時の縮小倍率（1/8）

        # ==========================================================
        # 差分矩形クリア
        # ==========================================================
        t0 = time.time()
        for item in self.diff_items:
            self.scene.removeItem(item)
        self.diff_items.clear()
        self.diff_list.clear()
        self.diff_map.clear()
        print(f"[DEBUG] 差分矩形クリア: {time.time() - t0:.3f} 秒")


        # ==========================================================
        # OpenCVで低解像度画像生成
        # ==========================================================
        self.progress.setLabelText("低解像度画像生成")
        self.progress.setValue(51)
        t0 = time.time()
        left_low = cv2.resize(self.left_arr, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_AREA)
        right_low = cv2.resize(self.right_arr, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_AREA)
        outtxt=f"低解像度画像生成完了: {time.time() - t0:.3f} 秒"
        print("[DEBUG] "+ outtxt)        
        self.progress.setLabelText(outtxt)
        self.progress.setValue(54)

        # ==========================================================
        # 低解像度差分検出
        # ==========================================================
        self.progress.setLabelText("低解像度差分マップ作成")
        self.progress.setValue(55)
        t0 = time.time()
        diff_low = np.any(left_low != right_low, axis=2)
        diff_low = diff_low.astype(np.uint8) * 255

        # 小ノイズ除去（モルフォロジー開閉）
        kernel = np.ones((3,3), np.uint8)
        diff_low = cv2.morphologyEx(diff_low, cv2.MORPH_OPEN, kernel)
        diff_low = cv2.morphologyEx(diff_low, cv2.MORPH_CLOSE, kernel)

        # 差分を元のサイズに拡大
        diff_mask_rough = cv2.resize(diff_low, (w, h), interpolation=cv2.INTER_NEAREST) > 0
        outtxt=f"低解像度差分マップ作成完了: {time.time() - t0:.3f} 秒"
        print("[DEBUG] "+ outtxt)        
        self.progress.setLabelText(outtxt)
        self.progress.setValue(59)

        # ==========================================================
        # 粗い差分マップから再比較対象領域を抽出
        # ==========================================================
        self.progress.setLabelText("高解像度再比較領域作成")
        self.progress.setValue(60)
        t0 = time.time()
        ys, xs = np.nonzero(diff_mask_rough)
        if len(xs) == 0:
            print("[DEBUG] 差分なし（低解像度段階）")
            return

        # 高解像度で再チェックする矩形を生成
        min_x, max_x = xs.min(), xs.max()
        min_y, max_y = ys.min(), ys.max()
        pad = 32  # 周辺を少し広げて再比較
        min_x = max(0, min_x - pad)
        min_y = max(0, min_y - pad)
        max_x = min(w, max_x + pad)
        max_y = min(h, max_y + pad)
        outtxt=f"高解像度再比較領域: ({min_x},{min_y}) - ({max_x},{max_y})"
        print("[DEBUG] "+ outtxt)        
        self.progress.setLabelText(outtxt)
        self.progress.setValue(64)

        # ==========================================================
        # 高解像度再比較（並列タイル処理）
        # ==========================================================
        self.progress.setLabelText("高解像度再比較")
        self.progress.setValue(65)
        t0 = time.time()
        diff_mask = np.zeros((h, w), dtype=bool)

        # 再比較対象領域をタイルに分割
        tasks = []
        for y0 in range(min_y, max_y, tile_size):
            for x0 in range(min_x, max_x, tile_size):
                h_tile = min(tile_size, max_y - y0)
                w_tile = min(tile_size, max_x - x0)
                arr_l_tile = self.left_arr[y0:y0+h_tile, x0:x0+w_tile, :]
                arr_r_tile = self.right_arr[y0:y0+h_tile, x0:x0+w_tile, :]
                tasks.append((arr_l_tile, arr_r_tile, x0, y0))
        print(f"[DEBUG] 高解像度再比較タスク生成: {len(tasks)} 個")

        progress = QProgressDialog("高解像度再比較中...", "キャンセル", 0, len(tasks), self)
        progress.setWindowTitle("進捗")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.canceled.connect(self._on_cancel)

        def diff_tile_worker(arr_l, arr_r, x0, y0):
            diff_tile = np.any(arr_l != arr_r, axis=2)
            return x0, y0, diff_tile

        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(diff_tile_worker, *t) for t in tasks]
            for i, future in enumerate(as_completed(futures), 1):
                if self.cancel_requested:
                    break
                x0, y0, diff_tile = future.result()
                diff_mask[y0:y0+diff_tile.shape[0], x0:x0+diff_tile.shape[1]] = diff_tile
                progress.setValue(i)
                QApplication.processEvents()

        progress.setValue(len(tasks))
        if self.cancel_requested:
            return
        outtxt=f"高解像度差分計算完了: {time.time() - t0:.3f} 秒"
        print("[DEBUG] "+ outtxt)        
        self.progress.setLabelText(outtxt)
        self.progress.setValue(69)

        # # ==========================================================
        # # ラベリング
        # # ==========================================================
        # structure = np.ones((3,3), dtype=int)
        # labeled, num_features = ndimage.label(diff_mask, structure=structure)
        # print(f"[DEBUG] ラベリング完了: {time.time() - t0:.3f} 秒, num_features={num_features}")
        # t0 = time.time()
        # # =============================
        # # ■ 並列ラベリング処理
        # # =============================
        # structure = np.ones((3, 3), dtype=int)
        # label_tiles = []
        # label_offset = 0
        # label_map = np.zeros((h, w), dtype=np.int32)

        # tasks_label = []
        # for y0 in range(0, h, tile_size):
        #     for x0 in range(0, w, tile_size):
        #         h_tile = min(tile_size, h - y0)
        #         w_tile = min(tile_size, w - x0)
        #         diff_tile = diff_mask[y0:y0+h_tile, x0:x0+w_tile]
        #         tasks_label.append((diff_tile, x0, y0))

        # print(f"[DEBUG] ラベリング並列タスク数: {len(tasks_label)}")

        # def label_worker(diff_tile, x0, y0):
        #     labeled_tile, num = ndimage.label(diff_tile, structure=structure)
        #     return x0, y0, labeled_tile, num

        # total_features = 0
        # with ThreadPoolExecutor() as executor:
        #     futures = [executor.submit(label_worker, *t) for t in tasks_label]
        #     for future in as_completed(futures):
        #         x0, y0, labeled_tile, num = future.result()
        #         if num > 0:
        #             # ラベル値をグローバルIDに補正
        #             labeled_tile[labeled_tile > 0] += label_offset
        #             label_map[y0:y0+labeled_tile.shape[0], x0:x0+labeled_tile.shape[1]] = labeled_tile
        #             label_offset += num
        #             total_features += num

        # print(f"[DEBUG] 並列ラベリング完了: {time.time() - t0:.3f} 秒, 総領域数={total_features}")
        # t0 = time.time()

        # # ==========================================================
        # # 外接矩形算出
        # # ==========================================================
        # ys, xs = np.nonzero(labeled)
        # labels = labeled[ys, xs]
        # rects = []
        # if len(labels) > 0:
        #     unique_labels = np.unique(labels)
        #     for label_id in unique_labels:
        #         if label_id == 0:
        #             continue
        #         mask = labels == label_id
        #         y_coords = ys[mask]
        #         x_coords = xs[mask]
        #         x0, x1 = x_coords.min(), x_coords.max()
        #         y0, y1 = y_coords.min(), y_coords.max()
        #         rects.append((x0, y0, x1, y1))

        # print(f"[DEBUG] 外接矩形算出完了: {time.time() - t0:.3f} 秒, 矩形数={len(rects)}")
        # t0 = time.time()

        # ==========================================================
        # ■ OpenCVによる高速ラベリング
        # ==========================================================
        self.progress.setLabelText("ラベリング")
        self.progress.setValue(70)
        t0 = time.time()
        diff_mask_uint8 = diff_mask.astype(np.uint8)  # OpenCVはuint8を要求
        num_labels, labeled = cv2.connectedComponents(diff_mask_uint8, connectivity=8)
        num_features = num_labels - 1  # 背景(0)を除く
        outtxt = f"ラベリング完了(OpenCV): {time.time() - t0:.3f} 秒, num_features={num_features}"
        print("[DEBUG] "+ outtxt)        
        self.progress.setLabelText(outtxt)
        self.progress.setValue(79)

        # ==========================================================
        # 外接矩形算出（並列化版）
        # ==========================================================
        self.progress.setLabelText("外接矩形算出")
        self.progress.setValue(80)
        t0 = time.time()
        ys, xs = np.nonzero(labeled)
        labels = labeled[ys, xs]
        if len(labels) == 0:
            print("[DEBUG] 差分なし")
            return

        unique_labels = np.unique(labels)
        rects = []

        # --- 並列処理関数 ---
        def rect_worker(self,label_ids,length):
            sub_rects = []
            for label_id in label_ids:
                if label_id == 0:
                    continue
                mask = labels == label_id
                y_coords = ys[mask]
                x_coords = xs[mask]
                x0, x1 = x_coords.min(), x_coords.max()
                y0, y1 = y_coords.min(), y_coords.max()
                sub_rects.append((x0, y0, x1, y1))
            self.progress.setValue(self.progress.value()+10/length)
            return sub_rects

        # --- ラベル分割 ---
        num_threads = min(8, len(unique_labels))  # 例: 最大8スレッド
        label_chunks = np.array_split(unique_labels, num_threads)
        

        # with ThreadPoolExecutor(max_workers=num_threads) as executor:
        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(rect_worker, self, chunk,len(label_chunks)) for chunk in label_chunks]
            for future in as_completed(futures):
                rects.extend(future.result())

        outtxt=f"外接矩形算出完了(並列): {time.time() - t0:.3f} 秒, 矩形数={len(rects)}"
        print("[DEBUG] "+ outtxt)        
        self.progress.setLabelText(outtxt)
        self.progress.setValue(89)
        
        # ==========================================================
        # Qt矩形生成
        # ==========================================================
        self.progress.setLabelText("Qt矩形生成")
        self.progress.setValue(90)
        t0 = time.time()
        for x0, y0, x1, y1 in rects:
            rect = QGraphicsRectItem(x0, y0, x1-x0+1, y1-y0+1)
            pen = QPen(QColor(255, 0, 0, 200))
            pen.setWidth(3)
            rect.setPen(pen)
            rect.setBrush(Qt.NoBrush)
            rect.setVisible(self.diff_enabled)
            self.scene.addItem(rect)
            self.diff_items.append(rect)

            item = QListWidgetItem(f"差分 ({x0}, {y0})")
            item.setData(Qt.UserRole, rect)
            self.diff_list.addItem(item)
            self.diff_map[(x0, y0)] = rect
        outtxt=f"Qt矩形作成完了: {time.time() - t0:.3f} 秒"
        print("[DEBUG] "+ outtxt)        
        self.progress.setLabelText(outtxt)
        self.progress.setValue(99)

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
