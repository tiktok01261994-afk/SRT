import os
import re
import asyncio
import threading
from flask import Flask
from google import genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import whisper
import yt_dlp

# ==========================================
# 1. API KEYS CONFIGURATION (ENVIRONMENT VARIABLES)
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

client = genai.Client(api_key=GEMINI_API_KEY)
print("⏳ Whisper Model ကို Load လုပ်နေပါသည်...")
whisper_model = whisper.load_model("base")
print("✅ Whisper Model အဆင်သင့်ဖြစ်ပါပြီ။")

app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "Telegram Bot is running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host='0.0.0.0', port=port)

# ==========================================
# 2. SUBTITLE LOGIC
# ==========================================
def download_youtube_audio(youtube_url, output_filename="temp_audio"):
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': output_filename,
        'quiet': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([youtube_url])
    return f"{output_filename}.mp3"

def format_timestamp(seconds):
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millisecs = int((seconds - int(seconds)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millisecs:03d}"

def translate_segments(segments):
    lines = [f"[{seg['id']}] {seg['text'].strip()}" for seg in segments]
    full_text = "\n".join(lines)
    
    prompt = f"""
You are a professional subtitle translator. 
Translate the following subtitle segment list into natural, conversational Myanmar language (Burmese).

Rules:
1. Preserve the exact line format `[ID] Translated Text`.
2. Do NOT merge, split, or omit any lines. Keep the total line count identical.
3. Translate accurately according to the context of spoken video.

Input Subtitles:
{full_text}
"""
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt
    )
    
    translated_map = {}
    for line in response.text.strip().split("\n"):
        match = re.match(r"^\[(\d+)\]\s*(.*)", line.strip())
        if match:
            translated_map[int(match.group(1))] = match.group(2)
    return translated_map

def generate_srt(segments, translated_map, output_srt="myanmar_subtitles.srt"):
    with open(output_srt, "w", encoding="utf-8") as f:
        for seg in segments:
            seg_id = seg["id"]
            start_time = format_timestamp(seg["start"])
            end_time = format_timestamp(seg["end"])
            myanmar_text = translated_map.get(seg_id, seg["text"].strip())
            
            f.write(f"{seg_id + 1}\n")
            f.write(f"{start_time} --> {end_time}\n")
            f.write(f"{myanmar_text}\n\n")
    return output_srt

# ==========================================
# 3. TELEGRAM HANDLERS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 မင်္ဂလာပါ! ကျွန်တော်က YouTube ဗီဒီယိုများမှ မြန်မာ စာတန်းထိုး (.srt) ထုတ်ပေးသည့် Bot ဖြစ်ပါတယ်။\n\n"
        "🔗 သင် စာတန်းထိုးထုတ်ချင်သော YouTube Video Link ကို ပေးပို့ပေးပါ:"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not ("youtube.com" in url or "youtu.be" in url):
        await update.message.reply_text("⚠️ ကျေးဇူးပြု၍ မှန်ကန်သော YouTube Video Link ကိုသာ ပေးပို့ပေးပါ။")
        return

    status_msg = await update.message.reply_text("⏳ [1/3] YouTube Video မှ အသံဖိုင်ကို ဒေါင်းလုဒ်ဆွဲနေပါသည်...")
    audio_file, srt_file = None, None
    
    try:
        loop = asyncio.get_event_loop()
        audio_file = await loop.run_in_executor(None, download_youtube_audio, url)
        
        await status_msg.edit_text("⏳ [2/3] Whisper AI ဖြင့် အသံကို စာသားပြောင်းနေပါသည်...")
        segments_res = await loop.run_in_executor(None, whisper_model.transcribe, audio_file)
        segments = segments_res["segments"]
        
        await status_msg.edit_text("⏳ [3/3] Gemini AI ဖြင့် မြန်မာဘာသာသို့ ပြန်ဆိုနေပါသည်...")
        translated_map = await loop.run_in_executor(None, translate_segments, segments)
        srt_file = await loop.run_in_executor(None, generate_srt, segments, translated_map)
        
        await status_msg.edit_text("🎉 Subtitle ဖိုင် ထုတ်လုပ်ခြင်း ပြီးစီးပါပြီ! ဖိုင် ပေးပို့နေပါသည်...")
        with open(srt_file, 'rb') as doc:
            await update.message.reply_document(document=doc, filename="myanmar_subtitles.srt")
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error ဖြစ်ပွားခဲ့ပါသည်: {e}")
    finally:
        if audio_file and os.path.exists(audio_file):
            os.remove(audio_file)
        if srt_file and os.path.exists(srt_file):
            os.remove(srt_file)

