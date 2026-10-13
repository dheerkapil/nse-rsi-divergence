"""Turn raw divergences into scored, filtered buy signals."""
from __future__ import annotations

import pandas as pd

import config
from src.indicators import rsi
from src.divergence import detect_divergence


def score(cand: dict, params: dict) -> float:
    """0–100 strength score.

    Components: RSI rise (40), depth of the lower price low (20),
    lowness of the second-pivot RSI (25), pivot separation (15).
    """
    rise = cand["pivot2_rsi"] - cand["pivot1_rsi"]
    drop_pct = (
        (cand["pivot1_price"] - cand["pivot2_price"]) / cand["pivot1_price"] * 100.0
        if cand["pivot1_price"] else 0.0
    )
    ceil = max(params["RSI_CEILING"], 1e-9)
    c_rise = min(rise / 15.0, 1.0) * 40.0
    c_drop = min(drop_pct / 10.0, 1.0) * 20.0
    c_level = max(0.0, min((ceil - cand["pivot2_rsi"]) / ceil, 1.0)) * 25.0
    c_sep = min(cand["sep"] / 20.0, 1.0) * 15.0
    return round(c_rise + c_drop + c_level + c_sep, 1)


def scan_symbol(symbol: str, df: pd.DataFrame, params: dict) -> dict | None:
    """Apply universe filters and return the strongest recent signal, or None."""
    if df is None or len(df) < params["MIN_HISTORY_BARS"]:
        return None

    last_close = float(df["close"].iloc[-1])
    if last_close < params["MIN_PRICE"]:
        return None

    if params.get("MIN_AVG_TURNOVER_LACS"):
        avg_turn = pd.to_numeric(df["turnover_lacs"], errors="coerce").tail(20).mean()
        if pd.notna(avg_turn) and avg_turn < params["MIN_AVG_TURNOVER_LACS"]:
            return None

    if params["GAP_GUARD_ENABLED"]:
        chg = df["close"].pct_change().abs()
        if (chg > params["GAP_GUARD_PCT"] / 100.0).any():
            return None  # likely an unadjusted split/bonus — skip

    r = rsi(df["close"], params["RSI_PERIOD"])
    cands = detect_divergence(df, r, params)
    if not cands:
        return None

    best = max(cands, key=lambda c: c["conf_idx"])  # most recent qualifying setup
    best["symbol"] = symbol
    best["strength"] = score(best, params)
    best["profile"] = params["PROFILE"]
    # enrichment for the dashboard / snapshot
    best["last_price"] = last_close
    best["last_date"] = str(df["date"].iloc[-1])
    best["age_bars"] = int(len(df) - 1 - best["conf_idx"])
    return best
