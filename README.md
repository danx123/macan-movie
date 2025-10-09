📺 Macan Movie
Macan Movie is a modern PySide6-based video player with support for playlists, thumbnail previews, subtitles (SRT), themes, and a mini player. This project is part of the Macan Angkasa ecosystem.

---

✨ Key Features
🎬 Modern Video Player UI with PySide6 + QtMultimedia
🎞️ Thumbnail Preview on slider hover (powered by OpenCV)
📜 Subtitle (SRT) Support with transparent overlay text rendering
🎶 Mini Player Mode (small, always-on-top window)
📂 Playlist Management (drag & drop, auto-save to config)
🕘 Watch History with delete/clear all option
🎨 Theme System: Dark, Light, Neon Blue
🔗 YouTube / Online Video Support via yt-dlp
💾 Thumbnail Cache using SQLite for fast loading
📺 TV Online

---
📸 Screenshots
<img width="1365" height="767" alt="image" src="https://github.com/user-attachments/assets/40ab3546-3fe2-4fe9-9ac5-7c1ac3b58260" />

---
🎬 Macan Movie v3.5.4
🔥 Changelog
- Update framework
- Rebuild with Nuitka for better performance

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
