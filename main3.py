class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SVG比較ツール")
        self.viewer = SvgComparisonView()

        load_button = QPushButton("SVGを読み込む")
        load_button.clicked.connect(self.load_svgs)

        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(0)
        slider.setMaximum(100)
        slider.setValue(50)
        slider.valueChanged.connect(self.viewer.set_opacity)

        toggle_diff_button = QPushButton("差分表示 ON/OFF")
        toggle_diff_button.clicked.connect(self.viewer.toggle_diff)

        layout = QVBoxLayout()
        layout.addWidget(load_button)
        layout.addWidget(slider)
        layout.addWidget(toggle_diff_button)
        layout.addWidget(self.viewer)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def load_svgs(self):
        file1, _ = QFileDialog.getOpenFileName(self, "画像1を選択", "", "SVG Files (*.svg)")
        file2, _ = QFileDialog.getOpenFileName(self, "画像2を選択", "", "SVG Files (*.svg)")
        if file1 and file2:
            self.viewer.load_svgs(file1, file2)
