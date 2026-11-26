# 📌 PinFetch - Universal Pinterest Video & Image Downloader

A full-featured, responsive, and high-performance Pinterest video and image downloader web application designed and optimized for **all forms of hardware** (smartphones, tablets, laptops, and desktop computers).

---

## 🌟 Key Features

- 📱 **Cross-Hardware & Mobile-First Compatibility**:
  - Touch-optimized layout with 48px+ tap targets.
  - Fluid responsive grid (`viewport-fit=cover`, safe-area-insets for notched iPhones and iPads).
  - Progressive Web App (PWA) manifest & Service Worker — installable to home screen on iOS Safari and Android Chrome.
  - Dedicated step-by-step guides for **iPhone/iPad**, **Android**, and **PC/Mac**.
- 🎬 **Multi-Resolution Video Downloads (.MP4 Guaranteed)**:
  - Automatically extracts all available qualities: **1080p Full HD**, **720p HD**, **480p SD**, and **360p**.
  - All videos are guaranteed to download in `.mp4` format. HLS streams (`.m3u8`) are dynamically remuxed to standard `.mp4` files using `ffmpeg`.
  - Direct MP4 streaming proxy with `Content-Disposition: attachment` headers, ensuring mobile browsers (Safari / Chrome) trigger native downloads rather than just playing the video in a tab.
  - HTTP Range Request (`206 Partial Content`) support for resume and fast seeking.
- 🖼 **Pinterest Image & Carousel Downloader**:
  - Automatically detects single image pins and multi-image carousel pins.
  - Downloads **Original Max-Resolution Uncompressed Images** directly from `i.pinimg.com/originals/...`.
  - Multiple size options: **Original**, **2K Ultra HD (1200px)**, **Full HD (736px)**, and **Standard HD (474px)**.
  - **Multi-Image Carousel Gallery**: Interactive photo grid displaying every picture in a carousel pin with individual 1-click download buttons.
- 🎵 **Audio Extractor**:
  - Converts and extracts video audio directly into **MP3** format in real-time.
- 📺 **In-Page Media Player & Image Lightbox**:
  - Preview before downloading with HTML5 video player, custom controls, and poster artwork.
- 📋 **One-Tap Clipboard Paste**:
  - Instantly pastes links from clipboard with 1 tap.
- 🕒 **Local History**:
  - Saves your recent downloads on device via `localStorage` with 1-click re-download.
- 🌙 **Dark & Light Mode**:
  - Automatically matches system preference with manual toggle and persistence.
- ⚡ **Multi-Strategy Extractor**:
  - Combines `yt-dlp`, Pinterest internal Unauth API, and HTML fallback. Supports `pin.it` short URLs, regional subdomains (`in.pinterest.com`, etc.), and direct CDN links.

---

## 🚀 Quick Start

### 1. Requirements
- Python 3.10+
- `ffmpeg` (for real-time audio MP3 extraction)
- `pip install -r requirements.txt`

### 2. Running the Application
From the project folder:
```bash
python app.py
```
Or simply double-click `run.bat` on Windows!

The server will start at:
- **Local Browser:** `http://localhost:5000`
- **Network (Mobile / Tablet on Wi-Fi):** `http://<your-computer-ip>:5000`

---

## 📱 Hardware & Device Compatibility Guide

### 🍏 iPhone & iPad (iOS / iPadOS Safari)
1. In the Pinterest app, tap **Share** &rarr; **Copy Link**.
2. Open Safari and visit PinFetch.
3. Tap **Paste** &rarr; **Download**.
4. Tap **Download Best Quality MP4**.
5. When Safari prompts, tap **Download**. Tap the download arrow in Safari's address bar &rarr; select the video &rarr; tap **Share** &rarr; **Save Video** to save directly into your Photos Camera Roll.

### 🤖 Android Phones & Tablets (Chrome / Samsung Internet)
1. Copy the pin link from Pinterest.
2. Paste into PinFetch and tap **Download**.
3. Tap **Download Best Quality MP4** — the file will download straight to your **Downloads** folder and show up in your Gallery.
4. *Tip:* Tap browser menu &rarr; **Add to Home screen** to use PinFetch as a full-screen app!

### 💻 PC, Mac & Laptop (Chrome, Edge, Safari, Firefox)
1. Copy URL from browser address bar.
2. Paste into PinFetch and choose your desired resolution (1080p, 720p, etc.).
3. Instant 1-click download directly to your computer.

---

## 📂 Project Structure

```
pinterest-downloader/
├── app.py                     # Flask web server & streaming download proxy
├── extractor.py               # Multi-strategy Pinterest extractor
├── requirements.txt           # Dependencies
├── run.bat                    # Windows 1-click launcher
├── README.md                  # Documentation
├── templates/
│   └── index.html             # Responsive semantic UI with SEO & iOS meta
└── static/
    ├── css/
    │   └── style.css          # Mobile-first stylesheet (dark/light themes)
    ├── js/
    │   ├── app.js             # Interactive client logic & download triggers
    │   └── pwa.js             # PWA installation & service worker registration
    ├── sw.js                  # Service Worker offline asset cache
    ├── manifest.json          # PWA Web App Manifest
    └── icons/                 # SVG logos and icons
```

---

## 🔒 Privacy & Legal
- PinFetch does not store user data or track browsing history.
- PinFetch is an independent educational tool not affiliated with Pinterest.
