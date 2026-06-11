import os
import time
import asyncio
import threading
import logging
from pyrogram import Client, filters, errors, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from internetarchive import upload, modify_metadata, delete as ia_delete
from http.server import BaseHTTPRequestHandler, HTTPServer

# Logging u samee
logging.basicConfig(level=logging.INFO)

# --- CONFIG (Koyeb Environment Variables) ---
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
IA_ACCESS_KEY = os.getenv("IA_ACCESS_KEY")
IA_SECRET_KEY = os.getenv("IA_SECRET_KEY")

app = Client("archive_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Kaydka ku-meel-gaarka ah
cancel_tasks = {} # Keydka msg_id -> bool
rename_states = {} # Keydka user_id -> identifier

# --- PROGRESS BAR HELPER ---
async def progress(current, total, message, start_time, status):
    # Hubi haddii la cancel-gareeyay
    if message.id in cancel_tasks and cancel_tasks[message.id]:
        app.stop_transmission()
        return

    now = time.time()
    last_edit = getattr(message, "last_edit_time", 0)
    if now - last_edit < 10:
        return

    percentage = current * 100 / total
    completed = int(percentage / 10)
    bar = "■" * completed + "□" * (10 - completed)
    
    # Badhanka Cancel
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel Download", callback_data=f"cancel_{message.id}")]])
    
    try:
        await message.edit_text(
            f"**{status}**: {percentage:.2f}%\n"
            f"[{bar}]\n"
            f"📦 {current/1024/1024:.2f} MB / {total/1024/1024:.2f} MB",
            reply_markup=kb
        )
        message.last_edit_time = now
    except:
        pass

# --- HANDLERS ---

@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply_text("✅ **Bot-kii waa shaqeynayaa!**\n\nIisoo dir filim aan Archive kuu dhigo.")

@app.on_message(filters.video | filters.document)
async def handle_media(client, message):
    status_msg = await message.reply_text("⏳ Isku diyaarinaya soo dejinta...")
    cancel_tasks[status_msg.id] = False
    
    path = None
    try:
        # 1. DOWNLOAD
        path = await message.download(
            progress=progress,
            progress_args=(status_msg, time.time(), "Downloading")
        )

        await status_msg.edit_text("✅ Download dhamaaday. Hadda waxaa bilaabanaya Upload-ka Archive.org...")

        # 2. UPLOAD
        identifier = f"tg_arch_{int(time.time())}_{message.id}"
        file_name = os.path.basename(path)
        
        def do_upload():
            upload(
                identifier, 
                files=[path], 
                metadata={'title': file_name, 'mediatype': 'movies'},
                access_key=IA_ACCESS_KEY, 
                secret_key=IA_SECRET_KEY,
                retries=10
            )

        await asyncio.to_thread(do_upload)

        # 3. SUCCESS BUTTONS
        link = f"https://archive.org/details/{identifier}"
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📝 Rename", callback_data=f"rename_{identifier}"),
                InlineKeyboardButton("🗑 Delete", callback_data=f"delete_{identifier}")
            ],
            [InlineKeyboardButton("📥 Download Link", url=link)]
        ])

        await status_msg.edit_text(
            f"🎉 **Upload Successful!**\n\n**Title:** `{file_name}`\n**ID:** `{identifier}`",
            reply_markup=kb
        )

    except Exception as e:
        error_text = "❌ Download was canceled." if "stop_transmission" in str(e) else f"❌ Error: `{str(e)}`"
        await status_msg.edit_text(error_text)
    
    finally:
        # 4. CLEANUP - Markasta masax faylka
        if path and os.path.exists(path):
            os.remove(path)
        if status_msg.id in cancel_tasks:
            del cancel_tasks[status_msg.id]

# --- CALLBACK QUERIES (BADHAMADA) ---

@app.on_callback_query()
async def cb_handler(client, query):
    data = query.data
    
    if data.startswith("cancel_"):
        msg_id = int(data.split("_")[1])
        cancel_tasks[msg_id] = True
        await query.answer("Canceling download...", show_alert=True)

    elif data.startswith("rename_"):
        ident = data.split("_")[1]
        rename_states[query.from_user.id] = ident
        await query.message.reply_text(f"✏️ Soo dir magaca cusub ee aad rabto in loo bixiyo filimka ID-giisu yahay `{ident}`:")
        await query.answer()

    elif data.startswith("delete_"):
        ident = data.split("_")[1]
        try:
            await asyncio.to_thread(ia_delete, ident, access_key=IA_ACCESS_KEY, secret_key=IA_SECRET_KEY)
            await query.message.edit_text(f"🗑 Filimkii (`{ident}`) si guul ah ayaa looga tirtiray Archive.org!")
        except Exception as e:
            await query.answer(f"Error: {str(e)}", show_alert=True)

# --- RENAME TEXT RECEIVER ---
@app.on_message(filters.text & ~filters.command("start"))
async def rename_text(client, message):
    user_id = message.from_user.id
    if user_id in rename_states:
        ident = rename_states[user_id]
        new_title = message.text
        try:
            await asyncio.to_thread(modify_metadata, ident, metadata={'title': new_title}, access_key=IA_ACCESS_KEY, secret_key=IA_SECRET_KEY)
            await message.reply_text(f"✅ Magaca filimka `{ident}` waxaa loo beddelay: **{new_title}**")
            del rename_states[user_id]
        except Exception as e:
            await message.reply_text(f"❌ Khalad dhacay: {str(e)}")

# --- KOYEB HEALTH CHECK SERVER ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"Bot is Healthy")
    def do_HEAD(self):
        self.send_response(200); self.end_headers()
    def log_message(self, format, *args): return

def run_server():
    server_address = ('0.0.0.0', 8000)
    httpd = HTTPServer(server_address, HealthHandler)
    httpd.serve_forever()

if __name__ == "__main__":
    # Kici Health Server dhinac kale
    threading.Thread(target=run_server, daemon=True).start()
    print("🚀 Bot is starting on Koyeb...")
    app.run()
