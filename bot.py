import os
import logging
import asyncio
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional

from PIL import Image
import img2pdf
from pypdf import PdfReader, PdfWriter
from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import openpyxl

from telegram import (
Update,
InlineKeyboardButton,
InlineKeyboardMarkup,
)
from telegram.ext import (
Application,
CommandHandler,
MessageHandler,
CallbackQueryHandler,
ContextTypes,
filters,
ConversationHandler,
)
from telegram.constants import ParseMode

logging.basicConfig(
format=”%(asctime)s | %(levelname)s | %(name)s | %(message)s”,
level=logging.INFO,
)
logger = logging.getLogger(**name**)

BOT_TOKEN = os.environ.get(“BOT_TOKEN”, “YOUR_BOT_TOKEN_HERE”)

TEMP_DIR = Path(tempfile.gettempdir()) / “fileflux”
TEMP_DIR.mkdir(exist_ok=True)

# Conversation states

WAITING_TRIM_START = “WAITING_TRIM_START”
WAITING_TRIM_END = “WAITING_TRIM_END”
WAITING_RESIZE = “WAITING_RESIZE”
WAITING_TIMESTAMP = “WAITING_TIMESTAMP”
WAITING_PDF_MERGE = “WAITING_PDF_MERGE”
WAITING_COMPRESS_QUALITY = “WAITING_COMPRESS_QUALITY”

IMAGE_FORMATS = [“JPEG”, “PNG”, “WEBP”, “BMP”, “GIF”, “TIFF”, “ICO”, “PDF”]
VIDEO_FORMATS = [“MP4”, “AVI”, “MKV”, “MOV”, “WEBM”, “GIF”, “MP3”, “AAC”, “WAV”, “VIDNOTE”]
AUDIO_FORMATS = [“MP3”, “WAV”, “AAC”, “OGG”, “FLAC”, “M4A”, “OPUS”]
DOC_FORMATS   = [“PDF”, “TXT”, “DOCX”]

EMOJI = {
“image”:  “🖼”,
“video”:  “🎬”,
“audio”:  “🎵”,
“doc”:    “📄”,
“done”:   “✅”,
“error”:  “❌”,
“wait”:   “⏳”,
“arrow”:  “➜”,
“bot”:    “🤖”,
“info”:   “ℹ️”,
“star”:   “⭐”,
“scissors”: “✂️”,
“compress”: “🗜”,
“resize”: “📐”,
“mute”:   “🔇”,
“thumb”:  “🖼”,
“merge”:  “📝”,
“stats”:  “📊”,
}

def detect_type(mime: Optional[str], filename: Optional[str]) -> Optional[str]:
if mime:
if mime.startswith(“image/”):  return “image”
if mime.startswith(“video/”):  return “video”
if mime.startswith(“audio/”):  return “audio”
if mime in (“application/pdf”, “text/plain”,
“application/vnd.openxmlformats-officedocument.wordprocessingml.document”,
“application/msword”):
return “doc”
if filename:
ext = Path(filename).suffix.lower()
IMG = {”.jpg”,”.jpeg”,”.png”,”.webp”,”.bmp”,”.gif”,”.tiff”,”.tif”,”.ico”,”.heic”,”.heif”}
VID = {”.mp4”,”.avi”,”.mkv”,”.mov”,”.webm”,”.flv”,”.wmv”,”.3gp”,”.m4v”}
AUD = {”.mp3”,”.wav”,”.aac”,”.ogg”,”.flac”,”.m4a”,”.opus”,”.wma”}
DOC = {”.pdf”,”.txt”,”.docx”,”.doc”,”.rtf”,”.odt”}
if ext in IMG: return “image”
if ext in VID: return “video”
if ext in AUD: return “audio”
if ext in DOC: return “doc”
return “unknown”

def format_buttons(file_type: str) -> InlineKeyboardMarkup:
formats_map = {
“image”: IMAGE_FORMATS,
“video”: VIDEO_FORMATS,
“audio”: AUDIO_FORMATS,
“doc”:   DOC_FORMATS,
}
formats = formats_map.get(file_type, [])
buttons, row = [], []
for i, fmt in enumerate(formats):
row.append(InlineKeyboardButton(fmt, callback_data=f”convert:{fmt}”))
if len(row) == 3:
buttons.append(row)
row = []
if row:
buttons.append(row)

