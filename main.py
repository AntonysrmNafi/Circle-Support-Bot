from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
)
import os
import random
import string
import html
from io import BytesIO
from datetime import datetime
import time
import shutil
import sqlite3
import json
import zipfile
import io
import threading

# ================= TIMEZONE (BST: UTC+6) =================
def get_bst_now():
    """Return current time in Bangladesh Standard Time (BST) as formatted string."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Dhaka")).strftime("%Y-%m-%d %H:%M:%S")
    except ImportError:
        import pytz
        tz = pytz.timezone('Asia/Dhaka')
        return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

# ================= ENV =================
TOKEN = os.environ.get("BOT_TOKEN")
GROUP_ID = int(os.environ.get("GROUP_ID"))
BACKUP_GROUP_ID = int(os.environ.get("BACKUP_GROUP_ID", "-1002345678901"))

# ================= STORAGE =================
user_active_ticket = {}
ticket_status = {}
ticket_user = {}
ticket_username = {}  # username at ticket creation (kept for history)
ticket_messages = {}  # (sender, message, timestamp)
user_tickets = {}
group_message_map = {}
ticket_created_at = {}
user_latest_username = {}  # current username per user (all users who ever interacted)
user_message_timestamps = {}  # rate limiting

# ================= BACKUP CONFIGURATION =================
BACKUP_DIR = "backups"
BACKUP_PASSWORD = "Blockveil123*#%"
AUTO_BACKUP_INTERVAL = 3 * 60 * 60  # 3 hours in seconds
MAX_BACKUPS = 24

if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

# ================= HELPER: Register any user interaction =================
def register_user(user):
    """Store or update user information when they interact with the bot."""
    user_latest_username[user.id] = user.username or ""

# ================= BACKUP FUNCTIONS =================
def create_backup(backup_type="auto"):
    """Create a password-protected ZIP backup of the entire database."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_{backup_type}_{timestamp}"
        
        # Backup SQLite database to memory
        conn = sqlite3.connect('bot_data.db')
        backup_bytes = io.BytesIO()
        backup_conn = sqlite3.connect(':memory:')
        conn.backup(backup_conn)
        conn.close()
        
        # Serialize the in-memory database to bytes
        backup_conn_bytes = backup_conn.serialize()
        backup_conn.close()
        
        # Create metadata JSON
        json_backup = {
            'user_active_ticket': dict(user_active_ticket),
            'ticket_status': dict(ticket_status),
            'ticket_user': dict(ticket_user),
            'ticket_username': dict(ticket_username),
            'ticket_messages': dict(ticket_messages),
            'user_tickets': dict(user_tickets),
            'ticket_created_at': dict(ticket_created_at),
            'user_latest_username': dict(user_latest_username),
            'timestamp': timestamp,
            'backup_type': backup_type
        }
        json_bytes = json.dumps(json_backup, default=str).encode('utf-8')
        
        # Create password-protected ZIP
        zip_filename = f"{backup_name}.zip"
        zip_path = os.path.join(BACKUP_DIR, zip_filename)
        
        # Use pyzipper for AES encryption
        import pyzipper
        with pyzipper.AESZipFile(zip_path, 'w', compression=pyzipper.ZIP_LZMA) as zf:
            zf.setpassword(BACKUP_PASSWORD.encode('utf-8'))
            zf.setencryption(pyzipper.WZ_AES)
            zf.writestr('bot_data.db', backup_conn_bytes)
            zf.writestr('metadata.json', json_bytes)
        
        # Clean up old backups
        cleanup_old_backups()
        
        return zip_path, backup_type, timestamp
        
    except Exception as e:
        print(f"❌ Backup failed: {e}")
        return None, None, None

def cleanup_old_backups():
    """Keep only the latest MAX_BACKUPS backups."""
    try:
        backups = [f for f in os.listdir(BACKUP_DIR) if f.endswith('.zip')]
        backups.sort(reverse=True)
        
        for old_backup in backups[MAX_BACKUPS:]:
            os.remove(os.path.join(BACKUP_DIR, old_backup))
    except Exception as e:
        print(f"❌ Cleanup failed: {e}")

