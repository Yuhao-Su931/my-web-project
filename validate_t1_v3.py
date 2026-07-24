#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final wrapper: reject incomplete minute files before running v2."""
import validate_t1_v2 as v

_call_number = 0


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
