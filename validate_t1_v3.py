#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import io, math
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import pandas as pd
import requests

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results';OUT.mkdir(exist_ok=True)
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://quote.eastmoney.com/'})
GH='https://raw.githubusercontent.com/njedu2023-prog/top10-decision/main'
CACHE={}
BUY_BPS=4.5;SELL_BPS=9.5

def get_json(url):
    r=S.get(url,timeout=8);r.raise_for_status();return r.json()
def get_csv(url):
    if url in CACHE:return CACHE[url].copy()
    r=S.get(url,timeout=8);r.raise_for_status();r.encoding='utf-8-sig';d=pd.read_csv(io.StringIO(r.text));d.columns=[str(c).lstrip('\ufeff') for c in d.columns];CACHE[url]=d;return d.copy()
def daily_row(date,code):
    d=get_csv(f'{GH}/data/market/raw/2026/{date}/daily.csv');m=d[d.ts_code.astype(str)==code]
    if m.empty:raise KeyError(f'daily {date} {code}')
    return m.iloc[0]
def secid(code):return ('1.' if code.endswith('.SH') else '0.')+code.split('.')[0]
def round_price(x):return float(Decimal(str(x)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))
def limit_ratio(code,name):
    if code.endswith('.BJ'):return .30
    if code.startswith(('300','301','688')):return .20
    if 'ST' in name.upper():return .05
    return .10

def minute_eastmoney(date,code):
    url=('https://push2his.eastmoney.com/api/qt/stock/trends2/get?secid='+secid(code)+
         '&ndays=5&iscr=0&iscca=0&ut=fa5fd1943c7b386f172d6893dbfba10b&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13&fields2=f51,f52,f53,f54,f55,f56,f57,f58')
    j=get_json(url);seq=((j.get('data') or {}).get('trends') or []);prefix=f'{date[:4]}-{date[4:6]}-{date[6:]}';rows=[]
    for x in seq:
        a=x.split(',')
        if len(a)>=8 and a[0].startswith(prefix):
            rows.append({'trade_time':pd.Timestamp(a[0]),'open':float(a[1]),'close':float(a[2]),'high':float(a[3]),'low':float(a[4]),'vol':float(a[5]),'amount':float(a[6])})
    if len(rows)<25:raise FileNotFoundError(f'eastmoney {date} {code} rows={len(rows)}')
    return pd.DataFrame(rows).sort_values('trade_time').reset_index(drop=True),'eastmoney'
def minute_tencent(date,code):
    prefix='sh' if code.endswith('.SH') else 'sz' if code.endswith('.SZ') else 'bj';symbol=prefix+code.split('.')[0]
    j=get_json(f'https://web.ifzq.gtimg.cn/appstock/app/day/query?code={symbol}')
    node=((j.get('data') or {}).get(symbol) or {});arr=node.get('data') or []
    day=next((x for x in arr if str(x.get('date'))==date),None)
    if not day:raise FileNotFoundError(f'tencent {date} {code}')
    rows=[]
    for x in day.get('data',[]):
        a=x.split();t=a[0];price=float(a[1]);cv=float(a[2]);ca=float(a[3]);rows.append({'trade_time':pd.Timestamp(f'{date[:4]}-{date[4:6]}-{date[6:]} {t[:2]}:{t[2:]}'),'close':price,'cumv':cv,'cuma':ca})
    d=pd.DataFrame(rows).sort_values('trade_time').reset_index(drop=True)
    if len(d)<25:raise FileNotFoundError(f'tencent rows={len(d)}')
    d['open']=d.close.shift(1).fillna(d.close);d['high']=d[['open','close']].max(axis=1);d['low']=d[['open','close']].min(axis=1);d['vol']=d.cumv.diff().fillna(d.cumv);d['amount']=d.cuma.diff().fillna(d.cuma)
    return d[['trade_time','open','close','high','low','vol','amount']],'tencent'
def minute(date,code):
    errors=[]
    for fn in (minute_eastmoney,minute_tencent):
        try:return fn(date,code)
        except Exception as e:errors.append(repr(e))
    raise RuntimeError(' | '.join(errors))

def classify(w):
    e=w.iloc[:3];op=float(w.iloc[0].open);drop=(float(e.low.min())/op-1)*100;rise=(float(e.high.max())/op-1)*100
    return 'direct_drop_then_rebound' if drop<=-1 and (abs(drop)>=rise or float(e.iloc[-1].close)<op) else 'rally_or_high_level_oscillation'
def next_fill(w,i):
    j=min(i+1,len(w)-1);return j,w.iloc[j].trade_time,float(w.iloc[j].open)
