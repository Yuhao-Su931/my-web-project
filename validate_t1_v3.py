#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Complete 35-sample run with full-market minute fallbacks and data checks."""
import pandas as pd
import validate_t1_v2 as v

_call_number = 0


def sanitize_prices(frame):
    frame = frame.copy()
    for col in ['open', 'close', 'high', 'low']:
        frame[col] = pd.to_numeric(frame[col], errors='coerce')
    frame['close'] = frame['close'].replace(0, pd.NA).ffill().bfill()
    frame['open'] = frame['open'].where(frame['open'] > 0, frame['close'])
    fallback_high = frame[['open', 'close']].max(axis=1)
    fallback_low = frame[['open', 'close']].min(axis=1)
    frame['high'] = frame['high'].where(frame['high'] > 0, fallback_high)
    frame['low'] = frame['low'].where(frame['low'] > 0, fallback_low)
    frame['high'] = pd.concat([frame['high'], fallback_high], axis=1).max(axis=1)
    frame['low'] = pd.concat([frame['low'], fallback_low], axis=1).min(axis=1)
    if frame[['open', 'close', 'high', 'low']].isna().any().any():
        raise ValueError('unrepairable zero/NA price')
    return frame


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
            frame = sanitize_prices(getter(date, code))
            if frame.empty:
                raise ValueError('empty minute data')
            last_time = frame.trade_time.max().strftime('%H:%M')
            first_time = frame.trade_time.min().strftime('%H:%M')
            rows_to_deadline = len(frame[frame.trade_time.dt.strftime('%H:%M') <= required_end])
            if last_time < required_end or rows_to_deadline < minimum_rows:
                raise ValueError(f'incomplete rows={len(frame)} first={first_time} last={last_time} required_end={required_end}')
            return frame, name
        except Exception as exc:
            errors.append(f'{name}:{exc}')
    raise RuntimeError(' | '.join(errors))


v.minute = complete_minute
v.main()