```
# Extra tools row based on type
if file_type == "image":
    buttons.append([
        InlineKeyboardButton("📐 Resize", callback_data="tool:resize"),
        InlineKeyboardButton("🗜 Compress", callback_data="tool:compress"),
    ])
if file_type == "video":
    buttons.append([
        InlineKeyboardButton("✂️ Trim", callback_data="tool:trim"),
        InlineKeyboardButton("🔇 Mute", callback_data="tool:mute"),
        InlineKeyboardButton("🖼 Thumbnail", callback_data="tool:thumbnail"),
    ])
    buttons.append([
        InlineKeyboardButton("🗜 Compress", callback_data="tool:compress"),
        InlineKeyboardButton("📊 File Info", callback_data="tool:info"),
    ])
if file_type == "audio":
    buttons.append([
        InlineKeyboardButton("📊 File Info", callback_data="tool:info"),
    ])
if file_type == "doc":
    buttons.append([
        InlineKeyboardButton("📝 Merge PDFs", callback_data="tool:merge_pdf"),
    ])

buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
return InlineKeyboardMarkup(buttons)
```

def user_dir(user_id: int) -> Path:
d = TEMP_DIR / str(user_id)
d.mkdir(exist_ok=True)
return d

def cleanup(user_id: int):
d = user_dir(user_id)
shutil.rmtree(d, ignore_errors=True)
d.mkdir(exist_ok=True)

def get_file_info(src: Path) -> dict:
“”“Get media file info using ffprobe.”””
cmd = [
“ffprobe”, “-v”, “quiet”, “-print_format”, “json”,
“-show_format”, “-show_streams”, str(src)
]
result = subprocess.run(cmd, capture_output=True, text=True)
import json
try:
data = json.loads(result.stdout)
fmt = data.get(“format”, {})
streams = data.get(“streams”, [])
video_stream = next((s for s in streams if s.get(“codec_type”) == “video”), None)
audio_stream = next((s for s in streams if s.get(“codec_type”) == “audio”), None)

```
    info = {
        "size": int(fmt.get("size", 0)),
        "duration": float(fmt.get("duration", 0)),
        "bitrate": int(fmt.get("bit_rate", 0)),
        "format": fmt.get("format_long_name", "Unknown"),
    }
    if video_stream:
        info["width"] = video_stream.get("width", 0)
        info["height"] = video_stream.get("height", 0)
        info["video_codec"] = video_stream.get("codec_name", "Unknown")
        info["fps"] = eval(video_stream.get("r_frame_rate", "0/1"))
    if audio_stream:
        info["audio_codec"] = audio_stream.get("codec_name", "Unknown")
        info["sample_rate"] = audio_stream.get("sample_rate", "Unknown")
        info["channels"] = audio_stream.get("channels", 0)
    return info
except Exception:
    return {}
```

# ─── Conversion Functions ─────────────────────────────────────────────────────

def convert_image(src: Path, target_fmt: str, out_dir: Path) -> Path:
fmt = target_fmt.upper()
if fmt == “PDF”:
out = out_dir / (src.stem + “.pdf”)
with open(out, “wb”) as f:
f.write(img2pdf.convert(str(src)))
return out

```
pil_fmt = "JPEG" if fmt == "JPG" else fmt
ext_map = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "BMP": "bmp",
           "GIF": "gif", "TIFF": "tiff", "ICO": "ico"}
ext = ext_map.get(pil_fmt, pil_fmt.lower())
out = out_dir / f"{src.stem}.{ext}"

img = Image.open(src)
if pil_fmt in ("JPEG", "BMP", "ICO") and img.mode in ("RGBA", "P", "LA"):
    img = img.convert("RGB")
save_kwargs = {}
if pil_fmt == "JPEG":
    save_kwargs["quality"] = 92
    save_kwargs["optimize"] = True
elif pil_fmt == "PNG":
    save_kwargs["optimize"] = True
img.save(out, pil_fmt, **save_kwargs)
return out
```

def resize_image(src: Path, width: int, height: int, out_dir: Path) -> Path:
ext = src.suffix
out = out_dir / f”{src.stem}_resized{ext}”
img = Image.open(src)
if width == 0:
ratio = height / img.height
width = int(img.width * ratio)
elif height == 0:
ratio = width / img.width
height = int(img.height * ratio)
img = img.resize((width, height), Image.LANCZOS)
img.save(out)
return out

def compress_image(src: Path, quality: int, out_dir: Path) -> Path:
out = out_dir / f”{src.stem}_compressed.jpg”
img = Image.open(src)
if img.mode in (“RGBA”, “P”, “LA”):
img = img.convert(“RGB”)
img.save(out, “JPEG”, quality=quality, optimize=True)
return out

def compress_video(src: Path, out_dir: Path, crf: int = 28) -> Path:
out = out_dir / f”{src.stem}_compressed.mp4”
cmd = [
“ffmpeg”, “-y”, “-i”, str(src),
“-c:v”, “libx264”, “-preset”, “medium”, “-crf”, str(crf),
“-c:a”, “aac”, “-b:a”, “128k”,
str(out)
]
subprocess.run(cmd, check=True, capture_output=True)
return out

def convert_video(src: Path, target_fmt: str, out_dir: Path) -> Path:
fmt = target_fmt.upper()

