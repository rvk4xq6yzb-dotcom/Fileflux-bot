# FileFlux — Telegram File Converter Bot 🤖

Convert images, videos, audio, and documents right inside Telegram.

---

## Supported Conversions

| Input Type | Output Formats |
|---|---|
| 🖼 Image (JPG, PNG, WEBP, BMP, GIF, TIFF, ICO) | JPEG, PNG, WEBP, BMP, GIF, TIFF, ICO, PDF |
| 🎬 Video (MP4, AVI, MKV, MOV, WEBM, FLV, 3GP) | MP4, AVI, MKV, MOV, WEBM, GIF, MP3, AAC, WAV |
| 🎵 Audio (MP3, WAV, AAC, OGG, FLAC, M4A, OPUS) | MP3, WAV, AAC, OGG, FLAC, M4A, OPUS |
| 📄 Document (PDF, TXT, DOCX) | PDF, TXT, DOCX |

---

## Setup

### Step 1 — Create your bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot`
3. Follow the prompts — choose a name and username
4. Copy your **API token** (looks like `123456789:ABCDefgh...`)

### Step 2 — Install system dependencies

**Ubuntu / Debian:**
```bash
sudo apt update && sudo apt install -y ffmpeg python3-pip
```

**macOS:**
```bash
brew install ffmpeg
```

**Windows:**
- Download ffmpeg from https://ffmpeg.org/download.html
- Add it to your PATH

### Step 3 — Install Python dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Configure & run

```bash
# Set your bot token (get it from @BotFather)
export BOT_TOKEN="your_token_here"

# Run the bot
python bot.py
```

---

## Running 24/7 (Production)

### Option A — systemd (Linux VPS)

Create `/etc/systemd/system/fileflux.service`:
```ini
[Unit]
Description=FileFlux Telegram Bot
After=network.target

[Service]
User=your_username
WorkingDirectory=/path/to/converter_bot
Environment=BOT_TOKEN=your_token_here
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable fileflux
sudo systemctl start fileflux
sudo systemctl status fileflux
```

### Option B — screen/tmux (quick)
```bash
screen -S fileflux
export BOT_TOKEN="your_token"
python bot.py
# Detach: Ctrl+A then D
```

### Option C — Railway / Render / Fly.io (free cloud hosting)

**Railway (easiest):**
1. Push this folder to a GitHub repo
2. Go to https://railway.app → New Project → Deploy from GitHub
3. Add environment variable `BOT_TOKEN` in the Railway dashboard
4. Done — Railway runs it 24/7 for free

**Render:**
1. Push to GitHub
2. New Web Service → connect repo
3. Set `BOT_TOKEN` in environment variables
4. Start command: `python bot.py`

---

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/help` | Usage guide |
| `/formats` | Full list of supported formats |
| `/cancel` | Cancel current conversion |

---

## Project Structure

```
converter_bot/
├── bot.py           ← Main bot (all logic here)
├── requirements.txt ← Python dependencies
└── README.md        ← This file
```

---

## How It Works

1. User sends a file (photo, video, audio, document)
2. Bot auto-detects the file type
3. Bot shows inline buttons with available output formats
4. User taps a format
5. Bot downloads the file, converts it using Pillow (images) or FFmpeg (video/audio) or reportlab/python-docx (documents)
6. Bot sends back the converted file

Files are processed in a temporary directory and cleaned up after each conversion.

---

## Troubleshooting

**"ffmpeg not found"** → Install ffmpeg (see Step 2 above)

**"File too large"** → Telegram bots have a 50 MB file limit. For larger files, consider running a local bot with a direct webhook.

**Video conversion is slow** → Normal for large files. For a VPS, use a server with more CPU cores.

**HEIC images not working** → Install `pillow-heif`:
```bash
pip install pillow-heif
```
Then add to the top of `bot.py`:
```python
from pillow_heif import register_heif_opener
register_heif_opener()
```
