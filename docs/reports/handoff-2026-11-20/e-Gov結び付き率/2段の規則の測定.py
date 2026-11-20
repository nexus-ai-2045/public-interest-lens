import sys,os,csv,re,json,time,collections,urllib.request
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from bridgelib import *
S=os.path.dirname(os.path.abspath(__file__))+'/'
def rd(n): return list(csv.DictReader(open(D+n)))
v=rd('data_derived_evaluation-ledger-v1_sample-v2_verdicts.csv')
cand=rd('data_derived_evaluation-ledger-v1_sample-v2_correction-candidates.csv')
corr=rd('data_derived_primary-source-corrections-v1_corrections.csv')
s1=rd('data_derived_evaluation-ledger-v1_sample-verdicts.csv'); s1ids={x['id'] for x in s1}
tri={x['id']:x for x in rd('triage.csv')}
econ={x['id']:x for x in csv.DictReader(open(S+'econ_labels.csv'))}
def normE(s):
    if not s: return ''
    if s.startswith('経済に効く'): return '経済'
    if s.startswith('制度'): return '制度'
    if s.startswith('判定不能'): return '判定不能'
    return s
# gold[item][id]=(正解, 今の値, 出所)
gold={'類型':{},'経済':{}}
for x in v:
    i=x['id']
    for it,site,key in (('類型',x['サイト_類型'],'類型'),('経済',normE(x['サイト_経済に効くか']),'経済に効くか')):
        c=[y for y in cand if y['id']==i and y['項目']==key]
        if c: gold[it][i]=(normE(c[0]['直した値']) if it=='経済' else c[0]['直した値'],site,'直した')
        elif site and (x['判定']=='合格' or key not in x['食い違い']): gold[it][i]=(site,site,'合格')
s1v={x['id']:x for x in s1}
for i in s1ids:
    for it,key in (('類型','類型'),('経済','経済に効くか')):
        c=[y for y in corr if y['id']==i and y['項目']==key]
        if c:
            before=c[0]['直す前の値']; gold[it][i]=(normE(c[0]['直した値']) if it=='経済' else c[0]['直した値'], normE(before) if it=='経済' else before,'直した'); continue
        x=s1v[i]
        if x['判定']=='合格' or key not in x['食い違い']:
            cur=tri.get(i,{}).get('種類','') if it=='類型' else normE(econ.get(i,{}).get('区分',''))
            if cur: gold[it][i]=(cur,cur,'合格')
# 本文
cache_p=S+'honbun.json'; hc=json.load(open(cache_p))
TC={'閣法':'09','衆法':'05','参法':'06'}
def honbun(i):
    if i in hc: return hc[i]
    k,kai,no=i.split('-')
    u=f'https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/honbun/houan/g{int(kai):03d}{TC[k]}{int(no):03d}.htm'
    try: t=urllib.request.urlopen(u,timeout=60).read().decode('shift_jis','ignore'); t=re.sub('<[^>]+>','',t)
    except Exception: t=''
    hc[i]=t; json.dump(hc,open(cache_p,'w'),ensure_ascii=False); time.sleep(0.3); return t
def main_part(t):
    t=re.sub(r'\s+',' ',t)
    m=re.search(r'第[一二三四五六七八九十百〇]+回 [閣衆参]第[一二三四五六七八九十百〇]+号',t)
    if m: t=t[m.start():]
    t=t.split('理 由')[0].split('理　由')[0]
    return t
def suppl_split(t):
    p=re.split(r' 附 則 | 附　則 ',t,maxsplit=1)
    return p[0],(p[1] if len(p)>1 else '')
NUM=r'[〇一二三四五六七八九十百千万億兆０-９0-9]+'
DATE=re.compile(r'^(平成|令和|昭和)?('+NUM+r'年)?('+NUM+r'月)?('+NUM+r'日)?(度)?$|^'+NUM+'(円|分の'+NUM+'|人|年|月|日|パーセント)?$')
REP=re.compile(r'「([^「」]{0,80})」を「([^「」]{0,80})」に')
def is_new(i):
    r=res.get(i); return r and r['新規か改正か']!='改正'
