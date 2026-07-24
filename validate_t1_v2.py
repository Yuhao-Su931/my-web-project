#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import io, math, time
from pathlib import Path
from typing import Dict
import pandas as pd
import requests
GH='https://raw.githubusercontent.com/njedu2023-prog/top10-decision/main'
ROOT=Path(__file__).resolve().parent; OUT=ROOT/'results'; OUT.mkdir(exist_ok=True)
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://quote.eastmoney.com/'})
CACHE:Dict[str,pd.DataFrame]={}; TICK=.01
MIN_RET=8.0; STABLE=3; ENTRY_LATEST='14:45'; FAST_LIMIT='10:00'; EXIT_DEADLINE='10:00'
EARLY_N=3; DIRECT_DROP=1.0; MIN_OBS=3; STALL=2; PULLBACK=.6; REBOUND=.8; REBOUND_WAIT=12; HARD_STOP=4.0
BUY_BPS=4.5; SELL_BPS=9.5

def req_json(url,retries=3):
    last=None
    for i in range(retries):
        try:
            r=S.get(url,timeout=30); r.raise_for_status(); return r.json()
        except Exception as e:
            last=e
            if i+1<retries: time.sleep(1.2*(2**i))
    raise last

def remote_csv(path):
    url=f'{GH}/{path}'
    if url in CACHE:return CACHE[url].copy()
    r=S.get(url,timeout=30)
    if r.status_code==404: raise FileNotFoundError(url)
    r.raise_for_status(); r.encoding='utf-8-sig'
    d=pd.read_csv(io.StringIO(r.text)); d.columns=[str(c).lstrip('\ufeff') for c in d.columns]; CACHE[url]=d
    return d.copy()
def daily(date): return remote_csv(f'data/market/raw/2026/{date}/daily.csv')
def limits(date): return remote_csv(f'data/market/raw/2026/{date}/stk_limit.csv')
def pick(df,code):
    m=df[df.ts_code.astype(str)==code]
    if m.empty: raise KeyError(f'{code} missing')
    return m.iloc[0]
def secid(code): return ('1.' if code.endswith('.SH') else '0.')+code.split('.')[0]

def minute_github(date,code):
    d=remote_csv(f"data/market/minute_1m/2026/{date}/{code.replace('.','_')}.csv")
    tc='time' if 'time' in d else 'trade_time'; d['trade_time']=pd.to_datetime(d[tc])
    for c in ['open','close','high','low','vol','amount']: d[c]=pd.to_numeric(d[c],errors='coerce')
    return d.dropna(subset=['trade_time','close']).sort_values('trade_time').reset_index(drop=True)
def minute_eastmoney(date,code):
    url=('https://push2his.eastmoney.com/api/qt/stock/trends2/get?secid='+secid(code)+'&ndays=5&iscr=0&iscca=0&ut=fa5fd1943c7b386f172d6893dbfba10b&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13&fields2=f51,f52,f53,f54,f55,f56,f57,f58')
    j=req_json(url); seq=((j.get('data') or {}).get('trends') or []); rows=[]
    prefix=f'{date[:4]}-{date[4:6]}-{date[6:]}'
    for x in seq:
        a=x.split(',')
        if len(a)>=8 and a[0].startswith(prefix):
            rows.append({'trade_time':pd.Timestamp(a[0]),'open':float(a[1]),'close':float(a[2]),'high':float(a[3]),'low':float(a[4]),'vol':float(a[5]),'amount':float(a[6])})
    if not rows: raise FileNotFoundError(f'Eastmoney {date} {code}')
    return pd.DataFrame(rows).sort_values('trade_time').reset_index(drop=True)
