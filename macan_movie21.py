import sys
import os
import re
import threading
import json
import time
import subprocess
import hashlib # /** MODIFIKASI **/ Ditambahkan untuk membuat nama file cache yang unik
import shutil # /** MODIFIKASI **/ Ditambahkan untuk menghapus direktori cache
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QSlider, QLabel, QFileDialog, QScrollArea, QGridLayout, QFrame, QMessageBox,
    QDialog, QListWidget, QDialogButtonBox, QMenu, QSizePolicy, QListWidgetItem,
    QAbstractItemView, QLineEdit, QStackedLayout, QGraphicsView, QGraphicsScene, QGraphicsTextItem,
    QProgressDialog, QComboBox, QStackedWidget
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import (
    Qt, QUrl, QSettings, QTimer, QSize, QPoint, QFileInfo, QEvent,
    pyqtSignal, QObject, QThread, pyqtSlot, QRectF, QTime, QBuffer
)
from PyQt6.QtGui import (
    QPixmap, QImage, QIcon, QMouseEvent, QKeyEvent, QAction, QPainter,
    QColor, QFont
)
from PyQt6.QtSvg import QSvgRenderer
import numpy as np

# Pustaka untuk thumbnail (OpenCV) dan fitur pemutar video modern
try:
    import cv2
except ImportError:
    print("Kesalahan: Pustaka 'opencv-python-headless' diperlukan.")
    print("Silakan install dengan: pip install opencv-python-headless")
    sys.exit(1)

try:
    import qtawesome as qta
except ImportError:
    print("Peringatan: Pustaka 'qtawesome' tidak ditemukan. Beberapa ikon mungkin tidak muncul.")
    qta = None

try:
    from yt_dlp import YoutubeDL
except ImportError:
    print("Peringatan: Pustaka 'yt-dlp' tidak ditemukan. Fitur pemutaran dari URL tidak akan berfungsi.")
    YoutubeDL = None

# --- KELAS PEMUTAR VIDEO BARU DAN DEPENDENSINYA (DARI macan_video_player47.py) ---

class ThumbnailPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip)
        self.setLayout(QVBoxLayout())
        self.label = QLabel("Memuat...")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout().addWidget(self.label)
        self.setFixedSize(160, 120)
        self.setStyleSheet("background-color: black; border: 1px solid white; color: white; border-radius: 4px;")

    def set_thumbnail(self, pixmap):
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(self.size() - QSize(4, 4), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.label.setPixmap(scaled_pixmap)
        else:
            self.label.setText("Gagal")

class ThumbnailGenerator(QObject):
    thumbnail_ready = pyqtSignal(QPixmap, float)

    @pyqtSlot(str, int, float)
    def generate(self, video_path, timestamp_ms, request_time):
        if not video_path or not os.path.exists(video_path) or timestamp_ms < 0:
            self.thumbnail_ready.emit(QPixmap(), request_time)
            return
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                self.thumbnail_ready.emit(QPixmap(), request_time)
                return
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_ms)
            ret, frame = cap.read()
            cap.release()
            if ret:
                rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_image.shape
                bytes_per_line = ch * w
                qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                pixmap = QPixmap.fromImage(qt_image)
                self.thumbnail_ready.emit(pixmap, request_time)
            else:
                self.thumbnail_ready.emit(QPixmap(), request_time)
        except Exception as e:
            print(f"Kesalahan saat generate thumbnail dengan OpenCV: {e}")
            self.thumbnail_ready.emit(QPixmap(), request_time)

class ClickableSlider(QSlider):
    hover_move = pyqtSignal(int)
    hover_leave = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.orientation() == Qt.Orientation.Horizontal:
                value = self.minimum() + (self.maximum() - self.minimum()) * event.pos().x() / self.width()
            else:
                value = self.minimum() + (self.maximum() - self.minimum()) * (self.height() - event.pos().y()) / self.height()
            self.setValue(int(value))
            self.sliderMoved.emit(int(value))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.hover_move.emit(event.pos().x())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.hover_leave.emit()
        super().leaveEvent(event)

class MiniPlayerWindow(QWidget):
    closing = pyqtSignal()

    def __init__(self, main_player_instance, parent=None):
        super().__init__(parent)
        self.main_player = main_player_instance
        self.audio_output = self.main_player.audio_output
        self.is_muted = self.audio_output.isMuted()
        self.last_volume = int(self.audio_output.volume() * 100) if not self.is_muted else 50
        self.is_playing = False
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        self.setWindowTitle("Macan Player - Mini")
        self.setFixedSize(480, 270)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        icon_path = "player.ico"
        if hasattr(sys, "_MEIPASS"): icon_path = os.path.join(sys._MEIPASS, icon_path)
        if os.path.exists(icon_path): self.setWindowIcon(QIcon(icon_path))
        self.setStyleSheet("background-color: #1c1c1c; color: #ecf0f1;")
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background-color: black;")
        self.position_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.btn_play_pause = QPushButton()
        if qta: self.btn_play_pause.setIcon(qta.icon('fa5s.play'))
        self.btn_stop = QPushButton()
        if qta: self.btn_stop.setIcon(qta.icon('fa5s.stop'))
        self.btn_mute = QPushButton()
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(int(self.audio_output.volume() * 100))
        self.volume_slider.setFixedWidth(100)
        self._update_volume_icon()
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self.btn_play_pause)
        controls_layout.addWidget(self.btn_stop)
        controls_layout.addStretch()
        controls_layout.addWidget(self.btn_mute)
        controls_layout.addWidget(self.volume_slider)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        main_layout.addWidget(self.video_widget, 1)
        main_layout.addWidget(self.position_slider)
        main_layout.addLayout(controls_layout)
        self.setLayout(main_layout)

    def _connect_signals(self):
        self.btn_mute.clicked.connect(self._toggle_mute)
        self.volume_slider.valueChanged.connect(self._set_volume)
        self.audio_output.volumeChanged.connect(self._sync_volume_slider)

    def showEvent(self, event):
        self.main_player.player.setVideoOutput(self.video_widget)
        super().showEvent(event)

    def _set_volume(self, value):
        self.audio_output.setVolume(value / 100.0)

    def _toggle_mute(self):
        self.is_muted = not self.is_muted
        if self.is_muted:
            self.last_volume = self.volume_slider.value()
            self.audio_output.setMuted(True)
        else:
            self.audio_output.setMuted(False)
            self.volume_slider.setValue(self.last_volume if self.last_volume > 0 else 50)
        self._update_volume_icon()

    def _update_volume_icon(self):
        if not qta: return
        volume = self.volume_slider.value()
        is_muted = self.audio_output.isMuted()
        if is_muted or volume == 0: icon = qta.icon('fa5s.volume-mute')
        elif 0 < volume <= 50: icon = qta.icon('fa5s.volume-down')
        else: icon = qta.icon('fa5s.volume-up')
        self.btn_mute.setIcon(icon)

    def _sync_volume_slider(self):
        volume_float = self.audio_output.volume()
        is_muted = self.audio_output.isMuted()
        self.is_muted = is_muted
        if not self.volume_slider.isSliderDown():
            self.volume_slider.setValue(0 if is_muted else int(volume_float * 100))
        self._update_volume_icon()

    def update_position(self, position):
        if not self.position_slider.isSliderDown():
            self.position_slider.setValue(position)

    def update_duration(self, duration):
        self.position_slider.setRange(0, duration)

    def update_play_pause_icon(self, is_playing):
        self.is_playing = is_playing
        if qta:
            icon = qta.icon('fa5s.pause') if is_playing else qta.icon('fa5s.play')
            self.btn_play_pause.setIcon(icon)

    def closeEvent(self, event):
        self.closing.emit()
        super().closeEvent(event)

