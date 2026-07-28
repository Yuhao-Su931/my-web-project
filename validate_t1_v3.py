#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Complete 35-sample run with minute-data completeness checks."""
import pandas as pd
import validate_t1_v2 as v

_call_number = 0

def sanitize_prices(frame):
    frame=frame.copy()
    for col in ['open','close','high','low']:
        frame[col]=pd.to_numeric(frame[col],errors='coerce')
    frame['close']=frame['close'].replace(0,pd.NA).ffill().bfill()
    frame['open']=frame['open'].where(frame['open']>0,frame['close'])
    fallback_high=frame[['open','close']].max(axis=1)
    fallback_low=frame[['open','close']].min(axis=1)
    frame['high']=frame['high'].where(frame['high']>0,fallback_high)
    frame['low']=frame['low'].where(frame['low']>0,fallback_low)
    frame['high']=pd.concat([frame['high'],fallback_high],axis=1).max(axis=1)
    frame['low']=pd.concat([frame['low'],fallback_low],axis=1).min(axis=1)
    if frame[['open','close','high','low']].isna().any().any():raise ValueError('unrepairable price')
    return frame

def complete_minute(date,code):
    global _call_number
    is_signal=(_call_number%2==0);_call_number+=1
    required_end='14:45' if is_signal else '10:00'
    minimum_rows=190 if is_signal else 25
    errors=[]
    for name,getter in [('github',v.minute_github),('eastmoney',v.minute_eastmoney),('tencent',v.minute_tencent)]:
        try:
            frame=sanitize_prices(getter(date,code))
            last=frame.trade_time.max().strftime('%H:%M')
            rows_to_deadline=len(frame[frame.trade_time.dt.strftime('%H:%M')<=required_end])
            if last<required_end or rows_to_deadline<minimum_rows:raise ValueError(f'incomplete rows={len(frame)} last={last}')
            return frame,name
        except Exception as exc:errors.append(f'{name}:{exc}')
    raise RuntimeError(' | '.join(errors))

v.minute=complete_minute
v.main()
