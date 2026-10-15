"""Fractal pivot detection and RSI-divergence scanning (bullish and bearish).

Regular bullish divergence = price makes a LOWER low  + RSI makes a HIGHER low
Regular bearish divergence = price makes a HIGHER high + RSI makes a LOWER high
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.indicators import ema, atr


def _atr_series(df: pd.DataFrame, params: dict):
    """ATR array if an ATR-based confirmation is enabled, else None."""
    if not (params.get("ATR_MULT") or 0.0):
        return None
    if not {"high", "low", "prev_close"}.issubset(df.columns):
        return None
    return atr(df["high"], df["low"], df["prev_close"],
               params.get("ATR_PERIOD", 14)).to_numpy(dtype=float)


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
    atr_vals = _atr_series(df, params)
    mult = params.get("ATR_MULT", 0.0) or 0.0

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
        # whichever first: an ATR-sized bounce off the pivot can confirm earlier
        if atr_vals is not None and not np.isnan(atr_vals[b]):
            need = mult * atr_vals[b]
            for t in range(b + 1, min(b + order, n)):
                hit = (closes[t] >= series[b] + need) if bullish else (closes[t] <= series[b] - need)
                if hit:
                    conf = t
                    break
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
    (knowable now, no look-ahead); it is paired with the **previous swing low**
    (the most extreme close in the ``order`` bars ending ``MIN_PIVOT_SEPARATION``
    bars before it). Returns at most one candidate. Promoted to confirmed once the
    close has moved ``ATR_MULT`` x ATR off it.
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

    # reference = the PREVIOUS swing low: the most extreme close in the `order`
    # bars ending `min_sep` bars before p. Using the previous swing low (not the
    # last confirmed fractal) avoids skipping back past recent lows when they
    # spoil each other in a decline.
    hi = p - min_sep + 1
    lo = hi - order
    if lo < 0:
        return []
    ref = series[lo:hi]
    a = lo + (int(np.argmin(ref)) if bullish else int(np.argmax(ref)))
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

    # whichever first: promote to confirmed once the close has moved k*ATR off
    # the provisional pivot (the fractal cannot apply to a provisional low).
    atr_vals = _atr_series(df, params)
    mult = params.get("ATR_MULT", 0.0) or 0.0
    state, conf = "forming", p
    if atr_vals is not None and not np.isnan(atr_vals[p]):
        need = mult * atr_vals[p]
        for t in range(p + 1, n):
            hit = (closes[t] >= series[p] + need) if bullish else (closes[t] <= series[p] - need)
            if hit:
                state, conf = "confirmed", t
                break

    return [{
        "symbol": None,
        "direction": direction,
        "state": state,
        "signal_date": str(dates[conf]),
        "price": float(closes[conf]),
        "rsi": float(r[conf]),
        "pivot1_date": str(dates[a]), "pivot1_price": float(series[a]), "pivot1_rsi": float(r[a]),
        "pivot2_date": str(dates[p]), "pivot2_price": float(series[p]), "pivot2_rsi": float(r[p]),
        "sep": int(p - a),
        "conf_idx": int(conf),
    }]
