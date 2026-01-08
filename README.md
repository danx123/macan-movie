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
<img width="1365" height="767" alt="Screenshot 2025-12-29 233229" src="https://github.com/user-attachments/assets/501abd29-128e-4b08-bf2a-c63d5ae28958" />
<img width="1365" height="767" alt="Screenshot 2025-12-29 235408" src="https://github.com/user-attachments/assets/19ad09c2-a8bd-47b7-a2d2-2997dc2d42cf" />


---
🎬 Macan Movie v5.7.0
Macan Movie Pro v5.7.0 introduces a Hybrid Player Engine architecture, designed to deliver optimal performance across both local media playback and online streaming scenarios.

What’s New

Hybrid Player Engine

Local media playback is now powered by QMediaPlayer (FFmpeg backend) for efficient decoding, low latency, and native system integration.

Online TV streaming is handled by libVLC, ensuring superior compatibility with live streams, adaptive formats, and unstable network conditions.


Dedicated TV Online Player

The TV Online player architecture is adapted from Macan Vision, bringing proven stability, refined buffering behavior, and resilient stream handling.


Engine Isolation & Optimization

Each playback engine operates within its intended domain, preventing cross-interference and improving overall reliability.


Improved Playback Consistency

Seamless switching between local playback and online TV without affecting application stability or performance.



Summary
This release transforms Macan Movie Pro into a dual-engine media platform, combining native efficiency and streaming robustness within a single, cohesive player architecture.
---

🛠️ Installation
Make sure Python 3.9+ is installed. Then run:
git clone https://github.com/danx123/macan-movie.git
cd macan-video-player
pip install -r requirements.txt

Requirements
PySide6
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


