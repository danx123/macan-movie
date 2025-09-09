import sys
import os
import cv2
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QSlider, QLabel, QFileDialog, QScrollArea, QGridLayout, QFrame
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import Qt, QUrl, QSettings, QTimer, QSize, QPoint
from PyQt6.QtGui import QPixmap, QImage, QIcon, QMouseEvent, QKeyEvent, QAction
from PyQt6.QtWidgets import QStyle

# -- Konstanta --
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv')
SETTINGS_ORGANIZATION = "Macam Movie"
SETTINGS_APPLICATION = "MoviePlayer"
SETTINGS_FOLDERS_KEY = "videoFolders"

# -- Fungsi Helper untuk Generate Thumbnail --
def generate_thumbnail(video_path: str, size: QSize = QSize(200, 120)) -> QPixmap:
    """
    Membuat thumbnail dari frame video menggunakan OpenCV.
    """
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return QPixmap() # Kembalikan pixmap kosong jika gagal

        # Ambil frame dari 10% durasi video untuk menghindari layar hitam di awal
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        pos = int(frame_count * 0.1)
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)

        ret, frame = cap.read()
        cap.release()

        if ret:
            # Konversi frame OpenCV (BGR) ke format QImage (RGB)
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qt_image)
            # Resize thumbnail dengan menjaga aspek rasio
            return pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    except Exception as e:
        print(f"Error generating thumbnail for {video_path}: {e}")

    return QPixmap() # Kembalikan pixmap kosong jika ada error

# -- Widget Kustom untuk Slider yang Bisa Diklik --
class ClickableSlider(QSlider):
    """
    Slider yang bisa diklik untuk loncat ke posisi tertentu.
    """
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            # Hitung nilai slider berdasarkan posisi klik mouse
            value = self.minimum() + (self.maximum() - self.minimum()) * event.pos().x() / self.width()
            self.setValue(int(value))
            # Trigger event sliderMoved agar player langsung seek
            self.sliderMoved.emit(int(value))
        super().mousePressEvent(event)

# -- Jendela Video Player --
class VideoPlayerWindow(QWidget):
    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bro Player")
        self.setGeometry(150, 150, 1280, 720)
        self.setStyleSheet("background-color: black;")
        self.setMouseTracking(True) # Aktifkan pelacakan mouse

        self.video_path = video_path
        self.is_playing = False
        
        # Timer untuk menyembunyikan kontrol dan kursor
        self.hide_timer = QTimer(self)
        self.hide_timer.setInterval(3000) # 3 detik
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide_controls_and_cursor)

        self._setup_ui()
        self._setup_player()
        self._connect_signals()
        
        self.load_video(video_path)
        self.toggle_play() # Langsung putar video saat dibuka
        self.hide_timer.start()

    def _setup_ui(self):
        # Layout utama
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Widget untuk menampilkan video
        self.video_widget = QVideoWidget()
        layout.addWidget(self.video_widget)

        # Panel Kontrol
        self.controls_widget = QWidget(self)
        self.controls_widget.setStyleSheet("""
            background-color: rgba(30, 30, 30, 180);
            color: white;
        """)
        controls_layout = QVBoxLayout(self.controls_widget)
        
        # Seek Bar
        seek_layout = QHBoxLayout()
        self.current_time_label = QLabel("00:00")
        self.seek_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.total_time_label = QLabel("00:00")
        seek_layout.addWidget(self.current_time_label)
        seek_layout.addWidget(self.seek_slider)
        seek_layout.addWidget(self.total_time_label)
        
        # Tombol-tombol kontrol
        buttons_layout = QHBoxLayout()
        self.play_pause_button = QPushButton() # Ikon diatur nanti
        self.play_pause_button.setFixedSize(32, 32)
        
        self.volume_button = QPushButton() # Ikon diatur nanti
        self.volume_button.setFixedSize(32, 32)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.setRange(0, 100)
        
        self.fullscreen_button = QPushButton() # Ikon diatur nanti
        self.fullscreen_button.setFixedSize(32, 32)

        buttons_layout.addStretch()
        buttons_layout.addWidget(self.play_pause_button)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.volume_button)
        buttons_layout.addWidget(self.volume_slider)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.fullscreen_button)
        buttons_layout.addStretch()
        
        controls_layout.addLayout(seek_layout)
        controls_layout.addLayout(buttons_layout)
        
        # Posisi panel kontrol di bawah
        layout.addWidget(self.controls_widget, alignment=Qt.AlignmentFlag.AlignBottom)

    def _setup_player(self):
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)
        
        self.audio_output.setVolume(0.8) # Volume default 80%
        self.volume_slider.setValue(80)

        # Mengatur Ikon untuk Tombol (menggunakan ikon bawaan Qt)
        self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        self.play_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        self.pause_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause)
        self.volume_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
        self.mute_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted)
        self.fullscreen_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp) # Mirip enter fullscreen
        
        self.play_pause_button.setIcon(self.pause_icon) # Mulai dengan ikon pause
        self.volume_button.setIcon(self.volume_icon)
        self.fullscreen_button.setIcon(self.fullscreen_icon)
    
    def _connect_signals(self):
        self.play_pause_button.clicked.connect(self.toggle_play)
        self.volume_button.clicked.connect(self.toggle_mute)
        self.volume_slider.valueChanged.connect(self.set_volume)
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)

        self.media_player.positionChanged.connect(self.update_position)
        self.media_player.durationChanged.connect(self.update_duration)
        self.seek_slider.sliderMoved.connect(self.set_position)

    def load_video(self, path):
        self.media_player.setSource(QUrl.fromLocalFile(path))

    def toggle_play(self):
        if self.is_playing:
            self.media_player.pause()
            self.play_pause_button.setIcon(self.play_icon)
        else:
            self.media_player.play()
            self.play_pause_button.setIcon(self.pause_icon)
        self.is_playing = not self.is_playing

    def toggle_mute(self):
        if self.audio_output.isMuted():
            self.audio_output.setMuted(False)
            self.volume_button.setIcon(self.volume_icon)
        else:
            self.audio_output.setMuted(True)
            self.volume_button.setIcon(self.mute_icon)

    def set_volume(self, value):
        self.audio_output.setVolume(value / 100)
        if value == 0:
            self.volume_button.setIcon(self.mute_icon)
        else:
            self.volume_button.setIcon(self.volume_icon)
    
    def update_position(self, position):
        self.seek_slider.setValue(position)
        self.current_time_label.setText(self.format_time(position))

    def update_duration(self, duration):
        self.seek_slider.setRange(0, duration)
        self.total_time_label.setText(self.format_time(duration))

    def set_position(self, position):
        self.media_player.setPosition(position)

    def format_time(self, ms):
        seconds = int((ms / 1000) % 60)
        minutes = int((ms / (1000 * 60)) % 60)
        hours = int((ms / (1000 * 60 * 60)) % 24)
        if hours > 0:
            return f"{hours:02}:{minutes:02}:{seconds:02}"
        return f"{minutes:02}:{seconds:02}"

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
            self.hide_timer.start()

    def hide_controls_and_cursor(self):
        if self.isFullScreen():
            self.controls_widget.hide()
            self.setCursor(Qt.CursorShape.BlankCursor)

    def show_controls_and_cursor(self):
        self.controls_widget.show()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.hide_timer.start() # Reset timer setiap mouse bergerak

    def mouseMoveEvent(self, event: QMouseEvent):
        self.show_controls_and_cursor()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key == Qt.Key.Key_F11:
            self.toggle_fullscreen()
        elif key == Qt.Key.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
        elif key == Qt.Key.Key_Space:
            self.toggle_play()
        else:
            super().keyPressEvent(event)
            
    def closeEvent(self, event):
        self.media_player.stop()
        super().closeEvent(event)


