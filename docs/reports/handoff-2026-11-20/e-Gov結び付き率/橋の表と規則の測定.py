import csv,json,re,collections,sys
D=sys.argv[1]
BR={'農業':'A','林業':'A','水産業':'A','鉱業':'B','工業':'C','道路':'F','河川':'F','国土開発':'F','商業':'G',
 '陸運':'H','海運':'H','航空':'H','貨物運送':'H','郵務':'H','観光':'I','電気通信':'J','金融・保険':'K',
 '建築・住宅':'L','土地':'L','都市計画':'L','教育':'P','厚生':'Q','社会福祉':'Q','文化':'R+S'}
ENERGY=re.compile('エネルギー|電気|ガス|石油|原子力|電源|熱供給|鉱物資源')
FIELD2IND={'金融':'K','農林水産':'A','医療・福祉':'Q','交通・移動':'H','建設':'F','専門サービス・研究開発':'M+N','通信・ネット':'J','教育':'P','エネルギー':'D','文化・娯楽・生活サービス':'R+S','製造業':'C','住宅・不動産':'L','商業':'G','宿泊・観光':'I','半導体・電子':'C','鉱業・採石':'B'}
def ind(cat,title):
    i=BR.get(cat)
    if i=='C' and ENERGY.search(title or ''): return 'D'
    return i  # None = 未定
# law_id -> (title,category)
meta={}
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
RULES=['R1','R2','R3']
# --- 群の本数
macro=list(csv.DictReader(open(D+'macro.csv')))
print('== 群の本数（macro.csv 結果=額 の行）')
amt=[x for x in macro if x['結果']=='額' and x['産業']!='COVID']
cur={x['id'] for x in amt if x['産業']!='_T'}
print('今の群',len(cur),' 額の行',len(amt))
out={}
for r in RULES:
    new={};c=collections.Counter()
    for x in amt:
        k=rule(x['id'],r)
        if k in ('NA','NOFIRST'): c[k]+=1; continue
        if k: new[x['id']]=k
        else: c['未定']+=1
    both=cur&set(new); same=sum(1 for i in both if new[i]==next(y['産業'] for y in amt if y['id']==i))
    print(r,'新しい群',len(new),'両方',len(both),'産業が同じ',same,'今だけ',len(cur-set(new)),'新だけ',len(set(new)-cur),dict(c))
    out[r]=new
# --- 標本との一致
gold={}
v=list(csv.DictReader(open(D+'data_derived_evaluation-ledger-v1_sample-v2_verdicts.csv')))
cc={x['id']:x['直した値'] for x in csv.DictReader(open(D+'data_derived_evaluation-ledger-v1_sample-v2_correction-candidates.csv')) if x['項目']=='分野'}
for x in v:
    if x['id'] in cc: gold[x['id']]=('標本2',cc[x['id']])
    elif x['判定']=='合格' or '分野' not in x['食い違い']: gold[x['id']]=('標本2',x['サイト_分野'])
mf={x['id']:x['分野'] for x in macro}
for x in csv.DictReader(open(D+'data_derived_evaluation-ledger-v1_sample-verdicts.csv')):
    if x['id'] in mf and (x['判定']=='合格' or '分野' not in x['食い違い']): gold.setdefault(x['id'],('標本1',mf[x['id']]))
def g2(f):
    if f=='コロナ対応' or not f: return 'SKIP'
    return FIELD2IND.get(f)  # None = 産業を特定しない
print('== 標本との一致（正解＝既存の裁定）')
gi={i:g2(f) for i,(s,f) in gold.items()}; gi={i:k for i,k in gi.items() if k!='SKIP'}
print('正解のある本数',len(gi),'うち産業あり',sum(1 for k in gi.values() if k),'うち産業を特定しない',sum(1 for k in gi.values() if not k))
multi={i for i in gi if (bases(i) or [])and len(bases(i))>1}
print('うち改正元2本以上',len(multi))
for r in RULES+['今']:
    c=collections.Counter()
    for i,k in gi.items():
        p=(next((y['産業'] for y in macro if y['id']==i),None) if r=='今' else rule(i,r))
        if r=='今' and p=='_T': p=None
        if p in ('NA','NOFIRST'): c['結び付かない']+=1; continue
        if k and p==k: c['一致(産業)']+=1
        elif not k and not p: c['一致(特定しない)']+=1
        elif k and not p: c['取りこぼし(群に入れない)']+=1
        elif not k and p: c['誤って産業']+=1
        else: c['別の産業']+=1
    cm=collections.Counter()
    for i in multi:
        k=gi[i]; p=(next((y['産業'] for y in macro if y['id']==i),None) if r=='今' else rule(i,r))
        if r=='今' and p=='_T': p=None
        cm['一致' if (p==k or (not k and not p)) else ('結び付かない' if p in ('NA','NOFIRST') else '不一致')]+=1
    print(r,dict(c),' 複数改正元のみ:',dict(cm))
print('== 直された14本（今の値は誤り）でのルール別の当たり')
for r in RULES:
    hit=0;rows=[]
    for i in cc:
        if i not in gi: continue
        k=gi[i]; p=rule(i,r)
        ok=(p==k) or (not k and p is None)
        hit+=ok; rows.append((i,k,p))
    print(r,hit,'/',len(rows),rows if r=='R1' else '')
print('== 2源の照合（今の産業 と 橋R2 が一致したら採る）')
c=collections.Counter()
for i,k in gi.items():
    cur_i=next((y['産業'] for y in macro if y['id']==i),None)
    if cur_i in (None,'_T'): cur_i=None
    p=rule(i,'R2')
    if p in ('NA','NOFIRST'): p='NA'
    if cur_i and cur_i==p: c['一致して採用:'+('正' if k==p else '誤')]+=1
    elif cur_i: c['食い違い・今の値:'+('正' if k==cur_i else '誤')]+=1
    else: c['今は産業なし:'+('正' if not k else '誤')]+=1
print(dict(c))
amtid={x['id']:x['産業'] for x in amt if x['産業']!='_T'}
n=sum(1 for i,k in amtid.items() if out['R2'].get(i)==k); print('全体：今の群1473本のうち橋R2と産業が一致',n)
