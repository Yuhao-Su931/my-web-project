from pathlib import Path
import json
import requests

OUT = Path('results')
OUT.mkdir(exist_ok=True)
urls = {
  'tencent_day_date': 'https://web.ifzq.gtimg.cn/appstock/app/day/query?code=sh600452&date=20260721',
  'tencent_day': 'https://web.ifzq.gtimg.cn/appstock/app/day/query?code=sh600452',
  'eastmoney_kline_1m': 'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.600452&klt=1&fqt=0&beg=20260720&end=20260721&fields1=f1,f2,f3,f4,f5,f6,f7,f8&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
  'eastmoney_trends5': 'https://push2his.eastmoney.com/api/qt/stock/trends2/get?secid=1.600452&ndays=5&iscr=0&iscca=0&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13&fields2=f51,f52,f53,f54,f55,f56,f57,f58'
}
res = {}
for name, url in urls.items():
    try:
        r = requests.get(url, timeout=30, headers={'User-Agent':'Mozilla/5.0','Referer':'https://quote.eastmoney.com/'})
        item = {'status': r.status_code, 'length': len(r.text), 'prefix': r.text[:1500]}
        try:
            item['json'] = r.json()
        except Exception as e:
            item['json_error'] = repr(e)
        res[name] = item
    except Exception as e:
        res[name] = {'error': repr(e)}
(OUT/'probe.json').write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k:{x:v.get(x) for x in ('status','length','error')} for k,v in res.items()}, ensure_ascii=False, indent=2))
