# -*- coding: utf-8 -*-
import os
import sys
import asyncio
import sqlite3
import json
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError, SessionPasswordNeededError
import requests
from dotenv import load_dotenv

load_dotenv()

BOT_API_ID = int(os.getenv('API_ID'))
BOT_API_HASH = os.getenv('API_HASH')
MAIN_BOT_TOKEN = os.getenv('MAIN_BOT_TOKEN')
LOGGER_BOT_TOKEN = os.getenv('LOGGER_BOT_TOKEN')
ADMINS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]

# ============================================
# KEYBOARD HELPERS
# ============================================
def make_keyboard(buttons):
    return {"inline_keyboard": buttons}

def dashboard_keyboard():
    return make_keyboard([
        [{"text": "👤 My Account", "callback_data": "account"},
         {"text": "📊 Status", "callback_data": "status"}],
        [{"text": "💬 Set Message", "callback_data": "setmessage"},
         {"text": "⏱️ Set Delay", "callback_data": "setdelay"}],
        [{"text": "🚀 Start Campaign", "callback_data": "startcampaign"},
         {"text": "🛑 Stop Campaign", "callback_data": "stopcampaign"}],
        [{"text": "🔑 Login", "callback_data": "login"},
         {"text": "💎 Premium", "callback_data": "premium"}],
        [{"text": "🚪 Logout", "callback_data": "logout"}]
    ])

def back_keyboard():
    return make_keyboard([[{"text": "🏠 Dashboard", "callback_data": "dashboard"}]])

def bot_api(method, data):
    url = f"https://api.telegram.org/bot{MAIN_BOT_TOKEN}/{method}"
    try:
        requests.post(url, data={k: json.dumps(v) if isinstance(v, dict) else v for k, v in data.items()}, timeout=10)
    except Exception as e:
        print(f"Bot API error: {e}")

