#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import requests

out=Path(__file__).resolve().parent/'results'
out.mkdir(exist_ok=True)
url='https://stock.gtimg.cn/data/index.php?appn=detail&action=download&c=sh600992&d=20260717'
try:
    r=requests.get(url,timeout=10,headers={'User-Agent':'Mozilla/5.0'})
    text=r.content.decode('gb18030',errors='replace')
    result='status='+str(r.status_code)+'\nbytes='+str(len(r.content))+'\n'+text[:20000]
except Exception as e:
    result='error='+repr(e)
(out/'tick_probe.txt').write_text(result,encoding='utf-8')
print(result[:4000])
