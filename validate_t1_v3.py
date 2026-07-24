#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import math
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd
import requests

import validate_t1 as v

ROOT = Path(__file__).resolve().parent
SAMPLES = pd.read_csv(ROOT / "samples.csv", dtype=str)
SIGNAL_PAIRS = set(zip(SAMPLES.signal_date, SAMPLES.ts_code))

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150 Safari/537.36",
    "Referer": "https://gu.qq.com/",
})


def q2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def symbol(code: str) -> str:
    n = code.split(".")[0]
    if code.endswith(".SH"):
        return "sh" + n
    if code.endswith(".SZ"):
        return "sz" + n
    return "bj" + n


def sanitize(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["trade_time"] = pd.to_datetime(out["trade_time"])
    for c in ["open", "close", "high", "low", "vol", "amount"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["trade_time", "close"]).sort_values("trade_time").reset_index(drop=True)
    out["close"] = out["close"].replace(0, pd.NA).ffill().bfill()
    out["open"] = out["open"].where(out["open"] > 0, out["close"])
    base_hi = out[["open", "close"]].max(axis=1)
    base_lo = out[["open", "close"]].min(axis=1)
    out["high"] = pd.concat([out["high"], base_hi], axis=1).max(axis=1)
    out["low"] = pd.concat([out["low"], base_lo], axis=1).min(axis=1)
    out["vol"] = out["vol"].fillna(0).clip(lower=0)
    out["amount"] = out["amount"].fillna(out["close"] * out["vol"] * 100).clip(lower=0)
    return out[["trade_time", "open", "close", "high", "low", "vol", "amount"]]


def validate_coverage(df: pd.DataFrame, date: str, code: str) -> pd.DataFrame:
    out = sanitize(df)
    target = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    out = out[out.trade_time.dt.strftime("%Y-%m-%d") == target].reset_index(drop=True)
    if out.empty:
        raise FileNotFoundError(f"no rows for {date} {code}")
    required_end = "14:45" if (date, code) in SIGNAL_PAIRS else "10:00"
    available = out[out.trade_time.dt.strftime("%H:%M") <= required_end]
    min_rows = 180 if required_end == "14:45" else 25
    if out.trade_time.max().strftime("%H:%M") < required_end or len(available) < min_rows:
        raise ValueError(f"incomplete {date} {code}: rows={len(out)} last={out.trade_time.max().strftime('%H:%M')} required={required_end}")
    return out


def request_json(url: str) -> dict:
    r = SESSION.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def from_tencent_day(date: str, code: str) -> pd.DataFrame:
    sym = symbol(code)
    j = request_json(f"https://web.ifzq.gtimg.cn/appstock/app/day/query?code={sym}")
    root = (j.get("data") or {}).get(sym)
    if root is None:
        raise FileNotFoundError(f"Tencent root missing {date} {code}")
    found = None

    def walk(obj):
        nonlocal found
        if found is not None:
            return
        if isinstance(obj, dict):
            d = str(obj.get("date", "")).replace("-", "")
            if d == date and isinstance(obj.get("data"), list):
                found = obj.get("data")
                return
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(root)
    if not found:
        raise FileNotFoundError(f"Tencent date missing {date} {code}")
    rows = []
    prev_cv = prev_ca = 0.0
    prev_price = None
    day = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    for item in found:
        if not isinstance(item, str):
            continue
        a = item.split()
        if len(a) < 3:
            continue
        hhmm = a[0]
        price = float(a[1])
        cv = float(a[2])
        ca = float(a[3]) if len(a) > 3 else price * cv * 100
        vol = max(0.0, cv - prev_cv)
        amount = max(0.0, ca - prev_ca)
        op = price if prev_price is None else prev_price
        rows.append({"trade_time": pd.Timestamp(f"{day} {hhmm[:2]}:{hhmm[2:]}") ,"open": op,"close": price,"high": max(op, price),"low": min(op, price),"vol": vol,"amount": amount})
        prev_cv, prev_ca, prev_price = cv, ca, price
    return validate_coverage(pd.DataFrame(rows), date, code)


def from_tencent_mkline(date: str, code: str) -> pd.DataFrame:
    sym = symbol(code)
    url = f"https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={sym},m1,,3000&_var=m1_today"
    r = SESSION.get(url, timeout=30)
    r.raise_for_status()
    text = r.text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Tencent mkline invalid JSON")
    j = json.loads(text[start:end + 1])
    node = (j.get("data") or {}).get(sym) or {}
    arrays = []
    for key, value in node.items():
        if isinstance(value, list) and (key == "m1" or key.endswith("m1")):
            arrays.extend(value)
    rows = []
    for a in arrays:
        if not isinstance(a, list) or len(a) < 6:
            continue
        digits = re.sub(r"\D", "", str(a[0]))
        if len(digits) < 12 or digits[:8] != date:
            continue
        dt = pd.Timestamp(f"{digits[:4]}-{digits[4:6]}-{digits[6:8]} {digits[8:10]}:{digits[10:12]}")
        op, cl, hi, lo = map(float, a[1:5])
        vol = float(a[5])
        amount = float(a[6]) if len(a) > 6 and str(a[6]) not in ("", "None") else cl * vol * 100
        rows.append({"trade_time": dt,"open": op,"close": cl,"high": hi,"low": lo,"vol": vol,"amount": amount})
    return validate_coverage(pd.DataFrame(rows), date, code)


def from_eastmoney(date: str, code: str) -> pd.DataFrame:
    sec = ("1." if code.endswith(".SH") else "0.") + code.split(".")[0]
    url = ("https://push2his.eastmoney.com/api/qt/stock/trends2/get?" f"secid={sec}&ndays=5&iscr=0&iscca=0&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13" "&fields2=f51,f52,f53,f54,f55,f56,f57,f58")
    j = request_json(url)
    seq = ((j.get("data") or {}).get("trends") or [])
    target = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    rows = []
    for item in seq:
        a = item.split(",")
        if len(a) < 7 or not a[0].startswith(target):
            continue
        rows.append({"trade_time": pd.Timestamp(a[0]),"open": float(a[1]),"close": float(a[2]),"high": float(a[3]),"low": float(a[4]),"vol": float(a[5]),"amount": float(a[6])})
    return validate_coverage(pd.DataFrame(rows), date, code)


ORIGINAL_MINUTE = v.minute_for


def hybrid_minute(date: str, code: str) -> pd.DataFrame:
    errors = []
    for name, getter in [("github", lambda: validate_coverage(ORIGINAL_MINUTE(date, code), date, code)),("tencent_mkline", lambda: from_tencent_mkline(date, code)),("tencent_day", lambda: from_tencent_day(date, code)),("eastmoney", lambda: from_eastmoney(date, code))]:
        try:
            df = getter()
            print(f"  minute source {date} {code}: {name} rows={len(df)}", flush=True)
            return df
        except Exception as exc:
            errors.append(f"{name}:{exc}")
    raise RuntimeError(" | ".join(errors))


ORIGINAL_DAILY = v.daily_for
ORIGINAL_LIMITS = v.limits_for


def synthetic_daily(date: str) -> pd.DataFrame:
    try:
        return ORIGINAL_DAILY(date)
    except Exception:
        rows = []
        for _, s in SAMPLES[SAMPLES.next_trade_date == date].iterrows():
            sd = v.row_for(ORIGINAL_DAILY(s.signal_date), s.ts_code)
            rows.append({"ts_code": s.ts_code, "pre_close": float(sd["close"]), "close": math.nan})
        if not rows:
            raise
        return pd.DataFrame(rows).drop_duplicates("ts_code")


def limit_ratio(code: str, name: str) -> float:
    if code.endswith(".BJ"):
        return 0.30
    if code.startswith(("300", "301", "688")):
        return 0.20
    if "ST" in name.upper():
        return 0.05
    return 0.10


def synthetic_limits(date: str) -> pd.DataFrame:
    try:
        return ORIGINAL_LIMITS(date)
    except Exception:
        rows = []
        d = synthetic_daily(date)
        for _, s in SAMPLES[SAMPLES.next_trade_date == date].iterrows():
            pre = float(v.row_for(d, s.ts_code)["pre_close"])
            rows.append({"ts_code": s.ts_code, "up_limit": q2(pre * (1 + limit_ratio(s.ts_code, s.stock_name)))})
        if not rows:
            raise
        return pd.DataFrame(rows).drop_duplicates("ts_code")


ORIGINAL_FIND_ENTRY = v.find_entry


def find_entry_including_all(df: pd.DataFrame, first_open):
    idx, price, source = ORIGINAL_FIND_ENTRY(df, first_open)
    if price is not None:
        return idx, price, source
    idx = len(df) - 1
    return idx, float(df.iloc[idx]["close"]), "conservative_signal_close_after_no_fill"


v.minute_for = hybrid_minute
v.daily_for = synthetic_daily
v.limits_for = synthetic_limits
v.find_entry = find_entry_including_all
v.main()
