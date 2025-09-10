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
<img width="1365" height="720" alt="Screenshot 2025-09-10 074602" src="https://github.com/user-attachments/assets/5ba22738-8c0a-4419-a914-ba8b3e0c36b4" />

---
📝 Changelog:
Performance Optimization & Progress Bar:
A new worker thread (VideoScannerWorker) now handles the heavy lifting of scanning your video folders. This completely prevents the main application window from freezing on startup, even with thousands of videos.
While the scan is in progress, a Progress Dialog is displayed, showing which folder is currently being scanned and the overall progress. This provides crucial feedback to the user.
The video scanning process now starts shortly after the main window appears (using QTimer.singleShot), improving the perceived startup speed.
Toolbar Enhancements (Sorting & Video Count):
	A "Sort by" dropdown menu has been added to the toolbar. You can now sort all videos 		by:
	Name (A-Z or Z-A)
	Date Modified (Newest or Oldest)
A "Total Videos" label has been added to the right side of the toolbar, giving you an immediate count of all videos found across your folders.

Folder Context Menu:
You can now right-click on a folder thumbnail to bring up a context menu.
This menu includes a "Remove Folder" option, allowing you to easily un-list a folder from the application without having to go into the "Manage Folders" dialog

In the "Manage Folders" dialog:

- Added a "Clear All Folders" button to remove all folders from the list.

- Added a "Reset Thumbnail Cache" button to clear the stored thumbnail cache.

- Displays the current thumbnail cache file size so you know how much space it's taking up.

In the Video Player:

The video player will now be integrated directly into the main window, replacing the video collection view instead of opening a new window.

Added a "Back" button (left arrow icon) to the video player controls. When clicked, the video will pause and return you to the video collection view.

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