class SRTParser:
    def __init__(self, srt_file_path):
        self.subtitles = []
        try:
            with open(srt_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self._parse(content)
        except Exception as e:
            print(f"Gagal membaca atau parse file SRT: {e}")

    def _time_to_ms(self, time_str):
        h, m, s, ms = map(int, re.split('[:,]', time_str))
        return (h * 3600 + m * 60 + s) * 1000 + ms

    def _parse(self, content):
        pattern = re.compile(r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.*?)\n\n', re.DOTALL)
        matches = pattern.findall(content)
        for match in matches:
            start_time_str, end_time_str, text = match[1], match[2], match[3]
            self.subtitles.append({
                'start_ms': self._time_to_ms(start_time_str),
                'end_ms': self._time_to_ms(end_time_str),
                'text': text.strip()
            })

    def get_subtitle(self, position_ms):
        for sub in self.subtitles:
            if sub['start_ms'] <= position_ms <= sub['end_ms']:
                return sub['text']
        return None

class YouTubeDLWorker(QObject):
    finished = pyqtSignal(str, str, str)
    def __init__(self, url):
        super().__init__()
        self.url = url
    def run(self):
        if not YoutubeDL:
            self.finished.emit(None, None, "Pustaka yt-dlp tidak terinstal.")
            return
        try:
            ydl_opts = {'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', 'quiet': True, 'no_warnings': True}
            with YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(self.url, download=False)
                title = info_dict.get('title', 'Judul tidak diketahui')
                self.finished.emit(info_dict['url'], title, None)
        except Exception as e:
            self.finished.emit(None, None, f"Error dari yt-dlp: {str(e)}")

class PlaylistWidget(QWidget):
    play_requested = pyqtSignal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Macan Player - Playlist")
        self.setGeometry(1100, 100, 300, 400)
        icon_path = "player.ico"
        if hasattr(sys, "_MEIPASS"): icon_path = os.path.join(sys._MEIPASS, icon_path)
        if os.path.exists(icon_path): self.setWindowIcon(QIcon(icon_path))
        self.playlist = []
        self._setup_ui()
        self._connect_signals()
        self.setAcceptDrops(True)
    def _setup_ui(self):
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setStyleSheet("background-color: #34495e;")
        self.btn_add_file = QPushButton(" Tambah File")
        if qta: self.btn_add_file.setIcon(qta.icon('fa5s.plus'))
        self.btn_remove = QPushButton(" Hapus")
        if qta: self.btn_remove.setIcon(qta.icon('fa5s.trash'))
        self.btn_clear = QPushButton(" Hapus Semua")
        if qta: self.btn_clear.setIcon(qta.icon('fa5s.times-circle'))
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self.btn_add_file)
        controls_layout.addWidget(self.btn_remove)
        controls_layout.addWidget(self.btn_clear)
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.list_widget)
        main_layout.addLayout(controls_layout)
        self.setLayout(main_layout)
    def _connect_signals(self):
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.btn_add_file.clicked.connect(self._add_to_playlist)
        self.btn_remove.clicked.connect(self._remove_from_playlist)
        self.btn_clear.clicked.connect(self._clear_playlist)
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: event.ignore()
    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.exists(file_path) and os.path.splitext(file_path)[1].lower() in ['.mp4', '.mkv', '.webm', '.avi']:
                self.playlist.append({'path': file_path, 'title': os.path.basename(file_path)})
                self._update_ui()
                self._save_playlist()
        event.acceptProposedAction()
    def _on_item_double_clicked(self, item):
        index = self.list_widget.row(item)
        if 0 <= index < len(self.playlist):
            self.play_requested.emit(self.playlist[index]['path'])
            self._update_selection(index)
    def _add_to_playlist(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Tambahkan ke Playlist", "", "Video Files (*.mp4 *.mkv *.webm *.avi)")
        if file_path:
            self.playlist.append({'path': file_path, 'title': os.path.basename(file_path)})
            self._update_ui()
            self._save_playlist()
    def _remove_from_playlist(self):
        selected_items = self.list_widget.selectedItems()
        if not selected_items: return
        index = self.list_widget.row(selected_items[0])
        del self.playlist[index]
        self._update_ui()
        self._save_playlist()
    def _clear_playlist(self):
        self.playlist.clear()
        self._update_ui()
        self._save_playlist()
    def _update_ui(self):
        self.list_widget.clear()
        for item in self.playlist: self.list_widget.addItem(item['title'])
    def _update_selection(self, index):
        if 0 <= index < self.list_widget.count(): self.list_widget.setCurrentRow(index)
    def get_current_index(self): return self.list_widget.currentRow()
    def get_playlist_data(self): return self.playlist
    def set_playlist_data(self, data):
        self.playlist = data
        self._update_ui()
    def _save_playlist(self):
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "player_config.json")
        try:
            with open(config_path, "r") as f: config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError): config = {}
        config['playlist'] = self.playlist
        with open(config_path, "w") as f: json.dump(config, f, indent=4)

