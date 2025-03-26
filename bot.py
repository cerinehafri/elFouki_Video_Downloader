import os
import time
import re
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    CallbackQueryHandler
)
import yt_dlp
from pydub import AudioSegment
import subprocess
import logging
from dotenv import load_dotenv
import telebot

# تحميل متغيرات البيئة
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# إعداد السجل
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# التحقق من وجود التوكن
if not TOKEN:
    logger.error("❌ لم يتم تعيين TELEGRAM_BOT_TOKEN في ملف .env")
    exit(1)

# الإعدادات العامة
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
SUPPORTED_SITES = [
    'youtube', 'twitter', 'facebook', 'instagram',
    'tiktok', 'pinterest', 'dailymotion', 'vimeo',
    'twitch', 'soundcloud', 'reddit'
]

# إنشاء مجلد التحميلات
os.makedirs("downloads", exist_ok=True)

def sanitize_filename(filename):
    """تنظيف اسم الملف من الأحرف الخاصة"""
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
    filename = filename[:100].strip()
    return filename or str(uuid.uuid4())

async def start(update: Update, context: CallbackContext) -> None:
    """رسالة الترحيب مع شرح الميزات الجديدة"""
    welcome_msg = """
🎥 *مرحبًا بكم في بوت الفوكي لتحميل الفيديوهات\!*  

📤 *كيفية الاستخدام:*  
1️⃣ أرسل *رابط الفيديو أو الصوت*\.  
2️⃣ اختر *نوع التحميل* \(🎥 فيديو أو 🎧 صوت\)\.  
3️⃣ انتظر وسيتم إرسال الملف إليك مباشرةً\.  
 

🌍 *المواقع المدعومة:*  
🔹 *YouTube* 🔹 *Facebook* 🔹 *Twitter*  
🔹 *TikTok* 🔹 *Instagram* 🔹 *SoundCloud*  
🔹 *وأكثر من ذلك\!*  

👨‍🏫 *بإشراف الأستاذ أبو مالك إبراهيم الفوكي*  

📢 تابعنا على [حساباتنا](https://linktr\\.ee/elfouki)  
"""

    await update.message.reply_text(welcome_msg, parse_mode="MarkdownV2")