```
if fmt == "GIF":
    out = out_dir / (src.stem + ".gif")
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-vf", "fps=10,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
        "-loop", "0", str(out)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out

if fmt == "VIDNOTE":
    out = out_dir / (src.stem + "_note.mp4")
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-t", "60",
        "-vf", "crop=min(iw\\,ih):min(iw\\,ih),scale=384:384",
        "-c:v", "libx264", "-preset", "fast", "-crf", "28",
        "-c:a", "aac", "-b:a", "64k",
        str(out)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out

if fmt in ("MP3", "AAC", "WAV", "OGG", "FLAC", "M4A", "OPUS"):
    return convert_audio(src, fmt, out_dir)

ext_map = {"MP4":"mp4","AVI":"avi","MKV":"mkv","MOV":"mov","WEBM":"webm"}
ext = ext_map.get(fmt, fmt.lower())
out = out_dir / f"{src.stem}.{ext}"
codec_map = {
    "MP4":  ["-c:v","libx264","-preset","fast","-crf","23","-c:a","aac"],
    "AVI":  ["-c:v","libxvid","-qscale:v","3","-c:a","libmp3lame"],
    "MKV":  ["-c:v","libx264","-preset","fast","-crf","23","-c:a","aac"],
    "MOV":  ["-c:v","libx264","-preset","fast","-crf","23","-c:a","aac"],
    "WEBM": ["-c:v","libvpx-vp9","-crf","30","-b:v","0","-c:a","libopus"],
}
codecs = codec_map.get(fmt, ["-c","copy"])
cmd = ["ffmpeg", "-y", "-i", str(src)] + codecs + [str(out)]
subprocess.run(cmd, check=True, capture_output=True)
return out
```

def trim_video(src: Path, start: str, end: str, out_dir: Path) -> Path:
out = out_dir / f”{src.stem}_trimmed.mp4”
cmd = [
“ffmpeg”, “-y”, “-i”, str(src),
“-ss”, start, “-to”, end,
“-c:v”, “libx264”, “-preset”, “fast”, “-crf”, “23”,
“-c:a”, “aac”,
str(out)
]
subprocess.run(cmd, check=True, capture_output=True)
return out

def mute_video(src: Path, out_dir: Path) -> Path:
out = out_dir / f”{src.stem}_muted.mp4”
cmd = [
“ffmpeg”, “-y”, “-i”, str(src),
“-c:v”, “copy”, “-an”,
str(out)
]
subprocess.run(cmd, check=True, capture_output=True)
return out

def extract_thumbnail(src: Path, timestamp: str, out_dir: Path) -> Path:
out = out_dir / f”{src.stem}_thumb.jpg”
cmd = [
“ffmpeg”, “-y”, “-i”, str(src),
“-ss”, timestamp, “-vframes”, “1”,
“-q:v”, “2”,
str(out)
]
subprocess.run(cmd, check=True, capture_output=True)
return out

def convert_audio(src: Path, target_fmt: str, out_dir: Path) -> Path:
fmt = target_fmt.upper()
ext_map = {“MP3”:“mp3”,“WAV”:“wav”,“AAC”:“aac”,“OGG”:“ogg”,
“FLAC”:“flac”,“M4A”:“m4a”,“OPUS”:“opus”}
ext = ext_map.get(fmt, fmt.lower())
out = out_dir / f”{src.stem}.{ext}”
codec_map = {
“MP3”:  [”-c:a”,“libmp3lame”,”-q:a”,“2”],
“WAV”:  [”-c:a”,“pcm_s16le”],
“AAC”:  [”-c:a”,“aac”,”-b:a”,“192k”],
“OGG”:  [”-c:a”,“libvorbis”,”-q:a”,“4”],
“FLAC”: [”-c:a”,“flac”],
“M4A”:  [”-c:a”,“aac”,”-b:a”,“192k”],
“OPUS”: [”-c:a”,“libopus”,”-b:a”,“128k”],
}
codecs = codec_map.get(fmt, [”-c:a”,“copy”])
cmd = [“ffmpeg”, “-y”, “-i”, str(src)] + codecs + [str(out)]
subprocess.run(cmd, check=True, capture_output=True)
return out

def convert_doc(src: Path, target_fmt: str, out_dir: Path) -> Path:
fmt = target_fmt.upper()
src_ext = src.suffix.lower()