def minute_tencent(date,code):
    prefix='sh' if code.endswith('.SH') else 'sz' if code.endswith('.SZ') else 'bj'
    j=req_json(f'https://web.ifzq.gtimg.cn/appstock/app/day/query?code={prefix}{code.split(".")[0]}')
    arr=(((j.get('data') or {}).get(prefix+code.split('.')[0]) or {}).get('data') or [])
    day=next((x for x in arr if str(x.get('date'))==date),None)
    if not day: raise FileNotFoundError(f'Tencent {date} {code}')
    rows=[]
    for x in day.get('data',[]):
        a=x.split(); t=a[0]; price=float(a[1]); cv=float(a[2]); ca=float(a[3])
        rows.append({'trade_time':pd.Timestamp(f'{date[:4]}-{date[4:6]}-{date[6:]} {t[:2]}:{t[2:]}'),'close':price,'cumv':cv,'cuma':ca})
    d=pd.DataFrame(rows).sort_values('trade_time').reset_index(drop=True)
    d['open']=d['close'].shift(1).fillna(d['close']); d['high']=d[['open','close']].max(axis=1); d['low']=d[['open','close']].min(axis=1)
    d['vol']=d.cumv.diff().fillna(d.cumv); d['amount']=d.cuma.diff().fillna(d.cuma)
    return d[['trade_time','open','close','high','low','vol','amount']]
def minute(date,code):
    errors=[]
    for name,fn in [('github',minute_github),('eastmoney',minute_eastmoney),('tencent',minute_tencent)]:
        try:return fn(date,code),name
        except Exception as e:errors.append(f'{name}:{e}')
    raise RuntimeError(' | '.join(errors))

def indicators(d,pre,up):
    o=d.copy();o['cv']=o.vol.fillna(0).clip(lower=0).cumsum();o['ca']=o.amount.fillna(0).clip(lower=0).cumsum();o['vwap']=o.ca/o.cv.replace(0,math.nan)
    ratio=(o.amount/o.vol.replace(0,math.nan)).median();med=o.close.median()
    if pd.notna(ratio) and med>0:
        scale=ratio/med
        if scale>50:o.vwap/=100
        elif scale<.02:o.vwap*=100
    o['ret']=(o.close/pre-1)*100;o['touch']=o.high>=up-TICK/2;o['on']=o.close>=up-TICK/2;o['below']=o.low<up-TICK/2
    return o
def board_info(d):
    ix=d.index[d.touch].tolist()
    if not ix:return 0,None,None,None
    ft=ix[0];fo=None;seg=0;opened=False;reseal=None
    if not bool(d.iloc[ft].on):fo=ft;seg=1;opened=True
    for i in range(ft+1,len(d)):
        if not opened and bool(d.iloc[i-1].on) and bool(d.iloc[i].below):seg+=1;opened=True;fo=i if fo is None else fo
        if opened and bool(d.iloc[i].on):opened=False;reseal=i
    return seg,ft,fo,reseal
def entry_from_minutes(d,fo):
    if fo is None:return None,None,'no_open_board'
    streak=0
    for i in range(fo,len(d)):
        r=d.iloc[i]
        if r.trade_time.strftime('%H:%M')>ENTRY_LATEST:break
        ok=r.ret>=MIN_RET and r.close>=r.vwap and not bool(r.on);streak=streak+1 if ok else 0
        if streak>=STABLE:
            j=i+1
            while j<len(d) and bool(d.iloc[j].on):j+=1
            if j<len(d):return j,float(d.iloc[j].open),'strict_3m_next_open'
    for i in range(fo,len(d)-1):
        r=d.iloc[i]
        if r.trade_time.strftime('%H:%M')>ENTRY_LATEST:break
        if r.ret>=MIN_RET and r.close>=r.vwap and not bool(r.on):
            j=i+1
            while j<len(d) and bool(d.iloc[j].on):j+=1
            if j<len(d):return j,float(d.iloc[j].open),'fallback_1m_next_open'
    return None,None,'no_executable_entry'
def limit_ratio(code,name=''):
    if code.endswith('.BJ'):return .30
    if code.startswith(('300','301','688')):return .20
    if 'ST' in name.upper():return .05
    return .10
