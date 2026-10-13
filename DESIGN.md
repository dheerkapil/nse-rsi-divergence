# NSE RSI-Divergence Buy-Signal Screener — Design Doc

**Status:** Logic locked (pre-build). Web-first; Telegram to follow.
**Look & feel:** mirrors `stock-alert-system` (Material palette, card layout, dark mode, login screen).

---

## 1. Purpose

Scan every NSE equity for **regular bullish RSI divergence** — the classic swing-buy
setup where price prints a *lower low* but RSI refuses to and prints a *higher low* —
and surface the freshest, highest-quality setups on a web dashboard.

Daily / end-of-day system (bhavcopy is EOD). Not intraday.

---

## 2. Data source

- **NSE full equity bhavcopy** (`sec_bhavdata_full_DDMMYYYY.csv`), one file per trading day.
- Gives per-symbol open, high, low, close, prev-close, volume, turnover, delivery %.
- Only the **EQ** series is kept.
- **Backfill:** ~1 year (~250 trading days) on first run, then append daily.

### Corporate-action guard
Bhavcopy prices are **unadjusted**. A split/bonus creates a huge artificial single-day
gap that both fakes "lower lows" and poisons RSI history.
**Guard:** if a symbol's close moves more than `GAP_GUARD_PCT` (default 35%) in one day,
flag it as a corporate-action suspect and exclude it from the pattern scan and RSI
continuity for a defined window. Refine later if needed.

---

## 3. Indicator

- **RSI:** Wilder's RSI, period **14** (default), on daily **closes**.
- Plain, no smoothing, standard parameters.

---

## 4. Pattern — regular bullish divergence

Definition: at two confirmed **pivot lows**,

- **price:** second low is *lower* than the first (`low2 < low1`), and
- **RSI:** second low is *higher* than the first (`rsi2 > rsi1`).

### Pivots
- **Fractal pivots:** a low that is the lowest bar within `PIVOT_ORDER` bars on each side.
- **Confirmed only:** a pivot is usable only after `PIVOT_ORDER` bars have passed.
- **Min separation:** the two lows must be at least `MIN_PIVOT_SEPARATION` bars apart
  (**default 5**, config-driven) — prevents one choppy stretch counting as two pivots.

### Downtrend gate
Regular bullish divergence is only meaningful at the end of a decline.
Gate: symbol must be in a downtrend (price below its falling EMA, or RSI arriving from
oversold). **On in the tight profile, off in loose.**

---

## 5. Strictness profiles

One `PROFILE` switch (`loose` | `tight`) drives three thresholds:

| Parameter            | Loose | Tight | Meaning                                   |
|----------------------|-------|-------|-------------------------------------------|
| `MIN_RSI_RISE`       | 1.0   | 5.0   | RSI must rise this much between the lows  |
| `MIN_PRICE_DROP_PCT` | 0.0   | 2.0   | Depth of the lower price low (%)          |
| `RSI_CEILING`        | 55    | 35    | 2nd-pivot RSI must be below this          |
| Downtrend gate       | off   | on    | Require a preceding decline               |

All values live in `config.py`, overridable by env vars.

---

## 6. Signal lifecycle

- Fires when a confirmed second pivot completes.
- **Active window:** `MAX_SIGNAL_AGE_DAYS` (default **10** trading days); drops off the
  dashboard after that, history retained.
- Re-firing later on the same symbol = a new, separate signal.

---

## 7. Scoring

Each signal gets a **0–100 strength score** to rank the dashboard. Composite of:

- magnitude of the RSI rise between lows,
- depth of the lower price low,
- RSI level at the second pivot (lower = stronger),
- pivot separation / timing quality.

Dashboard sorts by score by default.

---

## 8. Output — web dashboard (look & feel of `stock-alert-system`)

- Card layout, Roboto, Material palette, CSS variables, light/dark toggle, login screen.
- Sortable signals table.

**Columns:** Symbol · Signal Date · Price at signal · Current price · % move since ·
RSI now · Pivot-1 (date/price/RSI) · Pivot-2 (date/price/RSI) · Strength · Age (days).

- Telegram delivery: **phase 2** (same bot pattern as existing repos).

---

## 9. Config parameters (all in `config.py`)

```
PROFILE                 loose | tight
RSI_PERIOD              14
PIVOT_ORDER             5
MIN_PIVOT_SEPARATION    5      # reduced per request
LOOKBACK_BARS           120
MIN_RSI_RISE            1.0 / 5.0
MIN_PRICE_DROP_PCT      0.0 / 2.0
RSI_CEILING             55 / 35
MAX_SIGNAL_AGE_DAYS     10
GAP_GUARD_PCT           35
MIN_PRICE               20
MIN_AVG_TURNOVER_LACS   100
BACKFILL_DAYS           ~250
```

---

## 10. Architecture (planned)

```
nse-rsi-divergence/
├── config.py               # every knob
├── run_daily.py            # fetch -> store -> compute -> persist signals
├── scripts/backfill.py     # one-off 1-year history load
├── src/
│   ├── downloader.py       # NSE bhavcopy fetch + parse
│   ├── database.py         # SQLite price/signal store
│   ├── indicators.py       # Wilder RSI
│   ├── divergence.py       # pivot + divergence detection
│   └── signals.py          # scoring + lifecycle
├── web/app.py              # Flask dashboard + login
├── web/templates/          # index.html, login.html (stock-alert-system look & feel)
├── .github/workflows/      # daily run
└── tests/
```

---

## 11. Roadmap

1. **Phase 1 (now):** data → RSI → divergence → signals → web dashboard.
2. **Phase 2:** Telegram notifications.
3. **Phase 3:** refinements — hidden/positive-reversal divergence as a second labelled
   type, proper corporate-action adjustment, backtesting of signal outcomes.