```
if src_ext == ".pdf" and fmt == "TXT":
    from pdfminer.high_level import extract_text
    out = out_dir / (src.stem + ".txt")
    text = extract_text(str(src))
    out.write_text(text, encoding="utf-8")
    return out

if src_ext == ".pdf" and fmt == "DOCX":
    from pdfminer.high_level import extract_text
    out = out_dir / (src.stem + ".docx")
    text = extract_text(str(src))
    doc = Document()
    for line in text.split("\n"):
        doc.add_paragraph(line)
    doc.save(str(out))
    return out

if src_ext == ".txt" and fmt == "PDF":
    out = out_dir / (src.stem + ".pdf")
    content = src.read_text(encoding="utf-8", errors="replace")
    doc = SimpleDocTemplate(str(out), pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    for line in content.split("\n"):
        story.append(Paragraph(line or " ", styles["Normal"]))
        story.append(Spacer(1, 4))
    doc.build(story)
    return out

if src_ext == ".txt" and fmt == "DOCX":
    out = out_dir / (src.stem + ".docx")
    content = src.read_text(encoding="utf-8", errors="replace")
    doc = Document()
    for line in content.split("\n"):
        doc.add_paragraph(line)
    doc.save(str(out))
    return out

if src_ext == ".docx" and fmt == "PDF":
    out = out_dir / (src.stem + ".pdf")
    doc_in = Document(str(src))
    full_text = "\n".join(p.text for p in doc_in.paragraphs)
    pdf_doc = SimpleDocTemplate(str(out), pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    for line in full_text.split("\n"):
        story.append(Paragraph(line or " ", styles["Normal"]))
        story.append(Spacer(1, 4))
    pdf_doc.build(story)
    return out

if src_ext == ".docx" and fmt == "TXT":
    out = out_dir / (src.stem + ".txt")
    doc_in = Document(str(src))
    text = "\n".join(p.text for p in doc_in.paragraphs)
    out.write_text(text, encoding="utf-8")
    return out

raise ValueError(f"Conversion {src_ext.upper()} → {fmt} not supported")
```

def merge_pdfs(paths: list, out_dir: Path) -> Path:
out = out_dir / “merged.pdf”
writer = PdfWriter()
for p in paths:
reader = PdfReader(str(p))
for page in reader.pages:
writer.add_page(page)
with open(out, “wb”) as f:
writer.write(f)
return out

# ─── Handlers ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
text = (
f”{EMOJI[‘bot’]} *Welcome to FileFlux v2!*\n\n”
“I convert and process files instantly.\n\n”
f”{EMOJI[‘image’]} *Images* → JPEG, PNG, WEBP, BMP, GIF, TIFF, ICO, PDF + Resize + Compress\n”
f”{EMOJI[‘video’]} *Videos* → MP4, AVI, MKV, MOV, WEBM, GIF, Audio + Trim + Mute + Thumbnail + Compress\n”
f”{EMOJI[‘audio’]} *Audio* → MP3, WAV, AAC, OGG, FLAC, M4A, OPUS\n”
f”{EMOJI[‘doc’]} *Docs* → PDF ↔ TXT ↔ DOCX + PDF Merge\n\n”
“Just *send me a file* to get started.\n\n”
f”{EMOJI[‘info’]} /help for more info · /formats to see all formats”
)
await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
text = (
f”{EMOJI[‘info’]} *FileFlux v2 — Help*\n\n”
“*How to use:*\n”
“1. Send any file (photo, video, audio, document)\n”
“2. Pick a format or tool from the buttons\n”
“3. Follow any prompts (trim times, resize dimensions)\n”
“4. Receive your result\n\n”
“*Special tools:*\n”
“✂️ *Trim* — Cut video to specific start/end times (format: 0:00)\n”
“📐 *Resize* — Set new dimensions e.g. 1280x720 (use 0 for auto)\n”
“🗜 *Compress* — Reduce file size\n”
“🔇 *Mute* — Remove audio from video\n”
“🖼 *Thumbnail* — Extract a frame from a video\n”
“📝 *Merge PDFs* — Send multiple PDFs then merge\n”
“📊 *File Info* — See codec, resolution, duration, size\n\n”
“*Note:* Files must be under 20 MB (Telegram API limit)\n\n”
“/cancel — Cancel current operation”
)
await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_formats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
text = (
f”{EMOJI[‘star’]} *Supported Formats*\n\n”
f”{EMOJI[‘image’]} *Image:* JPG PNG WEBP BMP GIF TIFF ICO → + PDF\n”
f”{EMOJI[‘video’]} *Video:* MP4 AVI MKV MOV WEBM FLV 3GP → MP4 AVI MKV MOV WEBM GIF MP3 AAC WAV VIDNOTE\n”
f”{EMOJI[‘audio’]} *Audio:* MP3 WAV AAC OGG FLAC M4A OPUS WMA → MP3 WAV AAC OGG FLAC M4A OPUS\n”
f”{EMOJI[‘doc’]} *Docs:* PDF TXT DOCX → PDF TXT DOCX\n”
)
await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
uid = update.effective_user.id
cleanup(uid)
ctx.user_data.clear()
await update.message.reply_text(f”{EMOJI[‘done’]} Cancelled. Send a new file whenever you’re ready.”)

async def handle_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
msg = update.message
uid = update.effective_user.id