class HistoryWindow(QDialog):
    history_item_selected = pyqtSignal(dict)
    delete_selected_requested = pyqtSignal(int)
    clear_all_requested = pyqtSignal()
    def __init__(self, history_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Riwayat Tontonan")
        self.setGeometry(1100, 550, 300, 400)
        self.history_data = history_data
        self._setup_ui()
        self._connect_signals()
        self.populate_list()
    def _setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        self.btn_remove_selected = QPushButton(" Hapus Pilihan")
        if qta: self.btn_remove_selected.setIcon(qta.icon('fa5s.trash-alt'))
        self.btn_clear_all = QPushButton(" Hapus Semua")
        if qta: self.btn_clear_all.setIcon(qta.icon('fa5s.times'))
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.btn_remove_selected)
        button_layout.addWidget(self.btn_clear_all)
        self.main_layout.addWidget(self.list_widget)
        self.main_layout.addLayout(button_layout)
    def _connect_signals(self):
        self.list_widget.itemDoubleClicked.connect(self._on_item_selected)
        self.btn_remove_selected.clicked.connect(self._remove_selected)
        self.btn_clear_all.clicked.connect(self._clear_all)
    def populate_list(self):
        self.list_widget.clear()
        for item in reversed(self.history_data):
            list_item = QListWidgetItem(item.get('title', 'Judul Tidak Diketahui'))
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            self.list_widget.addItem(list_item)
    def _on_item_selected(self, item):
        self.history_item_selected.emit(item.data(Qt.ItemDataRole.UserRole))
        self.accept()
    def _remove_selected(self):
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "Info", "Pilih item yang ingin dihapus.")
            return
        original_index = len(self.history_data) - 1 - self.list_widget.row(selected_items[0])
        self.delete_selected_requested.emit(original_index)
    def _clear_all(self):
        if QMessageBox.question(self, "Konfirmasi", "Yakin hapus SEMUA riwayat?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.clear_all_requested.emit()

class ModernVideoPlayer(QWidget):
    request_thumbnail = pyqtSignal(str, int, float)
    back_requested = pyqtSignal()
    fullscreen_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.is_fullscreen = False
        self.normal_geometry = None
        self.last_volume = 50
        self.SKIP_INTERVAL = 10000
        self.playback_speeds = [0.5, 1.0, 1.5, 2.0]
        self.current_speed_index = 1
        self.config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "player_config.json")
        self.themes = {}
        self.theme_names = []
        self.current_theme_index = 0
        self.history = []
        self.current_media_info = {}
        self.srt_parser = None
        self.current_subtitle_text = ""
        self.playlist_widget = PlaylistWidget()
        self.history_window = HistoryWindow(self.history, self)
        self.controls_hide_timer = QTimer(self)
        self.controls_hide_timer.setInterval(2500)
        self.controls_hide_timer.setSingleShot(True)
        self._setup_player()
        self.mini_player_widget = MiniPlayerWindow(self)
        self._setup_thumbnail_feature()
        self._setup_themes()
        self._load_config()
        self._setup_ui()
        self._connect_signals()
        self._apply_theme(self.theme_names[self.current_theme_index])
        self.setAcceptDrops(True)
        self.video_widget.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.video_widget.setMouseTracking(True)
        self.controls_container.setMouseTracking(True)
        self.player.setVideoOutput(self.video_widget)

    def _setup_thumbnail_feature(self):
        self.last_thumbnail_request_time = 0.0
        self.thumbnail_preview = ThumbnailPreviewWidget()
        self.thumbnail_thread = QThread()
        self.thumbnail_generator = ThumbnailGenerator()
        self.thumbnail_generator.moveToThread(self.thumbnail_thread)
        self.thumbnail_thread.start()

    def _setup_player(self):
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

    def _setup_themes(self):
        self.themes = {
            "Dark": """
                QWidget { background-color: #1c1c1c; color: #ecf0f1; font-family: 'Segoe UI', Arial, sans-serif; }
                QPushButton { background-color: transparent; border: none; padding: 8px; border-radius: 4px; }
                QPushButton:hover { background-color: #3a3a3a; } QPushButton:pressed { background-color: #4a4a4a; }
                QLineEdit { background-color: #2c2c2c; border: 1px solid #444; padding: 5px; border-radius: 4px; }
                QSlider::groove:horizontal { height: 4px; background: #444; border-radius: 2px; }
                QSlider::handle:horizontal { background: #3498db; width: 12px; margin: -4px 0; border-radius: 6px; }
                QSlider::sub-page:horizontal { background: #3498db; border-radius: 2px; }
                QLabel { font-size: 12px; }
                QListWidget { background-color: #2c3e50; }
            """,
            "Light": """
                QWidget { background-color: #f0f0f0; color: #2c3e50; font-family: 'Segoe UI', Arial, sans-serif; }
                QPushButton { background-color: transparent; border: none; padding: 8px; border-radius: 4px; }
                QPushButton:hover { background-color: #dcdcdc; } QPushButton:pressed { background-color: #c0c0c0; }
                QLineEdit { background-color: #ffffff; border: 1px solid #bdc3c7; padding: 5px; border-radius: 4px; }
                QSlider::groove:horizontal { height: 4px; background: #bdc3c7; border-radius: 2px; }
                QSlider::handle:horizontal { background: #e74c3c; width: 12px; margin: -4px 0; border-radius: 6px; }
                QSlider::sub-page:horizontal { background: #e74c3c; border-radius: 2px; }
                QLabel { font-size: 12px; }
                QListWidget { background-color: #ffffff; }
            """,
            "Neon Blue": """
                QWidget { background-color: #0d0221; color: #b4f1f1; font-family: 'Segoe UI', Arial, sans-serif; }
                QPushButton { background-color: transparent; border: none; padding: 8px; border-radius: 4px; }
                QPushButton:hover { background-color: #261a3b; } QPushButton:pressed { background-color: #4d3375; }
                QLineEdit { background-color: #261a3b; border: 1px solid #00aaff; padding: 5px; border-radius: 4px; color: #ffffff; }
                QSlider::groove:horizontal { height: 4px; background: #261a3b; border-radius: 2px; }
                QSlider::handle:horizontal { background: #00aaff; width: 12px; margin: -4px 0; border-radius: 6px; }
                QSlider::sub-page:horizontal { background: #00aaff; border-radius: 2px; }
                QLabel { font-size: 12px; }
                QListWidget { background-color: #261a3b; }
            """,
        }
        self.theme_names = list(self.themes.keys())

    def _apply_theme(self, theme_name):
        if theme_name in self.themes:
            self.setStyleSheet(self.themes[theme_name])
            self.playlist_widget.setStyleSheet(self.themes[theme_name])
            self.history_window.setStyleSheet(self.themes[theme_name])
            self.mini_player_widget.setStyleSheet(self.themes[theme_name])

    def _change_theme(self):
        self.current_theme_index = (self.current_theme_index + 1) % len(self.theme_names)
        new_theme_name = self.theme_names[self.current_theme_index]
        self._apply_theme(new_theme_name)
        self.btn_change_theme.setToolTip(f"Ganti Tema (Sekarang: {new_theme_name})")

    def _load_config(self):
        try:
            with open(self.config_path, "r") as f: config = json.load(f)
            self.last_volume = config.get('last_volume', 50)
            self.audio_output.setVolume(self.last_volume / 100.0)
            self.playlist_widget.set_playlist_data(config.get('playlist', []))
            saved_theme = config.get('theme', 'Dark')
            if saved_theme in self.theme_names:
                self.current_theme_index = self.theme_names.index(saved_theme)
            self.history = config.get('history', [])
            self.history_window.history_data = self.history
            self.history_window.populate_list()
        except (FileNotFoundError, json.JSONDecodeError): pass

    def _save_config(self):
        config = {
            'last_volume': int(self.audio_output.volume() * 100),
            'playlist': self.playlist_widget.get_playlist_data(),
            'theme': self.theme_names[self.current_theme_index],
            'history': self.history
        }
        try:
            with open(self.config_path, "w") as f: json.dump(config, f, indent=4)
        except Exception as e: print(f"Gagal menyimpan konfigurasi: {e}")

    def _setup_ui(self):
        self.setWindowTitle("Macan Video Player")
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background-color: black;")
        self.video_widget.installEventFilter(self)
        self.subtitle_scene = QGraphicsScene()
        self.subtitle_view = QGraphicsView(self.subtitle_scene, self)
        self.subtitle_view.setStyleSheet("background: transparent; border: none;")
        self.subtitle_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.subtitle_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.subtitle_view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.subtitle_text_item = QGraphicsTextItem()
        font = QFont("Arial", 20, QFont.Weight.Bold)
        self.subtitle_text_item.setFont(font)
        self.subtitle_text_item.setDefaultTextColor(QColor("white"))
        self.subtitle_scene.addItem(self.subtitle_text_item)
        self.video_container = QWidget()
        self.video_stack_layout = QStackedLayout(self.video_container)
        self.video_stack_layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.splash_label = QLabel()
        splash_path = "splash.png"
        if hasattr(sys, "_MEIPASS"): splash_path = os.path.join(sys._MEIPASS, splash_path)
        if os.path.exists(splash_path):
            pixmap = QPixmap(splash_path)
            self.splash_label.setPixmap(pixmap.scaled(QSize(480, 480), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.splash_label.setText("Macan Video Player")
        self.splash_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.splash_label.setStyleSheet("background-color: black; color: white; font-size: 30px; font-weight: bold;")
        self.video_stack_layout.addWidget(self.video_widget)
        self.video_stack_layout.addWidget(self.splash_label)
        self.video_stack_layout.addWidget(self.subtitle_view)
        
        self.btn_back = QPushButton()
        if qta: self.btn_back.setIcon(qta.icon('fa5s.arrow-left'))
        self.btn_back.setToolTip("Kembali ke Koleksi")

        self.btn_open = QPushButton()
        if qta: self.btn_open.setIcon(qta.icon('fa5s.folder-open'))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("URL video (YouTube, dll)...")
        self.btn_load_url = QPushButton()
        if qta: self.btn_load_url.setIcon(qta.icon('fa5s.link'))
        self.btn_toggle_url_bar = QPushButton()
        if qta: self.btn_toggle_url_bar.setIcon(qta.icon('fa5s.globe'))
        self.btn_show_playlist = QPushButton()
        if qta: self.btn_show_playlist.setIcon(qta.icon('fa5s.list'))
        self.btn_show_history = QPushButton()
        if qta: self.btn_show_history.setIcon(qta.icon('fa5s.history'))
        self.position_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.time_label = QLabel("00:00 / 00:00")
        self.btn_prev_playlist = QPushButton()
        if qta: self.btn_prev_playlist.setIcon(qta.icon('fa5s.step-backward'))
        self.btn_next_playlist = QPushButton()
        if qta: self.btn_next_playlist.setIcon(qta.icon('fa5s.step-forward'))
        self.btn_play_pause = QPushButton()
        if qta: self.btn_play_pause.setIcon(qta.icon('fa5s.play'))
        self.btn_stop = QPushButton()
        if qta: self.btn_stop.setIcon(qta.icon('fa5s.stop'))
        self.btn_speed = QPushButton(f"{self.playback_speeds[self.current_speed_index]}x")
        self.btn_mute = QPushButton()
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.last_volume)
        self.volume_slider.setFixedWidth(120)
        if qta: self._update_volume_icon()
        self.btn_mini_player = QPushButton()
        if qta: self.btn_mini_player.setIcon(qta.icon('fa5s.window-minimize'))
        self.btn_fullscreen = QPushButton()
        if qta: self.btn_fullscreen.setIcon(qta.icon('fa5s.expand'))
        self.btn_change_theme = QPushButton()
        if qta: self.btn_change_theme.setIcon(qta.icon('fa5s.palette'))
        self.controls_container = QWidget()
        self.url_bar_widget = QWidget()
        url_bar_layout = QHBoxLayout()
        url_bar_layout.setContentsMargins(10, 0, 10, 5)
        url_bar_layout.addWidget(self.url_input)
        url_bar_layout.addWidget(self.btn_load_url)
        self.url_bar_widget.setLayout(url_bar_layout)
        self.url_bar_widget.setVisible(False)
        slider_layout = QHBoxLayout()
        slider_layout.setContentsMargins(10, 0, 10, 0)
        slider_layout.addWidget(self.position_slider)
        bottom_controls_layout = QHBoxLayout()
        bottom_controls_layout.setContentsMargins(10, 0, 10, 5)
        
        bottom_controls_layout.addWidget(self.btn_back)
        bottom_controls_layout.addWidget(self.btn_play_pause)
        bottom_controls_layout.addWidget(self.btn_stop)
        bottom_controls_layout.addWidget(self.btn_prev_playlist)
        bottom_controls_layout.addWidget(self.btn_next_playlist)
        bottom_controls_layout.addWidget(self.time_label)
        bottom_controls_layout.addStretch(1)
        bottom_controls_layout.addWidget(self.btn_open)
        bottom_controls_layout.addWidget(self.btn_toggle_url_bar)
        bottom_controls_layout.addWidget(self.btn_speed)
        bottom_controls_layout.addWidget(self.btn_show_playlist)
        bottom_controls_layout.addWidget(self.btn_mute)
        bottom_controls_layout.addWidget(self.volume_slider)
        bottom_controls_layout.addWidget(self.btn_mini_player)
        bottom_controls_layout.addWidget(self.btn_fullscreen)
        bottom_controls_layout.addWidget(self.btn_change_theme)
        container_layout = QVBoxLayout()
        container_layout.setContentsMargins(0, 5, 0, 0)
        container_layout.setSpacing(5)
        container_layout.addWidget(self.url_bar_widget)
        container_layout.addLayout(slider_layout)
        container_layout.addLayout(bottom_controls_layout)
        self.controls_container.setLayout(container_layout)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.video_container, 1)
        main_layout.addWidget(self.controls_container)
        self.setLayout(main_layout)
        self.video_widget.hide()
        self.splash_label.show()

    def _connect_signals(self):
        self.btn_back.clicked.connect(self.back_requested.emit)
        self.btn_open.clicked.connect(self._open_file)
        self.url_input.returnPressed.connect(self._load_from_url)
        self.btn_load_url.clicked.connect(self._load_from_url)
        self.btn_toggle_url_bar.clicked.connect(self._toggle_url_bar)
        self.btn_play_pause.clicked.connect(self._toggle_play_pause)
        self.btn_stop.clicked.connect(self._stop_video)
        self.btn_fullscreen.clicked.connect(self._toggle_fullscreen)
        self.btn_mute.clicked.connect(self._toggle_mute)
        self.btn_speed.clicked.connect(self._change_playback_speed)
        self.btn_show_playlist.clicked.connect(self._toggle_playlist_window)
        self.btn_prev_playlist.clicked.connect(self._play_previous_video)
        self.btn_next_playlist.clicked.connect(self._play_next_video)
        self.btn_change_theme.clicked.connect(self._change_theme)
        self.history_window.history_item_selected.connect(self._play_from_history)
        self.history_window.delete_selected_requested.connect(self._delete_history_item)
        self.history_window.clear_all_requested.connect(self._clear_all_history_data)
        self.btn_mini_player.clicked.connect(self._show_mini_player)
        self.mini_player_widget.closing.connect(self._show_main_from_mini)
        self.mini_player_widget.btn_play_pause.clicked.connect(self._toggle_play_pause)
        self.mini_player_widget.btn_stop.clicked.connect(self._stop_video)
        self.mini_player_widget.position_slider.sliderMoved.connect(self._set_position)
        self.volume_slider.valueChanged.connect(self._set_volume)
        self.position_slider.sliderMoved.connect(self._set_position)
        self.player.positionChanged.connect(self._update_position)
        self.player.durationChanged.connect(self._update_duration)
        self.player.playbackStateChanged.connect(self._update_play_pause_icon)
        self.player.mediaStatusChanged.connect(self._handle_media_status_changed)
        self.audio_output.volumeChanged.connect(self._sync_main_volume_slider)
        self.playlist_widget.play_requested.connect(self._load_and_play_from_playlist)
        self.controls_hide_timer.timeout.connect(self._hide_controls)
        self.position_slider.hover_move.connect(self._show_thumbnail_preview)
        self.position_slider.hover_leave.connect(self.thumbnail_preview.hide)
        self.thumbnail_generator.thumbnail_ready.connect(self._update_thumbnail)
        self.request_thumbnail.connect(self.thumbnail_generator.generate, Qt.ConnectionType.QueuedConnection)

    def _show_thumbnail_preview(self, x_pos):
        video_path = self.current_media_info.get('path', '')
        is_url = "://" in video_path
        if not self.player.hasVideo() or self.player.duration() <= 0 or is_url or not os.path.exists(video_path): return
        value = self.position_slider.minimum() + (self.position_slider.maximum() - self.position_slider.minimum()) * x_pos / self.position_slider.width()
        timestamp_ms = int(value)
        global_slider_pos = self.position_slider.mapToGlobal(self.position_slider.rect().topLeft())
        preview_x = global_slider_pos.x() + x_pos - (self.thumbnail_preview.width() / 2)
        preview_y = global_slider_pos.y() - self.thumbnail_preview.height() - 5
        self.thumbnail_preview.move(int(preview_x), int(preview_y))
        if not self.thumbnail_preview.isVisible():
            self.thumbnail_preview.show()
            self.thumbnail_preview.label.setText("Memuat...")
        current_time = time.time()
        if current_time - self.last_thumbnail_request_time > 0.1:
            self.last_thumbnail_request_time = current_time
            self.request_thumbnail.emit(video_path, timestamp_ms, current_time)

    @pyqtSlot(QPixmap, float)
    def _update_thumbnail(self, pixmap, request_time):
        if request_time == self.last_thumbnail_request_time and self.thumbnail_preview.isVisible():
            self.thumbnail_preview.set_thumbnail(pixmap)

    def _show_history_window(self):
        self.history_window.populate_list()
        self.history_window.exec()
    def _add_to_history(self, path, title):
        self.history = [item for item in self.history if item.get('path') != path]
        self.history.append({'path': path, 'title': title})
        if len(self.history) > 50: self.history = self.history[-50:]
    def _play_from_history(self, item):
        path = item.get('path')
        if not path: return
        self._load_video_file(path)
    def _load_subtitle_file(self, video_path):
        self.srt_parser = None
        self.subtitle_text_item.setHtml("")
        base_name, _ = os.path.splitext(video_path)
        srt_path = base_name + ".srt"
        if os.path.exists(srt_path):
            print(f"File subtitle ditemukan: {srt_path}")
            self.srt_parser = SRTParser(srt_path)
        else:
            print("Tidak ada file subtitle (.srt) yang cocok.")
    def _delete_history_item(self, index):
        if 0 <= index < len(self.history):
            del self.history[index]
            self.history_window.populate_list()
            self._save_config()
    def _clear_all_history_data(self):
        self.history.clear()
        self.history_window.populate_list()
        self._save_config()

    def _show_mini_player(self):
        self.mini_player_widget.show()
        self.window().hide()

    def _show_main_from_mini(self):
        self.player.setVideoOutput(self.video_widget)
        self.window().show()
        self.mini_player_widget.hide()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.exists(file_path) and os.path.splitext(file_path)[1].lower() in ['.mp4', '.mkv', '.webm', '.avi']:
                self._load_video_file(file_path)
                break
        event.acceptProposedAction()

    def _hide_controls(self):
        is_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if self.is_fullscreen and is_playing:
            self.setCursor(Qt.CursorShape.BlankCursor)
            self.controls_container.setVisible(False)

    def open_file_from_path(self, file_path):
        if file_path and os.path.exists(file_path) and any(file_path.lower().endswith(ext) for ext in ['.mp4', '.mkv', '.webm', '.avi']):
            self._load_video_file(file_path)
        else:
            QMessageBox.warning(self, "Tipe File Tidak Didukung", "File bukan video yang didukung.")

    def _toggle_url_bar(self):
        self.url_bar_widget.setVisible(not self.url_bar_widget.isVisible())

    def _open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Pilih Video", "", "Video Files (*.mp4 *.mkv *.webm *.avi)")
        if file_path: self._load_video_file(file_path)

    def _load_video_file(self, file_path_or_url):
        self.window().setWindowTitle(f"Macan Player - Memuat...")
        self._stop_video()
        is_url = "://" in file_path_or_url
        if not is_url:
            self._load_subtitle_file(file_path_or_url)
        source = QUrl(file_path_or_url) if is_url else QUrl.fromLocalFile(file_path_or_url)
        title = self.current_media_info.get('title', os.path.basename(file_path_or_url))
        self.current_media_info = {'path': file_path_or_url, 'title': title}
        self.player.setSource(source)
        self.player.play()
        self.window().setWindowTitle(f"Macan Player - {title}")
        self._update_control_states()
        self._add_to_history(file_path_or_url, title)

    def _load_and_play_from_playlist(self, file_path):
        self._load_video_file(file_path)
        self._update_playlist_nav_buttons()

    def _play_next_video(self):
        current_index = self.playlist_widget.get_current_index()
        playlist_data = self.playlist_widget.get_playlist_data()
        new_index = current_index + 1
        if 0 <= new_index < len(playlist_data):
            self._load_and_play_from_playlist(playlist_data[new_index]['path'])
            self.playlist_widget._update_selection(new_index)

    def _play_previous_video(self):
        current_index = self.playlist_widget.get_current_index()
        playlist_data = self.playlist_widget.get_playlist_data()
        new_index = current_index - 1
        if 0 <= new_index < len(playlist_data):
            self._load_and_play_from_playlist(playlist_data[new_index]['path'])
            self.playlist_widget._update_selection(new_index)

    def _update_playlist_nav_buttons(self):
        playlist_data = self.playlist_widget.get_playlist_data()
        current_index = self.playlist_widget.get_current_index()
        self.btn_prev_playlist.setEnabled(current_index > 0)
        self.btn_next_playlist.setEnabled(current_index < len(playlist_data) - 1)

    def _toggle_playlist_window(self):
        if self.playlist_widget.isVisible(): self.playlist_widget.hide()
        else: self.playlist_widget.show()

    def _load_from_url(self):
        url = self.url_input.text().strip()
        if not url: return
        self.window().setWindowTitle("Macan Player - Mengambil info video...")
        self.worker = YouTubeDLWorker(url)
        self.thread = threading.Thread(target=self.worker.run, daemon=True)
        self.worker.finished.connect(self._on_youtube_dl_finished)
        self.thread.start()

    def _on_youtube_dl_finished(self, video_url, title, error):
        if error or not video_url:
            QMessageBox.critical(self, "Error URL", error or "URL tidak valid.")
            self.window().setWindowTitle("Macan Player")
            return
        self.current_media_info = {'path': video_url, 'title': title}
        self._load_video_file(video_url)

    def _toggle_play_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _stop_video(self):
        self.player.stop()
        self._update_time_label(0, 0)
        self.position_slider.setValue(0)
        self._update_control_states()
        self.subtitle_text_item.setHtml("")
        self.current_subtitle_text = ""
        self.window().setWindowTitle("Macan Movie - Koleksi Video")

    def _skip_forward(self):
        self._set_position(self.player.position() + self.SKIP_INTERVAL)

    def _skip_backward(self):
        self._set_position(max(0, self.player.position() - self.SKIP_INTERVAL))

    def _change_playback_speed(self):
        self.current_speed_index = (self.current_speed_index + 1) % len(self.playback_speeds)
        new_speed = self.playback_speeds[self.current_speed_index]
        self.player.setPlaybackRate(new_speed)
        self.btn_speed.setText(f"{new_speed}x")

    def _update_position(self, position):
        if not self.position_slider.isSliderDown():
            self.position_slider.setValue(position)
            self._update_time_label(position, self.player.duration())
            self.mini_player_widget.update_position(position)
        if self.srt_parser:
            subtitle_text = self.srt_parser.get_subtitle(position)
            display_html = ""
            if subtitle_text:
                subtitle_text = subtitle_text.replace('\n', '<br>')
                style = "color: white; background-color: rgba(0, 0, 0, 0.6); padding: 5px; border-radius: 5px;"
                display_html = f"<div style='{style}'>{subtitle_text}</div>"
            if display_html != self.current_subtitle_text:
                self.current_subtitle_text = display_html
                self.subtitle_text_item.setHtml(f"<center>{display_html}</center>")
                self._reposition_subtitle()

    def _reposition_subtitle(self):
        if not self.subtitle_text_item.toPlainText(): return
        self.subtitle_scene.setSceneRect(QRectF(self.subtitle_view.rect()))
        text_rect = self.subtitle_text_item.boundingRect()
        view_rect = self.subtitle_view.viewport().rect()
        x = (view_rect.width() - text_rect.width()) / 2
        y = view_rect.height() - text_rect.height() - 20
        self.subtitle_text_item.setPos(x, y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_subtitle()

    def _update_duration(self, duration):
        self.position_slider.setRange(0, duration)
        self.mini_player_widget.update_duration(duration)

    def _set_position(self, position):
        self.player.setPosition(position)

    def _set_volume(self, value):
        self.audio_output.setVolume(value / 100.0)
        if value > 0 and self.audio_output.isMuted(): self.audio_output.setMuted(False)
        elif value == 0: self.audio_output.setMuted(True)

    def _toggle_mute(self):
        self.audio_output.setMuted(not self.audio_output.isMuted())

    def _update_volume_icon(self):
        if not qta: return
        volume = int(self.audio_output.volume() * 100)
        is_muted = self.audio_output.isMuted()
        if is_muted or volume == 0: icon = qta.icon('fa5s.volume-mute')
        elif 0 < volume <= 50: icon = qta.icon('fa5s.volume-down')
        else: icon = qta.icon('fa5s.volume-up')
        self.btn_mute.setIcon(icon)

    def _sync_main_volume_slider(self):
        volume_float = self.audio_output.volume()
        is_muted = self.audio_output.isMuted()
        if not self.volume_slider.isSliderDown():
            self.volume_slider.setValue(0 if is_muted else int(volume_float * 100))
        self._update_volume_icon()

    def _update_time_label(self, position, duration):
        if duration > 0:
            pos_time = QTime(0, 0, 0).addMSecs(position)
            dur_time = QTime(0, 0, 0).addMSecs(duration)
            fmt = 'hh:mm:ss' if duration >= 3600000 else 'mm:ss'
            self.time_label.setText(f"{pos_time.toString(fmt)} / {dur_time.toString(fmt)}")
        else:
            self.time_label.setText("00:00 / 00:00")

    def _update_control_states(self):
        is_media_loaded = self.player.mediaStatus() != QMediaPlayer.MediaStatus.NoMedia
        if is_media_loaded:
            self.splash_label.hide()
            self.video_widget.show()
        else:
            self.video_widget.hide()
            self.splash_label.show()
        self.btn_play_pause.setEnabled(is_media_loaded)
        self.btn_stop.setEnabled(is_media_loaded)
        self.btn_mini_player.setEnabled(is_media_loaded)
        self._update_playlist_nav_buttons()

    def _update_play_pause_icon(self, state):
        is_playing = state == QMediaPlayer.PlaybackState.PlayingState
        if qta:
            icon = qta.icon('fa5s.pause') if is_playing else qta.icon('fa5s.play')
            self.btn_play_pause.setIcon(icon)
        self.mini_player_widget.update_play_pause_icon(is_playing)

    def _handle_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            current_index = self.playlist_widget.get_current_index()
            playlist_data = self.playlist_widget.get_playlist_data()
            if current_index < len(playlist_data) - 1:
                self._play_next_video()
            else:
                self._stop_video()

    def _toggle_fullscreen(self):
        self.fullscreen_requested.emit()

    def set_fullscreen_state(self, is_fullscreen):
        self.is_fullscreen = is_fullscreen
        if qta:
            icon_name = 'fa5s.compress' if is_fullscreen else 'fa5s.expand'
            self.btn_fullscreen.setIcon(qta.icon(icon_name))
        
        if not is_fullscreen:
            self.controls_container.setVisible(True)
            self.setCursor(Qt.CursorShape.ArrowCursor)


    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_F11 or (key == Qt.Key.Key_Escape and self.is_fullscreen):
            self.fullscreen_requested.emit()
        elif key == Qt.Key.Key_Space:
            self._toggle_play_pause()
        elif key == Qt.Key.Key_Right: self._skip_forward()
        elif key == Qt.Key.Key_Left: self._skip_backward()
        else: super().keyPressEvent(event)
    
    def mouseMoveEvent(self, event):
        if self.is_fullscreen:
            self.controls_container.setVisible(True)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.controls_hide_timer.start()
        super().mouseMoveEvent(event)

    def eventFilter(self, source, event):
        if source is self.video_widget:
            if event.type() == QEvent.Type.MouseButtonPress:
                if self.btn_play_pause.isEnabled(): self._toggle_play_pause()
                return True
            elif event.type() == QEvent.Type.MouseButtonDblClick:
                self._toggle_fullscreen()
                return True
        return super().eventFilter(source, event)

    def closeEvent(self, event):
        self._save_config()
        self.playlist_widget.close()
        self.mini_player_widget.close()
        self.history_window.close()
        self.thumbnail_thread.quit()
        self.thumbnail_thread.wait()
        self.player.stop()
        event.accept()

# --- BAGIAN KODE ASLI DARI macan_movie11.py (DENGAN PENYESUAIAN) ---

# -- Konstanta --
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm')
SETTINGS_ORGANIZATION = "MacanMovieProfessional"
SETTINGS_APPLICATION = "MoviePlayer"
SETTINGS_FOLDERS_KEY = "videoFolders"
SETTINGS_GEOMETRY_KEY = "mainWindowGeometry"
SETTINGS_WINDOW_STATE_KEY = "mainWindowState"
SETTINGS_SORT_KEY = "sortMethod" # /** MODIFIKASI BARU **/ Kunci untuk menyimpan metode urut

# -- Manajer Ikon SVG --
class IconManager:
    SVG_DATA = {
        "minimize": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line></svg>""",
        "maximize": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path></svg>""",
        "restore": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 3 21 3 21 9"></polyline><polyline points="9 21 3 21 3 15"></polyline><line x1="21" y1="3" x2="14" y2="10"></line><line x1="3" y1="21" x2="10" y2="14"></line></svg>""",
        "close": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>""",
        "folder_add": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path><line x1="12" y1="11" x2="12" y2="17"></line><line x1="9" y1="14" x2="15" y2="14"></line></svg>""",
        "folder_manage": """<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="1"></circle><circle cx="17" cy="13" r="1"></circle><circle cx="7" cy="13" r="1"></circle></svg>""",
    }
    @staticmethod
    def get_icon(name: str, color: str = "#ecf0f1", size: QSize = QSize(24, 24)) -> QIcon:
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

# /** MODIFIKASI **/
# Blok berikut diubah total untuk menangani caching thumbnail ke file .jpg di disk.
# -- Disk Caching for Thumbnails --
class ThumbnailCache:
    """Manages disk caching for video thumbnails to speed up loading."""
    def __init__(self, cache_dir_name="macan_thumbnail_cache"):
        self.cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), cache_dir_name)
        self._initialize_cache_dir()

    def _initialize_cache_dir(self):
        """Creates the cache directory if it doesn't exist."""
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
        except OSError as e:
            print(f"Error creating cache directory {self.cache_dir}: {e}")

    def _get_cache_filepath(self, video_path: str) -> tuple[str, str]:
        """Generates a unique and safe filename for the cache files based on the video path."""
        # Gunakan hash SHA256 dari path video untuk nama file yang unik dan aman
        path_bytes = video_path.encode('utf-8')
        hash_name = hashlib.sha256(path_bytes).hexdigest()
        image_filepath = os.path.join(self.cache_dir, f"{hash_name}.jpg")
        meta_filepath = os.path.join(self.cache_dir, f"{hash_name}.meta")
        return image_filepath, meta_filepath

    def get_thumbnail(self, video_path: str) -> QPixmap | None:
        """Retrieves a thumbnail from the disk cache if it exists and is up-to-date."""
        if not os.path.exists(video_path):
            return None

        cache_image_path, cache_meta_path = self._get_cache_filepath(video_path)

        if os.path.exists(cache_image_path) and os.path.exists(cache_meta_path):
            try:
                # Dapatkan waktu modifikasi terakhir dari file video asli
                current_mtime = os.path.getmtime(video_path)
                
                # Baca waktu modifikasi yang tersimpan di file meta
                with open(cache_meta_path, 'r') as f:
                    cached_mtime_str = f.read()
                
                # Bandingkan apakah thumbnail masih valid
                if f"{current_mtime:.6f}" == cached_mtime_str:
                    pixmap = QPixmap(cache_image_path)
                    if not pixmap.isNull():
                        return pixmap
            except (IOError, ValueError, Exception) as e:
                print(f"Error reading from cache for {video_path}: {e}")
                # Jika ada error, hapus file cache yang mungkin rusak
                if os.path.exists(cache_image_path): os.remove(cache_image_path)
                if os.path.exists(cache_meta_path): os.remove(cache_meta_path)
        
        return None

    def set_thumbnail(self, video_path: str, pixmap: QPixmap):
        """Saves a thumbnail pixmap to the cache as a .jpg file and stores metadata."""
        if pixmap.isNull() or not os.path.exists(video_path):
            return

        cache_image_path, cache_meta_path = self._get_cache_filepath(video_path)
        
        try:
            # Simpan gambar thumbnail sebagai file .jpg
            pixmap.save(cache_image_path, "JPG", 90) # Kualitas 90

            # Dapatkan dan simpan waktu modifikasi terakhir file video
            current_mtime = os.path.getmtime(video_path)
            with open(cache_meta_path, 'w') as f:
                f.write(f"{current_mtime:.6f}")

        except (IOError, Exception) as e:
            print(f"Error caching thumbnail for {video_path}: {e}")

    def close(self):
        """No operation needed for file-based cache, but kept for interface consistency."""
        pass

    def get_cache_dir_path(self) -> str:
        """Returns the full path to the cache directory."""
        return self.cache_dir

    def clear_cache(self):
        """Deletes the entire cache directory and re-initializes it."""
        try:
            if os.path.isdir(self.cache_dir):
                shutil.rmtree(self.cache_dir)
                print("Thumbnail cache directory deleted.")
            self._initialize_cache_dir()
        except OSError as e:
            print(f"Error deleting cache directory: {e}")
        except Exception as e:
            print(f"Error re-initializing cache: {e}")

