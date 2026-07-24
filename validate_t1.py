#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import io
import math
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd
import requests

BASE = "https://raw.githubusercontent.com/njedu2023-prog/top10-decision/main"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "results"
OUT.mkdir(exist_ok=True)

MIN_RETURN_PCT = 8.0
STABLE_MINUTES = 3
ENTRY_LATEST = "14:45"
FAST_LIMIT_DEADLINE = "10:00"
ABSOLUTE_EXIT_TIME = "10:00"
EARLY_DIRECTION_MINUTES = 3
EARLY_DIRECT_DROP_PCT = 1.0
MIN_OBSERVE_MINUTES = 3
STALL_MINUTES = 2
PEAK_PULLBACK_PCT = 0.6
REBOUND_TRIGGER_PCT = 0.8
MAX_REBOUND_WAIT_MINUTES = 12
HARD_STOP_FROM_ENTRY_PCT = 4.0
COMMISSION_BPS_PER_SIDE = 2.5
STAMP_TAX_BPS_SELL = 5.0
SLIPPAGE_BPS_PER_SIDE = 2.0
TICK = 0.01

session = requests.Session()
session.headers.update({"User-Agent": "T1-validation/1.0"})
text_cache: Dict[str, str] = {}
df_cache: Dict[str, pd.DataFrame] = {}


def get_text(url: str, retries: int = 4) -> str:
    if url in text_cache:
        return text_cache[url]
    last = None
    for i in range(retries):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 404:
                raise FileNotFoundError(url)
            r.raise_for_status()
            r.encoding = "utf-8-sig"
            text_cache[url] = r.text
            return r.text
        except Exception as exc:
            last = exc
            if i + 1 == retries:
                raise
            time.sleep(1.5 * (2 ** i))
    raise last


def read_remote_csv(path: str) -> pd.DataFrame:
    url = f"{BASE}/{path}"
    if url in df_cache:
        return df_cache[url].copy()
    text = get_text(url)
    df = pd.read_csv(io.StringIO(text))
    df.columns = [str(c).lstrip("\ufeff") for c in df.columns]
    df_cache[url] = df
    return df.copy()


def daily_for(date: str) -> pd.DataFrame:
    return read_remote_csv(f"data/market/raw/2026/{date}/daily.csv")


def limits_for(date: str) -> pd.DataFrame:
    return read_remote_csv(f"data/market/raw/2026/{date}/stk_limit.csv")


def minute_for(date: str, code: str) -> pd.DataFrame:
    filename = code.replace(".", "_") + ".csv"
    df = read_remote_csv(f"data/market/minute_1m/2026/{date}/{filename}")
    time_col = "time" if "time" in df.columns else "trade_time"
    df["trade_time"] = pd.to_datetime(df[time_col])
    for c in ["open", "close", "high", "low", "vol", "amount"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["trade_time", "open", "close", "high", "low"])
    return df.sort_values("trade_time").reset_index(drop=True)


def row_for(df: pd.DataFrame, code: str) -> pd.Series:
    m = df[df["ts_code"].astype(str) == code]
    if m.empty:
        raise KeyError(f"{code} not found")
    return m.iloc[0]


def add_indicators(df: pd.DataFrame, pre_close: float, up_limit: float) -> pd.DataFrame:
    out = df.copy()
    out["cum_vol"] = out["vol"].fillna(0).clip(lower=0).cumsum()
    out["cum_amount"] = out["amount"].fillna(0).clip(lower=0).cumsum()
    out["vwap"] = out["cum_amount"] / out["cum_vol"].replace(0, math.nan)
    ratio = (out["amount"] / out["vol"].replace(0, math.nan)).median()
    median_close = out["close"].median()
    if pd.notna(ratio) and pd.notna(median_close) and median_close > 0:
        scale = ratio / median_close
        if scale > 50:
            out["vwap"] /= 100
        elif scale < 0.02:
            out["vwap"] *= 100
    out["return_pct"] = (out["close"] / pre_close - 1) * 100
    out["high_return_pct"] = (out["high"] / pre_close - 1) * 100
    out["low_return_pct"] = (out["low"] / pre_close - 1) * 100
    out["touch_limit"] = out["high"] >= up_limit - TICK / 2
    out["close_on_limit"] = out["close"] >= up_limit - TICK / 2
    out["below_limit"] = out["low"] < up_limit - TICK / 2
    return out


