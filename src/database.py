"""SQLite store for daily prices, detected signals and run metadata."""
from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd

import config


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS prices (
            symbol        TEXT NOT NULL,
            date          TEXT NOT NULL,
            open          REAL,
            high          REAL,
            low           REAL,
            close         REAL,
            prev_close    REAL,
            volume        INTEGER,
            turnover_lacs REAL,
            PRIMARY KEY (symbol, date)
        )
        """
    )
    # Drop a signals table that predates the 'direction' column
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='signals'").fetchone():
        cols = [row[1] for row in conn.execute("PRAGMA table_info(signals)")]
        if "direction" not in cols:
            conn.execute("DROP TABLE signals")
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS signals (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol       TEXT NOT NULL,
            direction    TEXT NOT NULL DEFAULT 'bullish',
            signal_date  TEXT NOT NULL,
            price        REAL,
            rsi          REAL,
            pivot1_date  TEXT, pivot1_price REAL, pivot1_rsi REAL,
            pivot2_date  TEXT, pivot2_price REAL, pivot2_rsi REAL,
            strength     REAL,
            profile      TEXT,
            is_fno       INTEGER DEFAULT 0,
            created_at   TEXT,
            UNIQUE (symbol, signal_date, profile, direction)
        )
        """
    )
    c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_prices_symbol ON prices(symbol)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(signal_date)")
    conn.commit()
    conn.close()


def store_prices(df: pd.DataFrame) -> int:
    """Upsert a bhavcopy DataFrame into the prices table."""
    if df is None or df.empty:
        return 0
    rows = df[
        ["symbol", "date", "open", "high", "low", "close", "prev_close", "volume", "turnover_lacs"]
    ].values.tolist()
    conn = get_conn()
    conn.executemany(
        """
        INSERT INTO prices (symbol, date, open, high, low, close, prev_close, volume, turnover_lacs)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, date) DO UPDATE SET
            open=excluded.open, high=excluded.high, low=excluded.low,
            close=excluded.close, prev_close=excluded.prev_close,
            volume=excluded.volume, turnover_lacs=excluded.turnover_lacs
        """,
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


def get_price_history(symbol: str, limit: int | None = None) -> pd.DataFrame:
    conn = get_conn()
    q = "SELECT date, open, high, low, close, prev_close, volume, turnover_lacs FROM prices WHERE symbol = ? ORDER BY date"
    df = pd.read_sql_query(q, conn, params=(symbol,))
    conn.close()
    if limit:
        df = df.tail(limit).reset_index(drop=True)
    return df


def get_symbols() -> list[str]:
    conn = get_conn()
    cur = conn.execute("SELECT DISTINCT symbol FROM prices")
    symbols = [r[0] for r in cur.fetchall()]
    conn.close()
    return symbols


def get_last_price_date() -> str | None:
    conn = get_conn()
    cur = conn.execute("SELECT MAX(date) FROM prices")
    val = cur.fetchone()[0]
    conn.close()
    return val


def store_signals(signals: list[dict]) -> int:
    if not signals:
        return 0
    conn = get_conn()
    n = 0
    for s in signals:
        conn.execute(
            """
            INSERT INTO signals (
                symbol, direction, signal_date, price, rsi,
                pivot1_date, pivot1_price, pivot1_rsi,
                pivot2_date, pivot2_price, pivot2_rsi,
                strength, profile, is_fno, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(symbol, signal_date, profile, direction) DO UPDATE SET
                price=excluded.price, rsi=excluded.rsi,
                pivot1_date=excluded.pivot1_date, pivot1_price=excluded.pivot1_price, pivot1_rsi=excluded.pivot1_rsi,
                pivot2_date=excluded.pivot2_date, pivot2_price=excluded.pivot2_price, pivot2_rsi=excluded.pivot2_rsi,
                strength=excluded.strength, is_fno=excluded.is_fno
            """,
            (
                s["symbol"], s.get("direction", "bullish"), s["signal_date"], s["price"], s["rsi"],
                s["pivot1_date"], s["pivot1_price"], s["pivot1_rsi"],
                s["pivot2_date"], s["pivot2_price"], s["pivot2_rsi"],
                s["strength"], s["profile"], int(bool(s.get("is_fno"))),
            ),
        )
        n += 1
    conn.commit()
    conn.close()
    return n


def get_signals(active_only: bool = True, asof: date | None = None) -> list[dict]:
    """Return signals, newest first. active_only filters to the freshness window."""
    conn = get_conn()
    if active_only:
        max_age = config.MAX_SIGNAL_AGE_DAYS
        rows = conn.execute(
            """
            SELECT * FROM signals
            WHERE julianday(?) - julianday(signal_date) <= ?
            ORDER BY strength DESC, signal_date DESC
            """,
            ((asof or date.today()).isoformat(), max_age),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM signals ORDER BY signal_date DESC, strength DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_meta(key: str, value: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def get_meta(key: str) -> str | None:
    conn = get_conn()
    cur = conn.execute("SELECT value FROM meta WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None
