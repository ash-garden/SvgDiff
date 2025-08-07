class SvgComparisonView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.image1 = None
        self.image2 = None
        self.pixmap1 = None
        self.pixmap2 = None

        self.opacity = 0.5
        self.scale_factor = 1.0
        self.show_diff = True  # 差分表示のフラグ

        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)

    def load_svgs(self, file1, file2):
        self.image1 = self.render_svg(file1)
        self.image2 = self.render_svg(file2)
        self.update_display()

    def render_svg(self, file_path):
        renderer = QSvgRenderer(file_path)
        size = renderer.defaultSize()
        image = QImage(size, QImage.Format_ARGB32)
        image.fill(Qt.transparent)

        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        return image

    def update_display(self):
        if not self.image1 or not self.image2:
            return

        self.scene.clear()

        # Pixmapを追加
        pix1 = QPixmap.fromImage(self.image1)
        pix2 = QPixmap.fromImage(self.image2)
        pixmap1_item = self.scene.addPixmap(pix1)
        pixmap2_item = self.scene.addPixmap(pix2)
        pixmap2_item.setOpacity(self.opacity)

        # 差分がONならばハイライト表示を追加
        if self.show_diff:
            diff = self.highlight_diff(self.image1, self.image2)
            diff_pix = QPixmap.fromImage(diff)
            self.scene.addPixmap(diff_pix)

    def highlight_diff(self, img1, img2):
        arr1 = np.array(img1.convertToFormat(QImage.Format_RGB32))
        arr2 = np.array(img2.convertToFormat(QImage.Format_RGB32))

        diff_mask = np.any(arr1 != arr2, axis=-1)
        highlight_img = QImage(img1.size(), QImage.Format_ARGB32)
        highlight_img.fill(Qt.transparent)

        for y in range(img1.height()):
            for x in range(img1.width()):
                if diff_mask[y, x]:
                    highlight_img.setPixelColor(x, y, QColor(255, 0, 0, 120))

        return highlight_img

    def set_opacity(self, value):
        self.opacity = value / 100
        self.update_display()

    def toggle_diff(self):
        self.show_diff = not self.show_diff  # 差分表示のトグル
        self.update_display()

    def wheelEvent(self, event: QWheelEvent):
        modifiers = QApplication.keyboardModifiers()
        if modifiers == Qt.ControlModifier:
            angle = event.angleDelta().y()
            factor = 1.1 if angle > 0 else 0.9
            self.scale(factor, factor)
        elif modifiers == Qt.ShiftModifier:
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - event.angleDelta().y())
        else:
            super().wheelEvent(event)
