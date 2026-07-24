#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final wrapper: reject incomplete minute files before running v2."""
import validate_t1_v2 as v


def complete_minute(date, code, required_end='10:00'):
    errors = []
    minimum_rows = 25 if required_end <= '10:00' else 190
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