def exit_rule(d,entry,pre,up):
    hm=d.trade_time.dt.strftime('%H:%M');w=d[(hm>='09:30')&(hm<='10:00')].copy().reset_index(drop=True)
    if len(w)<25:raise RuntimeError(f'incomplete T1 window rows={len(w)}')
    mode=classify(w);op=float(w.iloc[0].open);stop=entry*.96
    if op<=stop:si=fi=0;ft=w.iloc[0].trade_time;fp=op;reason='gap_below_hard_stop'
    else:
        peak=float(w.iloc[0].high);pi=0;trough=float(w.iloc[0].low);ti=0;started=False;rp=ri=None;fp=None
        for i,r in w.iterrows():
            hi,lo,cl=map(float,[r.high,r.low,r.close])
            if hi>=up-.005:si=fi=i;ft=r.trade_time;fp=up;reason='fast_limit_touch';break
            if cl<=stop:si=i;fi,ft,fp=next_fill(w,i);reason='hard_stop_after_open';break
            if mode=='rally_or_high_level_oscillation':
                if hi>peak:peak=hi;pi=i
                since=i-pi;pb=(cl/peak-1)*100
                if i+1>=3 and (since>=2 or pb<=-.6):si=i;fi,ft,fp=next_fill(w,i);reason='first_rally_stalled' if since>=2 else 'first_rally_reversed';break
            else:
                if lo<trough:trough=lo;ti=i;started=False;rp=ri=None
                if not started and hi>=trough*1.008:started=True;rp=hi;ri=i
                if started:
                    if hi>rp:rp=hi;ri=i
                    since=i-ri;pb=(cl/rp-1)*100
                    if since>=2 or pb<=-.6:si=i;fi,ft,fp=next_fill(w,i);reason='first_rebound_stalled' if since>=2 else 'first_rebound_failed';break
                elif i-ti>=12:si=i;fi,ft,fp=next_fill(w,i);reason='no_effective_rebound';break
        if fp is None:si=fi=len(w)-1;ft=w.iloc[-1].trade_time;fp=float(w.iloc[-1].close);reason='absolute_time_stop'
    win=w.iloc[:fi+1];hi_i=int(win.high.idxmax());wh=float(w.iloc[hi_i].high);wl=float(win.low.min());net=((fp*(1-SELL_BPS/10000))/(entry*(1+BUY_BPS/10000))-1)*100
    return {'t1_open':op,'t1_open_return_pct':(op/pre-1)*100,'first_wave_mode':mode,'window_high_time':w.iloc[hi_i].trade_time.strftime('%H:%M'),'window_high_return_pct':(wh/pre-1)*100,'window_low_return_pct':(wl/pre-1)*100,'exit_signal_time':w.iloc[si].trade_time.strftime('%H:%M'),'exit_fill_time':pd.Timestamp(ft).strftime('%H:%M'),'exit_price':fp,'exit_reason':reason,'gross_return_pct':(fp/entry-1)*100,'net_return_pct':net,'mfe_pct':(wh/entry-1)*100,'mae_pct':(wl/entry-1)*100}

def main():
    samples=pd.read_csv(ROOT/'samples.csv',dtype=str);rows=[]
    for i,s in samples.iterrows():
        sd,td,name,code=s.signal_date,s.next_trade_date,s.stock_name,s.ts_code;print(f'[{i+1}/35] {name}',flush=True);r={'signal_date':sd,'next_trade_date':td,'stock_name':name,'ts_code':code,'status':'error','detail':''}
        try:
            dr=daily_row(sd,code);pre=float(dr.pre_close);close=float(dr.close);ratio=limit_ratio(code,name);floor=.24 if ratio==.30 else .08;entry=max(close,round_price(pre*(1+floor)));up=round_price(close*(1+ratio));m,src=minute(td,code);r.update(signal_pre_close=pre,signal_close=close,entry_floor_pct=floor*100,entry_price=entry,entry_source='conservative_max_signal_close_or_floor',t1_pre_close=close,t1_up_limit=up,t1_minute_source=src);r.update(exit_rule(m,entry,close,up));r['status']='completed'
        except Exception as e:r['detail']=repr(e)
        rows.append(r)
    out=pd.DataFrame(rows);out.to_csv(OUT/'all_35_results.csv',index=False,encoding='utf-8-sig');c=out[out.status=='completed'].copy();c['net_return_pct']=pd.to_numeric(c.net_return_pct,errors='coerce');summary={'total_samples':len(out),'completed_samples':len(c),'not_completed_samples':int((out.status!='completed').sum()),'profit_samples':int((c.net_return_pct>0).sum()),'non_loss_samples':int((c.net_return_pct>=0).sum()),'loss_samples':int((c.net_return_pct<0).sum()),'win_rate_pct':float((c.net_return_pct>0).mean()*100) if len(c) else math.nan,'non_loss_rate_pct':float((c.net_return_pct>=0).mean()*100) if len(c) else math.nan,'average_net_return_pct':float(c.net_return_pct.mean()) if len(c) else math.nan,'median_net_return_pct':float(c.net_return_pct.median()) if len(c) else math.nan,'max_net_return_pct':float(c.net_return_pct.max()) if len(c) else math.nan,'min_net_return_pct':float(c.net_return_pct.min()) if len(c) else math.nan};pd.DataFrame([summary]).to_csv(OUT/'summary.csv',index=False,encoding='utf-8-sig')
    if len(c):
        bd=c.groupby('signal_date').net_return_pct.agg(samples='count',average='mean',median='median',worst='min',best='max').reset_index();wins=c.assign(win=c.net_return_pct>0).groupby('signal_date').win.sum().reset_index(name='wins');bd=bd.merge(wins,on='signal_date');bd['win_rate_pct']=bd.wins/bd.samples*100;bd.to_csv(OUT/'summary_by_date.csv',index=False,encoding='utf-8-sig')
    print(pd.DataFrame([summary]).to_string(index=False));print(out[['signal_date','stock_name','status','t1_minute_source','net_return_pct','detail']].to_string(index=False))
if __name__=='__main__':main()
