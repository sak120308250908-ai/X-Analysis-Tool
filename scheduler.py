import urllib.request
import urllib.error
import re
import json
import time
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
from database import init_db, upsert_tweets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

ACCOUNTS_FILE = Path("accounts.txt")
MAX_PAGES = 10
RETRY_WAIT = 60
MAX_RETRIES = 3
PAGE_INTERVAL = 2
ACCOUNT_INTERVAL = 300
BATCH_SIZE = 38

def fetch_page(screen_name, cursor=None):
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{screen_name}"
    if cursor:
        url += f"?cursor={cursor}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            logger.warning(f"[{screen_name}] 429 Rate Limited. {RETRY_WAIT}秒待機...")
            time.sleep(RETRY_WAIT)
            return [], None
        logger.error(f"[{screen_name}] HTTPError {e.code}")
        return [], None
    except Exception as e:
        logger.error(f"[{screen_name}] 取得エラー: {e}")
        return [], None
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">({.*?})</script>', html
    )
    if not match:
        return [], None
    try:
        data = json.loads(match.group(1))
        entries = data["props"]["pageProps"]["timeline"]["entries"]
    except Exception:
        return [], None
    tweets = [e for e in entries if e["type"] == "tweet"]
    next_cursor = None
    for e in entries:
        if e["type"] == "timeline_cursor" and e["content"]["cursorType"] == "Bottom":
            next_cursor = e["content"]["value"]
    return tweets, next_cursor

def build_record(screen_name, entry):
    try:
        tw = entry["content"]["tweet"]
        date_str = tw.get("created_at", "")
        utc_dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S +0000 %Y")
        jst_dt = utc_dt + timedelta(hours=9)
        likes = int(tw.get("favorite_count", 0))
        rts   = int(tw.get("retweet_count", 0))
        reps  = int(tw.get("reply_count", 0))
        qts   = int(tw.get("quote_count", 0))
        engagement = likes + rts * 2 + reps * 3
        media     = tw.get("entities", {}).get("media", [])
        media_ext = tw.get("extended_entities", {}).get("media", [])
        media_count = max(len(media), len(media_ext))
        text   = tw.get("full_text", tw.get("text", "")).replace("\n", " ")
        id_str = tw.get("id_str", "")
        url    = f"https://x.com/{screen_name}/status/{id_str}"
        return {
            "id_str": id_str, "screen_name": screen_name,
            "created_at_utc": utc_dt.isoformat(), "jst_datetime": jst_dt.isoformat(),
            "hour_jst": jst_dt.hour, "likes": likes, "retweets": rts,
            "replies": reps, "quotes": qts, "media_count": media_count,
            "engagement": engagement, "text": text, "url": url,
        }
    except Exception as e:
        logger.warning(f"[{screen_name}] レコード変換エラー: {e}")
        return None

def fetch_account(screen_name):
    logger.info(f"[{screen_name}] 取得開始")
    all_records = {}
    cursor = None
    for page in range(MAX_PAGES):
        retries = 0
        while retries < MAX_RETRIES:
            entries, next_cursor = fetch_page(screen_name, cursor)
            if entries or next_cursor is None:
                break
            retries += 1
        for entry in entries:
            rec = build_record(screen_name, entry)
            if rec and rec["id_str"] not in all_records:
                all_records[rec["id_str"]] = rec
        logger.info(f"[{screen_name}] page={page+1}, 累計={len(all_records)}件")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
        time.sleep(PAGE_INTERVAL)
    if all_records:
        upsert_tweets(screen_name, list(all_records.values()))
        logger.info(f"[{screen_name}] {len(all_records)}件をDBに保存しました")
    else:
        logger.warning(f"[{screen_name}] データが取得できませんでした")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--accounts", nargs="*", help="アカウントを直接指定")
    parser.add_argument("--all", action="store_true", help="全アカウントを強制取得")
    args = parser.parse_args()

    init_db()

    if args.accounts:
        targets = args.accounts
    elif ACCOUNTS_FILE.exists():
        all_accounts = [
            line.strip().lstrip("@")
            for line in ACCOUNTS_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        if args.all:
            targets = all_accounts
            logger.info(f"=== 全件モード: {len(all_accounts)}アカウント ===")
        else:
            day_of_week = datetime.now().weekday()
            start_idx = day_of_week * BATCH_SIZE
            end_idx = start_idx + BATCH_SIZE
            targets = all_accounts[start_idx:end_idx]
            day_names = ["月曜", "火曜", "水曜", "木曜", "金曜", "土曜", "日曜"]
            logger.info(
                f"=== {day_names[day_of_week]}日 担当: "
                f"{start_idx + 1}〜{min(end_idx, len(all_accounts))}番目 "
                f"({len(targets)}アカウント) ==="
            )
    else:
        logger.error(f"{ACCOUNTS_FILE} が見つかりません。")
        return

    if not targets:
        logger.warning("本日担当のアカウントがありません")
        return

    logger.info(f"=== バッチ開始: {len(targets)}アカウント ===")
    for i, account in enumerate(targets):
        fetch_account(account)
        if i < len(targets) - 1:
            time.sleep(ACCOUNT_INTERVAL)
    logger.info("=== バッチ完了 ===")

if __name__ == "__main__":
    main()
