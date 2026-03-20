# -*- coding: utf-8 -*-
import os
import sys
import asyncio
import sqlite3
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError, SessionPasswordNeededError
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot API credentials
BOT_API_ID = int(os.getenv('API_ID'))
BOT_API_HASH = os.getenv('API_HASH')
MAIN_BOT_TOKEN = os.getenv('MAIN_BOT_TOKEN')
LOGGER_BOT_TOKEN = os.getenv('LOGGER_BOT_TOKEN')

# Admin user IDs
ADMINS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]

# ============================================
# DATABASE CLASS
# ============================================
class Database:
    def __init__(self, db_name='premium_bot.db'):
        self.db_name = db_name
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_name, timeout=30.0, check_same_thread=False)
        conn.execute('PRAGMA journal_mode=WAL')
        return conn

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                phone TEXT,
                api_id INTEGER,
                api_hash TEXT,
                session_string TEXT,
                promo_message TEXT,
                is_active INTEGER DEFAULT 0,
                subscription_expiry TEXT,
                delay INTEGER DEFAULT 30,
                cycle_delay INTEGER DEFAULT 120
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS redeem_codes (
                code TEXT PRIMARY KEY,
                days INTEGER,
                used INTEGER DEFAULT 0,
                used_by INTEGER,
                used_at TEXT
            )
        ''')

        conn.commit()
        conn.close()

    def add_code(self, code, days):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO redeem_codes (code, days) VALUES (?, ?)', (code, days))
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            conn.close()
            return False

    def get_unused_codes(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT code, days FROM redeem_codes WHERE used = 0')
        result = cursor.fetchall()
        conn.close()
        return result

    def redeem_code(self, code, user_id, username):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT days, used FROM redeem_codes WHERE code = ?', (code,))
        result = cursor.fetchone()

        if not result:
            conn.close()
            return False, "Invalid code"

        days, used = result
        if used:
            conn.close()
            return False, "Code already used"

        expiry = datetime.now() + timedelta(days=days)
        expiry_str = expiry.strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute('UPDATE redeem_codes SET used = 1, used_by = ?, used_at = ? WHERE code = ?',
                      (user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), code))

        cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
        if cursor.fetchone():
            cursor.execute('UPDATE users SET subscription_expiry = ?, username = ? WHERE user_id = ?',
                          (expiry_str, username, user_id))
        else:
            cursor.execute('INSERT INTO users (user_id, username, subscription_expiry) VALUES (?, ?, ?)',
                          (user_id, username, expiry_str))

        conn.commit()
        conn.close()
        return True, days

    def is_premium(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT subscription_expiry FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()

        if not result or not result[0]:
            return False

        expiry = datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
        return datetime.now() < expiry

    def get_premium_users(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, subscription_expiry FROM users WHERE subscription_expiry IS NOT NULL')
        users = []
        for row in cursor.fetchall():
            try:
                expiry = datetime.strptime(row[2], '%Y-%m-%d %H:%M:%S')
                if datetime.now() < expiry:
                    users.append(row)
            except:
                pass
        conn.close()
        return users

    def revoke_premium(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET subscription_expiry = NULL WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()

    def save_session(self, user_id, phone, api_id, api_hash, session_string):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET phone = ?, api_id = ?, api_hash = ?, session_string = ? WHERE user_id = ?',
                      (phone, api_id, api_hash, session_string, user_id))
        conn.commit()
        conn.close()

    def get_user(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''SELECT user_id, phone, api_id, api_hash, session_string,
                         promo_message, is_active, delay, cycle_delay
                         FROM users WHERE user_id = ?''', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result

    def set_promo_message(self, user_id, message):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET promo_message = ? WHERE user_id = ?', (message, user_id))
        conn.commit()
        conn.close()

    def set_campaign_status(self, user_id, status):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET is_active = ? WHERE user_id = ?', (status, user_id))
        conn.commit()
        conn.close()

    def set_delay(self, user_id, delay):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET delay = ? WHERE user_id = ?', (delay, user_id))
        conn.commit()
        conn.close()

    def set_cycle_delay(self, user_id, cycle_delay):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET cycle_delay = ? WHERE user_id = ?', (cycle_delay, user_id))
        conn.commit()
        conn.close()

    def get_days_remaining(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT subscription_expiry FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()

        if not result or not result[0]:
            return 0

        expiry = datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
        remaining = expiry - datetime.now()
        return max(0, remaining.days)

# ============================================
# LOGGER CLASS
# ============================================
class Logger:
    def __init__(self, bot_token):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def send_log(self, chat_id, message):
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }
            requests.post(url, data=data, timeout=10)
        except Exception as e:
            print(f"Logger error: {e}")

