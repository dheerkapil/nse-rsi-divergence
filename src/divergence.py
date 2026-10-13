"""Fractal pivot detection and regular bullish RSI-divergence scanning.

Regular bullish divergence = price makes a LOWER low while RSI makes a
HIGHER low at two confirmed pivot lows. It is a reversal signal.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.indicators import ema


def find_pivot_lows(values: np.ndarray, order: int) -> list[int]:
    """Indices that are the unique lowest bar within ``order`` bars either side.

    Only returns pivots that are fully confirmed (at least ``order`` bars follow).
    """
    n = len(values)
    out: list[int] = []
    for i in range(order, n - order):
        window = values[i - order : i + order + 1]
        if np.isnan(window).any():
            continue
        v = values[i]
        if v == window.min() and int((window == v).sum()) == 1:
            out.append(i)
    return out


def detect_divergence(df: pd.DataFrame, rsi: pd.Series, params: dict) -> list[dict]:
    """Scan one symbol's history for regular bullish divergences.

    ``df``: columns date, open, high, low, close (ascending). ``rsi`` aligned to it.
    Returns candidate dicts (symbol unset) — one per qualifying pivot pair.
    """
    order = params["PIVOT_ORDER"]
    lookback = params["LOOKBACK_BARS"]
    min_sep = params["MIN_PIVOT_SEPARATION"]

    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    dates = df["date"].to_numpy()
    r = rsi.to_numpy(dtype=float)
    n = len(df)

    if n < max(params["MIN_HISTORY_BARS"], order * 2 + 2):
        return []

    basis = params.get("PIVOT_BASIS", "close")
    pivot_series = closes if basis == "close" else lows

    start = max(order, n - lookback - order)
    pivots = [p for p in find_pivot_lows(pivot_series, order) if p >= start]
    if len(pivots) < 2:
        return []

    ema_vals = ema(closes, params["DOWNTURN_EMA_SPAN"]).to_numpy() if params["DOWNTURN_GATE"] else None

    candidates: list[dict] = []
    for a, b in zip(pivots[:-1], pivots[1:]):
        if b - a < min_sep:
            continue
        if np.isnan(r[a]) or np.isnan(r[b]):
            continue
        # 1. price: lower low
        if not (pivot_series[b] < pivot_series[a] * (1.0 - params["MIN_PRICE_DROP_PCT"] / 100.0)):
            continue
        # 2. RSI: higher low
        if not (r[b] > r[a] + params["MIN_RSI_RISE"]):
            continue
        # 3. RSI ceiling at the second pivot
        if not (r[b] < params["RSI_CEILING"]):
            continue
        # 4. downtrend gate (tight profile)
        if params["DOWNTURN_GATE"] and ema_vals is not None:
            lb = params["DOWNTURN_SLOPE_BARS"]
            if b - lb < 0:
                continue
            if not (closes[b] < ema_vals[b] and ema_vals[b] < ema_vals[b - lb]):
                continue
        # 5. confirmation bar (pivot b becomes knowable `order` bars later)
        conf = b + order
        if conf >= n:
            continue

        candidates.append({
            "symbol": None,
            "signal_date": str(dates[conf]),
            "price": float(closes[conf]),
            "rsi": float(r[conf]),
            "pivot1_date": str(dates[a]), "pivot1_price": float(pivot_series[a]), "pivot1_rsi": float(r[a]),
            "pivot2_date": str(dates[b]), "pivot2_price": float(pivot_series[b]), "pivot2_rsi": float(r[b]),
            "sep": int(b - a),
            "conf_idx": int(conf),
        })
    return candidates