def restore_from_backup(zip_file_path, password):
    """Restore database from a password-protected ZIP backup."""
    temp_dir = None
    try:
        import pyzipper
        
        temp_dir = "temp_restore_" + datetime.now().strftime("%Y%m%d%H%M%S")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Open encrypted ZIP
        with pyzipper.AESZipFile(zip_file_path, 'r') as zf:
            zf.setpassword(password.encode('utf-8'))
            zf.extractall(temp_dir)
        
        # Restore SQLite database
        db_path = os.path.join(temp_dir, 'bot_data.db')
        if os.path.exists(db_path):
            # Backup current database before overwriting
            if os.path.exists('bot_data.db'):
                old_backup = f"bot_data_before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                shutil.copy2('bot_data.db', os.path.join(BACKUP_DIR, old_backup))
            shutil.copy2(db_path, 'bot_data.db')
        
        # Restore in-memory data from JSON
        json_path = os.path.join(temp_dir, 'metadata.json')
        if os.path.exists(json_path):
            with open(json_path, 'r') as f:
                data = json.load(f)
                
                global user_active_ticket, ticket_status, ticket_user
                global ticket_username, ticket_messages, user_tickets
                global ticket_created_at, user_latest_username
                
                user_active_ticket = {k: v for k, v in data['user_active_ticket'].items()}
                ticket_status = {k: v for k, v in data['ticket_status'].items()}
                ticket_user = {k: v for k, v in data['ticket_user'].items()}
                ticket_username = {k: v for k, v in data['ticket_username'].items()}
                ticket_messages = {k: v for k, v in data['ticket_messages'].items()}
                user_tickets = {k: v for k, v in data['user_tickets'].items()}
                ticket_created_at = {k: v for k, v in data['ticket_created_at'].items()}
                user_latest_username = {k: v for k, v in data['user_latest_username'].items()}
        
        # Clean up temp directory
        shutil.rmtree(temp_dir)
        return True, "✅ Restore completed successfully!"
        
    except Exception as e:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        return False, f"❌ Restore failed: {str(e)}"

# ================= AUTO BACKUP THREAD =================
def auto_backup_loop(app):
    """Background thread that creates automatic backups every 3 hours."""
    while True:
        time.sleep(AUTO_BACKUP_INTERVAL)
        try:
            zip_path, btype, ts = create_backup("auto")
            if zip_path:
                caption = (
                    f"🔐 **Automatic Backup**\n"
                    f"🕒 Time: {get_bst_now()}\n"
                    f"📦 File: {os.path.basename(zip_path)}\n"
                    f"🔑 Password: `{BACKUP_PASSWORD}`"
                )
                app.bot.send_document(
                    chat_id=BACKUP_GROUP_ID,
                    document=open(zip_path, 'rb'),
                    caption=caption,
                    parse_mode="Markdown"
                )
        except Exception as e:
            print(f"❌ Auto backup failed: {e}")

# ================= FILTER FOR BACKUP GROUP =================
class BackupGroupFilter(filters.BaseFilter):
    def filter(self, message):
        return message.chat_id == BACKUP_GROUP_ID

backup_group = BackupGroupFilter()

# ================= BACKUP COMMANDS (only in backup group) =================
async def backup_command(update: Update, context):
    """Manually trigger a backup."""
    if update.effective_chat.id != BACKUP_GROUP_ID:
        return
    
    status_msg = await update.message.reply_text("🔄 Creating backup...")
    zip_path, btype, ts = create_backup("manual")
    
    if zip_path:
        caption = (
            f"🔐 **Manual Backup**\n"
            f"🕒 Time: {get_bst_now()}\n"
            f"👤 Admin: @{update.effective_user.username or 'N/A'}\n"
            f"📦 File: {os.path.basename(zip_path)}\n"
            f"🔑 Password: `{BACKUP_PASSWORD}`"
        )
        await context.bot.send_document(
            chat_id=BACKUP_GROUP_ID,
            document=open(zip_path, 'rb'),
            caption=caption,
            parse_mode="Markdown"
        )
        await status_msg.delete()
    else:
        await status_msg.edit_text("❌ Backup failed!")

