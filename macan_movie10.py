import sys
import os
import cv2
import time
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QSlider, QLabel, QFileDialog, QScrollArea, QGridLayout, QFrame, QMessageBox,
    QDialog, QListWidget, QDialogButtonBox, QMenu, QSizePolicy
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import Qt, QUrl, QSettings, QTimer, QSize, QPoint, QFileInfo, QPointF, QRect
from PyQt6.QtGui import QPixmap, QImage, QIcon, QMouseEvent, QKeyEvent, QAction, QPainter, QPalette, QColor, QFontDatabase, QScreen
from PyQt6.QtSvg import QSvgRenderer

# -- Konstanta --
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv')
SETTINGS_ORGANIZATION = "MacanMovieProfessional"
SETTINGS_APPLICATION = "MoviePlayer"
SETTINGS_FOLDERS_KEY = "videoFolders"
SETTINGS_GEOMETRY_KEY = "mainWindowGeometry"
SETTINGS_WINDOW_STATE_KEY = "mainWindowState"

# -- Manajer Ikon SVG --
class IconManager:
    """Kelas untuk mengelola dan membuat ikon dari data SVG."""
    SVG_DATA = {
        "play": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>""",
        "pause": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>""",
        "stop": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18"></rect></svg>""",
        "volume_high": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"></path></svg>""",
        "volume_muted": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><line x1="23" y1="9" x2="17" y2="15"></line><line x1="17" y1="9" x2="23" y2="15"></line></svg>""",
        "fullscreen_enter": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path></svg>""",
        "fullscreen_exit": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"></path></svg>""",
        "folder_add": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path><line x1="12" y1="11" x2="12" y2="17"></line><line x1="9" y1="14" x2="15" y2="14"></line></svg>""",
        "folder_manage": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="1"></circle><circle cx="17" cy="13" r="1"></circle><circle cx="7" cy="13" r="1"></circle></svg>""",
        "minimize": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line></svg>""",
        "maximize": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path></svg>""",
        "restore": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 3 21 3 21 9"></polyline><polyline points="9 21 3 21 3 15"></polyline><line x1="21" y1="3" x2="14" y2="10"></line><line x1="3" y1="21" x2="10" y2="14"></line></svg>""",
        "close": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>""",
        "next": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 4 15 12 5 20 5 4"></polygon><line x1="19" y1="5" x2="19" y2="19"></line></svg>""",
        "previous": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="19 20 9 12 19 4 19 20"></polygon><line x1="5" y1="19" x2="5" y2="5"></line></svg>""",
    }

    @staticmethod
    def get_icon(name: str, color: str = "#ecf0f1", size: QSize = QSize(24, 24)) -> QIcon:
        """Membuat QIcon dari data SVG dari data SVG."""
        xml_data = IconManager.SVG_DATA.get(name)
        if not xml_data: return QIcon()
        
        xml_data = xml_data.replace('stroke="currentColor"', f'stroke="{color}"')
        
        renderer = QSvgRenderer(xml_data.encode('utf-8'))
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        
        return QIcon(pixmap)

# -- Fungsi Helper untuk Thumbnail --
def generate_thumbnail(video_path: str, size: QSize = QSize(220, 124)) -> QPixmap:
    """Membuat thumbnail dari frame video menggunakan OpenCV."""
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened(): return QPixmap()

        # Ambil frame dari 10% durasi video
        pos = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) * 0.1) 
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        cap.release()

        if ret:
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            q_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(q_image)
            return pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    except Exception as e:
        print(f"Error generating thumbnail for {video_path}: {e}")
    return QPixmap()

# -- Widget Kustom --
class ClickableSlider(QSlider):
    """Slider yang bisa diklik untuk loncat ke posisi tertentu."""
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.orientation() == Qt.Orientation.Horizontal:
                val = self.minimum() + (self.maximum() - self.minimum()) * event.pos().x() / self.width()
            else:
                val = self.minimum() + (self.maximum() - self.minimum()) * (self.height() - event.pos().y()) / self.height()
            self.setValue(int(val))
            self.sliderMoved.emit(int(val))
        super().mousePressEvent(event)
        
# -- JENDELA VIDEO PLAYER (IMPLEMENTASI ULANG) --
class VideoPlayerWindow(QMainWindow):
    def __init__(self, playlist: list, current_index: int, parent=None):
        super().__init__(parent)
        self.playlist = playlist
        self.current_index = current_index
        self.is_playing = False
        self.is_muted = False
        self.last_volume = 80
        self.init_window_size = QSize(1280, 720) # Ukuran awal jendela

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # FIX: Posisikan jendela di tengah layar
        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        x = (screen_geometry.width() - self.init_window_size.width()) // 2
        y = (screen_geometry.height() - self.init_window_size.height()) // 2
        self.setGeometry(x, y, self.init_window_size.width(), self.init_window_size.height())
        
        self.setMouseTracking(True)
        
        self.hide_timer = QTimer(self)
        self.hide_timer.setInterval(3000)
        self.hide_timer.timeout.connect(self.hide_controls)

        self._setup_ui()
        self._setup_player()
        self._connect_signals()
        
        self.load_video(self.playlist[self.current_index])
        self.toggle_play()

    def _setup_ui(self):
        self.container = QFrame(self)
        self.container.setObjectName("container")
        self.container.setStyleSheet("""
            #container {
                background-color: black;
                border-radius: 15px;
            }
        """)
        self.setCentralWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background-color: black;") # Tambahkan ini untuk memastikan latar belakang hitam
        self.video_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self.video_widget)

        # -- Controls Widget Overlay --
        # FIX: Pastikan controls_overlay adalah child dari centralWidget atau container
        # dan posisikan di atas video_widget dengan layout absolut.
        self.controls_overlay = QWidget(self.container) # Pastikan ini child dari self.container
        self.controls_overlay.setMouseTracking(True)
        # Jangan pakai QVBoxLayout untuk overlay karena ini akan menumpuk di atas video
        # Kita akan atur geometrinya secara manual di resizeEvent
        
        self.controls_widget = QWidget(self.controls_overlay) # controls_widget adalah child dari controls_overlay
        self.controls_widget.setStyleSheet("background-color: rgba(20, 20, 20, 0.8); border-radius: 10px;")
        controls_layout = QVBoxLayout(self.controls_widget)
        controls_layout.setContentsMargins(20, 10, 20, 15)

        seek_layout = QHBoxLayout()
        self.current_time_label = QLabel("00:00")
        self.current_time_label.setStyleSheet("color: white;") # Pastikan teksnya terlihat
        self.seek_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.total_time_label = QLabel("00:00")
        self.total_time_label.setStyleSheet("color: white;") # Pastikan teksnya terlihat
        seek_layout.addWidget(self.current_time_label)
        seek_layout.addWidget(self.seek_slider)
        seek_layout.addWidget(self.total_time_label)

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)
        self.prev_button = QPushButton()
        self.play_pause_button = QPushButton()
        self.next_button = QPushButton()
        self.stop_button = QPushButton()
        
        # Volume container
        self.volume_container = QWidget()
        volume_layout = QHBoxLayout(self.volume_container)
        volume_layout.setContentsMargins(0,0,0,0)
        self.volume_button = QPushButton()
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.hide()
        self.volume_container.enterEvent = lambda e: self.volume_slider.show()
        self.volume_container.leaveEvent = lambda e: self.volume_slider.hide()
        volume_layout.addWidget(self.volume_button)
        volume_layout.addWidget(self.volume_slider)

        self.fullscreen_button = QPushButton()
        self.close_button = QPushButton()

        for btn in [self.prev_button, self.play_pause_button, self.next_button, self.stop_button, self.volume_button, self.fullscreen_button, self.close_button]:
            btn.setFlat(True)
            btn.setIconSize(QSize(26, 26))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("QPushButton { border: none; background: transparent; } QPushButton:hover { background-color: rgba(255, 255, 255, 0.2); border-radius: 5px; }")


        buttons_layout.addStretch()
        buttons_layout.addWidget(self.prev_button)
        buttons_layout.addWidget(self.play_pause_button)
        buttons_layout.addWidget(self.next_button)
        buttons_layout.addWidget(self.stop_button)
        buttons_layout.addSpacing(20)
        buttons_layout.addWidget(self.volume_container)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.fullscreen_button)
        buttons_layout.addWidget(self.close_button)

        controls_layout.addLayout(seek_layout)
        controls_layout.addLayout(buttons_layout)
        
        # controls_widget diletakkan di dalam controls_overlay
        # controls_overlay tidak pakai QVBoxLayout, melainkan diatur geometrinya
        # Di sini kita hanya menambahkan controls_widget ke controls_overlay tanpa layouting QVBoxLayout
        # Kita akan atur posisi controls_widget di controls_overlay saat resizeEvent
        
        # Initially hide controls_overlay
        self.controls_overlay.hide()

    def _setup_player(self):
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)
        
        # FIX 1: Pindahkan blok definisi ikon ke atas agar tersedia saat set_volume() dipanggil.
        # Icons
        self.play_icon = IconManager.get_icon("play")
        self.pause_icon = IconManager.get_icon("pause")
        self.stop_icon = IconManager.get_icon("stop")
        self.volume_icon = IconManager.get_icon("volume_high")
        self.mute_icon = IconManager.get_icon("volume_muted")
        self.fullscreen_enter_icon = IconManager.get_icon("fullscreen_enter")
        self.fullscreen_exit_icon = IconManager.get_icon("restore")
        self.next_icon = IconManager.get_icon("next")
        self.prev_icon = IconManager.get_icon("previous")
        self.close_icon = IconManager.get_icon("close")
        
        # Sekarang aman untuk memanggil set_volume karena ikon sudah ada.
        self.set_volume(self.last_volume)
        self.volume_slider.setValue(self.last_volume)

        # Set ikon ke tombol
        self.play_pause_button.setIcon(self.pause_icon)
        self.stop_button.setIcon(self.stop_icon)
        self.volume_button.setIcon(self.volume_icon)
        self.fullscreen_button.setIcon(self.fullscreen_enter_icon)
        self.next_button.setIcon(self.next_icon)
        self.prev_button.setIcon(self.prev_icon)
        self.close_button.setIcon(self.close_icon)
    
    def _connect_signals(self):
        self.play_pause_button.clicked.connect(self.toggle_play)
        self.stop_button.clicked.connect(self.stop_video)
        self.next_button.clicked.connect(self.next_video)
        self.prev_button.clicked.connect(self.prev_video)
        self.volume_button.clicked.connect(self.toggle_mute)
        self.volume_slider.valueChanged.connect(self.set_volume)
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        self.close_button.clicked.connect(self.close)

        self.media_player.positionChanged.connect(self.update_position)
        self.media_player.durationChanged.connect(self.update_duration)
        self.media_player.mediaStatusChanged.connect(self.handle_media_status)
        self.seek_slider.sliderMoved.connect(self.set_position)
        
        # Sinyal error untuk debugging
        self.media_player.errorOccurred.connect(self.handle_player_error)

    def handle_player_error(self, error, error_string):
        print(f"Media Player Error: {error} - {error_string}")
        QMessageBox.critical(self, "Player Error", f"Terjadi kesalahan pada pemutar media:\n{error_string}")


    def load_video(self, path):
        if not os.path.exists(path):
            QMessageBox.critical(self, "File Not Found", f"Video file not found: {path}")
            return
        self.media_player.setSource(QUrl.fromLocalFile(path))
        self.setWindowTitle(f"Macan Player - {os.path.basename(path)}")
        self.is_playing = False # Reset state for new video
        
    def next_video(self):
        if not self.playlist: return
        self.current_index = (self.current_index + 1) % len(self.playlist)
        self.load_video(self.playlist[self.current_index])
        self.media_player.play()
        self.play_pause_button.setIcon(self.pause_icon)
        self.is_playing = True

    def prev_video(self):
        if not self.playlist: return
        self.current_index = (self.current_index - 1 + len(self.playlist)) % len(self.playlist)
        self.load_video(self.playlist[self.current_index])
        self.media_player.play()
        self.play_pause_button.setIcon(self.pause_icon)
        self.is_playing = True

    def toggle_play(self):
        if self.media_player.mediaStatus() == QMediaPlayer.MediaStatus.NoMedia:
            print("No media loaded, cannot play.")
            return

        if self.is_playing:
            self.media_player.pause()
            self.play_pause_button.setIcon(self.play_icon)
        else:
            self.media_player.play()
            self.play_pause_button.setIcon(self.pause_icon)
        self.is_playing = not self.is_playing
        self.show_controls()
        
    def stop_video(self):
        self.media_player.stop()
        self.close()

    def toggle_mute(self):
        if not self.is_muted:
            self.last_volume = self.volume_slider.value()
            self.volume_slider.setValue(0)
            self.volume_button.setIcon(self.mute_icon)
        else:
            # Jika sebelumnya volume 0, kembalikan ke last_volume (default 80 jika belum pernah diubah)
            if self.last_volume == 0:
                 self.last_volume = 80 # default value if it was 0 when muted
            self.volume_slider.setValue(self.last_volume)
            self.volume_button.setIcon(self.volume_icon)
        self.is_muted = not self.is_muted

    def set_volume(self, value):
        self.audio_output.setVolume(value / 100)
        self.is_muted = value == 0
        if self.is_muted:
            self.volume_button.setIcon(self.mute_icon)
        else:
            self.volume_button.setIcon(self.volume_icon)
            self.last_volume = value # Simpan volume terakhir yang tidak 0

    def update_position(self, position):
        self.seek_slider.setValue(position)
        self.current_time_label.setText(self.format_time(position))

    def update_duration(self, duration):
        self.seek_slider.setRange(0, duration)
        self.total_time_label.setText(self.format_time(duration))

    def set_position(self, position):
        self.media_player.setPosition(position)

    def handle_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.next_video()
        elif status == QMediaPlayer.MediaStatus.LoadedMedia:
            # Video siap diputar, atur play/pause icon dengan benar
            self.play_pause_button.setIcon(self.pause_icon if self.is_playing else self.play_icon)

    def format_time(self, ms):
        s = round(ms / 1000)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return (f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}")

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.fullscreen_button.setIcon(self.fullscreen_enter_icon)
        else:
            self.showFullScreen()
            self.fullscreen_button.setIcon(self.fullscreen_exit_icon)

    def hide_controls(self):
        if self.is_playing and self.controls_overlay.isVisible():
            self.controls_overlay.hide()
            self.setCursor(Qt.CursorShape.BlankCursor)

    def show_controls(self):
        if not self.controls_overlay.isVisible():
            self.controls_overlay.show()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.hide_timer.start()

    def resizeEvent(self, event):
        # FIX: Atur geometri controls_overlay dan controls_widget secara manual
        # Agar controls_overlay menutupi seluruh jendela, dan controls_widget berada di bawah.
        self.controls_overlay.setGeometry(self.rect())
        
        # Posisikan controls_widget di bagian bawah controls_overlay
        controls_height = self.controls_widget.sizeHint().height()
        self.controls_widget.setGeometry(
            0, self.controls_overlay.height() - controls_height,
            self.controls_overlay.width(), controls_height
        )
        super().resizeEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        self.show_controls()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key in (Qt.Key.Key_F, Qt.Key.Key_F11): self.toggle_fullscreen()
        elif key == Qt.Key.Key_Escape and self.isFullScreen(): self.toggle_fullscreen()
        elif key == Qt.Key.Key_Space: self.toggle_play()
        elif key == Qt.Key.Key_Right: self.media_player.setPosition(self.media_player.position() + 5000)
        elif key == Qt.Key.Key_Left: self.media_player.setPosition(self.media_player.position() - 5000)
        elif key == Qt.Key.Key_Up: self.volume_slider.setValue(self.volume_slider.value() + 5)
        elif key == Qt.Key.Key_Down: self.volume_slider.setValue(self.volume_slider.value() - 5)
        elif key == Qt.Key.Key_M: self.toggle_mute()
        else: super().keyPressEvent(event)

    def closeEvent(self, event):
        self.media_player.stop()
        super().closeEvent(event)


# -- Widget untuk Thumbnail Video --
class VideoThumbnailWidget(QFrame):
    def __init__(self, video_path: str, all_videos: list, main_window, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.all_videos = all_videos
        self.main_window = main_window
        
        self.setFixedSize(220, 180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("thumbnailCard")
        self.setStyleSheet("""
            #thumbnailCard {
                background-color: #2c3e50;
                border: 1px solid #34495e;
                border-radius: 8px;
            }
            #thumbnailCard:hover {
                background-color: #34495e;
                border: 1px solid #3498db;
            }
            QLabel { # Agar title_label memiliki warna yang benar
                color: #ecf0f1; 
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet("border: none; border-radius: 5px; background-color: #232d38;")
        self.thumbnail_label.setFixedSize(210, 118)
        
        pixmap = generate_thumbnail(video_path)
        if pixmap.isNull():
            self.thumbnail_label.setText("Gagal Memuat\nThumbnail")
        else:
            self.thumbnail_label.setPixmap(pixmap)

        file_name = os.path.splitext(os.path.basename(video_path))[0]
        self.title_label = QLabel(file_name)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("border: none;") # Hapus color di sini, biarkan global style
        layout.addWidget(self.thumbnail_label)
        layout.addWidget(self.title_label)
        
        self.player_window = None

    def open_player(self):
        # FIX: Pastikan daftar video tidak kosong
        if not self.all_videos:
            QMessageBox.warning(self, "Tidak Ada Video", "Tidak ada video yang dimuat untuk diputar.")
            return

        current_index = self.all_videos.index(self.video_path)
        self.player_window = VideoPlayerWindow(self.all_videos, current_index)
        self.player_window.show()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_player()
        super().mouseDoubleClickEvent(event)
    
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        open_action = QAction("Buka Video", self, triggered=self.open_player)
        info_action = QAction("Info File", self, triggered=self.show_file_info)
        remove_action = QAction("Hapus dari Tampilan", self, triggered=self.deleteLater)
        delete_action = QAction("Hapus File Permanen", self, triggered=self.delete_file)

        menu.addActions([open_action, info_action])
        menu.addSeparator()
        menu.addActions([remove_action, delete_action])
        menu.exec(event.globalPos())

    def show_file_info(self):
        try:
            file_info = QFileInfo(self.video_path)
            size_mb = file_info.size() / (1024 * 1024)
            info = (f"<b>Nama File:</b> {file_info.fileName()}<br>"
                    f"<b>Lokasi:</b> {file_info.absolutePath()}<br>"
                    f"<b>Ukuran:</b> {size_mb:.2f} MB<br>"
                    f"<b>Dibuat:</b> {file_info.birthTime().toString(Qt.DateFormat.ISODate)}<br>"
                    f"<b>Diubah:</b> {file_info.lastModified().toString(Qt.DateFormat.ISODate)}")
            QMessageBox.information(self, "Informasi File", info)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Tidak dapat mengambil info file: {e}")

    def delete_file(self):
        confirm = QMessageBox.warning(
            self, "Konfirmasi Hapus Permanen",
            f"Anda yakin ingin menghapus file ini secara permanen dari disk?\n\n<b>{self.video_path}</b>\n\nTindakan ini tidak bisa dibatalkan.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel
        )
        if confirm == QMessageBox.StandardButton.Yes:
            try:
                os.remove(self.video_path)
                QMessageBox.information(self, "Sukses", "File berhasil dihapus.")
                self.main_window.populate_videos()
            except OSError as e:
                QMessageBox.critical(self, "Error", f"Gagal menghapus file: {e}")

# -- Dialog Manajemen Folder --
class ManageFoldersDialog(QDialog):
    def __init__(self, folders, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Kelola Folder Video")
        self.setMinimumSize(450, 300)
        self.folders = folders
        
        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        
        # FIX 2: Tambahkan stylesheet untuk QListWidget agar teksnya terlihat di background gelap.
        self.list_widget.setStyleSheet("""
            QListWidget {
                color: #ecf0f1;
                background-color: #1e272e;
                border: 1px solid #4a6375;
                border-radius: 5px;
                padding: 5px;
            }
            QListWidget::item:hover {
                background-color: #34495e;
            }
            QListWidget::item:selected {
                background-color: #3498db;
                color: white;
            }
        """)
        
        self.list_widget.addItems(self.folders)
        layout.addWidget(self.list_widget)
        
        remove_button = QPushButton("Hapus Folder Terpilih")
        remove_button.clicked.connect(self.remove_selected_folder)
        layout.addWidget(remove_button)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
    def remove_selected_folder(self):
        selected_items = self.list_widget.selectedItems()
        if not selected_items: return
        folder_to_remove = selected_items[0].text()
        self.folders.remove(folder_to_remove)
        self.list_widget.takeItem(self.list_widget.row(selected_items[0]))
        # Panggil method di main_window untuk update folders dan populate ulang
        if self.parent() and hasattr(self.parent(), 'folders_updated'):
            self.parent().folders_updated(self.folders)

# -- FRAMELESS MAIN WINDOW --
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.drag_pos = QPoint()
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Macan Movie - Koleksi Video")
        self.setGeometry(100, 100, 1200, 700)
        
        self.settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
        self.video_folders = []
        self.video_files = [] # Cache video files

        self.setup_styles()
        self._setup_ui()
        self.load_settings()
        self.populate_videos()

    def setup_styles(self):
        self.setStyleSheet("""
            #mainContainer {
                background-color: #1e272e;
                border: 1px solid #4a6375;
                border-radius: 15px;
            }
            QScrollArea { border: none; }
            QLabel { color: #ecf0f1; }
            #titleLabel { font-size: 16px; font-weight: bold; }
        """)

    def _setup_ui(self):
        # Main container for rounded corners
        self.container = QWidget(self)
        self.container.setObjectName("mainContainer")
        self.setCentralWidget(self.container)
        
        main_layout = QVBoxLayout(self.container)
        main_layout.setContentsMargins(1, 1, 1, 1) # Small margin for border
        main_layout.setSpacing(0)

        # -- Custom Title Bar --
        self.title_bar = QFrame()
        self.title_bar.setFixedHeight(40)
        self.title_bar.setStyleSheet("background-color: #2c3e50; border-top-left-radius: 14px; border-top-right-radius: 14px;")
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(15, 0, 5, 0)
        
        title_label = QLabel("Macan Movie")
        title_label.setObjectName("titleLabel")

        self.minimize_button = self._create_title_button("minimize", self.showMinimized)
        self.maximize_button = self._create_title_button("maximize", self.toggle_maximize)
        self.close_button = self._create_title_button("close", self.close)
        self.close_button.setStyleSheet("QPushButton:hover { background-color: #e74c3c; }")

        title_layout.addWidget(title_label)
        title_layout.addStretch()
        title_layout.addWidget(self.minimize_button)
        title_layout.addWidget(self.maximize_button)
        title_layout.addWidget(self.close_button)

        # -- Content Area --
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(15, 10, 15, 15)

        button_layout = QHBoxLayout()
        add_folder_button = QPushButton("Tambah Folder")
        add_folder_button.setIcon(IconManager.get_icon("folder_add"))
        add_folder_button.clicked.connect(self.add_folder)
        
        manage_folder_button = QPushButton("Kelola Folder")
        manage_folder_button.setIcon(IconManager.get_icon("folder_manage"))
        manage_folder_button.clicked.connect(self.manage_folders)
        
        button_layout.addWidget(add_folder_button)
        button_layout.addWidget(manage_folder_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(15)
        
        self.scroll_area.setWidget(self.grid_container)
        layout.addWidget(self.scroll_area)
        
        main_layout.addWidget(self.title_bar)
        main_layout.addWidget(content_widget)

    def _create_title_button(self, icon_name, slot):
        button = QPushButton()
        button.setIcon(IconManager.get_icon(icon_name))
        button.setFixedSize(30, 30)
        button.setFlat(True)
        button.clicked.connect(slot)
        return button

    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
            self.maximize_button.setIcon(IconManager.get_icon("maximize"))
        else:
            self.showMaximized()
            self.maximize_button.setIcon(IconManager.get_icon("restore"))
    
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < self.title_bar.height():
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            
    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton and not self.drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_pos = QPoint()

    def add_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Pilih Folder Video")
        if folder_path and folder_path not in self.video_folders:
            self.video_folders.append(folder_path)
            self.save_folders()
            self.populate_videos()
            
    def manage_folders(self):
        dialog = ManageFoldersDialog(self.video_folders.copy(), self)
        dialog.exec()

    def folders_updated(self, new_folders):
        self.video_folders = new_folders
        self.save_folders()
        self.populate_videos()
        
    def save_folders(self):
        self.settings.setValue(SETTINGS_FOLDERS_KEY, self.video_folders)

    def load_settings(self):
        self.video_folders = self.settings.value(SETTINGS_FOLDERS_KEY, defaultValue=[], type=list)
        geometry = self.settings.value(SETTINGS_GEOMETRY_KEY, defaultValue=None)
        if geometry: self.restoreGeometry(geometry)
        if self.settings.value(SETTINGS_WINDOW_STATE_KEY, defaultValue=False, type=bool):
            self.showMaximized()
            self.maximize_button.setIcon(IconManager.get_icon("restore"))

    def clear_grid(self):
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()

    def populate_videos(self):
        self.clear_grid()
        self.video_files.clear()
        
        if not self.video_folders:
            self.show_message("Tidak ada folder video.\nKlik 'Tambah Folder' untuk memulai.")
            return

        for folder in self.video_folders:
            try:
                if os.path.exists(folder) and os.path.isdir(folder): # Tambahkan cek keberadaan folder
                    for root, _, files in os.walk(folder):
                        for file in files:
                            if file.lower().endswith(VIDEO_EXTENSIONS):
                                self.video_files.append(os.path.join(root, file))
                else:
                    print(f"Peringatan: Folder tidak ditemukan atau tidak valid: {folder}")
            except Exception as e:
                print(f"Error reading folder {folder}: {e}")
        
        if not self.video_files:
            self.show_message("Tidak ada file video yang ditemukan.")
            return

        self.reflow_grid(sorted(self.video_files))

    def show_message(self, message):
        self.clear_grid()
        msg_label = QLabel(message)
        msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_label.setStyleSheet("font-size: 18px; color: #7f8c8d;")
        # Hapus widget lama sebelum menambahkan yang baru jika ada
        if self.grid_layout.itemAtPosition(0,0):
            self.grid_layout.itemAtPosition(0,0).widget().deleteLater()
        self.grid_layout.addWidget(msg_label, 0, 0, 1, -1, alignment=Qt.AlignmentFlag.AlignCenter)
        
    def reflow_grid(self, video_files_list):
        self.clear_grid()
        # Perbaiki perhitungan kolom: pastikan minimal 1 kolom
        cols = max(1, (self.scroll_area.width() - self.grid_layout.contentsMargins().left() - self.grid_layout.contentsMargins().right() ) // 240) 
        
        for i, video_path in enumerate(video_files_list):
            row, col = divmod(i, cols)
            thumbnail = VideoThumbnailWidget(video_path, self.video_files, self)
            self.grid_layout.addWidget(thumbnail, row, col)
                
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Panggil reflow_grid dengan QTimer.singleShot untuk menghindari loop tak terbatas
        # dan memastikan event resize selesai sebelum layout ulang
        QTimer.singleShot(50, lambda: self.reflow_grid(self.video_files))
        
    def closeEvent(self, event):
        self.settings.setValue(SETTINGS_GEOMETRY_KEY, self.saveGeometry())
        self.settings.setValue(SETTINGS_WINDOW_STATE_KEY, self.isMaximized())
        super().closeEvent(event)

# -- Eksekusi Aplikasi --
if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Global Stylesheet
    app.setStyleSheet("""
        QWidget {
            font-family: 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', sans-serif;
            color: #ecf0f1;
            font-size: 11pt;
        }
        QPushButton { 
            background-color: #3498db; 
            color: white; 
            border: none; 
            padding: 8px 15px; 
            border-radius: 5px;
        }
        QPushButton:hover { background-color: #2980b9; }
        QPushButton:pressed { background-color: #1f618d; }
        
        QSlider::groove:horizontal {
            height: 4px;
            background: #4a6375;
            border-radius: 2px;
        }
        QSlider::handle:horizontal {
            background: #3498db;
            border: 5px solid #3498db;
            width: 8px;
            margin: -7px 0;
            border-radius: 7px;
        }
        QSlider::sub-page:horizontal {
            background: #3498db;
            border-radius: 2px;
        }
        
        QMenu {
            background-color: #2c3e50;
            border: 1px solid #4a6375;
            padding: 5px;
        }
        QMenu::item {
            padding: 5px 20px;
        }
        QMenu::item:selected {
            background-color: #3498db;
        }
        QMenu::separator {
            height: 1px;
            background: #4a6375;
            margin: 5px 0;
        }
        QMessageBox, QDialog {
            background-color: #2c3e50;
        }
    """)

    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())