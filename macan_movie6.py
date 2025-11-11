import sys
import os
import cv2
import time
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QSlider, QLabel, QFileDialog, QScrollArea, QGridLayout, QFrame, QMessageBox,
    QDialog, QListWidget, QListWidgetItem, QDialogButtonBox, QMenu
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import Qt, QUrl, QSettings, QTimer, QSize, QPoint, QFileInfo
from PyQt6.QtGui import QPixmap, QImage, QIcon, QMouseEvent, QKeyEvent, QAction, QPainter, QPalette, QColor
from PyQt6.QtSvg import QSvgRenderer


# -- Konstanta --
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv')
SETTINGS_ORGANIZATION = "MacanMovieEnhanced"
SETTINGS_APPLICATION = "MoviePlayer"
SETTINGS_FOLDERS_KEY = "videoFolders"
SETTINGS_GEOMETRY_KEY = "mainWindowGeometry"

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
        # FIX START: Menambahkan ikon minimize dan close
        "minimize": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line></svg>""",
        "close": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>""",
        # FIX END
    }

    @staticmethod
    def get_icon(name: str, color: str = "white") -> QIcon:
        """Membuat QIcon dari data SVG dengan warna yang ditentukan."""
        xml_data = IconManager.SVG_DATA.get(name)
        if not xml_data:
            return QIcon()
        
        xml_data = xml_data.replace('stroke="currentColor"', f'stroke="{color}"')
        
        renderer = QSvgRenderer(xml_data.encode('utf-8'))
        pixmap = QPixmap(32, 32)
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

        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        pos = int(frame_count * 0.1) 
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        cap.release()

        if ret:
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qt_image)
            return pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    except Exception as e:
        print(f"Error generating thumbnail for {video_path}: {e}")
    return QPixmap()

# -- Widget Kustom --
class ClickableSlider(QSlider):
    """Slider yang bisa diklik untuk loncat ke posisi tertentu."""
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.width() > 0:
                value = self.minimum() + (self.maximum() - self.minimum()) * event.pos().x() / self.width()
                self.setValue(int(value))
                self.sliderMoved.emit(int(value))
        super().mousePressEvent(event)

