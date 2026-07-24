#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final wrapper: correct Eastmoney OHLC and reject incomplete minute files."""
import pandas as pd
import validate_t1_v2 as v

_call_number = 0


def corrected_eastmoney(date, code):
    url = (
        'https://push2his.eastmoney.com/api/qt/stock/trends2/get?secid=' + v.secid(code) +
        '&ndays=5&iscr=0&iscca=0&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13'
        '&fields2=f51,f52,f53,f54,f55,f56,f57,f58'
    )
    j = v.req_json(url)
    seq = ((j.get('data') or {}).get('trends') or [])
    rows = []
    day_prefix = f'{date[:4]}-{date[4:6]}-{date[6:]}'
    for x in seq:
        a = x.split(',')
        if len(a) < 8 or not a[0].startswith(day_prefix):
            continue
        rows.append({
            'trade_time': pd.Timestamp(a[0]),
            'open': float(a[1]),
            'close': float(a[2]),
            'high': float(a[3]),
            'low': float(a[4]),
            'vol': float(a[5]),
            'amount': float(a[6]),
        })
    if not rows:
        raise FileNotFoundError(f'Eastmoney {date} {code}')
    return pd.DataFrame(rows).sort_values('trade_time').reset_index(drop=True)


v.minute_eastmoney = corrected_eastmoney


def complete_minute(date, code):
    global _call_number
    is_signal_day_call = (_call_number % 2 == 0)
    _call_number += 1
    required_end = '14:45' if is_signal_day_call else '10:00'
    minimum_rows = 190 if is_signal_day_call else 25
    errors = []
    for name, getter in [
        ('github', v.minute_github),
        ('eastmoney', v.minute_eastmoney),
        ('tencent', v.minute_tencent),
    ]:
        try:
            frame = getter(date, code)
            if frame.empty:
                raise ValueError('empty minute data')
            last_time = frame.trade_time.max().strftime('%H:%M')
            first_time = frame.trade_time.min().strftime('%H:%M')
            rows_to_deadline = len(
                frame[frame.trade_time.dt.strftime('%H:%M') <= required_end]
            )
            if last_time < required_end or rows_to_deadline < minimum_rows:
                raise ValueError(
                    f'incomplete rows={len(frame)} first={first_time} '
                    f'last={last_time} required_end={required_end}'
                )
            return frame, name
        except Exception as exc:
            errors.append(f'{name}:{exc}')
    raise RuntimeError(' | '.join(errors))


v.minute = complete_minute
v.main()