def board_info(df: pd.DataFrame) -> Tuple[int, Optional[int], Optional[int], Optional[int]]:
    touches = df.index[df["touch_limit"]].tolist()
    if not touches:
        return 0, None, None, None
    first_touch = touches[0]
    first_open = None
    segments = 0
    in_open = False
    reseal = None
    if not bool(df.iloc[first_touch]["close_on_limit"]):
        first_open = first_touch
        segments = 1
        in_open = True
    for i in range(first_touch + 1, len(df)):
        prev_on = bool(df.iloc[i - 1]["close_on_limit"])
        curr_below = bool(df.iloc[i]["below_limit"])
        curr_on = bool(df.iloc[i]["close_on_limit"])
        if not in_open and prev_on and curr_below:
            segments += 1
            in_open = True
            if first_open is None:
                first_open = i
        if in_open and curr_on:
            in_open = False
            reseal = i
    return segments, first_touch, first_open, reseal


def find_entry(df: pd.DataFrame, first_open: Optional[int]) -> Tuple[Optional[int], Optional[float], str]:
    if first_open is None:
        return None, None, "no_open_board_minute"
    streak = 0
    for i in range(first_open, len(df)):
        r = df.iloc[i]
        if r["trade_time"].strftime("%H:%M") > ENTRY_LATEST:
            break
        ok = r["return_pct"] >= MIN_RETURN_PCT and r["close"] >= r["vwap"] and not bool(r["close_on_limit"])
        streak = streak + 1 if ok else 0
        if streak >= STABLE_MINUTES:
            fill_i = i + 1
            while fill_i < len(df) and bool(df.iloc[fill_i]["close_on_limit"]):
                fill_i += 1
            if fill_i < len(df):
                return fill_i, float(df.iloc[fill_i]["open"]), "strict_3m_next_open"
            return None, None, "strict_signal_no_fill"
    for i in range(first_open, len(df) - 1):
        r = df.iloc[i]
        if r["trade_time"].strftime("%H:%M") > ENTRY_LATEST:
            break
        ok = r["return_pct"] >= MIN_RETURN_PCT and r["close"] >= r["vwap"] and not bool(r["close_on_limit"])
        if ok:
            fill_i = i + 1
            while fill_i < len(df) and bool(df.iloc[fill_i]["close_on_limit"]):
                fill_i += 1
            if fill_i < len(df):
                return fill_i, float(df.iloc[fill_i]["open"]), "fallback_1m_next_open"
    return None, None, "no_executable_entry"


def classify_open(work: pd.DataFrame) -> str:
    early = work.iloc[:max(2, EARLY_DIRECTION_MINUTES)]
    op = float(work.iloc[0]["open"])
    drop = (float(early["low"].min()) / op - 1) * 100
    rise = (float(early["high"].max()) / op - 1) * 100
    if drop <= -EARLY_DIRECT_DROP_PCT and (abs(drop) >= rise or float(early.iloc[-1]["close"]) < op):
        return "direct_drop_then_rebound"
    return "rally_or_high_level_oscillation"


def fill_next_open(work: pd.DataFrame, signal_i: int) -> Tuple[int, pd.Timestamp, float]:
    j = min(signal_i + 1, len(work) - 1)
    r = work.iloc[j]
    return j, r["trade_time"], float(r["open"])