```
# PDF merge collection mode
if ctx.user_data.get("tool") == "merge_pdf":
    if msg.document and msg.document.mime_type == "application/pdf":
        merge_files = ctx.user_data.get("merge_files", [])
        tg_file = await ctx.bot.get_file(msg.document.file_id)
        dest = user_dir(uid) / f"merge_{len(merge_files)}.pdf"
        await tg_file.download_to_drive(str(dest))
        merge_files.append(str(dest))
        ctx.user_data["merge_files"] = merge_files
        count = len(merge_files)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"📝 Merge {count} PDFs now", callback_data="do_merge"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel"),
        ]])
        await msg.reply_text(
            f"{EMOJI['done']} Got PDF {count}. Send more or tap merge.",
            reply_markup=keyboard
        )
        return

file_obj = None
mime = None
filename = None

if msg.photo:
    file_obj = msg.photo[-1]
    mime = "image/jpeg"
    filename = "photo.jpg"
elif msg.video:
    file_obj = msg.video
    mime = msg.video.mime_type
    filename = msg.video.file_name or "video.mp4"
elif msg.audio:
    file_obj = msg.audio
    mime = msg.audio.mime_type
    filename = msg.audio.file_name or "audio.mp3"
elif msg.voice:
    file_obj = msg.voice
    mime = msg.voice.mime_type or "audio/ogg"
    filename = "voice.ogg"
elif msg.video_note:
    file_obj = msg.video_note
    mime = "video/mp4"
    filename = "video_note.mp4"
elif msg.document:
    file_obj = msg.document
    mime = msg.document.mime_type
    filename = msg.document.file_name or "file"
elif msg.animation:
    file_obj = msg.animation
    mime = "video/mp4"
    filename = msg.animation.file_name or "animation.mp4"

if file_obj is None:
    await msg.reply_text(f"{EMOJI['error']} Couldn't detect a supported file.")
    return

file_size = getattr(file_obj, "file_size", None)
if file_size and file_size > 50 * 1024 * 1024:
    await msg.reply_text(f"{EMOJI['error']} File too large (>50 MB). Telegram bots handle up to 50 MB.")
    return

ftype = detect_type(mime, filename)
if ftype == "unknown":
    await msg.reply_text(f"{EMOJI['error']} Unsupported file type.")
    return

ctx.user_data["file_id"]   = file_obj.file_id
ctx.user_data["filename"]  = filename
ctx.user_data["file_type"] = ftype
ctx.user_data["mime"]      = mime
ctx.user_data["tool"]      = None

type_labels = {
    "image": f"{EMOJI['image']} Image",
    "video": f"{EMOJI['video']} Video",
    "audio": f"{EMOJI['audio']} Audio",
    "doc":   f"{EMOJI['doc']} Document",
}
label = type_labels.get(ftype, "File")
size_str = f" ({file_size // 1024} KB)" if file_size else ""

await msg.reply_text(
    f"{EMOJI['wait']} *{label} received*{size_str}\n`{filename}`\n\nChoose what to do:",
    parse_mode=ParseMode.MARKDOWN,
    reply_markup=format_buttons(ftype),
)
```

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
“”“Handle text input for trim times, resize dimensions, thumbnail timestamps.”””
uid = update.effective_user.id
text = update.message.text.strip()
tool = ctx.user_data.get(“tool”)

```
if tool == "trim_waiting_start":
    ctx.user_data["trim_start"] = text
    ctx.user_data["tool"] = "trim_waiting_end"
    await update.message.reply_text("Now send the *end time* (e.g. `1:30` or `0:45`):", parse_mode=ParseMode.MARKDOWN)
    return

if tool == "trim_waiting_end":
    ctx.user_data["trim_end"] = text
    await update.message.reply_text(f"{EMOJI['wait']} Trimming video...")
    await process_tool(update, ctx, "trim")
    return

if tool == "resize_waiting":
    try:
        parts = text.lower().replace("x", " ").replace(",", " ").split()
        w, h = int(parts[0]), int(parts[1])
        ctx.user_data["resize_w"] = w
        ctx.user_data["resize_h"] = h
        await update.message.reply_text(f"{EMOJI['wait']} Resizing image...")
        await process_tool(update, ctx, "resize")
    except Exception:
        await update.message.reply_text(f"{EMOJI['error']} Invalid format. Send dimensions like `1280x720` or `800x0` for auto height.", parse_mode=ParseMode.MARKDOWN)
    return

if tool == "thumbnail_waiting":
    ctx.user_data["thumb_time"] = text
    await update.message.reply_text(f"{EMOJI['wait']} Extracting thumbnail...")
    await process_tool(update, ctx, "thumbnail")
    return

if tool == "compress_waiting":
    try:
        quality = int(text)
        if not 1 <= quality <= 100:
            raise ValueError
        ctx.user_data["compress_quality"] = quality
        await update.message.reply_text(f"{EMOJI['wait']} Compressing...")
        await process_tool(update, ctx, "compress")
    except Exception:
        await update.message.reply_text(f"{EMOJI['error']} Send a number between 1 and 100.")
    return
```

