import json, requests
from pathlib import Path
OUT=Path('results'); OUT.mkdir(exist_ok=True)
def secid(code):
    sym, ex = code.split('.')
    return ('1.' if ex=='SH' else '0.') + sym
url='https://push2his.eastmoney.com/api/qt/stock/trends2/get'
p={'secid':secid('600992.SH'),'ndays':10,'iscr':0,'iscca':0,'fields1':'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13','fields2':'f51,f52,f53,f54,f55,f56,f57,f58'}
r=requests.get(url,params=p,timeout=30,headers={'User-Agent':'Mozilla/5.0','Referer':'https://quote.eastmoney.com/'})
obj={'status':r.status_code,'url':r.url,'text_head':r.text[:200]}
try:
    j=r.json(); trends=((j.get('data') or {}).get('trends') or [])
    obj.update({'rows':len(trends),'dates':sorted(set(x.split(' ')[0] for x in trends)),'sample':trends[:2]})
except Exception as e: obj['error']=repr(e)
(OUT/'probe_result.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(obj,ensure_ascii=False))
