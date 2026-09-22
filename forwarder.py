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
CHAT_ID       = int(os.environ["CHAT_ID"])
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "20"))    # ২০ সেকেন্ড
RECORDS       = int(os.getenv("RECORDS_PER_FETCH", "200"))  # max 200
API_URL       = "https://agent-api.unixsms.com/v2/cdr"

DATA_DIR   = Path(os.getenv("DATA_DIR", "."))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"
LOG_FILE   = DATA_DIR / "bot.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ==================== স্টেট ====================
def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_dt": "", "seen_ids": []}

def save_state(state):
    state["seen_ids"] = state["seen_ids"][-2000:]   # মেমরি বাঁচাতে
    tmp = str(STATE_FILE) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)

def rec_id(row):
    return f"{row.get('dt')}|{row.get('num')}|{row.get('cli')}|{row.get('message')}"

# ==================== API ====================
rate_limited_until = 0

def fetch(dt1=None):
    global rate_limited_until
    now = time.time()
    if now < rate_limited_until:
        log.info(f"Rate-limited — আরও {int(rate_limited_until-now)}s")
        return None

    params = {"token": API_TOKEN, "records": RECORDS}
    if dt1:
        params["dt1"] = dt1

    try:
        r = requests.get(API_URL, params=params, timeout=20)

        if r.status_code == 429:
            retry = max(int(r.headers.get("Retry-After", 60)), 60)
            rate_limited_until = time.time() + retry
            log.warning(f"429 — {retry}s থামছি")
            return None

        r.raise_for_status()
        return r.json()

    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            rate_limited_until = time.time() + 60
            log.warning("429 (HTTPError) — 60s থামছি")
            return None
        raise

# ==================== মেসেজ ====================
def fmt(row):
    return (
        f"📩 <b>New SMS</b>\n"
        f"🕒 <code>{row.get('dt')}</code>\n"
        f"📱 <code>{row.get('num')}</code>\n"
        f"🏷 {row.get('cli')}\n"
        f"💰 {row.get('payout')}\n"
        f"💬 {row.get('message')}"
    )

def send_to_group(text):
    try:
        bot.send_message(CHAT_ID, text)
        return True
    except Exception as e:
        log.error(f"TG send fail: {e}")
        return False

# ==================== ভেরিফিকেশন ====================
def verify_group():
    try:
        bot.send_message(
            CHAT_ID,
            f"✅ <b>Forwarder চালু</b>\n"
            f"⏱ Poll: {POLL_INTERVAL}s | 📥 Fetch: {RECORDS}\n"
            f"📢 Group: <code>{CHAT_ID}</code>"
        )
        log.info("✅ Startup message sent")
        return True
    except Exception as e:
        log.error(f"❌ {e}")
        return False

# ==================== মেইন ====================
def main():
    state = load_state()
    seen = set(state.get("seen_ids", []))
    last_dt = state.get("last_dt", "")
    first_run = len(seen) == 0

    log.info(f"Bot চালু | poll={POLL_INTERVAL}s | fetch={RECORDS} | first_run={first_run}")

    verify_group()

    while True:
        loop_start = time.time()
        try:
            data = fetch(dt1=last_dt if not first_run else None)

            if data is not None and data.get("status") == "success":
                new_rows = []
                for row in data.get("data", []):
                    rid = rec_id(row)
                    if rid not in seen:
                        seen.add(rid)
                        new_rows.append(row)

                if first_run:
                    state["seen_ids"] = list(seen)
                    if new_rows:
                        sorted_rows = sorted(new_rows, key=lambda x: x.get("dt", ""))
                        state["last_dt"] = sorted_rows[-1].get("dt", "")
                    save_state(state)
                    last_dt = state["last_dt"]
                    first_run = False
                    log.info(f"First run: {len(new_rows)} SMS স্কিপ, last_dt={last_dt}")

                elif new_rows:
                    new_rows.sort(key=lambda x: x.get("dt", ""))

                    sent = 0
                    for row in new_rows:
                        if send_to_group(fmt(row)):
                            sent += 1
                            last_dt = max(last_dt, row.get("dt", ""))
                        time.sleep(0.35)   # Telegram flood এড়াতে

                    state["seen_ids"] = list(seen)
                    state["last_dt"] = last_dt
                    save_state(state)
                    log.info(f"{sent}/{len(new_rows)} SMS পাঠানো হলো | last_dt={last_dt}")

        except Exception as e:
            log.error(f"Poll error: {e}")

        elapsed = time.time() - loop_start
        time.sleep(max(0, POLL_INTERVAL - elapsed))

if __name__ == "__main__":
    main()