async def handle_url(update: Update, context: CallbackContext):
    """معالجة الرابط وعرض خيارات التحميل"""
    url = update.message.text.strip()
    context.user_data['download_url'] = url
    
    # تحليل المعلومات الأساسية دون تحميل
    try:
        start_time = time.time()
        status_msg = await update.message.reply_text("🔍 جارٍ تحليل الرابط...")
        
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            duration = info.get('duration', 0)
            filesize = info.get('filesize') or info.get('filesize_approx') or 0
            
            # تقدير وقت التحميل (ثانية لكل ميجابايت)
            estimated_time = (filesize / (1024 * 1024) * 3) if isinstance(filesize, (int, float)) else 0
            
            # إنشاء لوحة اختيار
            keyboard = [
                [
                    InlineKeyboardButton("🎥 تحميل فيديو", callback_data='video'),
                    InlineKeyboardButton("🎧 تحميل صوت", callback_data='audio')
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            info_msg = (
                f"📌 معلومات المحتوى:\n"
                f"🏷️ العنوان: {info.get('title', 'غير معروف')}\n"
                f"⏱️ المدة: {int(duration)//60}:{int(duration)%60:02d}\n"
                f"📦 الحجم: {filesize/(1024*1024):.1f}MB\n"
                f"⏳ وقت التحميل المتوقع: {estimated_time:.1f} ثانية\n\n"
                "اختر طريقة التحميل:"
            )
            
            await status_msg.edit_text(info_msg, reply_markup=reply_markup)
            
    except Exception as e:
        logger.error(f"URL analysis error: {e}")
        await update.message.reply_text("❌ تعذر تحليل الرابط. يرجى التأكد من صحته.")

async def handle_choice(update: Update, context: CallbackContext):
    """معالجة اختيار المستخدم"""
    query = update.callback_query
    await query.answer()
    
    choice = query.data
    url = context.user_data.get('download_url')
    
    if not url:
        await query.edit_message_text("❌ انتهت صلاحية الرابط. يرجى إرساله مجددًا.")
        return
    
    try:
        # إنشاء شريط التقدم
        progress_msg = await query.edit_message_text(
            text=f"⏳ جارٍ التحميل كـ {'فيديو' if choice == 'video' else 'صوت'}...\n"
        )
        
        # دالة تحديث الشريط
        def progress_hook(d):
            nonlocal progress_msg
            if d['status'] == 'downloading':
                percent = d.get('_percent_str', '0%').strip('%')
                if percent.isdigit():
                    progress = int(percent) // 10
                    bar = '▰' * progress + '▱' * (10 - progress)
                    text = (
                        f"⏳ جارٍ التحميل كـ {'فيديو' if choice == 'video' else 'صوت'}...\n"
                        f"{bar} {percent}%\n"
                        f"⏱️ الوقت المنقضي: {d.get('_elapsed_str', '0:00')}"
                    )
                    try:
                        # التحديث كل 5% لتجنب إرسال الكثير من الطلبات
                        if int(percent) % 5 == 0:
                            context.application.create_task(
                                progress_msg.edit_text(text)
                            )
                    except Exception as e:
                        logger.error(f"Progress update error: {e}")
        # إعدادات التحميل الأساسية
        ydl_opts = {
            'outtmpl': 'downloads/%(id)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'restrictfilenames': True,
            'progress_hooks': [progress_hook],
        }

        # تحديد إعدادات التنسيق حسب الموقع
        site_specific_settings = {
            'facebook.com': {
                'format': 'best[ext=mp4]',
                'extractor_args': {
                    'facebook': {
                        'format': 'sd',
                        'video': {'format': 'mp4'}
                    }
                }
            },
            'fb.watch': {
                'format': 'best[ext=mp4]',
                'extractor_args': {
                    'facebook': {
                        'format': 'sd',
                        'video': {'format': 'mp4'}
                    }
                }
            },
            'tiktok.com': {
                'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]'
            },
            'twitter.com': {
                'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]'
            },
            'x.com': {
                'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]'
            },
            'instagram.com': {
                'format': 'bestvideo+bestaudio/best',
                'extractor_args': {
                    'instagram': {
                        'format': 'download'
                    }
                }
            },
            'youtube.com': {
                'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]'
            },
            'youtu.be': {
                'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]'
            }
        }

        # تطبيق الإعدادات الخاصة بالموقع
        for site, settings in site_specific_settings.items():
            if site in url:
                ydl_opts.update(settings)
                break
        else:  # الإعدادات الافتراضية للمواقع الأخرى
            ydl_opts.update({
                'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]'
            })

        # إعدادات ما بعد المعالجة حسب نوع التحميل
        if choice == 'video':
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4'
            }]
        else:
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
        'preferredquality': '192',
    }]



        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            original_path = ydl.prepare_filename(info)
            
            # التأكد من وجود الملف بعد التحميل
            if not os.path.exists(original_path):
                # محاولة إيجاد الملف بامتداد مختلف
                base_path = os.path.splitext(original_path)[0]
                for ext in ['.mp4', '.mkv', '.webm', '.m4a', '.mp3']:
                    if os.path.exists(base_path + ext):
                        original_path = base_path + ext
                        break
                else:
                    raise FileNotFoundError(f"لم يتم العثور على الملف: {original_path}")
            
            # إرسال الملف حسب النوع
            if choice == 'video':
                await query.message.reply_video(
                    video=open(original_path, 'rb'),
                    caption=f"🎬 {info.get('title', 'فيديو')}",
                    supports_streaming=True
                )
            else:
                await query.message.reply_audio(
                    audio=open(original_path, 'rb'),
                    title=info.get('title', 'صوت')
                )
            
            # حذف الملف المؤقت
            os.remove(original_path)
            await progress_msg.delete()
            
    except Exception as e:
        logger.error(f"Download error: {e}")
        await query.edit_message_text("❌ حدث خطأ أثناء التحميل. يرجى المحاولة لاحقًا.")

def main() -> None:
    """بدء تشغيل البوت مع إضافة معالج الاستجابة"""
    application = Application.builder().token(TOKEN).build()

    # إضافة المعالجات
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    application.add_handler(CallbackQueryHandler(handle_choice))

    # بدء البوت
    logger.info("✅ البوت يعمل الآن مع الميزات الجديدة...")
    application.run_polling()

if __name__ == "__main__":
    main()