def early_mode(w):
    e=w.iloc[:max(2,EARLY_N)];op=float(w.iloc[0].open);drop=(float(e.low.min())/op-1)*100;rise=(float(e.high.max())/op-1)*100
    return 'direct_drop_then_rebound' if drop<=-DIRECT_DROP and (abs(drop)>=rise or float(e.iloc[-1].close)<op) else 'rally_or_high_level_oscillation'
def next_fill(w,i):
    j=min(i+1,len(w)-1);return j,w.iloc[j].trade_time,float(w.iloc[j].open)
def exit_rule(d,entry,pre,up):
    hm=d.trade_time.dt.strftime('%H:%M');w=d[(hm>='09:30')&(hm<=EXIT_DEADLINE)].copy().reset_index(drop=True)
    if w.empty:raise RuntimeError('empty T+1 window')
    mode=early_mode(w);op=float(w.iloc[0].open);stop=entry*(1-HARD_STOP/100)
    if op<=stop:si=fi=0;ft=w.iloc[0].trade_time;fp=op;reason='gap_below_hard_stop'
    else:
        peak=float(w.iloc[0].high);pi=0;trough=float(w.iloc[0].low);ti=0;started=False;rp=ri=None;fp=None
        for i,r in w.iterrows():
            t=r.trade_time.strftime('%H:%M');hi,lo,cl=map(float,[r.high,r.low,r.close])
            if hi>=up-TICK/2 and t<=FAST_LIMIT:si=fi=i;ft=r.trade_time;fp=up;reason='fast_limit_touch';break
            if cl<=stop:si=i;fi,ft,fp=next_fill(w,i);reason='hard_stop_after_open';break
            if mode=='rally_or_high_level_oscillation':
                if hi>peak:peak=hi;pi=i
                since=i-pi;pb=(cl/peak-1)*100
                if i+1>=MIN_OBS and (since>=STALL or pb<=-PULLBACK):si=i;fi,ft,fp=next_fill(w,i);reason='first_rally_stalled' if since>=STALL else 'first_rally_reversed';break
            else:
                if lo<trough:trough=lo;ti=i;started=False;rp=ri=None
                if not started and hi>=trough*(1+REBOUND/100):started=True;rp=hi;ri=i
                if started:
                    if hi>rp:rp=hi;ri=i
                    since=i-ri;pb=(cl/rp-1)*100
                    if since>=STALL or pb<=-PULLBACK:si=i;fi,ft,fp=next_fill(w,i);reason='first_rebound_stalled' if since>=STALL else 'first_rebound_failed';break
                elif i-ti>=REBOUND_WAIT:si=i;fi,ft,fp=next_fill(w,i);reason='no_effective_rebound';break
        if fp is None:si=fi=len(w)-1;ft=w.iloc[-1].trade_time;fp=float(w.iloc[-1].close);reason='absolute_time_stop'
    win=w.iloc[:fi+1];hi_i=int(win.high.idxmax());wh=float(w.iloc[hi_i].high);wl=float(win.low.min());net=((fp*(1-SELL_BPS/10000))/(entry*(1+BUY_BPS/10000))-1)*100
    return {'t1_open':op,'t1_open_return_pct':(op/pre-1)*100,'t1_mode':mode,'window_high_time':w.iloc[hi_i].trade_time.strftime('%H:%M'),'window_high_return_pct':(wh/pre-1)*100,'window_low_return_pct':(wl/pre-1)*100,'exit_signal_time':w.iloc[si].trade_time.strftime('%H:%M'),'exit_fill_time':pd.Timestamp(ft).strftime('%H:%M'),'exit_price':fp,'exit_reason':reason,'gross_return_pct':(fp/entry-1)*100,'net_return_pct':net,'mfe_pct':(wh/entry-1)*100,'mae_pct':(wl/entry-1)*100}
