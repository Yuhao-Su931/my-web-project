#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import requests

out=Path(__file__).resolve().parent/'results'
out.mkdir(exist_ok=True)
urls=[
 'https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol=sh600992&scale=5&ma=no&datalen=1023',
 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh600992&scale=5&ma=no&datalen=1023'
]
parts=[]
for url in urls:
    try:
        r=requests.get(url,timeout=10,headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn/'})
        parts.append('URL='+url+'\nstatus='+str(r.status_code)+' bytes='+str(len(r.content))+'\n'+r.text[:30000])
    except Exception as e:
        parts.append('URL='+url+'\nerror='+repr(e))
result='\n\n==========\n\n'.join(parts)
(out/'tick_probe.txt').write_text(result,encoding='utf-8')
print(result[:5000])
