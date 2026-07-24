#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import requests

import validate_t1 as v

ROOT = Path(__file__).resolve().parent
SAMPLES = pd.read_csv(ROOT / 'samples.csv', dtype=str)
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn/'})


def symbol(code: str) -> str:
    n = code.split('.')[0]
    if code.endswith('.SH'):
        return 'sh' + n
    if code.endswith('.SZ'):
        return 'sz' + n
    return 'bj' + n


def sanitize(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    d['trade_time'] = pd.to_datetime(d['trade_time'])
    for c in ['open', 'close', 'high', 'low', 'vol', 'amount']:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=['trade_time', 'open', 'close', 'high', 'low']).sort_values('trade_time').reset_index(drop=True)
    d['vol'] = d['vol'].fillna(0).clip(lower=0)
    d['amount'] = d['amount'].fillna(d['close'] * d['vol']).clip(lower=0)
    return d[['trade_time', 'open', 'close', 'high', 'low', 'vol', 'amount']]


def sina_5m(date: str, code: str) -> pd.DataFrame:
    url = (
        'https://quotes.sina.cn/cn/api/json_v2.php/'
        'CN_MarketDataService.getKLineData?'
        f'symbol={symbol(code)}&scale=5&ma=no&datalen=1023'
    )
    r = SESSION.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    target = f'{date[:4]}-{date[4:6]}-{date[6:]}'
    rows = []
    for x in data:
        if not str(x.get('day', '')).startswith(target):
            continue
        close = float(x['close'])
        vol = float(x.get('volume', 0) or 0)
        amount = float(x.get('amount', 0) or 0)
        if amount <= 0:
            amount = close * vol
        rows.append({
            'trade_time': pd.Timestamp(x['day']),
            'open': float(x['open']),
            'close': close,
            'high': float(x['high']),
            'low': float(x['low']),
            'vol': vol,
            'amount': amount,
        })
    d = sanitize(pd.DataFrame(rows))
    if d.empty or d['trade_time'].max().strftime('%H:%M') < '14:45' or len(d) < 45:
        raise RuntimeError(f'Sina 5m incomplete {date} {code}: rows={len(d)}')
    print(f'SOURCE {date} {code}: sina_5m rows={len(d)}', flush=True)
    return d


def tencent_1m(date: str, code: str) -> pd.DataFrame:
    sym = symbol(code)
    url = f'https://web.ifzq.gtimg.cn/appstock/app/day/query?code={sym}'
    r = SESSION.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'})
    r.raise_for_status()
    root = (r.json().get('data') or {}).get(sym)
    found = None

    def walk(obj):
        nonlocal found
        if found is not None:
            return
        if isinstance(obj, dict):
            if str(obj.get('date', '')).replace('-', '') == date and isinstance(obj.get('data'), list):
                found = obj['data']
                return
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(root)
    if not found:
        raise RuntimeError(f'Tencent 1m date missing {date} {code}')

    day = f'{date[:4]}-{date[4:6]}-{date[6:]}'
    rows = []
    prev_price = None
    prev_vol = 0.0
    prev_amount = 0.0
    for item in found:
        if not isinstance(item, str):
            continue
        a = item.split()
        if len(a) < 3:
            continue
        hhmm = a[0]
        price = float(a[1])
        cum_vol = float(a[2])
        cum_amount = float(a[3]) if len(a) > 3 else price * cum_vol
        op = price if prev_price is None else prev_price
        rows.append({
            'trade_time': pd.Timestamp(f'{day} {hhmm[:2]}:{hhmm[2:]}'),
            'open': op,
            'close': price,
            'high': max(op, price),
            'low': min(op, price),
            'vol': max(0.0, cum_vol - prev_vol),
            'amount': max(0.0, cum_amount - prev_amount),
        })
        prev_price, prev_vol, prev_amount = price, cum_vol, cum_amount
    d = sanitize(pd.DataFrame(rows))
    morning = d[(d.trade_time.dt.strftime('%H:%M') >= '09:30') & (d.trade_time.dt.strftime('%H:%M') <= '10:00')]
    if len(morning) < 25:
        raise RuntimeError(f'Tencent 1m incomplete {date} {code}: morning_rows={len(morning)} total={len(d)}')
    print(f'SOURCE {date} {code}: tencent_1m rows={len(d)}', flush=True)
    return d


def minute_for(date: str, code: str) -> pd.DataFrame:
    if date == '20260717':
        return sina_5m(date, code)
    if date == '20260720':
        return tencent_1m(date, code)
    raise RuntimeError(f'unexpected date {date}')


def find_entry_5m(df: pd.DataFrame, first_open):
    if first_open is None:
        i = len(df) - 1
        return i, float(df.iloc[i]['close']), 'sina_5m_signal_close_no_open_detected'
    for i in range(first_open, len(df) - 1):
        r = df.iloc[i]
        if r['trade_time'].strftime('%H:%M') > '14:45':
            break
        if r['return_pct'] >= 8.0 and r['close'] >= r['vwap'] and not bool(r['close_on_limit']):
            j = i + 1
            while j < len(df) and bool(df.iloc[j]['close_on_limit']):
                j += 1
            if j < len(df):
                return j, float(df.iloc[j]['open']), 'sina_5m_stable_bar_next_open'
    i = len(df) - 1
    return i, float(df.iloc[i]['close']), 'sina_5m_signal_close_after_no_fill'


v.minute_for = minute_for
v.find_entry = find_entry_5m
v.main()