# -- Manajer Cache Global (akan diinisialisasi di MainWindow) --
thumbnail_cache_manager = None

# -- Fungsi Helper untuk Thumbnail (dengan Caching) --
def generate_thumbnail(video_path: str, size: QSize = QSize(220, 124)) -> QPixmap:
    # Coba ambil dari cache terlebih dahulu
    if thumbnail_cache_manager:
        cached_pixmap = thumbnail_cache_manager.get_thumbnail(video_path)
        if cached_pixmap:
            # Sesuaikan ukuran pixmap dari cache ke ukuran yang diminta
            return cached_pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)

    # Jika tidak ada di cache atau sudah usang, generate baru
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened(): return QPixmap()
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

            # Simpan versi dasar (standar) ke cache
            if thumbnail_cache_manager:
                base_pixmap = pixmap.scaled(QSize(220, 124), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                thumbnail_cache_manager.set_thumbnail(video_path, base_pixmap)

            # Kembalikan pixmap dengan ukuran yang diminta
            return pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    except Exception as e:
        print(f"Error generating thumbnail for {video_path}: {e}")
    return QPixmap()


# -- Widget untuk Thumbnail Video Tunggal --
class VideoThumbnailWidget(QFrame):
    def __init__(self, video_path: str, main_window, parent=None):
        super().__init__(parent)
        self.video_path = video_path
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
            QLabel { color: #ecf0f1; }
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
        self.title_label.setStyleSheet("border: none;")
        layout.addWidget(self.thumbnail_label)
        layout.addWidget(self.title_label)

    def open_player(self):
        if not self.video_path:
            QMessageBox.warning(self, "Tidak Ada Video", "Path video tidak valid.")
            return
        self.main_window.play_video(self.video_path)
        
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_player()
        super().mouseDoubleClickEvent(event)
    
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        open_action = QAction("Play Video", self, triggered=self.open_player)
        info_action = QAction("Video Info", self, triggered=self.show_file_info)
        remove_action = QAction("Remove from list", self, triggered=self.deleteLater)
        delete_action = QAction("Delete Video", self, triggered=self.delete_file)
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
                self.main_window.start_video_scan()
            except OSError as e:
                QMessageBox.critical(self, "Error", f"Gagal menghapus file: {e}")

# -- [BARU] Widget untuk Thumbnail Folder --
class FolderThumbnailWidget(QFrame):
    def __init__(self, folder_path: str, video_list: list, main_window, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        self.video_list = video_list
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
            QLabel { color: #ecf0f1; }
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)

        thumbnail_container = QWidget()
        thumbnail_container.setFixedSize(210, 118)
        thumbnail_container.setStyleSheet("border-radius: 5px; background-color: #232d38;")
        
        grid_layout = QGridLayout(thumbnail_container)
        grid_layout.setContentsMargins(2, 2, 2, 2)
        grid_layout.setSpacing(2)

        videos_to_preview = self.video_list[:4]
        positions = [(0, 0), (0, 1), (1, 0), (1, 1)]
        
        for i, video_path in enumerate(videos_to_preview):
            thumb_label = QLabel()
            pixmap = generate_thumbnail(video_path, QSize(103, 57)) 
            if not pixmap.isNull():
                thumb_label.setPixmap(pixmap)
            else:
                thumb_label.setText("Gagal")
            thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid_layout.addWidget(thumb_label, positions[i][0], positions[i][1])

        folder_name = os.path.basename(self.folder_path)
        item_count = len(self.video_list)
        self.title_label = QLabel(f"{folder_name}\n({item_count} item)")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("border: none;")

        main_layout.addWidget(thumbnail_container)
        main_layout.addWidget(self.title_label)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.main_window.show_folder_contents(self.folder_path)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        open_action = QAction("Open Folder Contents", self, triggered=lambda: self.main_window.show_folder_contents(self.folder_path))
        menu.addAction(open_action)
        menu.addSeparator()
        remove_action = QAction("Remove Folder", self, triggered=lambda: self.main_window.remove_folder(self.folder_path))
        menu.addAction(remove_action)
        menu.exec(event.globalPos())

# -- Dialog Manajemen Folder --
class ManageFoldersDialog(QDialog):
    def __init__(self, folders, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Video Folder")
        self.setMinimumSize(450, 350)
        icon_path = "player.ico"
        if hasattr(sys, "_MEIPASS"): icon_path = os.path.join(sys._MEIPASS, icon_path)
        if os.path.exists(icon_path): self.setWindowIcon(QIcon(icon_path))
        self.folders = folders
        layout = QVBoxLayout(self)

        cache_group_box = QFrame()
        cache_layout = QHBoxLayout(cache_group_box)
        self.cache_size_label = QLabel("Cache Size: ...")
        reset_cache_button = QPushButton("Reset Thumbnail Cache")
        reset_cache_button.clicked.connect(self.reset_thumbnail_cache)
        cache_layout.addWidget(self.cache_size_label)
        cache_layout.addStretch()
        cache_layout.addWidget(reset_cache_button)
        layout.addWidget(cache_group_box)
        self.update_cache_size_label()

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                color: #ecf0f1; background-color: #1e272e; border: 1px solid #4a6375;
                border-radius: 5px; padding: 5px;
            }
            QListWidget::item:hover { background-color: #34495e; }
            QListWidget::item:selected { background-color: #3498db; color: white; }
        """)
        self.list_widget.addItems(self.folders)
        layout.addWidget(self.list_widget)

        folder_buttons_layout = QHBoxLayout()
        remove_button = QPushButton("Remove Selected Folder")
        remove_button.clicked.connect(self.remove_selected_folder)
        clear_all_button = QPushButton("Clear All Folders")
        clear_all_button.clicked.connect(self.clear_all_folders)
        folder_buttons_layout.addWidget(remove_button)
        folder_buttons_layout.addWidget(clear_all_button)
        layout.addLayout(folder_buttons_layout)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
    def remove_selected_folder(self):
        selected_items = self.list_widget.selectedItems()
        if not selected_items: return
        folder_to_remove = selected_items[0].text()
        self.folders.remove(folder_to_remove)
        self.list_widget.takeItem(self.list_widget.row(selected_items[0]))
        if self.parent() and hasattr(self.parent(), 'folders_updated'):
            self.parent().folders_updated(self.folders)

    # /** MODIFIKASI **/ Metode ini diubah untuk menghitung ukuran direktori cache
    def update_cache_size_label(self):
        global thumbnail_cache_manager
        if not thumbnail_cache_manager:
            self.cache_size_label.setText("Cache not available.")
            return
        
        cache_dir = thumbnail_cache_manager.get_cache_dir_path()
        total_size = 0
        if os.path.isdir(cache_dir):
            try:
                for dirpath, _, filenames in os.walk(cache_dir):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        if not os.path.islink(fp):
                            total_size += os.path.getsize(fp)
            except OSError as e:
                self.cache_size_label.setText("Error calculating size.")
                print(f"Error calculating cache size: {e}")
                return

        size_mb = total_size / (1024 * 1024)
        self.cache_size_label.setText(f"Ukuran Cache: {size_mb:.2f} MB")

    def reset_thumbnail_cache(self):
        global thumbnail_cache_manager
        confirm = QMessageBox.question(
            self, "Konfirmasi Reset",
            "Yakin ingin menghapus dan mereset seluruh cache thumbnail?\n"
            "Thumbnail akan dibuat ulang saat pemindaian berikutnya.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel
        )
        if confirm == QMessageBox.StandardButton.Yes and thumbnail_cache_manager:
            thumbnail_cache_manager.clear_cache()
            QMessageBox.information(self, "Sukses", "Cache thumbnail telah direset.")
            self.update_cache_size_label()
            if self.parent() and hasattr(self.parent(), 'start_video_scan'):
                QTimer.singleShot(100, self.parent().start_video_scan)

    def clear_all_folders(self):
        confirm = QMessageBox.question(
            self, "Konfirmasi Hapus Semua",
            "Yakin ingin menghapus SEMUA folder dari daftar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.folders.clear()
            self.list_widget.clear()
            if self.parent() and hasattr(self.parent(), 'folders_updated'):
                self.parent().folders_updated(self.folders)

# -- Worker untuk scanning video di thread terpisah --
class VideoScannerWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict, list)

    def __init__(self, folders_to_scan):
        super().__init__()
        self.folders_to_scan = folders_to_scan

    @pyqtSlot()
    def run(self):
        grouped_videos = {}
        all_video_files = []
        total_folders = len(self.folders_to_scan)

        for i, folder in enumerate(self.folders_to_scan):
            self.progress.emit(i, total_folders, os.path.basename(folder))
            try:
                if os.path.exists(folder) and os.path.isdir(folder):
                    videos_in_folder = []
                    for root, _, files in os.walk(folder):
                        for file in files:
                            if file.lower().endswith(VIDEO_EXTENSIONS):
                                file_path = os.path.join(root, file)
                                videos_in_folder.append(file_path)
                    
                    if videos_in_folder:
                        grouped_videos[folder] = videos_in_folder
                        all_video_files.extend(videos_in_folder)
                else:
                    print(f"Peringatan: Folder tidak ditemukan atau tidak valid: {folder}")
            except Exception as e:
                print(f"Error reading folder {folder}: {e}")
        
        self.finished.emit(grouped_videos, all_video_files)


# -- FRAMELESS MAIN WINDOW --
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        global thumbnail_cache_manager
        if thumbnail_cache_manager is None:
            thumbnail_cache_manager = ThumbnailCache()

        self.drag_pos = QPoint()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Macan Movie - Koleksi Video")
        self.setGeometry(100, 100, 1200, 700)
        icon_path = "player.ico"
        if hasattr(sys, "_MEIPASS"): icon_path = os.path.join(sys._MEIPASS, icon_path)
        if os.path.exists(icon_path): self.setWindowIcon(QIcon(icon_path))
        self.settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
        
        self.video_folders = []
        self.video_files = [] 
        self.grouped_videos = {} 

        self.current_view = "all"
        self.selected_folder_path = None

        self.setup_styles()
        self._setup_ui()
        self.load_settings()
        
        QTimer.singleShot(500, self.start_video_scan)

    def setup_styles(self):
        self.setStyleSheet("""
            #mainContainer {
                background-color: #1e272e; border: 1px solid #4a6375; border-radius: 15px;
            }
            QScrollArea { border: none; }
            QLabel { color: #ecf0f1; }
            QComboBox { 
                background-color: #2c3e50; border: 1px solid #4a6375;
                padding: 4px; border-radius: 4px; 
            }
            QComboBox::drop-down { border: none; }
            QComboBox::down-arrow { image: url(none); }
            #titleLabel { font-size: 16px; font-weight: bold; }
            #sectionTitle { 
                font-size: 14pt; 
                font-weight: bold; 
                color: #bdc3c7; 
                padding-top: 10px; 
                padding-bottom: 5px;
            }
        """)

    def _setup_ui(self):
        self.container = QWidget(self)
        self.container.setObjectName("mainContainer")
        self.setCentralWidget(self.container)
        
        main_layout = QVBoxLayout(self.container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.stacked_widget = QStackedWidget()
        main_layout.addWidget(self.stacked_widget)

        collection_page = QWidget()
        collection_layout = QVBoxLayout(collection_page)
        collection_layout.setContentsMargins(1, 1, 1, 1)
        collection_layout.setSpacing(0)

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
        
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(15, 10, 15, 15)

        self.button_layout = QHBoxLayout()
        self.back_button = QPushButton("❮ Kembali")
        self.back_button.clicked.connect(self.show_all_folders_view)
        self.back_button.setVisible(False)
        
        add_folder_button = QPushButton("Tambah Folder")
        add_folder_button.setIcon(IconManager.get_icon("folder_add"))
        add_folder_button.clicked.connect(self.add_folder)
        manage_folder_button = QPushButton("Kelola Folder")
        manage_folder_button.setIcon(IconManager.get_icon("folder_manage"))
        manage_folder_button.clicked.connect(self.manage_folders)
        about_button = QPushButton("Tentang")
        about_button.clicked.connect(self.show_about_dialog)
        
        sort_label = QLabel("Urutkan:")
        self.sort_combo = QComboBox()
        self.sort_combo.addItems([
            "Nama (A-Z)", "Nama (Z-A)",
            "Tanggal (Terbaru)", "Tanggal (Terlama)"
        ])
        self.sort_combo.currentIndexChanged.connect(self.sort_and_reflow)
        self.video_count_label = QLabel("Total Video: 0")
        self.video_count_label.setStyleSheet("color: #bdc3c7;")

        self.button_layout.addWidget(self.back_button)
        self.button_layout.addWidget(add_folder_button)
        self.button_layout.addWidget(manage_folder_button)
        self.button_layout.addWidget(about_button)
        self.button_layout.addStretch()
        self.button_layout.addWidget(sort_label)
        self.button_layout.addWidget(self.sort_combo)
        self.button_layout.addSpacing(20)
        self.button_layout.addWidget(self.video_count_label)
        layout.addLayout(self.button_layout)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.main_content_container = QWidget()
        self.main_content_layout = QVBoxLayout(self.main_content_container)
        self.main_content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.folders_section_label = QLabel("Folders")
        self.folders_section_label.setObjectName("sectionTitle")
        self.folders_grid_container = QWidget()
        self.folders_grid_layout = QGridLayout(self.folders_grid_container)
        self.folders_grid_layout.setSpacing(15)

        self.videos_section_label = QLabel("All Videos")
        self.videos_section_label.setObjectName("sectionTitle")
        self.videos_grid_container = QWidget()
        self.videos_grid_layout = QGridLayout(self.videos_grid_container)
        self.videos_grid_layout.setSpacing(15)

        self.main_content_layout.addWidget(self.folders_section_label)
        self.main_content_layout.addWidget(self.folders_grid_container)
        self.main_content_layout.addWidget(self.videos_section_label)
        self.main_content_layout.addWidget(self.videos_grid_container)

        self.scroll_area.setWidget(self.main_content_container)
        layout.addWidget(self.scroll_area)
        
        collection_layout.addWidget(self.title_bar)
        collection_layout.addWidget(content_widget)

        self.player_page = ModernVideoPlayer()
        self.player_page.back_requested.connect(self.show_collection_view)
        self.player_page.fullscreen_requested.connect(self.toggle_main_window_fullscreen)

        self.stacked_widget.addWidget(collection_page)
        self.stacked_widget.addWidget(self.player_page)


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
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < self.title_bar.height() and self.stacked_widget.currentIndex() == 0:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            
    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton and not self.drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_pos = QPoint()

    # /** MODIFIKASI BARU **/ Logika diubah untuk auto-play next
    def play_video(self, file_path: str):
        # Tentukan daftar video aktif berdasarkan tampilan saat ini
        if self.current_view == "folder" and self.selected_folder_path:
            active_video_list = self.grouped_videos.get(self.selected_folder_path, [])
        else:
            active_video_list = self.video_files

        # Siapkan playlist untuk pemutar
        if file_path in active_video_list:
            current_index = active_video_list.index(file_path)
            playlist = [{'path': p, 'title': os.path.basename(p)} for p in active_video_list]
            
            # Atur playlist dan item yang dipilih di widget playlist pemutar
            self.player_page.playlist_widget.set_playlist_data(playlist)
            self.player_page.playlist_widget._update_selection(current_index)
            self.player_page._update_playlist_nav_buttons()
        
        # Mulai putar video
        self.player_page.open_file_from_path(file_path)
        self.stacked_widget.setCurrentIndex(1)
        if self.isFullScreen():
            self.title_bar.hide()

    def show_collection_view(self):
        self.player_page._stop_video()
        self.stacked_widget.setCurrentIndex(0)
        self.setWindowTitle("Macan Movie - Koleksi Video")
        self.title_bar.show()

    def toggle_main_window_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.player_page.set_fullscreen_state(False)
            self.title_bar.show()
        else:
            self.showFullScreen()
            self.player_page.set_fullscreen_state(True)
            if self.stacked_widget.currentIndex() == 1:
                 self.title_bar.hide()


    def add_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Pilih Folder Video")
        if folder_path and folder_path not in self.video_folders:
            self.video_folders.append(folder_path)
            self.save_settings() # /** MODIFIKASI **/ Gunakan save_settings
            self.start_video_scan()
            
    def manage_folders(self):
        dialog = ManageFoldersDialog(self.video_folders.copy(), self)
        dialog.exec()
        
    def remove_folder(self, folder_path):
        if folder_path in self.video_folders:
            self.video_folders.remove(folder_path)
            self.save_settings() # /** MODIFIKASI **/ Gunakan save_settings
            self.start_video_scan()

    def show_about_dialog(self):
        about_title = "Macan Movie — About"
        about_text = """Macan Movie is a modern video player developed as part of the Macan Angkasa ecosystem <b>Key Features:</b>

                        Modern and intuitive interface based on PyQt6. 

                        Thumbnail preview support using OpenCV. 

                        Subtitles (SRT) with smooth and responsive overlays. 

                        Playlist management with drag & drop and auto-save. 

                        Mini Player mode for a flexible viewing experience. 

                        Theme system (Dark, Light, Neon Blue) to suit user preferences. 

                        Easily manageable watch history. 

                        Support for online video streaming via yt-dlp. 

                        Macan Movie is designed with the philosophy: 

                        "Performance, Elegance, and Security." 

                        As part of the Macan Angkasa Software Ecosystem, Macan Movie aims to set a new standard in multimedia software. 

                        <b></b>© 2025 Danx Exodus — All rights reserved."""
        QMessageBox.about(self, about_title, about_text)

    def folders_updated(self, new_folders):
        self.video_folders = new_folders
        self.save_settings() # /** MODIFIKASI **/ Gunakan save_settings
        self.start_video_scan()
        
    # /** MODIFIKASI **/ Metode save_folders diganti dengan save_settings
    def save_settings(self):
        self.settings.setValue(SETTINGS_FOLDERS_KEY, self.video_folders)
        self.settings.setValue(SETTINGS_GEOMETRY_KEY, self.saveGeometry())
        self.settings.setValue(SETTINGS_WINDOW_STATE_KEY, self.isMaximized())
        self.settings.setValue(SETTINGS_SORT_KEY, self.sort_combo.currentIndex())

    # /** MODIFIKASI **/ Metode ini diubah untuk memuat metode urut
    def load_settings(self):
        self.video_folders = self.settings.value(SETTINGS_FOLDERS_KEY, defaultValue=[], type=list)
        
        # Muat metode urut yang disimpan
        sort_index = self.settings.value(SETTINGS_SORT_KEY, defaultValue=0, type=int)
        if 0 <= sort_index < self.sort_combo.count():
            self.sort_combo.setCurrentIndex(sort_index)
        
        geometry = self.settings.value(SETTINGS_GEOMETRY_KEY, defaultValue=None)
        if geometry: self.restoreGeometry(geometry)
        
        if self.settings.value(SETTINGS_WINDOW_STATE_KEY, defaultValue=False, type=bool):
            self.showMaximized()
            self.maximize_button.setIcon(IconManager.get_icon("restore"))


    def clear_layout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def start_video_scan(self):
        self.clear_layout(self.folders_grid_layout)
        self.clear_layout(self.videos_grid_layout)

        if not self.video_folders:
            self.show_message("Video tidak ditemukan.\nKlik 'Tambah Folder' untuk memulai.")
            self.video_count_label.setText("Total Video: 0")
            return

        self.progress_dialog = QProgressDialog("Scanning video folders...", "Cancel", 0, len(self.video_folders), self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setAutoClose(True)
        self.progress_dialog.show()

        self.scanner_thread = QThread()
        self.scanner_worker = VideoScannerWorker(self.video_folders)
        self.scanner_worker.moveToThread(self.scanner_thread)

        self.scanner_thread.started.connect(self.scanner_worker.run)
        self.scanner_worker.finished.connect(self.on_scan_finished)
        self.scanner_worker.progress.connect(self.on_scan_progress)
        self.progress_dialog.canceled.connect(self.scanner_thread.quit)

        self.scanner_thread.start()

    @pyqtSlot(dict, list)
    def on_scan_finished(self, grouped_videos, video_files):
        self.grouped_videos = grouped_videos
        self.video_files = video_files
        self.progress_dialog.close()
        self.scanner_thread.quit()
        self.scanner_thread.wait()
        
        if not self.video_files:
            self.show_message("Tidak ada file video di folder yang ditentukan.")
            self.video_count_label.setText("Total Video: 0")
        else:
            self.sort_and_reflow()

    @pyqtSlot(int, int, str)
    def on_scan_progress(self, current, total, folder_name):
        self.progress_dialog.setValue(current)
        self.progress_dialog.setLabelText(f"Scanning: {folder_name}...")
        QApplication.processEvents()

    def sort_and_reflow(self):
        sort_key = self.sort_combo.currentText()
        
        if "Nama" in sort_key:
            self.video_files.sort(reverse=("(Z-A)" in sort_key))
            for folder in self.grouped_videos:
                self.grouped_videos[folder].sort(reverse=("(Z-A)" in sort_key))
        elif "Tanggal" in sort_key:
            try:
                self.video_files.sort(key=os.path.getmtime, reverse=("(Terbaru)" in sort_key))
                for folder in self.grouped_videos:
                    self.grouped_videos[folder].sort(key=os.path.getmtime, reverse=("(Terbaru)" in sort_key))
            except FileNotFoundError:
                QMessageBox.warning(self, "Sort Error", "File tidak ditemukan saat pengurutan. Harap segarkan folder.")
                return

        self.video_count_label.setText(f"Total Video: {len(self.video_files)}")
        self.reflow_ui()

    def show_message(self, message):
        self.clear_layout(self.folders_grid_layout)
        self.clear_layout(self.videos_grid_layout)
        self.folders_section_label.hide()
        self.videos_section_label.hide()
        
        msg_label = QLabel(message)
        msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_label.setStyleSheet("font-size: 18px; color: #7f8c8d;")
        self.videos_grid_layout.addWidget(msg_label, 0, 0, 1, -1, alignment=Qt.AlignmentFlag.AlignCenter)
        
    def reflow_ui(self):
        self.clear_layout(self.folders_grid_layout)
        self.clear_layout(self.videos_grid_layout)

        cols = max(1, (self.scroll_area.width() - 30) // 240)

        if self.current_view == "all":
            self.back_button.setVisible(False)
            self.folders_section_label.show()
            self.folders_grid_container.show()
            self.videos_section_label.setText("All Videos")
            self.videos_section_label.show()
            self.videos_grid_container.show()

            sorted_folders = sorted(self.grouped_videos.keys())
            for i, folder_path in enumerate(sorted_folders):
                video_list = self.grouped_videos[folder_path]
                row, col = divmod(i, cols)
                thumbnail = FolderThumbnailWidget(folder_path, video_list, self)
                self.folders_grid_layout.addWidget(thumbnail, row, col)

            for i, video_path in enumerate(self.video_files):
                row, col = divmod(i, cols)
                thumbnail = VideoThumbnailWidget(video_path, self)
                self.videos_grid_layout.addWidget(thumbnail, row, col)

        elif self.current_view == "folder" and self.selected_folder_path:
            self.back_button.setVisible(True)
            self.folders_section_label.hide()
            self.folders_grid_container.hide()
            folder_name = os.path.basename(self.selected_folder_path)
            self.videos_section_label.setText(f"Video di '{folder_name}'")
            self.videos_section_label.show()
            self.videos_grid_container.show()
            
            videos_in_selected_folder = self.grouped_videos.get(self.selected_folder_path, [])
            for i, video_path in enumerate(videos_in_selected_folder):
                row, col = divmod(i, cols)
                thumbnail = VideoThumbnailWidget(video_path, self)
                self.videos_grid_layout.addWidget(thumbnail, row, col)

    def show_folder_contents(self, folder_path):
        self.current_view = "folder"
        self.selected_folder_path = folder_path
        self.reflow_ui() 

    def show_all_folders_view(self):
        self.current_view = "all"
        self.selected_folder_path = None
        self.reflow_ui() 
                
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.video_files:
            QTimer.singleShot(100, self.reflow_ui)
        
    def closeEvent(self, event):
        self.save_settings() # /** MODIFIKASI **/ Gunakan save_settings
        if thumbnail_cache_manager:
            thumbnail_cache_manager.close()
        super().closeEvent(event)

# -- Eksekusi Aplikasi --
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet("""
        QWidget {
            font-family: 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', sans-serif;
            color: #ecf0f1;
            font-size: 11pt;
        }
        QPushButton { 
            background-color: #3498db; color: white; border: none; 
            padding: 8px 15px; border-radius: 5px;
        }
        QPushButton:hover { background-color: #2980b9; }
        QPushButton:pressed { background-color: #1f618d; }
        QMenu {
            background-color: #2c3e50; border: 1px solid #4a6375; padding: 5px;
        }
        QMenu::item { padding: 5px 20px; }
        QMenu::item:selected { background-color: #3498db; }
        QMenu::separator {
            height: 1px; background: #4a6375; margin: 5px 0;
        }
        QMessageBox, QDialog { background-color: #2c3e50; }
        QProgressDialog { background-color: #2c3e50; }
    """)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec())