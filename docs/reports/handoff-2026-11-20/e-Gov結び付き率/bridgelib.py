import csv, json, re, collections, sys, os
# 同梱していない入力（cache.jsonl など）は作業フォルダから読む。フォルダが無いときは空の結果を出さず止める。

def require_egov_workdir():
    raw = os.environ.get("EGOV_WORKDIR", "").strip()
    if not raw:
        sys.stderr.write(
            "EGOV_WORKDIR が無い。この台本はリポジトリに同梱していない入力"
            "（cache.jsonl、result.csv、fallback.csv、econ_labels.csv など）を"
            "作業フォルダから読む。環境変数が無いので、空の結果は出さずここで止める。\n"
        )
        raise SystemExit(2)
    return raw if raw.endswith(os.sep) else raw + os.sep

BR={'農業':'A','林業':'A','水産業':'A','鉱業':'B','工業':'C','道路':'F','河川':'F','国土開発':'F','商業':'G',
 '陸運':'H','海運':'H','航空':'H','貨物運送':'H','郵務':'H','観光':'I','電気通信':'J','金融・保険':'K',
 '建築・住宅':'L','土地':'L','都市計画':'L','教育':'P','厚生':'Q','社会福祉':'Q','文化':'R+S'}
ENERGY=re.compile('エネルギー|電気|ガス|石油|原子力|電源|熱供給|鉱物資源')
FIELD2IND={'金融':'K','農林水産':'A','医療・福祉':'Q','交通・移動':'H','建設':'F','専門サービス・研究開発':'M+N','通信・ネット':'J','教育':'P','エネルギー':'D','文化・娯楽・生活サービス':'R+S','製造業':'C','住宅・不動産':'L','商業':'G','宿泊・観光':'I','半導体・電子':'C','鉱業・採石':'B'}
def ind(cat,title):
    i=BR.get(cat)
    if i=='C' and ENERGY.search(title or ''): return 'D'
    return i  # None = 未定
D = ""
meta = {}
res = {}
fb = {}
def load():
    global D, meta, res, fb
    D = require_egov_workdir()
    meta = {}
    for l in open(D+'cache.jsonl'):
        for L in json.loads(l)['v'].get('laws',[]):
            ri=L.get('revision_info') or {}; meta[L['law_info']['law_id']]=(ri.get('law_title'),ri.get('category'))
    res={x['id']:x for x in csv.DictReader(open(D+'result.csv'))}
    fb={x['id']:x for x in csv.DictReader(open(D+'fallback.csv'))}
def firstname(t):
    t=re.sub(r'案$','',t); m=re.match(r'^(.+?)(等)?の一部を改正する法律$',t)
    return re.split(r'及び|並びに|、',m.group(1))[0] if m else None
def bases(i):
    x=res.get(i)
    if not x: return None
    if x['改正元_law_id']:
        return [meta.get(b,(None,None)) for b in x['改正元_law_id'].split('|')]
    if x['e-Govに本体']=='1': return [meta.get(x['law_id'],(None,None))]
    f=fb.get(i)
    if f and f['一致数']=='1': return [(f['名前'],f['category'])]
    return None
def rule(i,r):
    b=bases(i)
    if not b: return 'NA'   # e-Gov と結び付かない
    inds=[ind(c,t) for t,c in b]
    if len(b)==1: return inds[0]
    if r=='R1':
        fn=firstname(res[i]['題名'])
        for (t,c),k in zip(b,inds):
            if fn and t==fn: return k
        return 'NOFIRST'
    if r=='R2':
        k,n=collections.Counter(inds).most_common(1)[0]
        return k if n*2>len(inds) else None
    if r=='R3':
        return inds[0] if len(set(inds))==1 else None

if __name__ == "__main__":
    load()