def analyze_exit(df: pd.DataFrame, entry: float, pre_close: float, up_limit: float) -> Dict[str, object]:
    hhmm = df["trade_time"].dt.strftime("%H:%M")
    work = df[(hhmm >= "09:30") & (hhmm <= ABSOLUTE_EXIT_TIME)].copy().reset_index(drop=True)
    if work.empty:
        raise RuntimeError("empty T+1 window")
    mode = classify_open(work)
    open_price = float(work.iloc[0]["open"])
    stop_price = entry * (1 - HARD_STOP_FROM_ENTRY_PCT / 100)
    if open_price <= stop_price:
        signal_i = fill_i = 0
        fill_time = work.iloc[0]["trade_time"]
        fill_price = open_price
        reason = "gap_below_hard_stop"
    else:
        peak = float(work.iloc[0]["high"])
        peak_i = 0
        trough = float(work.iloc[0]["low"])
        trough_i = 0
        rebound_started = False
        rebound_peak = None
        rebound_peak_i = None
        signal_i = fill_i = None
        fill_time = None
        fill_price = None
        reason = ""
        for i, r in work.iterrows():
            t = r["trade_time"].strftime("%H:%M")
            high, low, close = float(r["high"]), float(r["low"]), float(r["close"])
            if high >= up_limit - TICK / 2 and t <= FAST_LIMIT_DEADLINE:
                signal_i = fill_i = i
                fill_time = r["trade_time"]
                fill_price = up_limit
                reason = "fast_limit_touch"
                break
            if close <= stop_price:
                signal_i = i
                fill_i, fill_time, fill_price = fill_next_open(work, i)
                reason = "hard_stop_after_open"
                break
            if mode == "rally_or_high_level_oscillation":
                if high > peak:
                    peak, peak_i = high, i
                bars_since_peak = i - peak_i
                pullback = (close / peak - 1) * 100
                if i + 1 >= MIN_OBSERVE_MINUTES and (bars_since_peak >= STALL_MINUTES or pullback <= -PEAK_PULLBACK_PCT):
                    signal_i = i
                    fill_i, fill_time, fill_price = fill_next_open(work, i)
                    reason = "first_rally_stalled" if bars_since_peak >= STALL_MINUTES else "first_rally_reversed"
                    break
            else:
                if low < trough:
                    trough, trough_i = low, i
                    rebound_started = False
                    rebound_peak = rebound_peak_i = None
                if not rebound_started and high >= trough * (1 + REBOUND_TRIGGER_PCT / 100):
                    rebound_started = True
                    rebound_peak, rebound_peak_i = high, i
                if rebound_started:
                    if high > float(rebound_peak):
                        rebound_peak, rebound_peak_i = high, i
                    bars_since_peak = i - int(rebound_peak_i)
                    pullback = (close / float(rebound_peak) - 1) * 100
                    if bars_since_peak >= STALL_MINUTES or pullback <= -PEAK_PULLBACK_PCT:
                        signal_i = i
                        fill_i, fill_time, fill_price = fill_next_open(work, i)
                        reason = "first_rebound_stalled" if bars_since_peak >= STALL_MINUTES else "first_rebound_failed"
                        break
                elif i - trough_i >= MAX_REBOUND_WAIT_MINUTES:
                    signal_i = i
                    fill_i, fill_time, fill_price = fill_next_open(work, i)
                    reason = "no_effective_rebound"
                    break
        if fill_price is None:
            signal_i = fill_i = len(work) - 1
            fill_time = work.iloc[-1]["trade_time"]
            fill_price = float(work.iloc[-1]["close"])
            reason = "absolute_time_stop"
    window = work.iloc[: int(fill_i) + 1]
    high_i = int(window["high"].idxmax())
    window_high = float(work.iloc[high_i]["high"])
    window_low = float(window["low"].min())
    buy_cost = (COMMISSION_BPS_PER_SIDE + SLIPPAGE_BPS_PER_SIDE) / 10000
    sell_cost = (COMMISSION_BPS_PER_SIDE + STAMP_TAX_BPS_SELL + SLIPPAGE_BPS_PER_SIDE) / 10000
    gross = (float(fill_price) / entry - 1) * 100
    net = ((float(fill_price) * (1 - sell_cost)) / (entry * (1 + buy_cost)) - 1) * 100
    return {
        "t1_open": open_price,
        "t1_open_return_pct": (open_price / pre_close - 1) * 100,
        "t1_mode": mode,
        "window_high_time": work.iloc[high_i]["trade_time"].strftime("%H:%M"),
        "window_high_price": window_high,
        "window_high_return_pct": (window_high / pre_close - 1) * 100,
        "window_low_return_pct": (window_low / pre_close - 1) * 100,
        "exit_signal_time": work.iloc[int(signal_i)]["trade_time"].strftime("%H:%M"),
        "exit_fill_time": pd.Timestamp(fill_time).strftime("%H:%M"),
        "exit_price": float(fill_price),
        "exit_reason": reason,
        "gross_return_pct": gross,
        "net_return_pct": net,
        "mfe_pct": (window_high / entry - 1) * 100,
        "mae_pct": (window_low / entry - 1) * 100,
    }


