import csv,json,re,sys,time,os,urllib.request,urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bridgelib
D = bridgelib.require_egov_workdir().rstrip(os.sep)
rows=list(csv.DictReader(open(os.path.join(D,'enacted.csv'))))
cache_p=os.path.join(D,'cache.jsonl'); cache={}
if os.path.exists(cache_p):
    for l in open(cache_p):
        o=json.loads(l)
        if '_err' not in o['v']: cache[o['k']]=o['v']  # 一時的な失敗は次の実行で取り直す
cf=open(cache_p,'a')
def get(url):
    if url in cache: return cache[url]
    for i in range(4):
        try:
            with urllib.request.urlopen(url,timeout=60) as r: v=json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            if e.code==404: v={'_404':True}; break
            time.sleep(2**i); v={'_err':str(e)}
        except Exception as e:
            time.sleep(2**i); v={'_err':str(e)}
    if '_err' in v: return v
    cache[url]=v; cf.write(json.dumps({'k':url,'v':v},ensure_ascii=False)+'\n'); cf.flush(); time.sleep(0.15)
    return v
ERA={'平成':'4','令和':'5'}
out=open(os.path.join(D,'result.csv'),'w',newline=''); w=csv.writer(out)
w.writerow(['id','題名','新規か改正か','law_id','e-Govに本体','改正元の数','改正元_law_id','改正元_category','本体category','err'])
B='https://laws.e-gov.go.jp/api/2/laws?'
for x in rows:
    iid=f"{x['種別']}-{x['提出回次']}-{x['番号']}"
    m=re.match(r'(平成|令和)\s*(元|\d+)年',x['公布日'].strip()); n=x['法律番号'].strip()
    if not m or not n.isdigit():
        w.writerow([iid,x['題名'],x['新規か改正か'],'','','','','','','no_num']); continue
    y=1 if m.group(2)=='元' else int(m.group(2))
    pre="0" if x["種別"]=="閣法" else "1"; lid=f"{ERA[m.group(1)]}{y:02d}AC{pre}{int(n):09d}"
    a=get(B+urllib.parse.urlencode({'law_id':lid,'omit_current_revision_info':'true','limit':5}))
    b=get(B+urllib.parse.urlencode({'amendment_law_id':lid,'omit_current_revision_info':'true','limit':500}))
    err=';'.join(k for k,v in (('a',a),('b',b)) if '_err' in v)
    self_hit=[l for l in a.get('laws',[]) if l['law_info']['law_id']==lid]
    base=[l for l in b.get('laws',[]) if l['law_info']['law_id']!=lid]
    w.writerow([iid,x['題名'],x['新規か改正か'],lid,int(bool(self_hit)),len(base),
      '|'.join(l['law_info']['law_id'] for l in base),
      '|'.join((l.get('revision_info') or {}).get('category') or '' for l in base),
      (self_hit[0].get('revision_info') or {}).get('category','') if self_hit else '',err])
    out.flush()