# -- Jendela Video Player --
class VideoPlayerWindow(QMainWindow):
    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(os.path.basename(video_path))
        self.setGeometry(150, 150, 1280, 720)
        self.setMouseTracking(True)
        self.setStyleSheet("background-color: black;")

        self.video_path = video_path
        self.is_playing = False
        
        self.hide_timer = QTimer(self)
        self.hide_timer.setInterval(3000)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide_controls)
        
        self._setup_ui()
        self._setup_player()
        self._connect_signals()
        
        self.load_video(video_path)
        self.toggle_play()
        self.show_controls()

    def _setup_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.video_widget = QVideoWidget()
        layout.addWidget(self.video_widget)

        self.controls_widget = QWidget(self)
        self.controls_widget.setParent(self)
        self.controls_widget.setStyleSheet("""
            background-color: rgba(20, 20, 20, 0.85);
            color: white;
            border-radius: 10px;
        """)
        
        # Widget akan ditampilkan/disembunyikan secara langsung untuk stabilitas
        
        controls_layout = QVBoxLayout(self.controls_widget)
        controls_layout.setContentsMargins(15, 10, 15, 10)
        
        seek_layout = QHBoxLayout()
        self.current_time_label = QLabel("00:00")
        self.seek_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.total_time_label = QLabel("00:00")
        seek_layout.addWidget(self.current_time_label)
        seek_layout.addWidget(self.seek_slider)
        seek_layout.addWidget(self.total_time_label)
        
        buttons_layout = QHBoxLayout()
        self.play_pause_button = QPushButton()
        self.stop_button = QPushButton()

        volume_container = QWidget()
        volume_layout = QHBoxLayout(volume_container)
        volume_layout.setContentsMargins(0,0,0,0)
        self.volume_button = QPushButton()
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.hide()
        volume_container.enterEvent = lambda e: self.volume_slider.show()
        volume_container.leaveEvent = lambda e: self.volume_slider.hide()
        volume_layout.addWidget(self.volume_button)
        volume_layout.addWidget(self.volume_slider)

        self.fullscreen_button = QPushButton()
        
        # FIX START: Menambahkan tombol minimize dan close
        self.minimize_button = QPushButton()
        self.close_button = QPushButton()
        # FIX END

        for btn in [self.play_pause_button, self.stop_button, self.volume_button, self.fullscreen_button, self.minimize_button, self.close_button]:
            btn.setFlat(True)
            btn.setIconSize(QSize(28, 28))

        buttons_layout.addStretch()
        buttons_layout.addWidget(self.stop_button)
        buttons_layout.addWidget(self.play_pause_button)
        buttons_layout.addStretch()
        buttons_layout.addWidget(volume_container)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.fullscreen_button)
        # FIX START: Menambahkan widget tombol ke layout
        buttons_layout.addWidget(self.minimize_button)
        buttons_layout.addWidget(self.close_button)
        # FIX END
        
        controls_layout.addLayout(seek_layout)
        controls_layout.addLayout(buttons_layout)
        
    def _setup_player(self):
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)
        
        self.audio_output.setVolume(0.8)
        self.volume_slider.setValue(80)

        self.play_icon = IconManager.get_icon("play")
        self.pause_icon = IconManager.get_icon("pause")
        self.stop_icon = IconManager.get_icon("stop")
        self.volume_icon = IconManager.get_icon("volume_high")
        self.mute_icon = IconManager.get_icon("volume_muted")
        self.fullscreen_enter_icon = IconManager.get_icon("fullscreen_enter")
        self.fullscreen_exit_icon = IconManager.get_icon("fullscreen_exit")
        # FIX START: Menambahkan ikon untuk tombol baru
        self.minimize_icon = IconManager.get_icon("minimize")
        self.close_icon = IconManager.get_icon("close")
        # FIX END
        
        self.play_pause_button.setIcon(self.pause_icon)
        self.stop_button.setIcon(self.stop_icon)
        self.volume_button.setIcon(self.volume_icon)
        self.fullscreen_button.setIcon(self.fullscreen_enter_icon)
        # FIX START: Mengatur ikon untuk tombol baru
        self.minimize_button.setIcon(self.minimize_icon)
        self.close_button.setIcon(self.close_icon)
        # FIX END
    
    def _connect_signals(self):
        self.play_pause_button.clicked.connect(self.toggle_play)
        self.stop_button.clicked.connect(self.stop_video)
        self.volume_button.clicked.connect(self.toggle_mute)
        self.volume_slider.valueChanged.connect(self.set_volume)
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        # FIX START: Menghubungkan sinyal untuk tombol baru
        self.minimize_button.clicked.connect(self.showMinimized)
        self.close_button.clicked.connect(self.close)
        # FIX END

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
        self.show_controls()
        
    def stop_video(self):
        self.media_player.stop()
        self.close()

    def toggle_mute(self):
        self.audio_output.setMuted(not self.audio_output.isMuted())
        self.update_volume_icon()
        
    def set_volume(self, value):
        self.audio_output.setVolume(value / 100)
        if self.audio_output.isMuted() and value > 0:
            self.audio_output.setMuted(False)
        self.update_volume_icon()

    def update_volume_icon(self):
        if self.audio_output.isMuted() or self.audio_output.volume() == 0:
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
        self.show_controls()

    def hide_controls(self):
        if self.isFullScreen() and self.is_playing and self.controls_widget.isVisible():
            self.controls_widget.hide()
            self.setCursor(Qt.CursorShape.BlankCursor)

    def show_controls(self):
        if not self.controls_widget.isVisible():
            self.controls_widget.show()
        self.controls_widget.raise_()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.hide_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.width() * 0.8
        height = 100
        x = (self.width() - width) / 2
        y = self.height() - height - 20
        self.controls_widget.setGeometry(int(x), int(y), int(width), int(height))
        # Pastikan kontrol tetap di atas setelah resize
        self.controls_widget.raise_()

    def mouseMoveEvent(self, event: QMouseEvent):
        self.show_controls()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key in (Qt.Key.Key_F, Qt.Key.Key_F11):
            self.toggle_fullscreen()
        elif key == Qt.Key.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
        elif key == Qt.Key.Key_Space:
            self.toggle_play()
        elif key == Qt.Key.Key_Right:
            self.media_player.setPosition(self.media_player.position() + 5000)
        elif key == Qt.Key.Key_Left:
            self.media_player.setPosition(self.media_player.position() - 5000)
        elif key == Qt.Key.Key_Up:
            self.volume_slider.setValue(self.volume_slider.value() + 5)
        elif key == Qt.Key.Key_Down:
            self.volume_slider.setValue(self.volume_slider.value() - 5)
        elif key == Qt.Key.Key_M:
            self.toggle_mute()
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        self.show_controls()
            
    def closeEvent(self, event):
        self.media_player.stop()
        super().closeEvent(event)

