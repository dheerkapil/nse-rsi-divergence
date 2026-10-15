"""Turn raw divergences into scored, filtered signals (bullish and bearish)."""
from __future__ import annotations

import pandas as pd

import config
from src.indicators import rsi
from src.divergence import detect_divergence

DIRECTIONS = ("bullish", "bearish")


def score(cand: dict, params: dict) -> float:
    """0–100 strength score (direction-aware).

    Components: RSI delta (40), depth of the price move (20),
    RSI level at the second pivot (25), pivot separation (15).
    """
    delta = abs(cand["pivot2_rsi"] - cand["pivot1_rsi"])
    p1, p2 = cand["pivot1_price"], cand["pivot2_price"]
    move_pct = abs(p1 - p2) / p1 * 100.0 if p1 else 0.0
    if cand["direction"] == "bullish":
        ceil = max(params["RSI_CEILING"], 1e-9)
        c_level = max(0.0, min((ceil - cand["pivot2_rsi"]) / ceil, 1.0)) * 25.0
    else:
        floor = params.get("RSI_FLOOR", 50.0)
        c_level = max(0.0, min((cand["pivot2_rsi"] - floor) / max(100.0 - floor, 1e-9), 1.0)) * 25.0
    c_rsi = min(delta / 15.0, 1.0) * 40.0
    c_move = min(move_pct / 10.0, 1.0) * 20.0
    c_sep = min(cand["sep"] / 20.0, 1.0) * 15.0
    return round(c_rsi + c_move + c_level + c_sep, 1)


def scan_symbol(symbol: str, df: pd.DataFrame, params: dict, fno: set | None = None) -> list[dict]:
    """Return the best bullish and/or bearish signal for one symbol (0-2 items)."""
    if df is None or len(df) < params["MIN_HISTORY_BARS"]:
        return []

    last_close = float(df["close"].iloc[-1])
    if last_close < params["MIN_PRICE"]:
        return []

    if params.get("MIN_AVG_TURNOVER_LACS"):
        avg_turn = pd.to_numeric(df["turnover_lacs"], errors="coerce").tail(20).mean()
        if pd.notna(avg_turn) and avg_turn < params["MIN_AVG_TURNOVER_LACS"]:
            return []

    if params["GAP_GUARD_ENABLED"]:
        chg = df["close"].pct_change().abs()
        if (chg > params["GAP_GUARD_PCT"] / 100.0).any():
            return []

    r = rsi(df["close"], params["RSI_PERIOD"])

    out: list[dict] = []
    for direction in DIRECTIONS:
        cands = detect_divergence(df, r, params, direction)
        if not cands:
            continue
        best = max(cands, key=lambda c: c["conf_idx"])
        best["symbol"] = symbol
        best["strength"] = score(best, params)
        best["profile"] = params["PROFILE"]
        best["last_price"] = last_close
        best["last_date"] = str(df["date"].iloc[-1])
        best["age_bars"] = int(len(df) - 1 - best["conf_idx"])
        best["is_fno"] = bool(fno and symbol in fno)
        # invalidated if price closes beyond the level that defined the setup,
        # on any bar after the confirmation date (closes only)
        after = df["close"].iloc[best["conf_idx"] + 1:]
        if direction == "bullish":
            best["invalidated"] = bool((after < best["pivot2_price"]).any())
        else:
            best["invalidated"] = bool((after > best["pivot2_price"]).any())
        out.append(best)
    return out
