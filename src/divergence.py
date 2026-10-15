"""Fractal pivot detection and RSI-divergence scanning (bullish and bearish).

Regular bullish divergence = price makes a LOWER low  + RSI makes a HIGHER low
Regular bearish divergence = price makes a HIGHER high + RSI makes a LOWER high
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.indicators import ema


def _find_pivots(values: np.ndarray, order: int, kind: str) -> list[int]:
    n = len(values)
    out: list[int] = []
    for i in range(order, n - order):
        window = values[i - order : i + order + 1]
        if np.isnan(window).any():
            continue
        v = values[i]
        if kind == "low":
            if v == window.min() and int((window == v).sum()) == 1:
                out.append(i)
        else:
            if v == window.max() and int((window == v).sum()) == 1:
                out.append(i)
    return out


def find_pivot_lows(values: np.ndarray, order: int) -> list[int]:
    """Indices that are the unique lowest bar within ``order`` bars either side."""
    return _find_pivots(values, order, "low")


def find_pivot_highs(values: np.ndarray, order: int) -> list[int]:
    """Indices that are the unique highest bar within ``order`` bars either side."""
    return _find_pivots(values, order, "high")


def detect_divergence(df: pd.DataFrame, rsi: pd.Series, params: dict,
                      direction: str = "bullish") -> list[dict]:
    """Scan one symbol's history for regular divergences of the given direction.

    ``df``: columns date, open, high, low, close (ascending). ``rsi`` aligned to it.
    """
    order = params["PIVOT_ORDER"]
    lookback = params["LOOKBACK_BARS"]
    min_sep = params["MIN_PIVOT_SEPARATION"]

    lows = df["low"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    dates = df["date"].to_numpy()
    r = rsi.to_numpy(dtype=float)
    n = len(df)

    if n < max(params["MIN_HISTORY_BARS"], order * 2 + 2):
        return []

    bullish = direction == "bullish"
    basis = params.get("PIVOT_BASIS", "close")
    series = closes if basis == "close" else (lows if bullish else highs)

    start = max(order, n - lookback - order)
    piv = find_pivot_lows(series, order) if bullish else find_pivot_highs(series, order)
    pivots = [p for p in piv if p >= start]
    if len(pivots) < 2:
        return []

    gate = params["DOWNTURN_GATE"] if bullish else params.get("UPTREND_GATE", params["DOWNTURN_GATE"])
    ema_vals = ema(closes, params["DOWNTURN_EMA_SPAN"]).to_numpy() if gate else None

    flat = params.get("FLAT_TOL_PCT", 0.0) / 100.0   # flat top/bottom allowance
    rsi_delta = params["MIN_RSI_RISE"]

    candidates: list[dict] = []
    for a, b in zip(pivots[:-1], pivots[1:]):
        if b - a < min_sep:
            continue
        if np.isnan(r[a]) or np.isnan(r[b]):
            continue
        if bullish:
            if not (series[b] <= series[a] * (1.0 + flat)):  # lower low or flat
                continue
            if not (r[b] > r[a] + rsi_delta):                # higher RSI low
                continue
            if not (r[b] < params["RSI_CEILING"]):
                continue
        else:
            if not (series[b] >= series[a] * (1.0 - flat)):  # higher high or flat
                continue
            if not (r[b] < r[a] - rsi_delta):                # lower RSI high
                continue
            if not (r[b] > params.get("RSI_FLOOR", 50.0)):
                continue
        if gate and ema_vals is not None:
            lb = params["DOWNTURN_SLOPE_BARS"]
            if b - lb < 0:
                continue
            if bullish:
                if not (closes[b] < ema_vals[b] and ema_vals[b] < ema_vals[b - lb]):
                    continue
            else:
                if not (closes[b] > ema_vals[b] and ema_vals[b] > ema_vals[b - lb]):
                    continue
        conf = b + order
        if conf >= n:
            continue

        candidates.append({
            "symbol": None,
            "direction": direction,
            "state": "confirmed",
            "signal_date": str(dates[conf]),
            "price": float(closes[conf]),
            "rsi": float(r[conf]),
            "pivot1_date": str(dates[a]), "pivot1_price": float(series[a]), "pivot1_rsi": float(r[a]),
            "pivot2_date": str(dates[b]), "pivot2_price": float(series[b]), "pivot2_rsi": float(r[b]),
            "sep": int(b - a),
            "conf_idx": int(conf),
        })
    return candidates


def detect_forming(df: pd.DataFrame, rsi: pd.Series, params: dict,
                   direction: str = "bullish") -> list[dict]:
    """Provisional divergence, published *before* the second pivot is confirmed.

    The second pivot is the most extreme close in the last ``PIVOT_ORDER`` bars
    (knowable now, no look-ahead); it is paired with the last *confirmed* fractal
    pivot. Returns at most one candidate. Superseded once that low/high becomes a
    proper fractal, at which point the confirmed detector takes over.
    """
    order = params["PIVOT_ORDER"]
    min_sep = params["MIN_PIVOT_SEPARATION"]

    lows = df["low"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    dates = df["date"].to_numpy()
    r = rsi.to_numpy(dtype=float)
    n = len(df)
    if n < max(params["MIN_HISTORY_BARS"], order * 2 + 2):
        return []

    bullish = direction == "bullish"
    basis = params.get("PIVOT_BASIS", "close")
    series = closes if basis == "close" else (lows if bullish else highs)

    # provisional second pivot = most extreme close in the last `order` bars
    win = series[n - order:]
    p = (n - order) + (int(np.argmin(win)) if bullish else int(np.argmax(win)))

    piv = find_pivot_lows(series, order) if bullish else find_pivot_highs(series, order)
    prev = [x for x in piv if x <= p - order]
    if not prev:
        return []
    a = prev[-1]
    if p - a < min_sep or np.isnan(r[a]) or np.isnan(r[p]):
        return []

    gate = params["DOWNTURN_GATE"] if bullish else params.get("UPTREND_GATE", params["DOWNTURN_GATE"])
    ema_vals = ema(closes, params["DOWNTURN_EMA_SPAN"]).to_numpy() if gate else None

    flat = params.get("FLAT_TOL_PCT", 0.0) / 100.0
    rsi_delta = params["MIN_RSI_RISE"]

    if bullish:
        if not (series[p] <= series[a] * (1.0 + flat)):
            return []
        if not (r[p] > r[a] + rsi_delta):
            return []
        if not (r[p] < params["RSI_CEILING"]):
            return []
    else:
        if not (series[p] >= series[a] * (1.0 - flat)):
            return []
        if not (r[p] < r[a] - rsi_delta):
            return []
        if not (r[p] > params.get("RSI_FLOOR", 50.0)):
            return []

    if gate and ema_vals is not None:
        lb = params["DOWNTURN_SLOPE_BARS"]
        if p - lb < 0:
            return []
        if bullish:
            if not (closes[p] < ema_vals[p] and ema_vals[p] < ema_vals[p - lb]):
                return []
        else:
            if not (closes[p] > ema_vals[p] and ema_vals[p] > ema_vals[p - lb]):
                return []

    return [{
        "symbol": None,
        "direction": direction,
        "state": "forming",
        "signal_date": str(dates[p]),
        "price": float(closes[p]),
        "rsi": float(r[p]),
        "pivot1_date": str(dates[a]), "pivot1_price": float(series[a]), "pivot1_rsi": float(r[a]),
        "pivot2_date": str(dates[p]), "pivot2_price": float(series[p]), "pivot2_rsi": float(r[p]),
        "sep": int(p - a),
        "conf_idx": int(p),
    }]