def main() -> None:
    samples = pd.read_csv(ROOT / "samples.csv", dtype=str)
    rows = []
    for n, s in samples.iterrows():
        signal_date = s["signal_date"]
        t1_date = s["next_trade_date"]
        name = s["stock_name"]
        code = s["ts_code"]
        print(f"[{n+1}/{len(samples)}] {signal_date} {name} {code}", flush=True)
        result = {"signal_date": signal_date, "next_trade_date": t1_date, "stock_name": name, "ts_code": code, "status": "error", "detail": ""}
        try:
            sd = row_for(daily_for(signal_date), code)
            td = row_for(daily_for(t1_date), code)
            sl = row_for(limits_for(signal_date), code)
            tl = row_for(limits_for(t1_date), code)
            signal_pre = float(sd["pre_close"])
            signal_close = float(sd["close"])
            signal_up = float(sl["up_limit"])
            t1_pre = float(td["pre_close"])
            t1_up = float(tl["up_limit"])
            signal = add_indicators(minute_for(signal_date, code), signal_pre, signal_up)
            t1 = add_indicators(minute_for(t1_date, code), t1_pre, t1_up)
            segments, first_touch, first_open, reseal = board_info(signal)
            entry_i, entry_price, entry_source = find_entry(signal, first_open)
            result.update({
                "signal_pre_close": signal_pre,
                "signal_close": signal_close,
                "signal_up_limit": signal_up,
                "signal_first_touch": signal.iloc[first_touch]["trade_time"].strftime("%H:%M") if first_touch is not None else "",
                "signal_open_segments_1m": segments,
                "signal_first_open": signal.iloc[first_open]["trade_time"].strftime("%H:%M") if first_open is not None else "",
                "signal_reseal": signal.iloc[reseal]["trade_time"].strftime("%H:%M") if reseal is not None else "",
                "entry_source": entry_source,
                "entry_time": signal.iloc[entry_i]["trade_time"].strftime("%H:%M") if entry_i is not None else "",
                "entry_price": entry_price if entry_price is not None else "",
                "t1_pre_close": t1_pre,
                "t1_up_limit": t1_up,
            })
            if entry_price is None:
                result["status"] = "no_executable_entry"
                result["detail"] = entry_source
            else:
                result.update(analyze_exit(t1, float(entry_price), t1_pre, t1_up))
                result["status"] = "completed"
                result["detail"] = ""
        except FileNotFoundError as exc:
            result["status"] = "missing_minute_file"
            result["detail"] = str(exc)
        except Exception as exc:
            result["status"] = "error"
            result["detail"] = repr(exc)
        rows.append(result)
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "all_35_results.csv", index=False, encoding="utf-8-sig")
    completed = out[out["status"] == "completed"].copy()
    completed["net_return_pct"] = pd.to_numeric(completed["net_return_pct"], errors="coerce")
    summary = {
        "total_samples": len(out),
        "completed_samples": len(completed),
        "not_completed_samples": int((out["status"] != "completed").sum()),
        "profit_samples": int((completed["net_return_pct"] > 0).sum()),
        "non_loss_samples": int((completed["net_return_pct"] >= 0).sum()),
        "loss_samples": int((completed["net_return_pct"] < 0).sum()),
        "win_rate_pct": float((completed["net_return_pct"] > 0).mean() * 100) if len(completed) else math.nan,
        "non_loss_rate_pct": float((completed["net_return_pct"] >= 0).mean() * 100) if len(completed) else math.nan,
        "average_net_return_pct": float(completed["net_return_pct"].mean()) if len(completed) else math.nan,
        "median_net_return_pct": float(completed["net_return_pct"].median()) if len(completed) else math.nan,
        "max_net_return_pct": float(completed["net_return_pct"].max()) if len(completed) else math.nan,
        "min_net_return_pct": float(completed["net_return_pct"].min()) if len(completed) else math.nan,
    }
    pd.DataFrame([summary]).to_csv(OUT / "summary.csv", index=False, encoding="utf-8-sig")
    if len(completed):
        by_date = completed.groupby("signal_date")["net_return_pct"].agg(samples="count", average="mean", median="median", worst="min", best="max").reset_index()
        wins = completed.assign(win=completed["net_return_pct"] > 0).groupby("signal_date")["win"].sum().reset_index(name="wins")
        by_date = by_date.merge(wins, on="signal_date")
        by_date["win_rate_pct"] = by_date["wins"] / by_date["samples"] * 100
        by_date.to_csv(OUT / "summary_by_date.csv", index=False, encoding="utf-8-sig")
    print(pd.DataFrame([summary]).to_string(index=False))
    print(out[["signal_date", "stock_name", "status", "entry_source", "net_return_pct"]].to_string(index=False))


if __name__ == "__main__":
    main()