ORG={'行政組織','国家公務員','国会','行政手続','地方自治'}
def T(i):
    t=honbun(i)
    if not t: return 'NOTEXT'
    m=main_part(t); body,sup=suppl_split(m)
    if is_new(i) and 'の一部を次のように改正する' not in body[:400]: return '新規'
    b=bases(i) or []
    cats={c for _,c in b}
    if cats and cats<=ORG: return '組織手続'
    reps=REP.findall(body)
    ops=len(re.findall('改める|加える|削る|削除する',body))
    numeric=[1 for a,c in reps if DATE.match(a.replace(' ','')) and DATE.match(c.replace(' ',''))]
    adds=len(re.findall('加える',body))
    if ops==0: return '定型改正'          # 本則に改正なし（附則だけ）
    if adds==0 and len(numeric)==len(reps)==ops: return '定型改正'   # 数・日付の置き換えだけ
    return '実質改正'
BIND=re.compile('しなければならない|してはならない|許可|認可|免許|登録|届出|届け出|指定を受け|罰金|過料|課徴金|補助|交付金|助成|負担金|手数料|税|保険料|給付|融資|出資|債務保証|料金')
def E(i,typ):
    t=honbun(i)
    if not t: return 'NOTEXT'
    m=main_part(t); body,sup=suppl_split(m)
    if typ=='定型改正' or typ=='組織手続': return '制度'
    if typ=='新規': text=body
    else:
        # 加えた文と、置き換えの新しい側だけを見る
        new=' '.join(c for a,c in REP.findall(body))
        added=' '.join(re.findall(r'加える。(.*?)(?=(?: 第'+NUM+'条|$))',body))
        text=new+' '+added
        old=' '.join(a for a,c in REP.findall(body))
        if len(BIND.findall(text))<=len(BIND.findall(old)) and not added.strip(): return '制度'
    return '経済' if BIND.search(text) else '制度'
def score(item,fn,ids):
    c=collections.Counter()
    for i in ids:
        g=gold[item][i][0]; p=fn(i)
        if p=='NOTEXT': c['本文なし']+=1
        elif p==g: c['一致']+=1
        else: c[f'不一致']+=1
    return dict(c)
for item in ('類型','経済'):
    ids=list(gold[item]); fix=[i for i in ids if gold[item][i][2]=='直した']
    print('==',item,'正解のある本数',len(ids),'うち直した',len(fix),collections.Counter(g for g,_,_ in gold[item].values()))
    cur=lambda i,it=item:gold[it][i][1]
    rule=(lambda i:T(i)) if item=='類型' else (lambda i:E(i,T(i)))
    for nm,fn in (('今の付け方',cur),('規則',rule)):
        print(' ',nm,'全体',score(item,fn,ids),'直した',score(item,fn,fix))
    # 混同
    cm=collections.Counter((gold[item][i][0],rule(i)) for i in ids); print('  規則の混同（正解,規則）',dict(cm))
    if item=='経済':
        # 判定不能の正解を除いた2値
        ids2=[i for i in ids if gold[item][i][0] in ('経済','制度')]
        print('  正解が経済/制度の本数',len(ids2),'今',score(item,cur,ids2),'規則',score(item,rule,ids2))
print('== 2源の照合（今の値と規則）')
for item in ('類型','経済'):
    c=collections.Counter()
    for i,(g,cur,src) in gold[item].items():
        p=T(i) if item=='類型' else E(i,T(i))
        if p==cur: c['一致:'+('正' if g==p else '誤')]+=1
        else: c['食い違い:'+('今が正' if g==cur else ('規則が正' if g==p else '両方誤'))]+=1
    print(item,dict(c))
print('本文を取得した本数',sum(1 for k,v in hc.items() if v))
