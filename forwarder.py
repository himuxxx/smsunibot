import os
import time
import json
import logging
import requests
import telebot
from pathlib import Path

# ==================== কনফিগ ====================
BOT_TOKEN     = os.environ["BOT_TOKEN"]
API_TOKEN     = os.environ["UNIXSMS_TOKEN"]
CHAT_ID       = int(os.environ["CHAT_ID"])   # গ্রুপ ID (নেগেটিভ, যেমন -1001234567890)
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "2"))
RECORDS       = int(os.getenv("RECORDS_PER_FETCH", "50"))
API_URL       = "https://agent-api.unixsms.com/v2/cdr"

# Railway Volume mount path — না থাকলে বর্তমান ডিরেক্টরি
DATA_DIR    = Path(os.getenv("DATA_DIR", "."))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE  = DATA_DIR / "seen_ids.json"
LOG_FILE    = DATA_DIR / "bot.log"

# ==================== লগিং ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ==================== বট ====================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ==================== স্টেট ====================
def load_seen():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return set(json.load(f))
        except Exception as e:
            log.warning(f"State load failed: {e}")
            return set()
    return set()

def save_seen(seen):
    trimmed = list(seen)[-5000:]
    tmp = str(STATE_FILE) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(trimmed, f)
    os.replace(tmp, STATE_FILE)

def rec_id(row):
    return (
        f"{row.get('dt')}|{row.get('num')}|"
        f"{row.get('cli')}|{row.get('message')}"
    )

# ==================== API ====================
def fetch():
    r = requests.get(
        API_URL,
        params={"token": API_TOKEN, "records": RECORDS},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()

# ==================== মেসেজ ফরম্যাট ====================
def fmt(row):
    return (
        f"📩 <b>New SMS</b>\n"
        f"🕒 <code>{row.get('dt')}</code>\n"
        f"📱 <code>{row.get('num')}</code>\n"
        f"🏷 {row.get('cli')}\n"
        f"💰 {row.get('payout')}\n"
        f"💬 {row.get('message')}"
    )

# ==================== গ্রুপে পাঠানো ====================
def send_to_group(text):
    try:
        bot.send_message(CHAT_ID, text)
        return True
    except Exception as e:
        log.error(f"Send to group {CHAT_ID} failed: {e}")
        return False

# ==================== মেইন লুপ ====================
def main():
    seen = load_seen()
    first_run = len(seen) == 0
    log.info(f"Bot চালু হলো | group={CHAT_ID} | poll={POLL_INTERVAL}s | first_run={first_run}")

    # গ্রুপে startup message
    send_to_group(
        f"✅ Unix SMS Forwarder চালু হয়েছে\n"
        f"⏱ Poll: {POLL_INTERVAL}s | 📥 Fetch: {RECORDS}\n"
        f"📢 Group ID: <code>{CHAT_ID}</code>"
    )

    fail_count = 0

    while True:
        loop_start = time.time()
        try:
            data = fetch()

            if data.get("status") == "success":
                new_rows = []
                for row in data.get("data", []):
                    rid = rec_id(row)
                    if rid not in seen:
                        seen.add(rid)
                        new_rows.append(row)

                if first_run:
                    save_seen(seen)
                    first_run = False
                    log.info(f"First run: {len(new_rows)} পুরনো SMS স্কিপ")
                elif new_rows:
                    new_rows.sort(key=lambda x: x.get("dt", ""))
                    sent = 0
                    for row in new_rows:
                        if send_to_group(fmt(row)):
                            sent += 1
                        time.sleep(0.3)
                    save_seen(seen)
                    log.info(f"{sent} টি নতুন SMS গ্রুপে পাঠানো হলো")

                fail_count = 0

        except Exception as e:
            fail_count += 1
            log.error(f"Poll error #{fail_count}: {e}")
            if fail_count >= 5:
                log.warning("Backoff 30s")
                time.sleep(30)
                fail_count = 0

        elapsed = time.time() - loop_start
        time.sleep(max(0, POLL_INTERVAL - elapsed))

if __name__ == "__main__":
    main()