async def process_tool(update: Update, ctx: ContextTypes.DEFAULT_TYPE, tool_name: str):
“”“Download file and run a tool operation.”””
uid = update.effective_user.id
file_id   = ctx.user_data.get(“file_id”)
filename  = ctx.user_data.get(“filename”, “file”)
file_type = ctx.user_data.get(“file_type”)

```
work_dir = user_dir(uid)
try:
    tg_file = await ctx.bot.get_file(file_id)
    src_path = work_dir / filename
    await tg_file.download_to_drive(str(src_path))
except Exception as e:
    await update.message.reply_text(f"{EMOJI['error']} Download failed: {str(e)[:100]}")
    return

try:
    out_path = None

    if tool_name == "trim":
        start = ctx.user_data.get("trim_start", "0:00")
        end   = ctx.user_data.get("trim_end", "0:30")
        out_path = await asyncio.get_event_loop().run_in_executor(
            None, trim_video, src_path, start, end, work_dir
        )

    elif tool_name == "mute":
        out_path = await asyncio.get_event_loop().run_in_executor(
            None, mute_video, src_path, work_dir
        )

    elif tool_name == "thumbnail":
        ts = ctx.user_data.get("thumb_time", "0:00")
        out_path = await asyncio.get_event_loop().run_in_executor(
            None, extract_thumbnail, src_path, ts, work_dir
        )

    elif tool_name == "resize":
        w = ctx.user_data.get("resize_w", 0)
        h = ctx.user_data.get("resize_h", 0)
        out_path = await asyncio.get_event_loop().run_in_executor(
            None, resize_image, src_path, w, h, work_dir
        )

    elif tool_name == "compress":
        if file_type == "image":
            quality = ctx.user_data.get("compress_quality", 60)
            out_path = await asyncio.get_event_loop().run_in_executor(
                None, compress_image, src_path, quality, work_dir
            )
        else:
            out_path = await asyncio.get_event_loop().run_in_executor(
                None, compress_video, src_path, work_dir
            )

    elif tool_name == "info":
        info = await asyncio.get_event_loop().run_in_executor(
            None, get_file_info, src_path
        )
        size_mb = info.get("size", 0) / 1024 / 1024
        dur = info.get("duration", 0)
        minutes, seconds = int(dur // 60), int(dur % 60)
        lines = [
            f"{EMOJI['stats']} *File Info*",
            f"📁 Size: `{size_mb:.2f} MB`",
            f"⏱ Duration: `{minutes}:{seconds:02d}`",
            f"🎞 Format: `{info.get('format', 'Unknown')}`",
        ]
        if "width" in info:
            lines.append(f"📐 Resolution: `{info['width']}x{info['height']}`")
            lines.append(f"🎬 Video codec: `{info.get('video_codec', 'N/A')}`")
            lines.append(f"🎯 FPS: `{info.get('fps', 0):.1f}`")
        if "audio_codec" in info:
            lines.append(f"🎵 Audio codec: `{info.get('audio_codec', 'N/A')}`")
            lines.append(f"🔊 Sample rate: `{info.get('sample_rate', 'N/A')} Hz`")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        cleanup(uid)
        ctx.user_data.clear()
        return

    if out_path:
        out_size = out_path.stat().st_size
        caption = f"{EMOJI['done']} Done! `{out_path.name}` ({out_size // 1024} KB)"
        ext = out_path.suffix.lower()
        with open(out_path, "rb") as f:
            if tool_name == "thumbnail" or (file_type == "image" and ext != ".pdf"):
                await update.message.reply_photo(photo=f, caption=caption, parse_mode=ParseMode.MARKDOWN)
            elif file_type == "video" and ext in (".mp4", ".mov", ".webm") and tool_name != "thumbnail":
                await update.message.reply_video(video=f, caption=caption, parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_document(document=f, caption=caption, parse_mode=ParseMode.MARKDOWN)

except Exception as e:
    logger.error(f"Tool error ({tool_name}): {e}")
    await update.message.reply_text(f"{EMOJI['error']} Error: {str(e)[:200]}")
finally:
    cleanup(uid)
    ctx.user_data.clear()
```

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
query = update.callback_query
await query.answer()
uid = query.from_user.id

