# 🤖 Premium Telegram Promo Bot

Automated promotional message bot with premium subscription system.

---

## 📁 File Structure

```
├── main_bot.py        → Main bot (commands, campaigns)
├── logger_bot.py      → Logger bot (receives logs)
├── requirements.txt   → Python dependencies
├── Procfile           → For Railway deployment
├── .env.example       → Environment variables template
└── .gitignore         → Protects sensitive files
```

---

## ⚙️ Environment Variables

| Variable | Description |
|----------|-------------|
| `API_ID` | From https://my.telegram.org |
| `API_HASH` | From https://my.telegram.org |
| `MAIN_BOT_TOKEN` | From @BotFather |
| `LOGGER_BOT_TOKEN` | From @BotFather (2nd bot) |
| `ADMIN_IDS` | Your Telegram user ID |

---

## 🤖 Bot Commands

### Admin Commands
| Command | Description |
|---------|-------------|
| `/addcode CODE DAYS` | Create a redeem code |
| `/codes` | List unused codes |
| `/users` | List premium users |
| `/revoke USER_ID` | Revoke user's premium |

### User Commands
| Command | Description |
|---------|-------------|
| `/redeem CODE` | Activate subscription |
| `/start` | Show commands |
| `/login` | Connect Telegram account |
| `/setmessage` | Set promo message |
| `/setdelay` | Set message/cycle delay |
| `/startcampaign` | Start sending |
| `/stopcampaign` | Stop sending |
| `/status` | Check status |
| `/premium` | Check subscription |

---

## 🚀 OPTION 1 — Deploy on Railway (Recommended)

### Step 1 — Create GitHub Repo
1. Go to https://github.com → Sign Up / Login
2. Click **New Repository**
3. Name: `promo-bot` → Set to **Private** → Click **Create**
4. Upload all these files by dragging and dropping them

### Step 2 — Deploy on Railway
1. Go to https://railway.app
2. Click **Login with GitHub** (no credit card needed)
3. Click **New Project** → **Deploy from GitHub repo**
4. Select your `promo-bot` repository

### Step 3 — Add Environment Variables on Railway
1. Click on your project
2. Go to **Variables** tab
3. Add these one by one:
   - `API_ID` = your value
   - `API_HASH` = your value
   - `MAIN_BOT_TOKEN` = your value
   - `LOGGER_BOT_TOKEN` = your value
   - `ADMIN_IDS` = your telegram user id

### Step 4 — Deploy Both Bots
Railway reads the `Procfile` automatically.
It will run both `main_bot.py` and `logger_bot.py` together.

1. Click **Deploy**
2. Wait 1-2 minutes
3. Both bots are now live 24/7 ✅

---

## 🚀 OPTION 2 — Deploy on Koyeb (No CC, Free Forever)

### Step 1 — GitHub (same as Railway Step 1)
Upload all files to a private GitHub repo.

### Step 2 — Create Koyeb Account
1. Go to https://koyeb.com
2. Click **Sign Up** → Use GitHub (no credit card needed)

### Step 3 — Deploy Main Bot
1. Click **Create App**
2. Choose **GitHub** as source
3. Select your `promo-bot` repo
4. Set **Run command**: `python main_bot.py`
5. Add Environment Variables:
   - `API_ID` = your value
   - `API_HASH` = your value
   - `MAIN_BOT_TOKEN` = your value
   - `LOGGER_BOT_TOKEN` = your value
   - `ADMIN_IDS` = your telegram user id
6. Click **Deploy**

### Step 4 — Deploy Logger Bot (separate service)
1. Click **Create App** again
2. Same repo, same env variables
3. Set **Run command**: `python logger_bot.py`
4. Click **Deploy**

Both services run 24/7 for free ✅

---

## 🔑 Before You Start

### Get your ADMIN_IDS (Your Telegram User ID)
1. Open Telegram
2. Search for `@userinfobot`
3. Send `/start`
4. It will show your User ID
5. Copy that number → use it as `ADMIN_IDS`

### Create 2 Bots on BotFather
1. Open Telegram → search `@BotFather`
2. Send `/newbot` → follow steps → copy token → this is `MAIN_BOT_TOKEN`
3. Send `/newbot` again → follow steps → copy token → this is `LOGGER_BOT_TOKEN`

---

## 💡 How to Use After Deployment

1. Open your main bot on Telegram
2. You'll see: *"Subscription Not Active"*
3. Go to the bot and send: `/addcode TEST123 30`
4. Now send to the bot: `/redeem TEST123`
5. You're premium! Use `/start` to see all commands

---

## ⚠️ Important Notes

- Never share your `.env` file or session files publicly
- The `.gitignore` protects these files from being uploaded to GitHub
- Each user needs their own API_ID and API_HASH from my.telegram.org
- Use responsibly to avoid Telegram bans
