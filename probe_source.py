from pathlib import Path
import json
import requests

OUT = Path('results')
OUT.mkdir(exist_ok=True)
base = 'https://push2his.eastmoney.com/api/qt/stock/trends2/get?secid=1.600452&iscr=0&iscca=0&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13&fields2=f51,f52,f53,f54,f55,f56,f57,f58'
urls = {
  'eastmoney_trends5': base + '&ndays=5',
  'eastmoney_trends6': base + '&ndays=6',
  'eastmoney_trends10': base + '&ndays=10',
  'eastmoney_trends20': base + '&ndays=20',
  'eastmoney_kline_1m_lmt5000': 'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.600452&klt=1&fqt=0&lmt=5000&end=20500101&fields1=f1,f2,f3,f4,f5,f6,f7,f8&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'
}
res = {}
for name, url in urls.items():
    try:
        r = requests.get(url, timeout=30, headers={'User-Agent':'Mozilla/5.0','Referer':'https://quote.eastmoney.com/'})
        item = {'status': r.status_code, 'length': len(r.text)}
        try:
            j = r.json()
            item['json'] = j
            data = j.get('data') if isinstance(j, dict) else None
            seq = data.get('trends') if isinstance(data, dict) and 'trends' in data else data.get('klines') if isinstance(data, dict) else None
            if isinstance(seq, list):
                item['rows'] = len(seq)
                item['first'] = seq[0] if seq else None
                item['last'] = seq[-1] if seq else None
                item['dates'] = sorted({str(x)[:10] for x in seq})
        except Exception as e:
            item['json_error'] = repr(e)
            item['prefix'] = r.text[:1000]
        res[name] = item
    except Exception as e:
        res[name] = {'error': repr(e)}
(OUT/'probe.json').write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k:{x:v.get(x) for x in ('status','length','rows','first','last','dates','error')} for k,v in res.items()}, ensure_ascii=False, indent=2))
