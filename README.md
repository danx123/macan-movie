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
<img width="1269" height="683" alt="Screenshot 2025-11-10 072946" src="https://github.com/user-attachments/assets/25018c85-8cd1-4754-a0fa-d8c6e2cbf692" />
<img width="1271" height="686" alt="Screenshot 2025-11-10 073040" src="https://github.com/user-attachments/assets/290c0782-4b81-416c-aeb6-f5b182f02ee1" />




---
🎬 Macan Movie v4.0.0
🚀 Performance & Responsiveness
Asynchronous Thumbnail Generation: This is the most significant change. The synchronous generate_thumbnail function has been replaced by a multithreaded system using QThreadPool and QRunnable (ThumbnailWorker).
Non-Blocking UI: Thumbnails for the collection (VideoThumbnailWidget) and folder previews (FolderThumbnailWidget) are now generated in the background. This prevents the user interface from freezing or stuttering when loading or scrolling through large video libraries.
Lazy Loading: Widgets now display a "Loading..." placeholder text and are updated with the thumbnail image via a Qt signal (@Slot) once the background worker completes its task.
🌎 Internationalization (i18n)
UI Translation: A comprehensive pass was made to translate the application's user interface from Indonesian (Bahasa Indonesia) to English.
Affected Components: This includes tooltips, button labels, placeholders, dialog titles, and message box text in ModernVideoPlayer, MainWindow, OnlineTVDialog, and ManageFoldersDialog.
🎨 UI & Style Refinements
QComboBox Style Fix: Corrected a UI defect where QComboBox dropdown menus (e.g., "Sort by" and "Playlist Source") did not inherit the application's dark theme. Explicit styling was added to their QAbstractItemView for a consistent look and feel.
Icon & Branding Update:
The application icon reference was updated from player.ico to macan_movie.ico.
The "About" dialog title and text were updated from "Macan Movie" to "Macan Movie Pro".
🧹 Code Refactoring
Sorting Logic: The sorting logic in MainWindow.sort_and_reflow was simplified. It now defaults to sorting by name and explicitly checks for the date sorting option, improving code clarity.
Import Optimization: Added QRunnable and QThreadPool to Qt imports to support the new asynchronous thumbnail system.
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


