# Unix SMS Telegram Forwarder

Unix SMS Agent API থেকে নতুন SMS Telegram-এ forward করে।

## Railway-তে ডিপ্লয়

1. GitHub-এ প্রাইভেট রিপো হিসেবে পুশ করুন
2. Railway → New Project → Deploy from GitHub
3. Variables সেট করুন:
   - `BOT_TOKEN` — BotFather টোকেন
   - `UNIXSMS_TOKEN` — Unix SMS API টোকেন
   - `CHAT_ID` — আপনার Telegram ID
   - `POLL_INTERVAL` — `2`
   - `RECORDS_PER_FETCH` — `50`
   - `DATA_DIR` — `/data`
4. Settings → Deploy → Start Command: `python forwarder.py`
5. Volume attach করুন → Mount path: `/data`
