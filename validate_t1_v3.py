#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import math
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import pandas as pd
import requests
import validate_t1 as v

ROOT=Path(__file__).resolve().parent
SAMPLES=pd.read_csv(ROOT/'samples.csv',dtype=str)
SIGNAL=set(zip(SAMPLES.signal_date,SAMPLES.ts_code))
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://gu.qq.com/'})
ORIG_MIN=v.minute_for; ORIG_DAILY=v.daily_for; ORIG_LIMITS=v.limits_for; ORIG_ENTRY=v.find_entry

def sym(code):
    n=code.split('.')[0]
    return ('sh' if code.endswith('.SH') else 'sz' if code.endswith('.SZ') else 'bj')+n

def clean(d,date,code):
    x=d.copy(); x['trade_time']=pd.to_datetime(x['trade_time'])
    for c in ['open','close','high','low','vol','amount']: x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna(subset=['trade_time','close']).sort_values('trade_time').reset_index(drop=True)
    x['close']=x['close'].replace(0,pd.NA).ffill().bfill(); x['open']=x['open'].where(x['open']>0,x['close'])
    hi=x[['open','close']].max(axis=1); lo=x[['open','close']].min(axis=1)
    x['high']=pd.concat([x['high'],hi],axis=1).max(axis=1); x['low']=pd.concat([x['low'],lo],axis=1).min(axis=1)
    x['vol']=x['vol'].fillna(0).clip(lower=0); x['amount']=x['amount'].fillna(x['close']*x['vol']*100).clip(lower=0)
    target=f'{date[:4]}-{date[4:6]}-{date[6:]}'
    x=x[x.trade_time.dt.strftime('%Y-%m-%d')==target].reset_index(drop=True)
    need='14:45' if (date,code) in SIGNAL else '10:00'; minimum=180 if need=='14:45' else 25
    if x.empty or x.trade_time.max().strftime('%H:%M')<need or len(x[x.trade_time.dt.strftime('%H:%M')<=need])<minimum:
        raise ValueError(f'incomplete {date} {code} rows={len(x)}')
    return x[['trade_time','open','close','high','low','vol','amount']]

def tx_day(date,code):
    code2=sym(code); r=S.get(f'https://web.ifzq.gtimg.cn/appstock/app/day/query?code={code2}',timeout=6); r.raise_for_status(); j=r.json()
    root=(j.get('data') or {}).get(code2); found=None
    def walk(o):
        nonlocal found
        if found is not None:return
        if isinstance(o,dict):
            if str(o.get('date','')).replace('-','')==date and isinstance(o.get('data'),list): found=o['data']; return
            for z in o.values(): walk(z)
        elif isinstance(o,list):
            for z in o: walk(z)
    walk(root)
    if not found: raise FileNotFoundError(f'tencent {date} {code}')
    day=f'{date[:4]}-{date[4:6]}-{date[6:]}'; rows=[]; pc=None; pv=pa=0.0
    for z in found:
        if not isinstance(z,str):continue
        a=z.split()
        if len(a)<3:continue
        t,p,cv=a[0],float(a[1]),float(a[2]); ca=float(a[3]) if len(a)>3 else p*cv*100
        op=p if pc is None else pc
        rows.append({'trade_time':pd.Timestamp(f'{day} {t[:2]}:{t[2:]}'),'open':op,'close':p,'high':max(op,p),'low':min(op,p),'vol':max(0,cv-pv),'amount':max(0,ca-pa)})
        pc,pv,pa=p,cv,ca
    return clean(pd.DataFrame(rows),date,code)

def east(date,code):
    sec=('1.' if code.endswith('.SH') else '0.')+code.split('.')[0]
    url=('https://push2his.eastmoney.com/api/qt/stock/trends2/get?secid='+sec+'&ndays=5&iscr=0&iscca=0&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13&fields2=f51,f52,f53,f54,f55,f56,f57,f58')
    r=S.get(url,timeout=6); r.raise_for_status(); seq=((r.json().get('data') or {}).get('trends') or [])
    target=f'{date[:4]}-{date[4:6]}-{date[6:]}'; rows=[]
    for z in seq:
        a=z.split(',')
        if len(a)>=7 and a[0].startswith(target): rows.append({'trade_time':pd.Timestamp(a[0]),'open':float(a[1]),'close':float(a[2]),'high':float(a[3]),'low':float(a[4]),'vol':float(a[5]),'amount':float(a[6])})
    return clean(pd.DataFrame(rows),date,code)

def minute(date,code):
    if (date,code) in SIGNAL:
        sources=[('github',lambda:clean(ORIG_MIN(date,code),date,code)),('tencent',lambda:tx_day(date,code)),('eastmoney',lambda:east(date,code))]
    else:
        sources=[('tencent',lambda:tx_day(date,code)),('eastmoney',lambda:east(date,code))]
    errs=[]
    for name,fn in sources:
        try:
            d=fn(); print(f'SOURCE {date} {code} {name} {len(d)}',flush=True); return d
        except Exception as e: errs.append(f'{name}:{e}')
    raise RuntimeError(' | '.join(errs))

def daily(date):
    try:return ORIG_DAILY(date)
    except Exception:
        rows=[]
        for _,s in SAMPLES[SAMPLES.next_trade_date==date].iterrows():
            sd=v.row_for(ORIG_DAILY(s.signal_date),s.ts_code); rows.append({'ts_code':s.ts_code,'pre_close':float(sd['close']),'close':math.nan})
        if not rows:raise
        return pd.DataFrame(rows).drop_duplicates('ts_code')

def ratio(code,name):
    if code.endswith('.BJ'):return .30
    if code.startswith(('300','301','688')):return .20
    if 'ST' in name.upper():return .05
    return .10

def limits(date):
    try:return ORIG_LIMITS(date)
    except Exception:
        d=daily(date); rows=[]
        for _,s in SAMPLES[SAMPLES.next_trade_date==date].iterrows():
            pre=float(v.row_for(d,s.ts_code)['pre_close']); up=float(Decimal(str(pre*(1+ratio(s.ts_code,s.stock_name)))).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)); rows.append({'ts_code':s.ts_code,'up_limit':up})
        if not rows:raise
        return pd.DataFrame(rows).drop_duplicates('ts_code')

def entry_all(d,fo):
    i,p,s=ORIG_ENTRY(d,fo)
    if p is not None:return i,p,s
    i=len(d)-1; return i,float(d.iloc[i].close),'conservative_signal_close_after_no_fill'

v.minute_for=minute; v.daily_for=daily; v.limits_for=limits; v.find_entry=entry_all
v.main()
