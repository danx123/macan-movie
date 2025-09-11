📺 Macan Movie
Macan Movie is a modern PyQt6-based video player with support for playlists, thumbnail previews, subtitles (SRT), themes, and a mini player. This project is part of the Macan Angkasa ecosystem.

---

✨ Key Features
🎬 Modern Video Player UI with PyQt6 + QtMultimedia
🎞️ Thumbnail Preview on slider hover (powered by OpenCV)
📜 Subtitle (SRT) Support with transparent overlay text rendering
🎶 Mini Player Mode (small, always-on-top window)
📂 Playlist Management (drag & drop, auto-save to config)
🕘 Watch History with delete/clear all option
🎨 Theme System: Dark, Light, Neon Blue
🔗 YouTube / Online Video Support via yt-dlp
💾 Thumbnail Cache using SQLite for fast loading

---
📸 Screenshots
<img width="1365" height="767" alt="image" src="https://github.com/user-attachments/assets/0dbcd053-7977-4606-9ab4-25f0a30782e7" />


---
🎬 Macan Movie v3.0.0
🔥 Changelog
⚡ Optimasi Cache → metode cache diubah dari SQLite3 menjadi direct write-to-disk → performa lebih cepat dan ringan.
🔎 Search Function → cari video dengan cepat di playlist / folder.
⏭️ Auto Next Play → otomatis lanjut ke video berikutnya.
📂 Persistent Sorting → metode pengurutan file/folder tersimpan otomatis.
🏷️ Now Playing Label → QLabel di player menampilkan nama video yang sedang diputar.
🎶 Smart Playlist → playlist cerdas berdasarkan hasil pencarian.

---

🛠️ Installation
Make sure Python 3.9+ is installed. Then run:
git clone https://github.com/danx123/macan-movie.git
cd macan-video-player
pip install -r requirements.txt

Requirements
PyQt6
opencv-python-headless
numpy
qtawesome (optional for icons)
yt-dlp (optional for streaming from URL)

---

🎮 Shortcuts & Controls
Space → Play / Pause
← / → → Skip backward / forward 10 seconds
F11 / Esc → Toggle fullscreen
Double-click thumbnail → Play video

---

📌 Note
Some features (icons, video streaming) require qtawesome & yt-dlp.
Configurations & playlists are automatically saved in player_config.json.
