import sys
import os, json, shutil
import numpy as np
from scipy import ndimage
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QSlider, QLabel, QColorDialog,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
    QProgressDialog, QListWidget, QListWidgetItem, QSplitter,QSizePolicy,QMessageBox ,
    QDialog,QProgressBar,QDialogButtonBox
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QPainter, QPixmap, QImage, QColor, QPen
from PySide6.QtCore import Qt,QRectF, QThread, Signal, Slot
from scipy.ndimage import label
import time  
import cv2

class MyExceptionCancel(Exception):
    def __init__(self, arg=""):
        self.arg = arg

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
        
        self.setWindowTitle("SVG比較ツール")
        self.setGeometry(100, 100, 1400, 900)

        # Scene & View
        self.scene = QGraphicsScene(self)
        self.view = GraphicsView()
        self.view.setScene(self.scene)

        # 操作性が悪い（レスポンスが悪く使い物にならない）
        # from PySide6.QtOpenGLWidgets import QOpenGLWidget
        # self.view.setViewport(QOpenGLWidget())

        # 差分リスト
        self.diff_list = QListWidget()
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


        self.save_result_btn = QPushButton("比較結果を保存")
        self.load_result_btn = QPushButton("保存結果を読み込み")
        self.save_result_btn.clicked.connect(self.save_compare_result)
        self.load_result_btn.clicked.connect(self.load_compare_result)

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
        btn_layout.addWidget(self.save_result_btn)
        btn_layout.addWidget(self.load_result_btn)
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
        layout.addLayout(left_layout)
        layout.addLayout(right_layout)
        layout.addWidget(splitter)
        self.setLayout(layout)

    def log_time(label, t0):
        print(f"[DEBUG] {label}: {time.time()-t0:.3f} 秒")
        
    # -------------------- SVG読み込み --------------------
    def load_left(self):
        try:
            self.load_svg("left")
        except(MyExceptionCancel) as e :
            QMessageBox.information(self, "情報", "キャンセルしました")

    def load_right(self):
        try:
            self.load_svg("right")
        except(MyExceptionCancel) as e :
            QMessageBox.information(self, "情報", "キャンセルしました")

    def load_svg(self, side: str):
        is_left = (side == "left")
        title = "左SVGを選択" if is_left else "右SVGを選択"
        path, _ = QFileDialog.getOpenFileName(self, title, "", "SVG Files (*.svg)")
        if not path:
            return

        progress = QProgressDialog("...", "キャンセル", 0, 100, self)
        progress.setWindowTitle("進捗")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.canceled.connect(self._on_cancel)

        # 共通処理
        progress.setLabelText("ラベル更新")
        t0 = time.time()
        label = self.left_path_label if is_left else self.right_path_label
        label.setText(f"{'左' if is_left else '右'}画像: {path}")
        label.setToolTip(path)
        print(f"[DEBUG] ラベル更新: {time.time() - t0:.3f} 秒")
        progress.setValue(5)
        if self.cancel_requested: raise MyExceptionCancel("")
            

        progress.setLabelText("QSvgRenderer作成")
        t0 = time.time()
        renderer = QSvgRenderer(path)
        print(f"[DEBUG] QSvgRenderer作成: {time.time() - t0:.3f} 秒")
        progress.setValue(20)
        if self.cancel_requested: raise MyExceptionCancel("")

        progress.setLabelText("svg_to_qimage")
        t0 = time.time()
        img = self.svg_to_qimage(renderer)
        print(f"[DEBUG] svg_to_qimage: {time.time() - t0:.3f} 秒")
        progress.setValue(30)
        if self.cancel_requested: raise MyExceptionCancel("")

        progress.setLabelText("qimage_to_numpy_safe")
        t0 = time.time()
        arr = self.qimage_to_numpy_safe(img)
        print(f"[DEBUG] qimage_to_numpy_safe: {time.time() - t0:.3f} 秒")
        progress.setValue(40)
        if self.cancel_requested: raise MyExceptionCancel("")

        if is_left:
            self.left_renderer, self.left_img, self.left_arr = renderer, img, arr
        else:
            self.right_renderer, self.right_img, self.right_arr = renderer, img, arr

        progress.setLabelText("update_scene_pixmaps")
        t0 = time.time()
        self.update_scene_pixmaps()
        print(f"[DEBUG] update_scene_pixmaps: {time.time() - t0:.3f} 秒")
        progress.setValue(50)
        if self.cancel_requested: raise MyExceptionCancel("")

        progress.setLabelText("compute_diff")
        t0 = time.time()
        self.compute_diff()
        print(f"[DEBUG] compute_diff: {time.time() - t0:.3f} 秒")
        progress.setValue(100)
        if self.cancel_requested: raise MyExceptionCancel("")
                    
    def save_compare_result(self):
        if self.left_arr is None or self.right_arr is None:
            return

        folder = QFileDialog.getExistingDirectory(self, "保存先フォルダを選択")
        if not folder:
            return
        self.cancel_requested = False
        self.progress = QProgressDialog("...", "キャンセル", 0, 100, self)
        self.progress.setWindowTitle("進捗")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.setLabelText("左右SVGコピー開始")
        self.progress.setValue(0)
        # 左右SVGコピー
        left_src = self.left_path_label.text().replace("左画像: ", "")
        right_src = self.right_path_label.text().replace("右画像: ", "")
        if os.path.exists(left_src):
            shutil.copy(left_src, os.path.join(folder, "left.svg"))
        if os.path.exists(right_src):
            shutil.copy(right_src, os.path.join(folder, "right.svg"))
        self.progress.setLabelText("左右SVGコピー完了")
        self.progress.setValue(10)

        self.progress.setLabelText("差分矩形データJson変換-開始")
        addVal = 80/len(self.diff_items)
        # 差分矩形データをJSONに保存
        rects = []
        for rect in self.diff_items:
            self.progress.setValue( self.progress.value() + addVal )
            r = rect.rect()
            rects.append({
                "x": r.x(), "y": r.y(), "w": r.width(), "h": r.height()
            })

        self.progress.setLabelText("Json保存-開始")
        self.progress.setValue(90)
        with open(os.path.join(folder, "diff_rects.json"), "w", encoding="utf-8") as f:
            json.dump(rects, f, ensure_ascii=False, indent=2)
        self.progress.setLabelText("Json保存-完了")
        self.progress.setValue(99)

        print(f"[INFO] 比較結果を保存しました: {folder}")
        self.progress.setValue(100)
        QMessageBox.information(self, "情報", "比較結果を保存しました")

    def load_compare_result(self):
        folder = QFileDialog.getExistingDirectory(self, "保存済み結果フォルダを選択")
        if not folder:
            return

        left_svg = os.path.join(folder, "left.svg")
        self.left_path_label.setText(f"左画像: {left_svg}")
        right_svg = os.path.join(folder, "right.svg")
        self.right_path_label.setText(f"右画像: {right_svg}")

        rects_json = os.path.join(folder, "diff_rects.json")

        if not (os.path.exists(left_svg) and os.path.exists(right_svg) and os.path.exists(rects_json)):
            print("[ERROR] 保存結果が不完全です。")
            return

        self.cancel_requested = False
        self.progress = QProgressDialog("...", "キャンセル", 0, 100, self)
        self.progress.setWindowTitle("進捗")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.setLabelText("左右SVG再読み込み開始")
        self.progress.setValue(10)
        # 左右再読込
        self.left_renderer = QSvgRenderer(left_svg)
        self.right_renderer = QSvgRenderer(right_svg)
        
        self.progress.setLabelText("左右SVG再読み込み開始")
        self.progress.setValue(20)
        self.left_img = self.svg_to_qimage(self.left_renderer)
        self.right_img = self.svg_to_qimage(self.right_renderer)
        self.progress.setLabelText("左右SVG再読み込み完了")
        self.progress.setValue(50)

        self.progress.setLabelText("update_scene_pixmaps")
        self.progress.setValue(51)
        self.update_scene_pixmaps()

        self.progress.setLabelText("差分矩形復元開始")
        self.progress.setValue(80)
        for item in self.diff_items:
            self.scene.removeItem(item)
        self.diff_items.clear()
        self.diff_list.clear()

        # 差分矩形復元
        with open(rects_json, "r", encoding="utf-8") as f:
            rects = json.load(f)

        for info in rects:
            rect = QGraphicsRectItem(info["x"], info["y"], info["w"], info["h"])
            pen = QPen(QColor(255, 0, 0, 200))
            pen.setWidth(3)
            rect.setPen(pen)
            rect.setBrush(Qt.NoBrush)
            rect.setVisible(self.diff_enabled)
            self.scene.addItem(rect)
            self.diff_items.append(rect)

            item = QListWidgetItem(f"差分 ({info['x']}, {info['y']})")
            item.setData(Qt.UserRole, rect)
            self.diff_list.addItem(item)
        self.progress.setLabelText("差分矩形復元完了")
        self.progress.setValue(99)

        print(f"[INFO] 保存結果を読み込みました: {folder}")    
        self.progress.setValue(100)
        QMessageBox.information(self, "情報", "保存結果を読み込みました")
            
    # -------------------- UI更新 --------------------
    def update_Ralpha(self, value):
        self.alpha = value / 100.0
        self.ralpha_label.setText(f"透過度: {value}%")
        if self.right_pixmap_item:
            self.right_pixmap_item.setOpacity(self.alpha)

    def update_Lalpha(self, value):
        self.alpha = value / 100.0
        self.lalpha_label.setText(f"透過度: {value}%")
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
    #13秒
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
        return np.array(arr)  # copyが必要な場合だけここで
        # return arr.copy()
        # return arr

    #15秒
    # def qimage_to_numpy_safe(self, img: QImage):
    #     """QImage → NumPy配列（安全変換）"""
    #     if img.format() != QImage.Format_RGBA8888:
    #         img = img.convertToFormat(QImage.Format_RGBA8888)
    #     width = img.width()
    #     height = img.height()
    #     ptr = img.bits()
    #     arr = np.frombuffer(ptr, np.uint8).reshape((height, width, 4)).copy()
    #     return arr


    # -------------------- Scene 更新 --------------------
    def update_scene_pixmaps(self): #10s
        if not self.left_img or not self.right_img:
            return

        t0 = time.time()
        # 10.125 秒
        left_pix = QPixmap.fromImage(self.left_img)
        right_pix = QPixmap.fromImage(self.right_img)

        # 10.465 秒
        # def make_pixmap(img):
        #     return QPixmap.fromImage(img)
        # # 左右を別スレッドで QPixmap に変換
        # with ThreadPoolExecutor(max_workers=2) as executor:
        #     future_left = executor.submit(make_pixmap, self.left_img)
        #     future_right = executor.submit(make_pixmap, self.right_img)
        #     left_pix = future_left.result()
        #     right_pix = future_right.result()

        print(f"[DEBUG] QPixmapに変換: {time.time() - t0:.3f} 秒")

        t0 = time.time()
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
        print(f"[DEBUG] QGraphicsPixmapItem: {time.time() - t0:.3f} 秒")

        t0 = time.time()
        self.view.setSceneRect(0, 0,
                               max(self.left_img.width(), self.right_img.width()),
                               max(self.left_img.height(), self.right_img.height()))
        print(f"[DEBUG] setSceneRect: {time.time() - t0:.3f} 秒")

    def compute_diff(self):
        """左右の画像を比較して差分領域を表示（マスク単位で絞り込み対応版）"""
        if self.left_arr is None or self.right_arr is None:
            print("左右いずれかの画像が未読み込みのため、比較できません。")
            return

        # --- 初期化 ---
        print("差分計算開始")
        t0 = time.time()
        for item in self.diff_items:
            self.scene.removeItem(item)
        self.diff_items.clear()
        self.diff_list.clear()
        print(f"[DEBUG] 差分矩形クリア: {time.time() - t0:.3f} 秒")

        arr_l = self.left_arr
        arr_r = self.right_arr

        if arr_l.shape != arr_r.shape:
            print("左右の画像サイズが異なります。比較を中止します。")
            return

        h, w, _ = arr_l.shape

        # --- ステップ1: 低解像度比較 ---
        scale = 0.1  # 1/10サイズで比較
        arr_l_low = cv2.resize(arr_l, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        arr_r_low = cv2.resize(arr_r, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        diff_low = cv2.absdiff(arr_l_low, arr_r_low)
        diff_low = np.any(diff_low != 0, axis=2).astype(np.uint8) * 255

        # --- ステップ2: ノイズ除去（モルフォロジー） ---
        kernel = np.ones((3, 3), np.uint8)
        diff_low = cv2.morphologyEx(diff_low, cv2.MORPH_OPEN, kernel)
        diff_low = cv2.morphologyEx(diff_low, cv2.MORPH_CLOSE, kernel)

        # --- ステップ3: 差分領域をラベリング ---
        num_labels, labels_low = cv2.connectedComponents(diff_low)
        print(f"検出された差分領域数: {num_labels - 1}")

        # スケール倍率（低解像度 → 高解像度）
        scale_x = w / diff_low.shape[1]
        scale_y = h / diff_low.shape[0]

        # --- ステップ4: 各差分領域ごとに高解像度再比較 ---
        rects = []
        for label_id in range(1, num_labels):  # 0 は背景
            ys, xs = np.nonzero(labels_low == label_id)
            if len(xs) == 0 or len(ys) == 0:
                continue

            # ラベル領域（低解像度座標）
            x1, x2 = xs.min(), xs.max()
            y1, y2 = ys.min(), ys.max()

            # 高解像度座標に変換
            x1h = int(x1 * scale_x)
            x2h = int((x2 + 1) * scale_x)
            y1h = int(y1 * scale_y)
            y2h = int((y2 + 1) * scale_y)

            # 安全クリップ
            x1h = max(0, x1h)
            y1h = max(0, y1h)
            x2h = min(w, x2h)
            y2h = min(h, y2h)

            # 領域抽出
            arr_l_tile = arr_l[y1h:y2h, x1h:x2h]
            arr_r_tile = arr_r[y1h:y2h, x1h:x2h]
            if arr_l_tile.size == 0 or arr_r_tile.size == 0:
                continue

            # 高解像度差分
            diff_high = cv2.absdiff(arr_l_tile, arr_r_tile)
            diff_high = np.any(diff_high != 0, axis=2)

            # 差分座標抽出
            ys_h, xs_h = np.nonzero(diff_high)
            if len(xs_h) == 0 or len(ys_h) == 0:
                continue

            # --- 小さいノイズ除去（面積閾値） ---
            area = (x2h - x1h) * (y2h - y1h)
            if area < 100:  # 面積閾値
                continue

            # --- 最終的な矩形領域を算出 ---
            rect = QRectF(
                float(x1h + xs_h.min()),
                float(y1h + ys_h.min()),
                float(xs_h.max() - xs_h.min()),
                float(ys_h.max() - ys_h.min())
            )
            rects.append(rect)

        # --- ステップ5: 差分矩形を描画 ---
        pen = QPen(Qt.red)
        for rect in rects:
            item = QGraphicsRectItem(rect)
            item.setPen(pen)
            self.scene.addItem(item)
            self.diff_items.append(item)

            item = QListWidgetItem(f"差分 ({rect.x()}, {rect.y()})")
            item.setData(Qt.UserRole, rect)
            self.diff_list.addItem(item)

        print(f"描画された差分矩形数: {len(rects)}")
        print("差分計算完了")
        QMessageBox.information(self, "情報", "差分表示完了しました")

    def _on_cancel(self):
        self.cancel_requested = True

    # -------------------- リスト選択処理 --------------------
    def on_diff_selection_changed(self):
        items = self.diff_list.selectedItems()
        if not items:
            return
        item = items[0]  # 複数選択対応ならループする
        data = item.data(Qt.UserRole)

        # QGraphicsRectItem の場合
        if isinstance(data, QRectF):
            center_point = data.center()
            self.view.centerOn(center_point)       # 中心に移動
            self.view.ensureVisible(data, 20, 20)  # 余白20pxで矩形を表示           


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SVGOverlayCompare()
    window.show()
    sys.exit(app.exec())
