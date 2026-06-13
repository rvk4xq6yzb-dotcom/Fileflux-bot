import os
import subprocess
subprocess.run(["pip", "install", "--quiet", "ffmpeg-python"], check=False)
os.system("apt-get install -y ffmpeg 2>/dev/null || true")
"""
FileFlux Telegram Bot
A powerful file converter bot supporting images, videos, audio, documents and more.
"""

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
    Message,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Bot Token ────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ─── Temp directory for processing ────────────────────────────────────────────
TEMP_DIR = Path(tempfile.gettempdir()) / "fileflux"
TEMP_DIR.mkdir(exist_ok=True)

# ─── Conversion maps ──────────────────────────────────────────────────────────
IMAGE_FORMATS = ["JPEG", "PNG", "WEBP", "BMP", "GIF", "TIFF", "ICO", "PDF"]
VIDEO_FORMATS = ["MP4", "AVI", "MKV", "MOV", "WEBM", "GIF", "MP3", "AAC", "WAV"]
AUDIO_FORMATS = ["MP3", "WAV", "AAC", "OGG", "FLAC", "M4A", "OPUS"]
DOC_FORMATS   = ["PDF", "TXT", "DOCX"]

EMOJI = {
    "image":  "🖼",
    "video":  "🎬",
    "audio":  "🎵",
    "doc":    "📄",
    "zip":    "📦",
    "done":   "✅",
    "error":  "❌",
    "wait":   "⏳",
    "arrow":  "➜",
    "bot":    "🤖",
    "info":   "ℹ️",
    "star":   "⭐",
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def detect_type(mime: Optional[str], filename: Optional[str]) -> Optional[str]:
    """Return coarse file type: image | video | audio | doc | unknown."""
    if mime:
        if mime.startswith("image/"):  return "image"
        if mime.startswith("video/"):  return "video"
        if mime.startswith("audio/"):  return "audio"
        if mime in ("application/pdf", "text/plain",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/msword"):
            return "doc"
    if filename:
        ext = Path(filename).suffix.lower()
        IMG = {".jpg",".jpeg",".png",".webp",".bmp",".gif",".tiff",".tif",".ico",".heic",".heif"}
        VID = {".mp4",".avi",".mkv",".mov",".webm",".flv",".wmv",".3gp",".m4v"}
        AUD = {".mp3",".wav",".aac",".ogg",".flac",".m4a",".opus",".wma"}
        DOC = {".pdf",".txt",".docx",".doc",".rtf",".odt"}
        if ext in IMG: return "image"
        if ext in VID: return "video"
        if ext in AUD: return "audio"
        if ext in DOC: return "doc"
    return "unknown"


def format_buttons(file_type: str) -> InlineKeyboardMarkup:
    """Build inline keyboard for target format selection."""
    formats_map = {
        "image": IMAGE_FORMATS,
        "video": VIDEO_FORMATS,
        "audio": AUDIO_FORMATS,
        "doc":   DOC_FORMATS,
    }
    formats = formats_map.get(file_type, [])
    buttons, row = [], []
    for i, fmt in enumerate(formats):
        row.append(InlineKeyboardButton(fmt, callback_data=f"convert:{fmt}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)


def user_dir(user_id: int) -> Path:
    d = TEMP_DIR / str(user_id)
    d.mkdir(exist_ok=True)
    return d


def cleanup(user_id: int):
    d = user_dir(user_id)
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(exist_ok=True)

# ─── Conversion engine ────────────────────────────────────────────────────────

def convert_image(src: Path, target_fmt: str, out_dir: Path) -> Path:
    fmt = target_fmt.upper()
    if fmt == "PDF":
        out = out_dir / (src.stem + ".pdf")
        with open(out, "wb") as f:
            f.write(img2pdf.convert(str(src)))
        return out

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


def convert_video(src: Path, target_fmt: str, out_dir: Path) -> Path:
    fmt = target_fmt.upper()

    # Video → GIF (special case)
    if fmt == "GIF":
        out = out_dir / (src.stem + ".gif")
        cmd = [
            "ffmpeg", "-y", "-i", str(src),
            "-vf", "fps=10,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
            "-loop", "0", str(out)
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return out

    # Video → audio extraction
    if fmt in ("MP3", "AAC", "WAV", "OGG", "FLAC", "M4A", "OPUS"):
        return convert_audio(src, fmt, out_dir)

    # Video → video
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


def convert_audio(src: Path, target_fmt: str, out_dir: Path) -> Path:
    fmt = target_fmt.upper()
    ext_map = {"MP3":"mp3","WAV":"wav","AAC":"aac","OGG":"ogg",
               "FLAC":"flac","M4A":"m4a","OPUS":"opus"}
    ext = ext_map.get(fmt, fmt.lower())
    out = out_dir / f"{src.stem}.{ext}"
    codec_map = {
        "MP3":  ["-c:a","libmp3lame","-q:a","2"],
        "WAV":  ["-c:a","pcm_s16le"],
        "AAC":  ["-c:a","aac","-b:a","192k"],
        "OGG":  ["-c:a","libvorbis","-q:a","4"],
        "FLAC": ["-c:a","flac"],
        "M4A":  ["-c:a","aac","-b:a","192k"],
        "OPUS": ["-c:a","libopus","-b:a","128k"],
    }
    codecs = codec_map.get(fmt, ["-c:a","copy"])
    cmd = ["ffmpeg", "-y", "-i", str(src)] + codecs + [str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def convert_doc(src: Path, target_fmt: str, out_dir: Path) -> Path:
    fmt = target_fmt.upper()
    src_ext = src.suffix.lower()

    # PDF → TXT
    if src_ext == ".pdf" and fmt == "TXT":
        from pdfminer.high_level import extract_text
        out = out_dir / (src.stem + ".txt")
        text = extract_text(str(src))
        out.write_text(text, encoding="utf-8")
        return out

    # PDF → DOCX
    if src_ext == ".pdf" and fmt == "DOCX":
        from pdfminer.high_level import extract_text
        out = out_dir / (src.stem + ".docx")
        text = extract_text(str(src))
        doc = Document()
        for line in text.split("\n"):
            doc.add_paragraph(line)
        doc.save(str(out))
        return out

    # TXT → PDF
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

    # TXT → DOCX
    if src_ext == ".txt" and fmt == "DOCX":
        out = out_dir / (src.stem + ".docx")
        content = src.read_text(encoding="utf-8", errors="replace")
        doc = Document()
        for line in content.split("\n"):
            doc.add_paragraph(line)
        doc.save(str(out))
        return out

    # DOCX → PDF
    if src_ext == ".docx" and fmt == "PDF":
        # Extract text and build PDF
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

    # DOCX → TXT
    if src_ext == ".docx" and fmt == "TXT":
        out = out_dir / (src.stem + ".txt")
        doc_in = Document(str(src))
        text = "\n".join(p.text for p in doc_in.paragraphs)
        out.write_text(text, encoding="utf-8")
        return out

    raise ValueError(f"Conversion {src_ext.upper()} → {fmt} not supported")


# ─── Handlers ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        f"{EMOJI['bot']} *Welcome to FileFlux!*\n\n"
        "I convert files between formats instantly.\n\n"
        f"{EMOJI['image']} *Images* → JPEG, PNG, WEBP, BMP, GIF, TIFF, ICO, PDF\n"
        f"{EMOJI['video']} *Videos* → MP4, AVI, MKV, MOV, WEBM, GIF, MP3, WAV…\n"
        f"{EMOJI['audio']} *Audio* → MP3, WAV, AAC, OGG, FLAC, M4A, OPUS\n"
        f"{EMOJI['doc']} *Docs* → PDF ↔ TXT ↔ DOCX\n\n"
        "Just *send me a file* and I'll show you what it can become.\n\n"
        f"{EMOJI['info']} Use /help for detailed info."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        f"{EMOJI['info']} *FileFlux — Help*\n\n"
        "*How to use:*\n"
        "1. Send any file (photo, video, audio, document)\n"
        "2. Pick the target format from the buttons\n"
        "3. Receive your converted file in seconds\n\n"
        "*Tips:*\n"
        "• For large videos, conversion may take a moment\n"
        "• Photos sent as compressed images are supported\n"
        "• Send files *as document* to preserve original quality\n"
        "• Video → GIF creates an animated 480px-wide GIF\n\n"
        "*Commands:*\n"
        "/start — Welcome message\n"
        "/help — This help message\n"
        "/cancel — Cancel current conversion\n"
        "/formats — Show all supported formats"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_formats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        f"{EMOJI['star']} *Supported Formats*\n\n"
        f"{EMOJI['image']} *Image input:* JPG, PNG, WEBP, BMP, GIF, TIFF, ICO, HEIC\n"
        f"   {EMOJI['arrow']} Output: JPEG, PNG, WEBP, BMP, GIF, TIFF, ICO, PDF\n\n"
        f"{EMOJI['video']} *Video input:* MP4, AVI, MKV, MOV, WEBM, FLV, 3GP\n"
        f"   {EMOJI['arrow']} Output: MP4, AVI, MKV, MOV, WEBM, GIF, MP3, AAC, WAV\n\n"
        f"{EMOJI['audio']} *Audio input:* MP3, WAV, AAC, OGG, FLAC, M4A, OPUS, WMA\n"
        f"   {EMOJI['arrow']} Output: MP3, WAV, AAC, OGG, FLAC, M4A, OPUS\n\n"
        f"{EMOJI['doc']} *Document input:* PDF, TXT, DOCX\n"
        f"   {EMOJI['arrow']} Output: PDF, TXT, DOCX\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cleanup(uid)
    ctx.user_data.clear()
    await update.message.reply_text(f"{EMOJI['done']} Cancelled. Send a new file whenever you're ready.")


async def handle_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Receive any file/photo/video/audio and prompt for target format."""
    msg = update.message
    uid = update.effective_user.id

    # Determine the file object + metadata
    file_obj = None
    mime = None
    filename = None

    if msg.photo:
        file_obj = msg.photo[-1]  # largest size
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
        await msg.reply_text(f"{EMOJI['error']} I couldn't detect a supported file. Please send an image, video, audio, or document.")
        return

    # File size guard (Telegram bot API limit: 20 MB download)
    file_size = getattr(file_obj, "file_size", None)
    if file_size and file_size > 50 * 1024 * 1024:
        await msg.reply_text(
            f"{EMOJI['error']} File too large (>{50} MB). Telegram bots can only handle files up to 50 MB."
        )
        return

    ftype = detect_type(mime, filename)
    if ftype == "unknown":
        await msg.reply_text(
            f"{EMOJI['error']} Unsupported file type. Send images, videos, audio, or documents (PDF/TXT/DOCX)."
        )
        return

    # Store state
    ctx.user_data["file_id"]   = file_obj.file_id
    ctx.user_data["filename"]  = filename
    ctx.user_data["file_type"] = ftype
    ctx.user_data["mime"]      = mime

    type_labels = {
        "image": f"{EMOJI['image']} Image",
        "video": f"{EMOJI['video']} Video",
        "audio": f"{EMOJI['audio']} Audio",
        "doc":   f"{EMOJI['doc']} Document",
    }
    label = type_labels.get(ftype, "File")
    size_str = f" ({file_size // 1024} KB)" if file_size else ""

    await msg.reply_text(
        f"{EMOJI['wait']} *{label} received*{size_str}\n\n"
        f"File: `{filename}`\n\n"
        "Choose the format to convert to:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=format_buttons(ftype),
    )


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle inline button presses for format selection."""
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if query.data == "cancel":
        cleanup(uid)
        ctx.user_data.clear()
        await query.edit_message_text(f"{EMOJI['done']} Cancelled.")
        return

    if not query.data.startswith("convert:"):
        return

    target_fmt = query.data.split(":", 1)[1]
    file_id    = ctx.user_data.get("file_id")
    filename   = ctx.user_data.get("filename", "file")
    file_type  = ctx.user_data.get("file_type")

    if not file_id:
        await query.edit_message_text(f"{EMOJI['error']} Session expired. Please send your file again.")
        return

    await query.edit_message_text(
        f"{EMOJI['wait']} Converting *{filename}* → *{target_fmt}*…\n\nThis may take a moment for large files.",
        parse_mode=ParseMode.MARKDOWN,
    )

    # Download
    work_dir = user_dir(uid)
    try:
        tg_file = await ctx.bot.get_file(file_id)
        src_path = work_dir / filename
        await tg_file.download_to_drive(str(src_path))
    except Exception as e:
        logger.error(f"Download error: {e}")
        await query.edit_message_text(f"{EMOJI['error']} Failed to download the file. Please try again.")
        return

    # Convert
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
        logger.error(f"ffmpeg error: {e.stderr}")
        await query.edit_message_text(
            f"{EMOJI['error']} Conversion failed. The file may be corrupted or the format combination isn't supported."
        )
        cleanup(uid)
        return
    except Exception as e:
        logger.error(f"Conversion error: {e}")
        await query.edit_message_text(
            f"{EMOJI['error']} Conversion error: {str(e)[:200]}"
        )
        cleanup(uid)
        return

    # Send result
    try:
        out_size = out_path.stat().st_size
        caption  = f"{EMOJI['done']} *Converted!*\n`{out_path.name}` ({out_size // 1024} KB)"

        with open(out_path, "rb") as f:
            # Choose the right send method for better Telegram rendering
            ext = out_path.suffix.lower()
            if file_type == "image" and ext != ".pdf":
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
        logger.error(f"Send error: {e}")
        await query.edit_message_text(
            f"{EMOJI['error']} Converted but failed to send: {str(e)[:200]}"
        )
    finally:
        cleanup(uid)
        ctx.user_data.clear()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ ERROR: Set your BOT_TOKEN environment variable first!")
        print("   export BOT_TOKEN='your_actual_token'")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("formats", cmd_formats))
    app.add_handler(CommandHandler("cancel",  cmd_cancel))

    # File handlers
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE |
        filters.VIDEO_NOTE | filters.Document.ALL | filters.ANIMATION,
        handle_file
    ))

    # Inline button handler
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("🤖 FileFlux Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