# ============================================
# PROMO BOT CLASS
# ============================================
class PromoBot:
    def __init__(self):
        self.bot = TelegramClient('bot_session', BOT_API_ID, BOT_API_HASH)
        self.db = Database()
        self.logger = Logger(LOGGER_BOT_TOKEN)
        self.tasks = {}
        self.login_states = {}
        self.pending_message = {}   # Track users waiting to set message
        self.pending_delay = {}     # Track users waiting to set delay

    async def start(self):
        await self.bot.start(bot_token=MAIN_BOT_TOKEN)
        print("✓ Main bot started")
        self.register_handlers()
        print("✓ Bot is running...")
        await self.bot.run_until_disconnected()

    def register_handlers(self):

        # ==================== ADMIN COMMANDS ====================

        @self.bot.on(events.NewMessage(pattern='/addcode'))
        async def addcode(event):
            if event.sender_id not in ADMINS:
                return
            try:
                parts = event.message.text.split()
                if len(parts) != 3:
                    await event.reply("❌ Usage: /addcode <CODE> <DAYS>")
                    return
                code = parts[1]
                days = int(parts[2])
                if self.db.add_code(code, days):
                    await event.reply(f"✅ Code added!\n\nCode: `{code}`\nDuration: {days} days", parse_mode='md')
                else:
                    await event.reply("❌ Code already exists")
            except ValueError:
                await event.reply("❌ Days must be a number")
            except Exception as e:
                await event.reply(f"❌ Error: {e}")

        @self.bot.on(events.NewMessage(pattern='/codes'))
        async def codes(event):
            if event.sender_id not in ADMINS:
                return
            codes_list = self.db.get_unused_codes()
            if not codes_list:
                await event.reply("📋 No unused codes available")
                return
            msg = "📋 **Unused Codes:**\n\n"
            for code, days in codes_list:
                msg += f"• `{code}` - {days} days\n"
            await event.reply(msg, parse_mode='md')

        @self.bot.on(events.NewMessage(pattern='/users'))
        async def users(event):
            if event.sender_id not in ADMINS:
                return
            users_list = self.db.get_premium_users()
            if not users_list:
                await event.reply("👥 No active premium users")
                return
            msg = "👥 **Active Premium Users:**\n\n"
            for user_id, username, expiry in users_list:
                expiry_date = datetime.strptime(expiry, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d')
                username_str = f"@{username}" if username else f"ID: {user_id}"
                msg += f"• {username_str}\n  Expires: {expiry_date}\n\n"
            await event.reply(msg, parse_mode='md')

        @self.bot.on(events.NewMessage(pattern='/revoke'))
        async def revoke(event):
            if event.sender_id not in ADMINS:
                return
            try:
                parts = event.message.text.split()
                if len(parts) != 2:
                    await event.reply("❌ Usage: /revoke <user_id>")
                    return
                user_id = int(parts[1])
                self.db.revoke_premium(user_id)
                if user_id in self.tasks:
                    self.tasks[user_id].cancel()
                    del self.tasks[user_id]
                await event.reply(f"✅ Premium revoked for user {user_id}")
                try:
                    await self.bot.send_message(user_id, "⚠️ Your premium subscription has been revoked by admin.")
                except:
                    pass
            except ValueError:
                await event.reply("❌ Invalid user ID")
            except Exception as e:
                await event.reply(f"❌ Error: {e}")

        # ==================== USER COMMANDS ====================

        @self.bot.on(events.NewMessage(pattern='/start'))
        async def start(event):
            user_id = event.sender_id
            if not self.db.is_premium(user_id):
                await event.reply(
                    "🔒 **Subscription Not Active**\n\n"
                    "This is a premium bot. Contact the owner to get a redeem code.\n\n"
                    "Use /redeem <CODE> to activate your subscription."
                )
                return
            await event.reply(
                "✅ **Welcome to Premium Promo Bot!**\n\n"
                "Available Commands:\n"
                "/login - Login with your Telegram account\n"
                "/setmessage - Set promotional message\n"
                "/setdelay - Set delay between messages\n"
                "/startcampaign - Start sending campaign\n"
                "/stopcampaign - Stop campaign\n"
                "/status - Check campaign status\n"
                "/premium - Check subscription status"
            )

        @self.bot.on(events.NewMessage(pattern='/redeem'))
        async def redeem(event):
            user_id = event.sender_id
            username = event.sender.username
            try:
                parts = event.message.text.split()
                if len(parts) != 2:
                    await event.reply("❌ Usage: /redeem <CODE>")
                    return
                code = parts[1]
                success, result = self.db.redeem_code(code, user_id, username)
                if success:
                    await event.reply(
                        f"🎉 **Subscription Activated!**\n\n"
                        f"Duration: {result} days\n\n"
                        f"Use /start to see available commands."
                    )
                else:
                    await event.reply(f"❌ {result}")
            except Exception as e:
                await event.reply(f"❌ Error: {e}")

        @self.bot.on(events.NewMessage(pattern='/premium'))
        async def premium(event):
            user_id = event.sender_id
            if not self.db.is_premium(user_id):
                await event.reply("❌ You don't have an active subscription.")
                return
            days = self.db.get_days_remaining(user_id)
            await event.reply(f"✅ **Premium Active**\n\n🗓️ Days remaining: {days}")

        @self.bot.on(events.NewMessage(pattern='/login'))
        async def login(event):
            user_id = event.sender_id
            if not self.db.is_premium(user_id):
                await event.reply("❌ Premium subscription required. Use /redeem <CODE>")
                return

            # FIX: Check if already logged in
            user = self.db.get_user(user_id)
            if user and user[4]:  # session_string exists
                await event.reply("✅ You're already logged in!\n\nUse /status to check your campaign.")
                return

            await event.reply(
                "🔑 **Login to Your Telegram Account**\n\n"
                "First, you need your API credentials from Telegram:\n\n"
                "1. Visit: https://my.telegram.org/apps\n"
                "2. Login with your phone number\n"
                "3. Create an app (if you haven't)\n"
                "4. Copy your API_ID and API_HASH\n\n"
                "📝 Send them in this format:\n"
                "`API_ID API_HASH`\n\n"
                "Example: `12345678 abcdef1234567890abcdef12`\n\n"
                "Send /cancel to cancel"
            )
            self.login_states[user_id] = {'step': 'waiting_api'}

            @self.bot.on(events.NewMessage(from_users=user_id))
            async def api_handler(api_event):
                if user_id not in self.login_states:
                    self.bot.remove_event_handler(api_handler)
                    return
                if self.login_states[user_id].get('step') != 'waiting_api':
                    return
                if api_event.message.text.startswith('/cancel'):
                    self.bot.remove_event_handler(api_handler)
                    del self.login_states[user_id]
                    await api_event.reply("❌ Login cancelled")
                    return
                if api_event.message.text.startswith('/'):
                    return

                self.bot.remove_event_handler(api_handler)

                try:
                    parts = api_event.message.text.strip().split()
                    if len(parts) != 2:
                        await api_event.reply("❌ Invalid format. Please send: `API_ID API_HASH`\n\nUse /login to try again")
                        del self.login_states[user_id]
                        return

                    api_id = int(parts[0])
                    api_hash = parts[1]

                    self.login_states[user_id]['api_id'] = api_id
                    self.login_states[user_id]['api_hash'] = api_hash
                    self.login_states[user_id]['step'] = 'waiting_phone'

                    await api_event.reply("✅ API credentials received!\n\n📱 Now send your phone number (with country code)\n\nExample: `+911234567890`\n\nSend /cancel to cancel")

                    @self.bot.on(events.NewMessage(from_users=user_id))
                    async def phone_handler(phone_event):
                        if user_id not in self.login_states:
                            self.bot.remove_event_handler(phone_handler)
                            return
                        if self.login_states[user_id].get('step') != 'waiting_phone':
                            return
                        if phone_event.message.text.startswith('/cancel'):
                            self.bot.remove_event_handler(phone_handler)
                            del self.login_states[user_id]
                            await phone_event.reply("❌ Login cancelled")
                            return
                        if not phone_event.message.text.startswith('+'):
                            await phone_event.reply("❌ Phone must start with + and country code\nExample: +911234567890")
                            return

                        self.bot.remove_event_handler(phone_handler)
                        phone = phone_event.message.text.strip()
                        api_id = self.login_states[user_id]['api_id']
                        api_hash = self.login_states[user_id]['api_hash']

                        try:
                            user_client = TelegramClient(StringSession(), api_id, api_hash)
                            await user_client.connect()
                            await user_client.send_code_request(phone)

                            self.login_states[user_id]['client'] = user_client
                            self.login_states[user_id]['phone'] = phone
                            self.login_states[user_id]['step'] = 'waiting_code'

                            await phone_event.reply("📨 Code sent! Please enter the verification code:\n\nSend /cancel to cancel")

                            @self.bot.on(events.NewMessage(from_users=user_id))
                            async def code_handler(code_event):
                                if user_id not in self.login_states:
                                    self.bot.remove_event_handler(code_handler)
                                    return
                                if self.login_states[user_id].get('step') != 'waiting_code':
                                    return
                                if code_event.message.text.startswith('/cancel'):
                                    self.bot.remove_event_handler(code_handler)
                                    try:
                                        await self.login_states[user_id]['client'].disconnect()
                                    except:
                                        pass
                                    del self.login_states[user_id]
                                    await code_event.reply("❌ Login cancelled")
                                    return
                                if not code_event.message.text.replace('-', '').replace(' ', '').isdigit():
                                    await code_event.reply("❌ Please enter only the numeric code")
                                    return

                                self.bot.remove_event_handler(code_handler)
                                code = code_event.message.text.strip()
                                user_client = self.login_states[user_id]['client']
                                phone = self.login_states[user_id]['phone']
                                api_id = self.login_states[user_id]['api_id']
                                api_hash = self.login_states[user_id]['api_hash']

                                try:
                                    await user_client.sign_in(phone, code)
                                except SessionPasswordNeededError:
                                    self.login_states[user_id]['step'] = 'waiting_password'
                                    await code_event.reply("🔐 2FA enabled. Please send your password:\n\nSend /cancel to cancel")

                                    @self.bot.on(events.NewMessage(from_users=user_id))
                                    async def password_handler(pwd_event):
                                        if user_id not in self.login_states:
                                            self.bot.remove_event_handler(password_handler)
                                            return
                                        if self.login_states[user_id].get('step') != 'waiting_password':
                                            return
                                        if pwd_event.message.text.startswith('/cancel'):
                                            self.bot.remove_event_handler(password_handler)
                                            try:
                                                await self.login_states[user_id]['client'].disconnect()
                                            except:
                                                pass
                                            del self.login_states[user_id]
                                            await pwd_event.reply("❌ Login cancelled")
                                            return
                                        if pwd_event.message.text.startswith('/'):
                                            return

                                        self.bot.remove_event_handler(password_handler)
                                        password = pwd_event.message.text.strip()
                                        user_client = self.login_states[user_id]['client']
                                        phone = self.login_states[user_id]['phone']
                                        api_id = self.login_states[user_id]['api_id']
                                        api_hash = self.login_states[user_id]['api_hash']

                                        try:
                                            await user_client.sign_in(password=password)
                                            session_string = user_client.session.save()
                                            self.db.save_session(user_id, phone, api_id, api_hash, session_string)
                                            await pwd_event.reply("✅ Login successful! Use /start to continue.")
                                            await user_client.disconnect()
                                            del self.login_states[user_id]
                                            self.logger.send_log(user_id, f"✅ Account added: {phone}")
                                        except Exception as e:
                                            await pwd_event.reply(f"❌ Login failed: {e}\n\nUse /login to try again")
                                            await user_client.disconnect()
                                            del self.login_states[user_id]
                                    return

                                except Exception as e:
                                    await code_event.reply(f"❌ Login failed: {e}\n\nUse /login to try again")
                                    await user_client.disconnect()
                                    del self.login_states[user_id]
                                    return

                                session_string = user_client.session.save()
                                self.db.save_session(user_id, phone, api_id, api_hash, session_string)
                                await code_event.reply("✅ Login successful! Use /start to continue.")
                                await user_client.disconnect()
                                del self.login_states[user_id]
                                self.logger.send_log(user_id, f"✅ Account added: {phone}")

                        except Exception as e:
                            await phone_event.reply(f"❌ Error: {e}\n\nUse /login to try again")
                            if user_id in self.login_states:
                                del self.login_states[user_id]

                except ValueError:
                    await api_event.reply("❌ Invalid API_ID. It must be a number.\n\nUse /login to try again")
                    if user_id in self.login_states:
                        del self.login_states[user_id]
                except Exception as e:
                    await api_event.reply(f"❌ Error: {e}\n\nUse /login to try again")
                    if user_id in self.login_states:
                        del self.login_states[user_id]

        @self.bot.on(events.NewMessage(pattern='/setmessage'))
        async def setmessage(event):
            user_id = event.sender_id
            if not self.db.is_premium(user_id):
                await event.reply("❌ Premium subscription required.")
                return
            self.pending_message[user_id] = True
            await event.reply("💬 Please send the promotional message you want to broadcast:")

        @self.bot.on(events.NewMessage(pattern='/setdelay'))
        async def setdelay(event):
            user_id = event.sender_id
            if not self.db.is_premium(user_id):
                await event.reply("❌ Premium subscription required.")
                return
            self.pending_delay[user_id] = True
            await event.reply(
                "⏱️ **Set Delays:**\n\n"
                "Send in format: `MESSAGE_DELAY CYCLE_DELAY`\n\n"
                "Message Delay (seconds): 30, 45, or 60\n"
                "Cycle Delay (minutes): 2, 5, or 10\n\n"
                "Example: `45 5`",
                parse_mode='md'
            )

        @self.bot.on(events.NewMessage(pattern='/startcampaign'))
        async def startcampaign(event):
            user_id = event.sender_id
            if not self.db.is_premium(user_id):
                await event.reply("❌ Premium subscription required.")
                return
            user = self.db.get_user(user_id)
            if not user or not user[4]:
                await event.reply("❌ Please login first using /login")
                return
            if not user[5]:
                await event.reply("❌ Please set a message first using /setmessage")
                return
            if user_id in self.tasks:
                await event.reply("⚠️ Campaign already running!")
                return
            self.db.set_campaign_status(user_id, 1)
            task = asyncio.create_task(self.run_campaign(user_id))
            self.tasks[user_id] = task
            await event.reply("🚀 Campaign started!")
            self.logger.send_log(user_id, "🚀 Campaign started")

        @self.bot.on(events.NewMessage(pattern='/stopcampaign'))
        async def stopcampaign(event):
            user_id = event.sender_id
            if not self.db.is_premium(user_id):
                await event.reply("❌ Premium subscription required.")
                return
            if user_id not in self.tasks:
                await event.reply("⚠️ No campaign running!")
                return
            self.db.set_campaign_status(user_id, 0)
            self.tasks[user_id].cancel()
            del self.tasks[user_id]
            await event.reply("🛑 Campaign stopped!")
            self.logger.send_log(user_id, "🛑 Campaign stopped")

        # Global handler to catch setmessage and setdelay responses
        @self.bot.on(events.NewMessage())
        async def global_handler(event):
            user_id = event.sender_id
            text = event.message.text
            if not text or text.startswith('/'):
                return

            # Handle pending setmessage
            if user_id in self.pending_message:
                del self.pending_message[user_id]
                self.db.set_promo_message(user_id, text)
                await event.reply("✅ Promotional message saved!\n\nUse /startcampaign to begin.")
                return

            # Handle pending setdelay
            if user_id in self.pending_delay:
                del self.pending_delay[user_id]
                try:
                    parts = text.split()
                    msg_delay = int(parts[0])
                    cycle_delay = int(parts[1])
                    if msg_delay not in [30, 45, 60]:
                        await event.reply("❌ Message delay must be 30, 45, or 60 seconds")
                        return
                    if cycle_delay not in [2, 5, 10]:
                        await event.reply("❌ Cycle delay must be 2, 5, or 10 minutes")
                        return
                    self.db.set_delay(user_id, msg_delay)
                    self.db.set_cycle_delay(user_id, cycle_delay * 60)
                    await event.reply(
                        f"✅ Delays set!\n\n"
                        f"Message Delay: {msg_delay}s\n"
                        f"Cycle Delay: {cycle_delay}m"
                    )
                except (ValueError, IndexError):
                    await event.reply("❌ Invalid format. Use: MESSAGE_DELAY CYCLE_DELAY\n\nExample: 45 5")
                return

        # FIX: user_id was undefined in original code
        @self.bot.on(events.NewMessage(pattern='/status'))
        async def status(event):
            user_id = event.sender_id  # BUG FIX: was missing in original
            if not self.db.is_premium(user_id):
                await event.reply("❌ Premium subscription required.")
                return
            user = self.db.get_user(user_id)
            if not user:
                await event.reply("❌ No data found. Please use /login first.")
                return
            status_text = "🟢 Running" if user[6] else "🔴 Stopped"
            phone = user[1] if user[1] else "Not set"
            message_preview = (user[5][:50] + '...') if user[5] and len(user[5]) > 50 else (user[5] or "Not set")
            await event.reply(
                f"📊 **Campaign Status**\n\n"
                f"Status: {status_text}\n"
                f"Phone: {phone}\n"
                f"Message: {message_preview}\n"
                f"Delay: {user[7]}s\n"
                f"Cycle Delay: {user[8] // 60}m",
                parse_mode='md'
            )

    async def run_campaign(self, user_id):
        try:
            user = self.db.get_user(user_id)
            phone = user[1]
            api_id = user[2]
            api_hash = user[3]
            session_string = user[4]
            message = user[5]
            msg_delay = user[7]
            cycle_delay = user[8]

            user_client = TelegramClient(StringSession(session_string), api_id, api_hash)
            await user_client.connect()

            dialogs = await user_client.get_dialogs()
            groups = [d for d in dialogs if d.is_group]

            if not groups:
                await self.bot.send_message(user_id, "❌ No groups found!")
                self.db.set_campaign_status(user_id, 0)
                await user_client.disconnect()
                return

            await self.bot.send_message(user_id, f"✅ Found {len(groups)} groups. Starting campaign...")

            while self.db.get_user(user_id)[6]:
                sent = 0
                failed = 0

                # FIX: Refresh message each round in case user updated it
                user = self.db.get_user(user_id)
                message = user[5]

                for group in groups:
                    if not self.db.get_user(user_id)[6]:
                        break
                    try:
                        await user_client.send_message(group.entity, message)
                        sent += 1
                        log_msg = f"[{phone}] ✓ Sent to {group.name}"
                        self.logger.send_log(user_id, log_msg)
                        print(log_msg)
                        await asyncio.sleep(msg_delay)

                    except FloodWaitError as e:
                        wait_time = e.seconds
                        await self.bot.send_message(user_id, f"⚠️ FloodWait: Waiting {wait_time}s...")
                        await asyncio.sleep(wait_time)

                    except Exception as e:
                        failed += 1
                        log_msg = f"[{phone}] ✗ Failed {group.name}: {str(e)}"
                        self.logger.send_log(user_id, log_msg)
                        print(log_msg)
                        await asyncio.sleep(10)

                await self.bot.send_message(
                    user_id,
                    f"✅ **Round Complete!**\n\n"
                    f"Sent: {sent}\n"
                    f"Failed: {failed}\n\n"
                    f"Next round in {cycle_delay // 60} minutes..."
                )
                print(f"User {user_id}: Round complete. Waiting {cycle_delay}s...")
                await asyncio.sleep(cycle_delay)

            await user_client.disconnect()

        except asyncio.CancelledError:
            print(f"User {user_id}: Campaign cancelled")
        except Exception as e:
            print(f"User {user_id}: Campaign error: {e}")
            self.db.set_campaign_status(user_id, 0)
            if user_id in self.tasks:
                del self.tasks[user_id]
            try:
                await self.bot.send_message(user_id, f"❌ Campaign stopped due to error:\n{str(e)}")
            except:
                pass

# ============================================
# MAIN FUNCTION
# ============================================
async def main():
    print("=" * 50)
    print("Premium Telegram Promotional Bot")
    print("=" * 50)

    # Validate env vars
    missing = []
    if not os.getenv('API_ID'): missing.append('API_ID')
    if not os.getenv('API_HASH'): missing.append('API_HASH')
    if not os.getenv('MAIN_BOT_TOKEN'): missing.append('MAIN_BOT_TOKEN')
    if not os.getenv('LOGGER_BOT_TOKEN'): missing.append('LOGGER_BOT_TOKEN')
    if not os.getenv('ADMIN_IDS'): missing.append('ADMIN_IDS')

    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        sys.exit(1)

    bot = PromoBot()
    await bot.start()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nBot stopped by user")
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        sys.exit(1)
