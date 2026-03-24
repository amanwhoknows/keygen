import telebot
import sqlite3
import hmac
import hashlib
import time
import os
from datetime import datetime, timedelta

# --- CONFIGURATION ---
API_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_IDS = [5663906373]
CHANNEL_USERNAME = '@SHADYTOOLS' # Must include the @ symbol
GROUP_USERNAME = '@SHADYCHATGROUP'     # Must include the @ symbol
MASTER_SECRET = os.environ.get('MASTER_SECRET').encode('utf-8')

bot = telebot.TeleBot(API_TOKEN)

# --- DATABASE SETUP ---
conn = sqlite3.connect('/data/users.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS keys (
        user_id INTEGER PRIMARY KEY,
        hwid TEXT,
        last_generated TIMESTAMP
    )
''')
conn.commit()

@bot.message_handler(commands=['backup'])
def handle_backup(message):
    # Security check: Only let admins use this command
    if message.from_user.id not in ADMIN_IDS:
        return

    bot.reply_to(message, "⏳ Fetching your database backup...", parse_mode="Markdown")
    
    try:
        # HARDCODED FIX: Explicitly target the Railway volume path
        with open('/data/users.db', 'rb') as db_file:
            bot.send_document(
                message.chat.id, 
                db_file, 
                caption="📦 **Here is your latest Database Backup!**\n\nKeep this safe.",
                parse_mode="Markdown"
            )
    except Exception as e:
        bot.reply_to(message, f"❌ **Failed to send backup:**\n`{e}`", parse_mode="Markdown")
        
def check_membership(user_id, chat_username):
    """Checks if the user is currently in the specified Telegram chat."""
    try:
        member = bot.get_chat_member(chat_username, user_id)
        # We include 'restricted' in case your group mutes new users temporarily
        return member.status in ['member', 'administrator', 'creator', 'restricted']
    except Exception as e:
        return False

def generate_key(hwid, hours=5):
    """Generates the exact HMAC signature and Hex Timestamp expected by auth.py"""
    expiry_timestamp = int(time.time()) + (hours * 3600)
    expiry_hex = hex(expiry_timestamp)[2:].upper()

    payload = f"{hwid}:{expiry_hex}".encode('utf-8')
    signature_raw = hmac.new(MASTER_SECRET, payload, hashlib.sha256).hexdigest().upper()
    sig_formatted = f"{signature_raw[:4]}-{signature_raw[4:8]}-{signature_raw[8:12]}-{signature_raw[12:16]}"
    
    return f"{sig_formatted}-{expiry_hex}"

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    user_id = message.from_user.id
    
    # Check their status the second they start the bot
    in_channel = check_membership(user_id, CHANNEL_USERNAME)
    in_group = check_membership(user_id, GROUP_USERNAME)

    if not in_channel or not in_group:
        # STEP 1: They haven't joined yet
        text = (
            f"👋 **Welcome to the ShadyMail Keygen!**\n\n"
            f"To get your free 5-Hour Access Key, you must first join our communities:\n\n"
            f"1️⃣ 📢 Channel: {CHANNEL_USERNAME}\n"
            f"2️⃣ 💬 Group: {GROUP_USERNAME}\n\n"
            f"⏳ **Once you have joined BOTH, type /start again!**"
        )
        bot.reply_to(message, text, parse_mode="Markdown")
    else:
        # STEP 2: They are verified, ask for HWID
        text = (
            f"✅ **Verification Complete!**\n\n"
            f"Thank you for joining the community.\n\n"
            f"💻 **Please paste your HWID into this chat now to generate your free 5-hour key.**\n"
            f"*(Note: Limit 1 HWID per user. 24-hour cooldown).* "
        )
        bot.reply_to(message, text, parse_mode="Markdown")
@bot.message_handler(commands=['broadcast'])
def handle_broadcast(message):
    # Security check: Only let admins use this command
    if message.from_user.id not in ADMIN_IDS:
        return

    # Remove the word '/broadcast' from the message they typed
    text_to_send = message.text.replace('/broadcast', '').strip()
    
    if not text_to_send:
        bot.reply_to(message, "⚠️ **Usage:** `/broadcast Your message goes here`", parse_mode="Markdown")
        return

    # Fetch every user ID from our database
    cursor.execute('SELECT user_id FROM keys')
    users = cursor.fetchall()

    if not users:
        bot.reply_to(message, "❌ No users found in the database.")
        return

    bot.reply_to(message, f"⏳ **Broadcasting to {len(users)} users...** Please wait.", parse_mode="Markdown")

    success_count = 0
    fail_count = 0

    # Loop through everyone and send the message
    for user in users:
        uid = user[0]
        try:
            bot.send_message(uid, text_to_send, parse_mode="Markdown")
            success_count += 1
            # TELEGRAM LIMIT: Bots can only send ~30 messages per second. 
            # This tiny pause prevents Telegram from banning your bot for spam.
            time.sleep(0.05) 
        except Exception:
            # If it fails, it usually means the user blocked the bot or deleted their account
            fail_count += 1

    bot.reply_to(
        message, 
        f"✅ **Broadcast Complete!**\n\n"
        f"📩 **Sent Successfully:** `{success_count}`\n"
        f"🚫 **Failed (Blocked bot):** `{fail_count}`",
        parse_mode="Markdown"
    )
    
@bot.message_handler(func=lambda message: True)
def handle_keygen(message):
    user_id = message.from_user.id
    hwid = message.text.strip()

    # 1. Validate HWID format
    if len(hwid) < 10 or " " in hwid:
        bot.reply_to(message, "⚠️ Invalid HWID format. Please copy it exactly from the software.")
        return

    # 2. Dual Force Join Check
    in_channel = check_membership(user_id, CHANNEL_USERNAME)
    in_group = check_membership(user_id, GROUP_USERNAME)

    if not in_channel or not in_group:
        bot.reply_to(
            message, 
            f"❌ **Access Denied**\n\nYou must join BOTH to use this bot:\n"
            f"📢 Channel: {CHANNEL_USERNAME}\n"
            f"💬 Group: {GROUP_USERNAME}\n\n"
            f"Join both and send your HWID again!", 
            parse_mode="Markdown"
        )
        return

    # 3. Database Checks (Cooldowns & HWID Locks)
    cursor.execute('SELECT hwid, last_generated FROM keys WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    now = datetime.now()

    if row:
        saved_hwid, last_generated_str = row
        last_generated = datetime.fromisoformat(last_generated_str)

        # Enforce 1 HWID per user
        if saved_hwid != hwid:
            bot.reply_to(message, f"🚫 **HWID Locked**\nYour account is locked to HWID:\n`{saved_hwid}`\n\nYou cannot generate keys for a different computer.", parse_mode="Markdown")
            return

        # Enforce 24-Hour Cooldown
        time_since_last = now - last_generated
        if time_since_last < timedelta(hours=24):
            remaining = timedelta(hours=24) - time_since_last
            hours, remainder = divmod(remaining.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            bot.reply_to(message, f"⏳ **Cooldown Active**\n\nYou must wait {hours}h {minutes}m before generating another free key.")
            return
            
        # Update timestamp for this new generation
        cursor.execute('UPDATE keys SET last_generated = ? WHERE user_id = ?', (now.isoformat(), user_id))
    else:
        # First-time user setup
        cursor.execute('INSERT INTO keys (user_id, hwid, last_generated) VALUES (?, ?, ?)', (user_id, hwid, now.isoformat()))
    
    conn.commit()

    # 4. Generate the Key
    new_key = generate_key(hwid, hours=5)
    
    response = (
        f"✅ **Free License Generated!**\n\n"
        f"**HWID:** `{hwid}`\n"
        f"**Key:** `{new_key}`\n"
        f"**Duration:** `5 Hours`\n\n"
        f"Enjoy the tool! Purchase a lifetime key in our channel for unlimited access."
    )
    bot.reply_to(message, response, parse_mode="Markdown")

print("[*] Public Keygen Bot is running with Dual-Join verification...")
bot.infinity_polling()
