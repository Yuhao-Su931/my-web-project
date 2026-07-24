#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import json
import requests

out=Path(__file__).resolve().parent/'results'
out.mkdir(exist_ok=True)
results=[]
for n in [1023,3000,5000,10000]:
    url=f'https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol=sh600992&scale=1&ma=no&datalen={n}'
    try:
        r=requests.get(url,timeout=15,headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn/'})
        data=r.json() if r.text.strip().startswith('[') else []
        days=[str(x.get('day','')) for x in data if isinstance(x,dict)]
        results.append({'datalen':n,'status':r.status_code,'bytes':len(r.content),'rows':len(data),'first':days[0] if days else '', 'last':days[-1] if days else '', 'has_20260717':any(d.startswith('2026-07-17') for d in days)})
    except Exception as e:
        results.append({'datalen':n,'error':repr(e)})
text=json.dumps(results,ensure_ascii=False,indent=2)
(out/'tick_probe.txt').write_text(text,encoding='utf-8')
print(text)
