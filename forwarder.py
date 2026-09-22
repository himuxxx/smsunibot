import os
import re
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
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "20"))
RECORDS       = int(os.getenv("RECORDS_PER_FETCH", "200"))
API_URL       = "https://agent-api.unixsms.com/v2/cdr"

DATA_DIR   = Path(os.getenv("DATA_DIR", "."))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"
LOG_FILE   = DATA_DIR / "bot.log"

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

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ==================== Country Map ====================
COUNTRY_MAP = {
    "880": ("🇧🇩", "Bangladesh"),
    "977": ("🇳🇵", "Nepal"),
    "91":  ("🇮🇳", "India"),
    "92":  ("🇵🇰", "Pakistan"),
    "94":  ("🇱🇰", "Sri Lanka"),
    "95":  ("🇲🇲", "Myanmar"),
    "60":  ("🇲🇾", "Malaysia"),
    "62":  ("🇮🇩", "Indonesia"),
    "63":  ("🇵🇭", "Philippines"),
    "65":  ("🇸🇬", "Singapore"),
    "66":  ("🇹🇭", "Thailand"),
    "84":  ("🇻🇳", "Vietnam"),
    "86":  ("🇨🇳", "China"),
    "81":  ("🇯🇵", "Japan"),
    "82":  ("🇰🇷", "South Korea"),
    "1":   ("🇺🇸", "USA/Canada"),
    "7":   ("🇷🇺", "Russia"),
    "20":  ("🇪🇬", "Egypt"),
    "27":  ("🇿🇦", "South Africa"),
    "31":  ("🇳🇱", "Netherlands"),
    "33":  ("🇫🇷", "France"),
    "34":  ("🇪🇸", "Spain"),
    "39":  ("🇮🇹", "Italy"),
    "44":  ("🇬🇧", "UK"),
    "49":  ("🇩🇪", "Germany"),
    "55":  ("🇧🇷", "Brazil"),
    "90":  ("🇹🇷", "Turkey"),
    "966": ("🇸🇦", "Saudi Arabia"),
    "971": ("🇦🇪", "UAE"),
    "974": ("🇶🇦", "Qatar"),
    "965": ("🇰🇼", "Kuwait"),
    "968": ("🇴🇲", "Oman"),
    "973": ("🇧🇭", "Bahrain"),
    "962": ("🇯🇴", "Jordan"),
    "964": ("🇮🇶", "Iraq"),
    "98":  ("🇮🇷", "Iran"),
    "93":  ("🇦🇫", "Afghanistan"),
    "212": ("🇲🇦", "Morocco"),
    "213": ("🇩🇿", "Algeria"),
    "216": ("🇹🇳", "Tunisia"),
    "234": ("🇳🇬", "Nigeria"),
    "254": ("🇰🇪", "Kenya"),
    "255": ("🇹🇿", "Tanzania"),
    "256": ("🇺🇬", "Uganda"),
    "263": ("🇿🇼", "Zimbabwe"),
    "381": ("🇷🇸", "Serbia"),
    "380": ("🇺🇦", "Ukraine"),
    "370": ("🇱🇹", "Lithuania"),
    "371": ("🇱🇻", "Latvia"),
    "372": ("🇪🇪", "Estonia"),
    "48":  ("🇵🇱", "Poland"),
    "40":  ("🇷🇴", "Romania"),
    "36":  ("🇭🇺", "Hungary"),
    "30":  ("🇬🇷", "Greece"),
    "351": ("🇵🇹", "Portugal"),
    "353": ("🇮🇪", "Ireland"),
    "45":  ("🇩🇰", "Denmark"),
    "46":  ("🇸🇪", "Sweden"),
    "47":  ("🇳🇴", "Norway"),
    "358": ("🇫🇮", "Finland"),
    "41":  ("🇨🇭", "Switzerland"),
    "43":  ("🇦🇹", "Austria"),
    "32":  ("🇧🇪", "Belgium"),
    "61":  ("🇦🇺", "Australia"),
    "64":  ("🇳🇿", "New Zealand"),
}

def detect_country(number):
    num = str(number).lstrip('+').lstrip('0')
    for length in (3, 2, 1):
        prefix = num[:length]
        if prefix in COUNTRY_MAP:
            return COUNTRY_MAP[prefix]
    return ("🌍", "Unknown")

def extract_otp(message):
    if not message:
        return None
    match = re.search(r'\b(\d{4,8})\b', message)
    return match.group(1) if match else None

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
    state["seen_ids"] = state["seen_ids"][-2000:]
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
        log.info(f"Rate-limited — আরও {int(rate_limited_until - now)}s")
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

# ==================== মেসেজ ফরম্যাট ====================
def fmt(row):
    cli  = row.get('cli', 'Unknown')
    num  = str(row.get('num', ''))
    dt   = row.get('dt', '')
    msg  = row.get('message', '').strip()

    flag, country = detect_country(num)
    otp = extract_otp(msg)

    lines = [
        f"✨ <b>OTP Received</b> ✨",
        "",
        f"⏰ <b>Time:</b> {dt}",
        f"📞 <b>Number:</b> <code>{num}</code>",
        f"🌍 <b>Country:</b> {flag} {country}",
        f"🔧 <b>Service:</b> {cli}",
    ]

    if otp:
        lines.append(f"🔐 <b>OTP Code:</b> <code>{otp}</code>")

    lines.append(f"📝 <b>Msg:</b> {msg}")

    return "\n".join(lines)

def send_to_group(text):
    try:
        bot.send_message(CHAT_ID, text)
        return True
    except Exception as e:
        log.error(f"TG send fail: {e}")
        return False

# ==================== গ্রুপ ভেরিফিকেশন ====================
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
        log.error(f"❌ গ্রুপে পাঠানো যাচ্ছে না: {e}")
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
                    log.info(f"First run: {len(new_rows)} SMS স্কিপ | last_dt={last_dt}")

                elif new_rows:
                    new_rows.sort(key=lambda x: x.get("dt", ""))
                    sent = 0
                    for row in new_rows:
                        if send_to_group(fmt(row)):
                            sent += 1
                            last_dt = max(last_dt, row.get("dt", ""))
                        time.sleep(0.35)

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