def main():
    samples=pd.read_csv(ROOT/'samples.csv',dtype=str);rows=[]
    for n,s in samples.iterrows():
        sd,td,name,code=s.signal_date,s.next_trade_date,s.stock_name,s.ts_code;print(f'[{n+1}/35] {sd} {name}',flush=True)
        r={'signal_date':sd,'next_trade_date':td,'stock_name':name,'ts_code':code,'status':'error','detail':''}
        try:
            sday=pick(daily(sd),code);spre=float(sday.pre_close);sclose=float(sday.close);sup=float(pick(limits(sd),code).up_limit);r.update(signal_pre_close=spre,signal_close=sclose,signal_up_limit=sup)
            try:tday=pick(daily(td),code);tpre=float(tday.pre_close);tup=float(pick(limits(td),code).up_limit)
            except Exception:tpre=sclose;tup=round(tpre*(1+limit_ratio(code,name))+1e-10,2)
            r.update(t1_pre_close=tpre,t1_up_limit=tup)
            try:
                sm,ssrc=minute(sd,code);si=indicators(sm,spre,sup);seg,ft,fo,rs=board_info(si);ei,ep,es=entry_from_minutes(si,fo);r.update(signal_minute_source=ssrc,signal_first_touch=si.iloc[ft].trade_time.strftime('%H:%M') if ft is not None else '',signal_open_segments_1m=seg,signal_first_open=si.iloc[fo].trade_time.strftime('%H:%M') if fo is not None else '',signal_reseal=si.iloc[rs].trade_time.strftime('%H:%M') if rs is not None else '')
                if ep is None:ep=sclose;es='conservative_signal_close_after_no_fill';et='15:00'
                else:et=si.iloc[ei].trade_time.strftime('%H:%M')
            except Exception as e:ep=sclose;es='conservative_signal_close_no_tday_1m';et='15:00';r['signal_data_note']=str(e)
            r.update(entry_source=es,entry_time=et,entry_price=ep);tm,tsrc=minute(td,code);ti=indicators(tm,tpre,tup);r['t1_minute_source']=tsrc;r.update(exit_rule(ti,float(ep),tpre,tup));r['status']='completed'
        except Exception as e:r['detail']=repr(e)
        rows.append(r)
    out=pd.DataFrame(rows);out.to_csv(OUT/'all_35_results.csv',index=False,encoding='utf-8-sig');c=out[out.status=='completed'].copy();c['net_return_pct']=pd.to_numeric(c.net_return_pct,errors='coerce')
    summary={'total_samples':len(out),'completed_samples':len(c),'not_completed_samples':int((out.status!='completed').sum()),'profit_samples':int((c.net_return_pct>0).sum()),'non_loss_samples':int((c.net_return_pct>=0).sum()),'loss_samples':int((c.net_return_pct<0).sum()),'win_rate_pct':float((c.net_return_pct>0).mean()*100) if len(c) else float('nan'),'non_loss_rate_pct':float((c.net_return_pct>=0).mean()*100) if len(c) else float('nan'),'average_net_return_pct':float(c.net_return_pct.mean()) if len(c) else float('nan'),'median_net_return_pct':float(c.net_return_pct.median()) if len(c) else float('nan'),'max_net_return_pct':float(c.net_return_pct.max()) if len(c) else float('nan'),'min_net_return_pct':float(c.net_return_pct.min()) if len(c) else float('nan')};pd.DataFrame([summary]).to_csv(OUT/'summary.csv',index=False,encoding='utf-8-sig')
    if len(c):
        bd=c.groupby('signal_date').net_return_pct.agg(samples='count',average='mean',median='median',worst='min',best='max').reset_index();wins=c.assign(win=c.net_return_pct>0).groupby('signal_date').win.sum().reset_index(name='wins');bd=bd.merge(wins,on='signal_date');bd['win_rate_pct']=bd.wins/bd.samples*100;bd.to_csv(OUT/'summary_by_date.csv',index=False,encoding='utf-8-sig')
    print(pd.DataFrame([summary]).to_string(index=False));print(out[['signal_date','stock_name','status','entry_source','t1_minute_source','net_return_pct','detail']].to_string(index=False))
if __name__=='__main__':main()
