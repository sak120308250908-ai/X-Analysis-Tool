"""
database.py
PostgreSQL (Supabase) のCRUD操作をまとめたモジュール。
scheduler.py（書き込み）と app.py（読み込み）の両方から使用する。
"""

import os
import psycopg2
import psycopg2.extras
import pandas as pd
from datetime import datetime, timezone


def get_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ.get("DB_NAME", "postgres"),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=10,
        sslmode="require",
    )


def init_db():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    screen_name      TEXT PRIMARY KEY,
                    display_name     TEXT,
                    last_fetched_at  TIMESTAMPTZ
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tweets (
                    id_str          TEXT PRIMARY KEY,
                    screen_name     TEXT NOT NULL REFERENCES accounts(screen_name),
                    created_at_utc  TIMESTAMPTZ,
                    jst_datetime    TIMESTAMPTZ,
                    hour_jst        INTEGER,
                    likes           INTEGER DEFAULT 0,
                    retweets        INTEGER DEFAULT 0,
                    replies         INTEGER DEFAULT 0,
                    quotes          INTEGER DEFAULT 0,
                    media_count     INTEGER DEFAULT 0,
                    engagement      INTEGER DEFAULT 0,
                    text            TEXT,
                    url             TEXT,
                    fetched_at      TIMESTAMPTZ
                )
            """)
        conn.commit()


def upsert_tweets(screen_name: str, records: list[dict]):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO accounts (screen_name, last_fetched_at)
                VALUES (%s, %s)
                ON CONFLICT (screen_name) DO UPDATE
                    SET last_fetched_at = EXCLUDED.last_fetched_at
            """, (screen_name, now))
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO tweets
                    (id_str, screen_name, created_at_utc, jst_datetime, hour_jst,
                     likes, retweets, replies, quotes, media_count, engagement,
                     text, url, fetched_at)
                VALUES
                    (%(id_str)s, %(screen_name)s, %(created_at_utc)s, %(jst_datetime)s,
                     %(hour_jst)s, %(likes)s, %(retweets)s, %(replies)s, %(quotes)s,
                     %(media_count)s, %(engagement)s, %(text)s, %(url)s, %(fetched_at)s)
                ON CONFLICT (id_str) DO UPDATE SET
                    likes       = EXCLUDED.likes,
                    retweets    = EXCLUDED.retweets,
                    replies     = EXCLUDED.replies,
                    quotes      = EXCLUDED.quotes,
                    media_count = EXCLUDED.media_count,
                    engagement  = EXCLUDED.engagement,
                    fetched_at  = EXCLUDED.fetched_at
            """, [{**r, "fetched_at": now} for r in records])
        conn.commit()


def load_tweets(screen_name: str) -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query(
            "SELECT * FROM tweets WHERE screen_name = %s ORDER BY jst_datetime DESC",
            conn,
            params=(screen_name,)
        )
    if df.empty:
        return df
    df['JST_Date'] = pd.to_datetime(df['jst_datetime'], utc=True).dt.tz_convert('Asia/Tokyo')
    df['Hour'] = df['hour_jst']
    df.rename(columns={
        'likes': 'Likes', 'retweets': 'Retweets',
        'replies': 'Replies', 'quotes': 'Quotes',
        'media_count': 'MediaCount', 'engagement': 'Engagement',
        'text': 'Text', 'url': 'URL'
    }, inplace=True)
    return df


def list_accounts() -> list[dict]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT screen_name, last_fetched_at FROM accounts ORDER BY screen_name"
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_last_fetched(