# -- Widget untuk Thumbnail Video --
class VideoThumbnailWidget(QWidget):
    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.setFixedSize(220, 180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setFrameShape(QFrame.Shape.Box)
        self.thumbnail_label.setFixedSize(200, 120)
        
        pixmap = generate_thumbnail(video_path)
        if pixmap.isNull():
            self.thumbnail_label.setText("Error\nThumbnail")
        else:
            self.thumbnail_label.setPixmap(pixmap)

        # Ambil nama file tanpa ekstensi
        file_name = os.path.splitext(os.path.basename(video_path))[0]
        self.title_label = QLabel(file_name)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.title_label.setWordWrap(True)

        layout.addWidget(self.thumbnail_label)
        layout.addWidget(self.title_label)
        
        self.player_window = None

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            print(f"Opening player for: {self.video_path}")
            # Buat instance player baru setiap kali diklik
            self.player_window = VideoPlayerWindow(self.video_path)
            self.player_window.show()


# -- Jendela Utama Aplikasi --
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Macan Movie - Video Collection")
        self.setGeometry(100, 100, 1000, 600)
        self.video_folders = []
        self.settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)

        self._setup_ui()
        self.load_folders()
        self.populate_videos()

    def _setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        layout = QVBoxLayout(main_widget)

        # Tombol Tambah Folder
        add_folder_button = QPushButton("Tambah Folder Video")
        add_folder_button.clicked.connect(self.add_folder)
        layout.addWidget(add_folder_button, alignment=Qt.AlignmentFlag.AlignLeft)

        # Area Scroll untuk menampung grid video
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(10)
        
        self.scroll_area.setWidget(self.grid_container)
        layout.addWidget(self.scroll_area)

    def add_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Pilih Folder Video")
        if folder_path and folder_path not in self.video_folders:
            self.video_folders.append(folder_path)
            self.save_folders()
            self.populate_videos()

    def save_folders(self):
        self.settings.setValue(SETTINGS_FOLDERS_KEY, self.video_folders)

    def load_folders(self):
        folders = self.settings.value(SETTINGS_FOLDERS_KEY, defaultValue=[], type=list)
        self.video_folders = folders

    def clear_grid(self):
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def populate_videos(self):
        self.clear_grid()
        
        video_files = []
        for folder in self.video_folders:
            try:
                for file in os.listdir(folder):
                    if file.lower().endswith(VIDEO_EXTENSIONS):
                        video_files.append(os.path.join(folder, file))
            except FileNotFoundError:
                print(f"Warning: Folder not found: {folder}")
                continue
        
        if not video_files:
            no_video_label = QLabel("Tidak ada video ditemukan.\nSilakan 'Tambah Folder Video' untuk memulai.")
            no_video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid_layout.addWidget(no_video_label, 0, 0)
            return

        # Menghitung jumlah kolom berdasarkan lebar jendela
        cols = max(1, self.width() // 240) 
        row, col = 0, 0
        
        for video_path in sorted(video_files):
            thumbnail = VideoThumbnailWidget(video_path)
            self.grid_layout.addWidget(thumbnail, row, col)
            col += 1
            if col >= cols:
                col = 0
                row += 1


# -- Eksekusi Aplikasi --
if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Mengatur style agar mirip Windows
    app.setStyle("Fusion")
    
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())