```
if query.data == "cancel":
    cleanup(uid)
    ctx.user_data.clear()
    await query.edit_message_text(f"{EMOJI['done']} Cancelled.")
    return

if query.data == "do_merge":
    merge_files = ctx.user_data.get("merge_files", [])
    if len(merge_files) < 2:
        await query.edit_message_text(f"{EMOJI['error']} Send at least 2 PDFs to merge.")
        return
    await query.edit_message_text(f"{EMOJI['wait']} Merging {len(merge_files)} PDFs...")
    try:
        out_path = await asyncio.get_event_loop().run_in_executor(
            None, merge_pdfs, [Path(p) for p in merge_files], user_dir(uid)
        )
        out_size = out_path.stat().st_size
        with open(out_path, "rb") as f:
            await query.message.reply_document(
                document=f,
                caption=f"{EMOJI['done']} Merged PDF ready! ({out_size // 1024} KB)",
                parse_mode=ParseMode.MARKDOWN
            )
        await query.edit_message_text(f"{EMOJI['done']} Merge complete!")
    except Exception as e:
        await query.edit_message_text(f"{EMOJI['error']} Merge failed: {str(e)[:200]}")
    finally:
        cleanup(uid)
        ctx.user_data.clear()
    return

# Tool buttons
if query.data.startswith("tool:"):
    tool = query.data.split(":", 1)[1]
    file_id = ctx.user_data.get("file_id")
    file_type = ctx.user_data.get("file_type")

    if not file_id:
        await query.edit_message_text(f"{EMOJI['error']} Session expired. Send your file again.")
        return

    if tool == "trim":
        ctx.user_data["tool"] = "trim_waiting_start"
        await query.edit_message_text(
            f"✂️ *Video Trim*\n\nSend the *start time* (e.g. `0:10` or `1:30`):",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if tool == "resize":
        ctx.user_data["tool"] = "resize_waiting"
        await query.edit_message_text(
            f"📐 *Resize Image*\n\nSend dimensions as `widthxheight`\n\nExamples:\n• `1280x720`\n• `800x0` (auto height)\n• `0x1080` (auto width)",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if tool == "thumbnail":
        ctx.user_data["tool"] = "thumbnail_waiting"
        await query.edit_message_text(
            f"🖼 *Extract Thumbnail*\n\nSend the timestamp to capture (e.g. `0:05` or `1:23`):",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if tool == "compress":
        if file_type == "image":
            ctx.user_data["tool"] = "compress_waiting"
            await query.edit_message_text(
                f"🗜 *Compress Image*\n\nSend quality level (1-100):\n• 80 = high quality\n• 60 = balanced\n• 40 = smaller size",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        else:
            ctx.user_data["tool"] = "compress"
            await query.edit_message_text(f"{EMOJI['wait']} Compressing video...")
            await process_tool_from_callback(query, ctx, uid, "compress")
            return

    if tool == "mute":
        await query.edit_message_text(f"{EMOJI['wait']} Removing audio...")
        await process_tool_from_callback(query, ctx, uid, "mute")
        return

    if tool == "info":
        await query.edit_message_text(f"{EMOJI['wait']} Reading file info...")
        await process_tool_from_callback(query, ctx, uid, "info")
        return

    if tool == "merge_pdf":
        ctx.user_data["tool"] = "merge_pdf"
        ctx.user_data["merge_files"] = []
        await query.edit_message_text(
            f"📝 *PDF Merge Mode*\n\nSend me the PDFs one by one. When done, tap the merge button.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

# Format conversion
if query.data.startswith("convert:"):
    target_fmt = query.data.split(":", 1)[1]
    file_id    = ctx.user_data.get("file_id")
    filename   = ctx.user_data.get("filename", "file")
    file_type  = ctx.user_data.get("file_type")

    if not file_id:
        await query.edit_message_text(f"{EMOJI['error']} Session expired. Send your file again.")
        return

    await query.edit_message_text(
        f"{EMOJI['wait']} Converting *{filename}* → *{target_fmt}*…",
        parse_mode=ParseMode.MARKDOWN,
    )

    work_dir = user_dir(uid)
    try:
        tg_file = await ctx.bot.get_file(file_id)
        src_path = work_dir / filename
        await tg_file.download_to_drive(str(src_path))
    except Exception as e:
        await query.edit_message_text(f"{EMOJI['error']} Download failed.")
        return

    try:
        converters = {
            "image": convert_image,
            "video": convert_video,
            "audio": convert_audio,
            "doc":   convert_doc,
        }
        converter = converters.get(file_type)
        if not converter:
            raise ValueError(f"No converter for type: {file_type}")

        out_path = await asyncio.get_event_loop().run_in_executor(
            None, converter, src_path, target_fmt, work_dir
        )
    except subprocess.CalledProcessError as e:
        await query.edit_message_text(f"{EMOJI['error']} Conversion failed. File may be corrupted or format unsupported.")
        cleanup(uid)
        return
    except Exception as e:
        await query.edit_message_text(f"{EMOJI['error']} Error: {str(e)[:200]}")
        cleanup(uid)
        return

    try:
        out_size = out_path.stat().st_size
        caption  = f"{EMOJI['done']} *Converted!*\n`{out_path.name}` ({out_size // 1024} KB)"

        with open(out_path, "rb") as f:
            ext = out_path.suffix.lower()
            if "note" in out_path.stem:
                await query.message.reply_video_note(video_note=f)
            elif file_type == "image" and ext != ".pdf":
                await query.message.reply_photo(photo=f, caption=caption, parse_mode=ParseMode.MARKDOWN)
            elif file_type == "video" and ext in (".mp4", ".mov", ".webm"):
                await query.message.reply_video(video=f, caption=caption, parse_mode=ParseMode.MARKDOWN)
            elif file_type == "audio" and ext in (".mp3", ".ogg", ".m4a", ".aac"):
                await query.message.reply_audio(audio=f, caption=caption, parse_mode=ParseMode.MARKDOWN)
            else:
                await query.message.reply_document(document=f, caption=caption, parse_mode=ParseMode.MARKDOWN)

        await query.edit_message_text(
            f"{EMOJI['done']} Done! Your *{target_fmt}* file is ready.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        await query.edit_message_text(f"{EMOJI['error']} Converted but failed to send: {str(e)[:200]}")
    finally:
        cleanup(uid)
        ctx.user_data.clear()
```

