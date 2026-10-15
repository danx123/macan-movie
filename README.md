# 📺 Macan Movie

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white">
  <img alt="PySide6" src="https://img.shields.io/badge/PySide6-Qt%20for%20Python-41CD52?logo=qt&logoColor=white">
  <img alt="Platform" src="https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows&logoColor=white">
  <img alt="Playback engines" src="https://img.shields.io/badge/Engines-Qt%20%7C%20Rust%20%7C%20VLC-8A2BE2">
  <img alt="Equalizer" src="https://img.shields.io/badge/Equalizer-10--band-orange">
  <img alt="Macan Angkasa" src="https://img.shields.io/badge/Part%20of-Macan%20Angkasa-red">
</p>

<p align="center">
  <a href="https://github.com/danx123/macan-movie/releases"><img alt="Total downloads" src="https://img.shields.io/github/downloads/danx123/macan-movie/total?logo=github&label=Downloads"></a>
</p>

**Macan Movie** is a modern PySide6-based video player for Windows with a choice of three playback engines, a 10-band equalizer, playlists, thumbnail previews, subtitles, TV online and streaming. This project is part of the **Macan Angkasa** ecosystem.

---

## ✨ Key Features

### Playback
- 🎬 **Modern video player UI** built with PySide6 + QtMultimedia
- ⚙️ **Selectable playback engine:** Qt Multimedia (default), native Rust `media_engine` (PyO3), or VLC (libVLC)
- ⏩ **Playback speed** control (0.5x – 2x)
- 🎨 **Color adjustment** dialog for video display
- 🖥️ **Fullscreen mode** with a dedicated TV fullscreen overlay

### 🎚️ 10-band Equalizer
- 10 bands (60 Hz – 16 kHz), ±20 dB per band, plus a preamp
- Built-in presets: Flat, Rock, Pop, Jazz, Classical, Bass Boost, Treble Boost, Vocal, Cinematic, Electronic, Acoustic
- Save and delete your own custom presets
- Runs natively inside libVLC in real time, with no audio processing in Python
- Settings are stored for every engine and applied as soon as the VLC engine is selected
- Software DSP is pure numpy (FFT-based FIR), no scipy required

### Library
- 📂 **Playlist management** (drag & drop, auto-saved to config)
- 🕘 **Watch history** with delete / clear all option
- 🎞️ **Thumbnail preview** on slider hover (powered by OpenCV)
- 💾 **Thumbnail cache** using SQLite for fast loading
- 🗂️ **Built-in file explorer** and **Recycle Bin**
- 🔐 **Macan Vault**, an encrypted file vault

### Subtitles
- 📜 **SRT subtitle support** with transparent overlay rendering
- 🧩 **Embedded MKV subtitle extraction**
- 🛠️ Subtitle settings panel

### Online
- 📺 **TV Online**
- 🌐 **Streaming Media**
- 🔗 **YouTube / online video** support via yt-dlp

### Windows integration
- 🔒 **System Media Transport Controls (SMTC):** media keys and lock screen controls
- 🧷 **Taskbar thumbnail buttons**
- 🪟 **Snap layout overlay**

---

## 📸 Screenshots

<img width="1365" height="767" alt="image" src="https://github.com/user-attachments/assets/e5555797-edb8-4027-ae2a-2e8bb9784b2f" />

<img width="1363" height="739" alt="Screenshot 2026-04-28 195544" src="https://github.com/user-attachments/assets/2c454968-0bd7-4345-a338-ca399da7dd82" />
<img width="1365" height="767" alt="Screenshot 2026-02-16 175144" src="https://github.com/user-attachments/assets/a22b3402-7f45-4d6a-988b-66575bfa72c6" />
<img width="1365" height="767" alt="Screenshot 2025-12-29 235408" src="https://github.com/user-attachments/assets/19ad09c2-a8bd-47b7-a2d2-2997dc2d42cf" />

---

## 🛠️ Installation

Make sure Python 3.9+ is installed. Then run:

```bash
git clone https://github.com/danx123/macan-movie.git
cd macan-movie
pip install -r requirements.txt
```

### Requirements

| Package | Purpose | Required |
|---|---|---|
| `PySide6` | UI and QtMultimedia playback | ✅ |
| `opencv-python-headless` | Thumbnail previews | ✅ |
| `numpy` | Image conversion and equalizer DSP | ✅ |
| `requests` | TV Online | Optional |
| `qtawesome` | Icons | Optional |
| `yt-dlp` | Streaming from URL | Optional |
| `python-vlc` + VLC (libVLC) | VLC engine, TV Online, native equalizer | Optional |
| `winsdk` | Windows media controls (SMTC) | Optional |
| `media_engine` (native module) | Rust playback engine | Optional |

> The equalizer only changes the audible output on the **VLC engine**. On the Qt and Rust engines your settings are saved and applied once you switch to VLC.

---

## 🎮 Shortcuts & Controls

| Key | Action |
|---|---|
| `Space` | Play / Pause |
| `←` / `→` | Skip backward / forward 10 seconds |
| `F11` / `Esc` | Toggle fullscreen |
| Double-click thumbnail | Play video |

---

## 🐯 About

Macan Movie is part of the **Macan Angkasa** suite of Windows desktop applications.