# ==========================================
# 4. MAIN RUNNER
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    
    tg_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 Bot is live!")
    tg_app.run_polling()
You are a professional subtitle translator. 
Translate the following subtitle segment list into natural, conversational Myanmar language (Burmese).

Rules:
1. Preserve the exact line format `[ID] Translated Text`.
2. Do NOT merge, split, or omit any lines. Keep the total line count identical.
3. Translate accurately according to the context of spoken video.

Input Subtitles:
{full_text}
"""
    response = client.models.generate_content(
        model="gemini-2.5-flash", contents=prompt
    )

    translated_map = {}
    for line in response.text.strip().split("\n"):
        match = re.match(r"^\[(\d+)\]\s*(.*)", line.strip())
        if match:
            translated_map[int(match.group(1))] = match.group(2)
    return translated_map


def generate_srt(
    segments, translated_map, output_srt="myanmar_subtitles.srt"
):
    with open(output_srt, "w", encoding="utf-8") as f:
        for seg in segments:
            seg_id = seg["id"]
            start_time = format_timestamp(seg["start"])
            end_time = format_timestamp(seg["end"])
            myanmar_text = translated_map.get(seg_id, seg["text"].strip())

            f.write(f"{seg_id + 1}\n")
            f.write(f"{start_time} --> {end_time}\n")
            f.write(f"{myanmar_text}\n\n")
    return output_srt


# ==========================================
# 3. TELEGRAM HANDLERS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 မင်္ဂလာပါ! ကျွန်တော်က YouTube ဗီဒီယိုများမှ မြန်မာ စာတန်းထိုး (.srt) ထုတ်ပေးသည့် Bot ဖြစ်ပါတယ်။\n\n"
        "🔗 သင် စာတန်းထိုးထုတ်ချင်သော YouTube Video Link ကို ပေးပို့ပေးပါ:"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not ("youtube.com" in url or "youtu.be" in url):
        await update.message.reply_text(
            "⚠️ ကျေးဇူးပြု၍ မှန်ကန်သော YouTube Video Link ကိုသာ ပေးပို့ပေးပါ။"
        )
        return

    status_msg = await update.message.reply_text(
        "⏳ [1/3] YouTube Video မှ အသံဖိုင်ကို ဒေါင်းလုဒ်ဆွဲနေပါသည်..."
    )
    audio_file, srt_file = None, None

    try:
        loop = asyncio.get_event_loop()
        audio_file = await loop.run_in_executor(
            None, download_youtube_audio, url
        )

        await status_msg.edit_text(
            "⏳ [2/3] Whisper AI ဖြင့် အသံကို စာသားပြောင်းနေပါသည်..."
        )
        segments_res = await loop.run_in_executor(
            None, whisper_model.transcribe, audio_file
        )
        segments = segments_res["segments"]

        await status_msg.edit_text(
            "⏳ [3/3] Gemini AI ဖြင့် မြန်မာဘာသာသို့ ပြန်ဆိုနေပါသည်..."
        )
        translated_map = await loop.run_in_executor(
            None, translate_segments, segments
        )
        srt_file = await loop.run_in_executor(
            None, generate_srt, segments, translated_map
        )

        await status_msg.edit_text(
            "🎉 Subtitle ဖိုင် ထုတ်လုပ်ခြင်း ပြီးစီးပါပြီ! ဖိုင် ပေးပို့နေပါသည်..."
        )
        with open(srt_file, "rb") as doc:
            await update.message.reply_document(
                document=doc, filename="myanmar_subtitles.srt"
            )

    except Exception as e:
        await update.message.reply_text(f"❌ Error ဖြစ်ပွားခဲ့ပါသည်: {e}")
    finally:
        if audio_file and os.path.exists(audio_file):
            os.remove(audio_file)
        if srt_file and os.path.exists(srt_file):
            os.remove(srt_file)


# ==========================================
# 4. MAIN RUNNER
# ==========================================
if __name__ == "__main__":
    # Flask Server ကို Thread အနေဖြင့် Run ထားမည်
    threading.Thread(target=run_flask, daemon=True).start()

    # Telegram Bot ကို Run မည်
    tg_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print("🤖 Bot is live!")
    tg_app.run_polling()