async def process_tool_from_callback(query, ctx, uid, tool_name):
“”“Process tool operations triggered directly from callback (no extra input needed).”””
filename  = ctx.user_data.get(“filename”, “file”)
file_id   = ctx.user_data.get(“file_id”)
file_type = ctx.user_data.get(“file_type”)
work_dir  = user_dir(uid)

```
try:
    tg_file = await ctx.bot.get_file(file_id)
    src_path = work_dir / filename
    await tg_file.download_to_drive(str(src_path))
except Exception as e:
    await query.edit_message_text(f"{EMOJI['error']} Download failed.")
    return

try:
    out_path = None

    if tool_name == "mute":
        out_path = await asyncio.get_event_loop().run_in_executor(
            None, mute_video, src_path, work_dir
        )

    elif tool_name == "compress":
        out_path = await asyncio.get_event_loop().run_in_executor(
            None, compress_video, src_path, work_dir
        )

    elif tool_name == "info":
        info = await asyncio.get_event_loop().run_in_executor(
            None, get_file_info, src_path
        )
        size_mb = info.get("size", 0) / 1024 / 1024
        dur = info.get("duration", 0)
        minutes, seconds = int(dur // 60), int(dur % 60)
        lines = [
            f"{EMOJI['stats']} *File Info*",
            f"📁 Size: `{size_mb:.2f} MB`",
            f"⏱ Duration: `{minutes}:{seconds:02d}`",
            f"🎞 Format: `{info.get('format', 'Unknown')}`",
        ]
        if "width" in info:
            lines.append(f"📐 Resolution: `{info['width']}x{info['height']}`")
            lines.append(f"🎬 Video codec: `{info.get('video_codec', 'N/A')}`")
            lines.append(f"🎯 FPS: `{info.get('fps', 0):.1f}`")
        if "audio_codec" in info:
            lines.append(f"🎵 Audio codec: `{info.get('audio_codec', 'N/A')}`")
            lines.append(f"🔊 Sample rate: `{info.get('sample_rate', 'N/A')} Hz`")
        await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        cleanup(uid)
        ctx.user_data.clear()
        return

    if out_path:
        out_size = out_path.stat().st_size
        caption = f"{EMOJI['done']} Done! `{out_path.name}` ({out_size // 1024} KB)"
        ext = out_path.suffix.lower()
        with open(out_path, "rb") as f:
            if file_type == "video" and ext in (".mp4", ".mov", ".webm"):
                await query.message.reply_video(video=f, caption=caption, parse_mode=ParseMode.MARKDOWN)
            else:
                await query.message.reply_document(document=f, caption=caption, parse_mode=ParseMode.MARKDOWN)
        await query.edit_message_text(f"{EMOJI['done']} Done!")

except Exception as e:
    logger.error(f"Tool error ({tool_name}): {e}")
    await query.edit_message_text(f"{EMOJI['error']} Error: {str(e)[:200]}")
finally:
    cleanup(uid)
    ctx.user_data.clear()
```

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
if BOT_TOKEN == “YOUR_BOT_TOKEN_HERE”:
print(“❌ ERROR: Set your BOT_TOKEN environment variable first!”)
return

```
app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start",   cmd_start))
app.add_handler(CommandHandler("help",    cmd_help))
app.add_handler(CommandHandler("formats", cmd_formats))
app.add_handler(CommandHandler("cancel",  cmd_cancel))

app.add_handler(MessageHandler(
    filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE |
    filters.VIDEO_NOTE | filters.Document.ALL | filters.ANIMATION,
    handle_file
))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(CallbackQueryHandler(handle_callback))

print("🤖 FileFlux v2 Bot is running...")
app.run_polling(drop_pending_updates=True)
```

if **name** == “**main**”:
main()