# -- Widget untuk Thumbnail Video --
class VideoThumbnailWidget(QFrame):
    def __init__(self, video_path: str, main_window, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.main_window = main_window
        self.setFixedSize(220, 180)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            VideoThumbnailWidget {
                background-color: #2c3e50;
                border-radius: 8px;
            }
            VideoThumbnailWidget:hover {
                background-color: #34495e;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setStyleSheet("border: none; border-radius: 5px;")
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
        self.title_label.setStyleSheet("color: white; border: none;")

        layout.addWidget(self.thumbnail_label)
        layout.addWidget(self.title_label)
        
        self.player_window = None

    def open_player(self):
        print(f"Opening player for: {self.video_path}")
        self.player_window = VideoPlayerWindow(self.video_path)
        self.player_window.show()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_player()
        super().mousePressEvent(event)
    
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        
        open_action = QAction("Buka Video", self)
        open_action.triggered.connect(self.open_player)
        menu.addAction(open_action)
        
        info_action = QAction("Info File", self)
        info_action.triggered.connect(self.show_file_info)
        menu.addAction(info_action)

        menu.addSeparator()
        
        remove_action = QAction("Hapus dari Tampilan", self)
        remove_action.triggered.connect(self.deleteLater)
        menu.addAction(remove_action)
        
        delete_action = QAction("Hapus File Permanen", self)
        delete_action.triggered.connect(self.delete_file)
        menu.addAction(delete_action)

        menu.exec(event.globalPos())

    def show_file_info(self):
        try:
            file_info = QFileInfo(self.video_path)
            file_size_mb = file_info.size() / (1024 * 1024)
            info_text = (
                f"<b>Nama File:</b> {file_info.fileName()}<br>"
                f"<b>Lokasi:</b> {file_info.absolutePath()}<br>"
                f"<b>Ukuran:</b> {file_size_mb:.2f} MB<br>"
                f"<b>Dibuat:</b> {file_info.birthTime().toString(Qt.DateFormat.ISODate)}<br>"
                f"<b>Diubah:</b> {file_info.lastModified().toString(Qt.DateFormat.ISODate)}"
            )
            QMessageBox.information(self, "Informasi File", info_text)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Tidak dapat mengambil info file: {e}")

    def delete_file(self):
        confirm = QMessageBox.warning(
            self,
            "Konfirmasi Hapus Permanen",
            f"Anda yakin ingin menghapus file ini secara permanen dari disk?\n\n<b>{self.video_path}</b>\n\nTindakan ini tidak bisa dibatalkan.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel
        )

        if confirm == QMessageBox.StandardButton.Yes:
            try:
                os.remove(self.video_path)
                QMessageBox.information(self, "Sukses", "File berhasil dihapus secara permanen.")
                self.main_window.populate_videos()
            except OSError as e:
                QMessageBox.critical(self, "Error", f"Gagal menghapus file: {e}")

# -- Dialog Manajemen Folder --
class ManageFoldersDialog(QDialog):
    def __init__(self, folders, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Kelola Folder Video")
        self.setMinimumSize(400, 300)
        
        self.folders = folders
        
        layout = QVBoxLayout(self)
        
        self.list_widget = QListWidget()
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
        if not selected_items:
            QMessageBox.information(self, "Info", "Pilih folder yang ingin dihapus.")
            return

        folder_to_remove = selected_items[0].text()
        self.folders.remove(folder_to_remove)
        self.list_widget.takeItem(self.list_widget.row(selected_items[0]))
        self.parent().folders_updated(self.folders)

# -- Jendela Utama Aplikasi --
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Macan Movie - Koleksi Video")
        self.setGeometry(100, 100, 1200, 700)
        self.video_folders = []
        self.settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
        self.setStyleSheet("""
            QMainWindow { background-color: #1e272e; }
            QLabel { color: white; }
            QPushButton { 
                background-color: #3498db; color: white; border: none; 
                padding: 10px 15px; border-radius: 5px;
            }
            QPushButton:hover { background-color: #2980b9; }
            QScrollArea { border: none; }
        """)

        self._setup_ui()
        self.load_settings()
        self.populate_videos()

    def _setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        layout = QVBoxLayout(main_widget)

        button_layout = QHBoxLayout()
        add_folder_button = QPushButton("Tambah Folder")
        add_folder_button.setIcon(IconManager.get_icon("folder_add", color="white"))
        add_folder_button.clicked.connect(self.add_folder)
        
        manage_folder_button = QPushButton("Kelola Folder")
        manage_folder_button.setIcon(IconManager.get_icon("folder_manage", color="white"))
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
        if geometry:
            self.restoreGeometry(geometry)

    def clear_grid(self):
        while self.grid_layout.count():
            child = self.grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def populate_videos(self):
        self.clear_grid()
        
        video_files = []
        if not self.video_folders:
            self.show_message("Tidak ada folder yang ditambahkan.\nSilakan klik 'Tambah Folder' untuk memulai.")
            return

        for folder in self.video_folders:
            try:
                for root, dirs, files in os.walk(folder):
                    for file in files:
                        if file.lower().endswith(VIDEO_EXTENSIONS):
                            video_files.append(os.path.join(root, file))
            except FileNotFoundError:
                print(f"Peringatan: Folder tidak ditemukan: {folder}")
                self.video_folders.remove(folder)
                self.save_folders()
                continue
        
        if not video_files:
            self.show_message("Tidak ada video yang ditemukan di folder yang dipilih.")
            return

        self.reflow_grid(sorted(video_files))

    def show_message(self, message):
        self.clear_grid()
        no_video_label = QLabel(message)
        no_video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no_video_label.setStyleSheet("font-size: 16px; color: #95a5a6;")
        self.grid_layout.addWidget(no_video_label, 0, 0, 1, -1)
        
    def reflow_grid(self, video_files):
        self.clear_grid()
        cols = max(1, self.width() // 240) 
        row, col = 0, 0
        
        for video_path in video_files:
            thumbnail = VideoThumbnailWidget(video_path, self)
            self.grid_layout.addWidget(thumbnail, row, col)
            col += 1
            if col >= cols:
                col = 0
                row += 1
                
    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(100, self.populate_videos)
        
    def closeEvent(self, event):
        self.settings.setValue(SETTINGS_GEOMETRY_KEY, self.saveGeometry())
        super().closeEvent(event)

# -- Eksekusi Aplikasi --
if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    app.setStyle("Fusion")
    
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    dark_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    app.setPalette(dark_palette)

    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())