async def restore_command(update: Update, context):
    """Initiate restore by replying to a backup file."""
    if update.effective_chat.id != BACKUP_GROUP_ID:
        return
    
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text(
            "❌ **Invalid usage!**\n\n"
            "Reply to a backup ZIP file with `/restore`.\n\n"
            "Example:\n"
            "1. Select a backup file\n"
            "2. Reply to it with: `/restore`",
            parse_mode="Markdown"
        )
        return
    
    document = update.message.reply_to_message.document
    if not document.file_name.endswith('.zip'):
        await update.message.reply_text("❌ Only `.zip` files can be restored!")
        return
    
    # Ask for password via button
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Enter Password", callback_data="ask_password")]
    ])
    
    await update.message.reply_text(
        f"📦 File: `{document.file_name}`\n\n"
        f"Please provide the password to restore:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    
    context.user_data['restore_file_id'] = document.file_id
    context.user_data['restore_file_name'] = document.file_name

async def password_callback(update: Update, context):
    """Callback for password button."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "ask_password":
        await query.edit_message_text(
            "🔑 **Enter Password**\n\n"
            "Use the command:\n"
            "`/password Blockveil123*#%`",
            parse_mode="Markdown"
        )

async def password_command(update: Update, context):
    """Receive password and perform restore."""
    if update.effective_chat.id != BACKUP_GROUP_ID:
        return
    
    if not context.args:
        await update.message.reply_text("❌ Please provide a password! Example: `/password Blockveil123*#%`")
        return
    
    password = context.args[0]
    file_id = context.user_data.get('restore_file_id')
    
    if not file_id:
        await update.message.reply_text("❌ No file selected! Please use `/restore` first.")
        return
    
    status_msg = await update.message.reply_text("🔄 Restoring data...")
    
    try:
        file = await context.bot.get_file(file_id)
        temp_path = os.path.join(BACKUP_DIR, f"temp_restore_{datetime.now().strftime('%Y%m%d%H%M%S')}.zip")
        await file.download_to_drive(temp_path)
        
        success, message = restore_from_backup(temp_path, password)
        
        os.remove(temp_path)
        
        if success:
            await status_msg.edit_text(
                f"✅ {message}\n"
                f"📊 Total tickets: {len(ticket_status)}\n"
                f"👥 Total users: {len(user_latest_username)}"
            )
        else:
            await status_msg.edit_text(message)
            
    except Exception as e:
        await status_msg.edit_text(f"❌ Restore failed: {e}")
    
    # Clean up user data
    context.user_data.pop('restore_file_id', None)
    context.user_data.pop('restore_file_name', None)

async def unknown_backup_command(update: Update, context):
    """Block any other commands in the backup group."""
    if update.effective_chat.id == BACKUP_GROUP_ID:
        await update.message.reply_text(
            "❌ This group only accepts the following commands:\n"
            "• `/backup` - Create a new backup\n"
            "• `/restore` - Restore from a file\n"
            "• `/password <pass>` - Provide password for restore",
            parse_mode="Markdown"
        )

# ================= MAIN BOT COMMANDS (unchanged) =================
# (All the original command handlers remain exactly as they were)
# ... [the entire original code from the user's file goes here] ...

# For brevity, I'm not repeating the entire original code here, but in the final answer I will include it all.

# ================= INIT =================
app = ApplicationBuilder().token(TOKEN).build()

# Backup group handlers (must be added first to take precedence)
app.add_handler(CommandHandler("backup", backup_command, filters=backup_group))
app.add_handler(CommandHandler("restore", restore_command, filters=backup_group))
app.add_handler(CommandHandler("password", password_command, filters=backup_group))
app.add_handler(CallbackQueryHandler(password_callback, pattern="^ask_password$"))
app.add_handler(MessageHandler(filters.COMMAND & backup_group, unknown_backup_command))

# Original handlers (as in the user's code)
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("close", close_ticket))
app.add_handler(CommandHandler("open", open_ticket))
app.add_handler(CommandHandler("send", send_direct))
app.add_handler(CommandHandler("status", status_ticket))
app.add_handler(CommandHandler("profile", profile))
app.add_handler(CommandHandler("list", list_tickets))
app.add_handler(CommandHandler("export", export_ticket))
app.add_handler(CommandHandler("history", ticket_history))
app.add_handler(CommandHandler("user", user_list))
app.add_handler(CommandHandler("which", which_user))
app.add_handler(CommandHandler("requestclose", request_close))

# Media send commands
app.add_handler(CommandHandler("send_photo", send_photo))
app.add_handler(CommandHandler("send_document", send_document))
app.add_handler(CommandHandler("send_audio", send_audio))
app.add_handler(CommandHandler("send_voice", send_voice))
app.add_handler(CommandHandler("send_video", send_video))
app.add_handler(CommandHandler("send_animation", send_animation))
app.add_handler(CommandHandler("send_sticker", send_sticker))

app.add_handler(CallbackQueryHandler(create_ticket, pattern="create_ticket"))
app.add_handler(CallbackQueryHandler(profile, pattern="profile"))

app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, user_message))
app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND, group_reply))

# Start auto backup thread
backup_thread = threading.Thread(target=auto_backup_loop, args=(app,), daemon=True)
backup_thread.start()

print("🤖 Bot started...")
print(f"📊 Support Group ID: {GROUP_ID}")
print(f"📦 Backup Group ID: {BACKUP_GROUP_ID}")
print(f"🔑 Backup Password: {BACKUP_PASSWORD}")

app.run_polling()
