import json, requests

def secid(code):
    sym, ex = code.split('.')
    return ('1.' if ex=='SH' else '0.') + sym

def probe(code):
    url='https://push2his.eastmoney.com/api/qt/stock/trends2/get'
    p={'secid':secid(code),'ndays':10,'iscr':0,'fields1':'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13','fields2':'f51,f52,f53,f54,f55,f56,f57,f58'}
    r=requests.get(url,params=p,timeout=30,headers={'User-Agent':'Mozilla/5.0','Referer':'https://quote.eastmoney.com/'})
    print(code, r.status_code, r.url)
    j=r.json(); trends=((j.get('data') or {}).get('trends') or [])
    dates=sorted(set(x.split(' ')[0] for x in trends))
    print('rows',len(trends),'dates',dates)
    open('probe_result.json','w',encoding='utf-8').write(json.dumps({'code':code,'rows':len(trends),'dates':dates,'sample':trends[:2]},ensure_ascii=False,indent=2))
probe('600992.SH')
