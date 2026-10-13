#!/usr/bin/env python3
"""Daily pipeline: fetch bhavcopy -> store -> scan -> persist signals -> snapshot.

Usage:
    python run_daily.py                 # today's bhavcopy (walks back over holidays)
    python run_daily.py --date 2026-10-09
    python run_daily.py --no-fetch      # rescan existing DB only
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))

import requests  # noqa: E402

import config  # noqa: E402
from src.downloader import fetch_bhavcopy  # noqa: E402
from src.database import (  # noqa: E402
    init_db, store_prices, get_symbols, get_price_history,
    store_signals, set_meta, get_last_price_date,
)
from src.signals import scan_symbol  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
HISTORY_BARS = 300  # bars loaded per symbol for the scan


def _today_ist() -> date:
    return datetime.now(IST).date()


def latest_available_bhavcopy(session: requests.Session, start: date, max_back: int = 7):
    """Return (date, df) for the most recent published bhavcopy at/behind ``start``."""
    d = start
    for _ in range(max_back):
        if d.weekday() < 5:  # skip weekends outright
            df = fetch_bhavcopy(d, session=session)
            if df is not None and not df.empty:
                return d, df
        d -= timedelta(days=1)
    return None, None


def scan_all(params: dict) -> list[dict]:
    signals: list[dict] = []
    symbols = get_symbols()
    for sym in symbols:
        df = get_price_history(sym, limit=HISTORY_BARS)
        sig = scan_symbol(sym, df, params)
        if sig:
            signals.append(sig)
    signals.sort(key=lambda s: (s["strength"], s["signal_date"]), reverse=True)
    return signals


def write_snapshot(signals: list[dict], params: dict, asof: str) -> Path:
    payload = {
        "generated_at": datetime.now(IST).isoformat(),
        "profile": params["PROFILE"],
        "asof": asof,
        "count": len(signals),
        "signals": signals,
    }
    out = config.OUTPUT_DIR / "daily_signals.json"
    out.write_text(json.dumps(payload, indent=2))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="target date YYYY-MM-DD (default: today IST)")
    ap.add_argument("--no-fetch", action="store_true", help="skip download, rescan DB")
    args = ap.parse_args()

    init_db()
    params = config.active_params()

    asof = args.date or _today_ist().isoformat()

    if not args.no_fetch:
        target = date.fromisoformat(asof)
        session = requests.Session()
        got, df = latest_available_bhavcopy(session, target)
        if df is None:
            print(f"[run_daily] No bhavcopy available at/behind {asof}. Aborting.")
            return 1
        n = store_prices(df)
        asof = got.isoformat()
        print(f"[run_daily] Stored {n} EQ rows for {asof} (profile={params['PROFILE']})")

    signals = scan_all(params)
    store_signals(signals)
    set_meta("last_run", datetime.now(IST).isoformat())
    set_meta("last_price_date", get_last_price_date() or "")
    snap = write_snapshot(signals, params, asof)

    print(f"[run_daily] {len(signals)} active signal(s); snapshot -> {snap}")
    for s in signals[:15]:
        print(f"   {s['symbol']:>12}  {s['signal_date']}  RSI2={s['pivot2_rsi']:.1f}  "
              f"strength={s['strength']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