def send_msg(chat_id, text, keyboard=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if keyboard:
        data["reply_markup"] = json.dumps(keyboard)
    bot_api("sendMessage", data)

def edit_msg(chat_id, msg_id, text, keyboard=None):
    data = {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "Markdown"}
    if keyboard:
        data["reply_markup"] = json.dumps(keyboard)
    bot_api("editMessageText", data)

# ============================================
# DATABASE
# ============================================
class Database:
    def __init__(self, db_name='premium_bot.db'):
        self.db_name = db_name
        self.init_db()

    def get_conn(self):
        conn = sqlite3.connect(self.db_name, timeout=30.0, check_same_thread=False)
        conn.execute('PRAGMA journal_mode=WAL')
        return conn

    def init_db(self):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, phone TEXT,
            api_id INTEGER, api_hash TEXT, session_string TEXT,
            promo_message TEXT, is_active INTEGER DEFAULT 0,
            subscription_expiry TEXT, delay INTEGER DEFAULT 30,
            cycle_delay INTEGER DEFAULT 120)''')
        c.execute('''CREATE TABLE IF NOT EXISTS redeem_codes (
            code TEXT PRIMARY KEY, days INTEGER, used INTEGER DEFAULT 0,
            used_by INTEGER, used_at TEXT)''')
        conn.commit()
        conn.close()

    def add_code(self, code, days):
        conn = self.get_conn()
        c = conn.cursor()
        try:
            c.execute('INSERT INTO redeem_codes (code, days) VALUES (?, ?)', (code, days))
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            conn.close()
            return False

    def get_unused_codes(self):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT code, days FROM redeem_codes WHERE used = 0')
        r = c.fetchall()
        conn.close()
        return r

    def redeem_code(self, code, user_id, username):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT days, used FROM redeem_codes WHERE code = ?', (code,))
        result = c.fetchone()
        if not result:
            conn.close()
            return False, "Invalid code"
        days, used = result
        if used:
            conn.close()
            return False, "Code already used"
        expiry = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        c.execute('UPDATE redeem_codes SET used=1, used_by=?, used_at=? WHERE code=?',
                  (user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), code))
        c.execute('SELECT user_id FROM users WHERE user_id=?', (user_id,))
        if c.fetchone():
            c.execute('UPDATE users SET subscription_expiry=?, username=? WHERE user_id=?', (expiry, username, user_id))
        else:
            c.execute('INSERT INTO users (user_id, username, subscription_expiry) VALUES (?,?,?)', (user_id, username, expiry))
        conn.commit()
        conn.close()
        return True, days

    def is_premium(self, user_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT subscription_expiry FROM users WHERE user_id=?', (user_id,))
        r = c.fetchone()
        conn.close()
        if not r or not r[0]:
            return False
        return datetime.now() < datetime.strptime(r[0], '%Y-%m-%d %H:%M:%S')

    def get_premium_users(self):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT user_id, username, subscription_expiry FROM users WHERE subscription_expiry IS NOT NULL')
        users = []
        for row in c.fetchall():
            try:
                if datetime.now() < datetime.strptime(row[2], '%Y-%m-%d %H:%M:%S'):
                    users.append(row)
            except: pass
        conn.close()
        return users

    def revoke_premium(self, user_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('UPDATE users SET subscription_expiry=NULL WHERE user_id=?', (user_id,))
        conn.commit()
        conn.close()

    def save_session(self, user_id, phone, api_id, api_hash, session_string):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('UPDATE users SET phone=?, api_id=?, api_hash=?, session_string=? WHERE user_id=?',
                  (phone, api_id, api_hash, session_string, user_id))
        conn.commit()
        conn.close()

    def get_user(self, user_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT user_id, phone, api_id, api_hash, session_string, promo_message, is_active, delay, cycle_delay FROM users WHERE user_id=?', (user_id,))
        r = c.fetchone()
        conn.close()
        return r

    def set_promo_message(self, user_id, message):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('UPDATE users SET promo_message=? WHERE user_id=?', (message, user_id))
        conn.commit()
        conn.close()

    def set_campaign_status(self, user_id, status):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('UPDATE users SET is_active=? WHERE user_id=?', (status, user_id))
        conn.commit()
        conn.close()

    def set_delay(self, user_id, delay):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('UPDATE users SET delay=? WHERE user_id=?', (delay, user_id))
        conn.commit()
        conn.close()

    def set_cycle_delay(self, user_id, cycle_delay):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('UPDATE users SET cycle_delay=? WHERE user_id=?', (cycle_delay, user_id))
        conn.commit()
        conn.close()

    def get_days_remaining(self, user_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('SELECT subscription_expiry FROM users WHERE user_id=?', (user_id,))
        r = c.fetchone()
        conn.close()
        if not r or not r[0]:
            return 0
        return max(0, (datetime.strptime(r[0], '%Y-%m-%d %H:%M:%S') - datetime.now()).days)

    def logout_user(self, user_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute('UPDATE users SET phone=NULL, api_id=NULL, api_hash=NULL, session_string=NULL, is_active=0 WHERE user_id=?', (user_id,))
        conn.commit()
        conn.close()

# ============================================
# LOGGER
# ============================================
class Logger:
    def __init__(self, token):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"

    def send_log(self, chat_id, message):
        try:
            requests.post(self.url, data={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'}, timeout=10)
        except Exception as e:
            print(f"Logger error: {e}")

# ============================================
# MAIN BOT
# ============================================
class PromoBot:
    def __init__(self):
        self.bot = TelegramClient('bot_session', BOT_API_ID, BOT_API_HASH)
        self.db = Database()
        self.logger = Logger(LOGGER_BOT_TOKEN)
        self.tasks = {}
        self.login_states = {}
        self.pending_message = {}
        self.pending_delay = {}

    def dashboard_text(self, user_id):
        user = self.db.get_user(user_id)
        days = self.db.get_days_remaining(user_id)
        phone = user[1] if user and user[1] else "Not connected"
        msg_status = "✅ Set" if user and user[5] else "❌ Not set"
        campaign = "🟢 Running" if user and user[6] else "🔴 Stopped"
        delay = f"{user[7]}s" if user and user[7] else "30s"
        cycle = f"{user[8]//60}m" if user and user[8] else "2m"
        return (
            f"🤖 *Premium Promo Bot*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📱 Account: `{phone}`\n"
            f"💬 Ad Message: {msg_status}\n"
            f"⏱️ Delay: {delay}  |  Cycle: {cycle}\n"
            f"📡 Campaign: {campaign}\n"
            f"💎 Premium: {days} days left\n"
            f"━━━━━━━━━━━━━━━━"
        )

    async def start(self):
        await self.bot.start(bot_token=MAIN_BOT_TOKEN)
        print("✓ Main bot started")
        self.register_handlers()
        print("✓ Bot is running...")
        await self.bot.run_until_disconnected()

    def register_handlers(self):

        # ── ADMIN COMMANDS ──────────────────────────

        @self.bot.on(events.NewMessage(pattern='/addcode'))
        async def addcode(event):
            if event.sender_id not in ADMINS: return
            try:
                _, code, days = event.message.text.split()
                if self.db.add_code(code, int(days)):
                    await event.reply(f"✅ Code `{code}` added for {days} days", parse_mode='md')
                else:
                    await event.reply("❌ Code already exists")
            except:
                await event.reply("❌ Usage: /addcode CODE DAYS")

        @self.bot.on(events.NewMessage(pattern='/codes'))
        async def codes(event):
            if event.sender_id not in ADMINS: return
            codes_list = self.db.get_unused_codes()
            if not codes_list:
                await event.reply("📋 No unused codes")
                return
            msg = "📋 *Unused Codes:*\n\n" + "\n".join([f"• `{c}` — {d} days" for c, d in codes_list])
            await event.reply(msg, parse_mode='md')

        @self.bot.on(events.NewMessage(pattern='/users'))
        async def users(event):
            if event.sender_id not in ADMINS: return
            users_list = self.db.get_premium_users()
            if not users_list:
                await event.reply("👥 No active premium users")
                return
            msg = "👥 *Premium Users:*\n\n"
            for uid, uname, expiry in users_list:
                exp = datetime.strptime(expiry, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d')
                msg += f"• {'@'+uname if uname else 'ID:'+str(uid)} — {exp}\n"
            await event.reply(msg, parse_mode='md')

        @self.bot.on(events.NewMessage(pattern='/revoke'))
        async def revoke(event):
            if event.sender_id not in ADMINS: return
            try:
                uid = int(event.message.text.split()[1])
                self.db.revoke_premium(uid)
                if uid in self.tasks:
                    self.tasks[uid].cancel()
                    del self.tasks[uid]
                await event.reply(f"✅ Premium revoked for {uid}")
                try: await self.bot.send_message(uid, "⚠️ Your premium has been revoked.")
                except: pass
            except:
                await event.reply("❌ Usage: /revoke USER_ID")

        # ── USER COMMANDS ────────────────────────────

        @self.bot.on(events.NewMessage(pattern='/start'))
        async def start(event):
            uid = event.sender_id
            if not self.db.is_premium(uid):
                send_msg(uid,
                    "🔒 *Subscription Required*\n\n"
                    "Contact the owner for a redeem code.\n"
                    "Then use: `/redeem YOUR_CODE`",
                    make_keyboard([[{"text": "🎟️ I have a code — /redeem CODE", "callback_data": "redeem_hint"}]])
                )
                return
            send_msg(uid, self.dashboard_text(uid), dashboard_keyboard())

        @self.bot.on(events.NewMessage(pattern='/redeem'))
        async def redeem(event):
            uid = event.sender_id
            username = event.sender.username
            try:
                code = event.message.text.split()[1]
                success, result = self.db.redeem_code(code, uid, username)
                if success:
                    send_msg(uid,
                        f"🎉 *Subscription Activated!*\n\n💎 Duration: {result} days",
                        make_keyboard([[{"text": "🏠 Open Dashboard", "callback_data": "dashboard"}]])
                    )
                else:
                    await event.reply(f"❌ {result}")
            except IndexError:
                await event.reply("❌ Usage: /redeem CODE")
            except Exception as e:
                await event.reply(f"❌ Error: {e}")

        # ── CALLBACK BUTTONS ─────────────────────────

        @self.bot.on(events.CallbackQuery())
        async def callbacks(event):
            uid = event.sender_id
            data = event.data.decode('utf-8')
            await event.answer()

            if data == 'redeem_hint':
                await self.bot.send_message(uid, "Send your code like this:\n`/redeem YOUR_CODE`", parse_mode='md')
                return

            if not self.db.is_premium(uid):
                await event.answer("❌ Premium required!", alert=True)
                return

            mid = event.query.msg_id

            if data == 'dashboard':
                edit_msg(uid, mid, self.dashboard_text(uid), dashboard_keyboard())

            elif data == 'premium':
                days = self.db.get_days_remaining(uid)
                edit_msg(uid, mid,
                    f"💎 *Premium Status*\n\n✅ Active\n🗓️ Days remaining: *{days}*",
                    back_keyboard())

            elif data == 'account':
                user = self.db.get_user(uid)
                phone = user[1] if user and user[1] else "Not connected"
                connected = "✅ Connected" if user and user[4] else "❌ Not connected"
                edit_msg(uid, mid,
                    f"👤 *My Account*\n\n📱 Phone: `{phone}`\n🔗 Status: {connected}",
                    make_keyboard([
                        [{"text": "🔑 Login", "callback_data": "login"},
                         {"text": "🚪 Logout", "callback_data": "logout"}],
                        [{"text": "🏠 Dashboard", "callback_data": "dashboard"}]
                    ]))

            elif data == 'status':
                user = self.db.get_user(uid)
                if not user:
                    await event.answer("❌ Login first!", alert=True)
                    return
                s = "🟢 Running" if user[6] else "🔴 Stopped"
                msg_preview = (user[5][:50]+'...') if user[5] and len(user[5]) > 50 else (user[5] or "Not set")
                edit_msg(uid, mid,
                    f"📊 *Campaign Status*\n\n"
                    f"📱 Phone: `{user[1] or 'Not set'}`\n"
                    f"💬 Message: {msg_preview}\n"
                    f"📡 Status: {s}\n"
                    f"⏱️ Delay: {user[7]}s  |  Cycle: {user[8]//60}m",
                    back_keyboard())

            elif data == 'setmessage':
                self.pending_message[uid] = True
                if uid in self.pending_delay: del self.pending_delay[uid]
                edit_msg(uid, mid,
                    "💬 *Set Promotional Message*\n\nSend your promo message now:\n\n_Type /cancel to go back_",
                    make_keyboard([[{"text": "❌ Cancel", "callback_data": "dashboard"}]]))

            elif data == 'setdelay':
                self.pending_delay[uid] = True
                if uid in self.pending_message: del self.pending_message[uid]
                edit_msg(uid, mid,
                    "⏱️ *Set Delays*\n\n"
                    "Format: `MSG_DELAY CYCLE_DELAY`\n\n"
                    "• Message delay (sec): `30`, `45`, `60`\n"
                    "• Cycle delay (min): `2`, `5`, `10`\n\n"
                    "Example: `45 5`\n\n_Type /cancel to go back_",
                    make_keyboard([[{"text": "❌ Cancel", "callback_data": "dashboard"}]]))

            elif data == 'startcampaign':
                user = self.db.get_user(uid)
                if not user or not user[4]:
                    await event.answer("❌ Login first!", alert=True)
                    return
                if not user[5]:
                    await event.answer("❌ Set message first!", alert=True)
                    return
                if uid in self.tasks:
                    await event.answer("⚠️ Already running!", alert=True)
                    return
                self.db.set_campaign_status(uid, 1)
                task = asyncio.create_task(self.run_campaign(uid))
                self.tasks[uid] = task
                self.logger.send_log(uid, "🚀 Campaign started")
                edit_msg(uid, mid, self.dashboard_text(uid), dashboard_keyboard())
                await self.bot.send_message(uid, "🚀 *Campaign Started!*", parse_mode='md')

            elif data == 'stopcampaign':
                if uid not in self.tasks:
                    await event.answer("⚠️ Not running!", alert=True)
                    return
                self.db.set_campaign_status(uid, 0)
                self.tasks[uid].cancel()
                del self.tasks[uid]
                self.logger.send_log(uid, "🛑 Campaign stopped")
                edit_msg(uid, mid, self.dashboard_text(uid), dashboard_keyboard())
                await self.bot.send_message(uid, "🛑 *Campaign Stopped!*", parse_mode='md')

            elif data == 'login':
                user = self.db.get_user(uid)
                if user and user[4]:
                    await event.answer("✅ Already logged in!", alert=True)
                    return
                self.login_states[uid] = {'step': 'waiting_api'}
                edit_msg(uid, mid,
                    "🔑 *Login to Your Telegram Account*\n\n"
                    "1. Go to https://my.telegram.org/apps\n"
                    "2. Create an app\n"
                    "3. Copy API\\_ID and API\\_HASH\n\n"
                    "Send in this format:\n`API_ID API_HASH`\n\n"
                    "Example: `12345678 abcdef1234567890`",
                    make_keyboard([[{"text": "❌ Cancel", "callback_data": "cancel_login"}]]))

            elif data == 'cancel_login':
                if uid in self.login_states:
                    try:
                        c = self.login_states[uid].get('client')
                        if c: await c.disconnect()
                    except: pass
                    del self.login_states[uid]
                edit_msg(uid, mid, self.dashboard_text(uid), dashboard_keyboard())

            elif data == 'logout':
                if uid in self.tasks:
                    self.tasks[uid].cancel()
                    del self.tasks[uid]
                self.db.logout_user(uid)
                edit_msg(uid, mid, self.dashboard_text(uid), dashboard_keyboard())
                await self.bot.send_message(uid, "✅ Logged out successfully!")

        # ── GLOBAL MESSAGE HANDLER ───────────────────

        @self.bot.on(events.NewMessage())
        async def global_handler(event):
            uid = event.sender_id
            text = event.message.text
            if not text: return

            # Cancel
            if text.strip() == '/cancel':
                for d in [self.pending_message, self.pending_delay]:
                    if uid in d: del d[uid]
                if uid in self.login_states:
                    try:
                        c = self.login_states[uid].get('client')
                        if c: await c.disconnect()
                    except: pass
                    del self.login_states[uid]
                if self.db.is_premium(uid):
                    send_msg(uid, self.dashboard_text(uid), dashboard_keyboard())
                return

            # Pending setmessage
            if uid in self.pending_message and not text.startswith('/'):
                del self.pending_message[uid]
                self.db.set_promo_message(uid, text)
                send_msg(uid, "✅ *Message saved!*\n\nReady to start campaign.",
                    make_keyboard([
                        [{"text": "🚀 Start Campaign", "callback_data": "startcampaign"}],
                        [{"text": "🏠 Dashboard", "callback_data": "dashboard"}]
                    ]))
                return

            # Pending setdelay
            if uid in self.pending_delay and not text.startswith('/'):
                del self.pending_delay[uid]
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
                    self.db.set_delay(uid, msg_delay)
                    self.db.set_cycle_delay(uid, cycle_delay * 60)
                    send_msg(uid,
                        f"✅ *Delays Updated!*\n\n⏱️ Message: {msg_delay}s\n🔄 Cycle: {cycle_delay}m",
                        back_keyboard())
                except (ValueError, IndexError):
                    await event.reply("❌ Format: `MSG_DELAY CYCLE_DELAY`\nExample: `45 5`")
                return

            # Login flow
            if uid in self.login_states:
                await self.handle_login(event, uid, text)

    async def handle_login(self, event, uid, text):
        if text.startswith('/'): return
        state = self.login_states[uid]
        step = state.get('step')

        if step == 'waiting_api':
            try:
                parts = text.strip().split()
                if len(parts) != 2:
                    await event.reply("❌ Format: `API_ID API_HASH`")
                    return
                api_id = int(parts[0])
                api_hash = parts[1]
                state['api_id'] = api_id
                state['api_hash'] = api_hash
                state['step'] = 'waiting_phone'
                send_msg(uid,
                    "✅ Credentials received!\n\n📱 Send your phone number:\nExample: `+911234567890`",
                    make_keyboard([[{"text": "❌ Cancel", "callback_data": "cancel_login"}]]))
            except ValueError:
                await event.reply("❌ API\\_ID must be a number")
                del self.login_states[uid]

        elif step == 'waiting_phone':
            if not text.startswith('+'):
                await event.reply("❌ Must start with + and country code\nExample: `+911234567890`")
                return
            try:
                user_client = TelegramClient(StringSession(), state['api_id'], state['api_hash'])
                await user_client.connect()
                await user_client.send_code_request(text.strip())
                state['client'] = user_client
                state['phone'] = text.strip()
                state['step'] = 'waiting_code'
                send_msg(uid, "📨 *Code sent!*\n\nEnter the verification code:",
                    make_keyboard([[{"text": "❌ Cancel", "callback_data": "cancel_login"}]]))
            except Exception as e:
                await event.reply(f"❌ Error: {e}")
                del self.login_states[uid]

        elif step == 'waiting_code':
            code = text.replace('-', '').replace(' ', '')
            if not code.isdigit():
                await event.reply("❌ Enter only the numeric code")
                return
            try:
                await state['client'].sign_in(state['phone'], code)
                session = state['client'].session.save()
                self.db.save_session(uid, state['phone'], state['api_id'], state['api_hash'], session)
                await state['client'].disconnect()
                del self.login_states[uid]
                self.logger.send_log(uid, f"✅ Logged in: {state['phone']}")
                send_msg(uid, "✅ *Login Successful!*\n\nYour account is connected.",
                    make_keyboard([
                        [{"text": "💬 Set Message", "callback_data": "setmessage"}],
                        [{"text": "🏠 Dashboard", "callback_data": "dashboard"}]
                    ]))
            except SessionPasswordNeededError:
                state['step'] = 'waiting_password'
                send_msg(uid, "🔐 *2FA Enabled*\n\nSend your 2FA password:",
                    make_keyboard([[{"text": "❌ Cancel", "callback_data": "cancel_login"}]]))
            except Exception as e:
                await event.reply(f"❌ Invalid code: {e}")
                await state['client'].disconnect()
                del self.login_states[uid]

        elif step == 'waiting_password':
            try:
                await state['client'].sign_in(password=text)
                session = state['client'].session.save()
                self.db.save_session(uid, state['phone'], state['api_id'], state['api_hash'], session)
                await state['client'].disconnect()
                del self.login_states[uid]
                self.logger.send_log(uid, f"✅ Logged in (2FA): {state['phone']}")
                send_msg(uid, "✅ *Login Successful!*\n\nYour account is connected.",
                    make_keyboard([
                        [{"text": "💬 Set Message", "callback_data": "setmessage"}],
                        [{"text": "🏠 Dashboard", "callback_data": "dashboard"}]
                    ]))
            except Exception as e:
                await event.reply(f"❌ 2FA failed: {e}")
                await state['client'].disconnect()
                del self.login_states[uid]

    async def run_campaign(self, uid):
        try:
            user = self.db.get_user(uid)
            phone, api_id, api_hash = user[1], user[2], user[3]
            session_string = user[4]
            msg_delay = user[7]
            cycle_delay = user[8]

            user_client = TelegramClient(StringSession(session_string), api_id, api_hash)
            await user_client.connect()

            dialogs = await user_client.get_dialogs()
            groups = [d for d in dialogs if d.is_group]

            if not groups:
                await self.bot.send_message(uid, "❌ No groups found!")
                self.db.set_campaign_status(uid, 0)
                await user_client.disconnect()
                return

            await self.bot.send_message(uid, f"📊 Found *{len(groups)}* groups. Starting...", parse_mode='md')

            while self.db.get_user(uid)[6]:
                sent = 0
                failed = 0
                user = self.db.get_user(uid)
                message = user[5]

                for group in groups:
                    if not self.db.get_user(uid)[6]: break
                    try:
                        await user_client.send_message(group.entity, message)
                        sent += 1
                        self.logger.send_log(uid, f"[{phone}] ✓ {group.name}")
                        await asyncio.sleep(msg_delay)
                    except FloodWaitError as e:
                        await self.bot.send_message(uid, f"⚠️ FloodWait: {e.seconds}s...")
                        await asyncio.sleep(e.seconds)
                    except Exception as e:
                        failed += 1
                        self.logger.send_log(uid, f"[{phone}] ✗ {group.name}: {e}")
                        await asyncio.sleep(10)

                send_msg(uid,
                    f"✅ *Round Complete!*\n\n📤 Sent: {sent}\n❌ Failed: {failed}\n\n⏳ Next in {cycle_delay//60}m...",
                    make_keyboard([[{"text": "🛑 Stop Campaign", "callback_data": "stopcampaign"}]]))
                await asyncio.sleep(cycle_delay)

            await user_client.disconnect()

        except asyncio.CancelledError:
            print(f"User {uid}: Campaign cancelled")
        except Exception as e:
            print(f"User {uid}: Error: {e}")
            self.db.set_campaign_status(uid, 0)
            if uid in self.tasks: del self.tasks[uid]
            try: await self.bot.send_message(uid, f"❌ Campaign error:\n{e}")
            except: pass

# ============================================
# MAIN
# ============================================
async def main():
    print("=" * 50)
    print("Premium Telegram Promotional Bot")
    print("=" * 50)
    missing = [v for v in ['API_ID','API_HASH','MAIN_BOT_TOKEN','LOGGER_BOT_TOKEN','ADMIN_IDS'] if not os.getenv(v)]
    if missing:
        print(f"❌ Missing: {', '.join(missing)}")
        sys.exit(1)
    await PromoBot().start()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped")
    except Exception as e:
        print(f"Fatal: {e}")
        sys.exit(1)
