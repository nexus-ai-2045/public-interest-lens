import sys,os,csv,re,json,time,collections,urllib.request
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import bridgelib
bridgelib.load()
from bridgelib import *
S = D
# ---- 正解（bridge.py と同じ作り方）
macro=list(csv.DictReader(open(D+'macro.csv'))); mf={x['id']:x for x in macro}
gold={}
v=list(csv.DictReader(open(D+'data_derived_evaluation-ledger-v1_sample-v2_verdicts.csv')))
cc={x['id']:x['直した値'] for x in csv.DictReader(open(D+'data_derived_evaluation-ledger-v1_sample-v2_correction-candidates.csv')) if x['項目']=='分野'}
for x in v:
    if x['id'] in cc: gold[x['id']]=cc[x['id']]
    elif x['判定']=='合格' or '分野' not in x['食い違い']: gold[x['id']]=x['サイト_分野']
for x in csv.DictReader(open(D+'data_derived_evaluation-ledger-v1_sample-verdicts.csv')):
    if x['id'] in mf and (x['判定']=='合格' or '分野' not in x['食い違い']): gold.setdefault(x['id'],mf[x['id']]['分野'])
gi={}
for i,f in gold.items():
    if f=='コロナ対応' or not f: continue
    gi[i]=FIELD2IND.get(f)
# ---- 許認可の局→産業（取り決め v0）
KY={('金融庁',None):'K',('経済産業省','資源エネルギー庁'):'D',('経済産業省','製造産業局'):'C',('環境省','原子力規制委員会'):'D',
 ('国土交通省','海事局'):'H',('国土交通省','自動車局'):'H',('国土交通省','航空局'):'H',('国土交通省','鉄道局'):'H',('国土交通省','港湾局'):'H',
 ('国土交通省','観光庁'):'I',('国土交通省','住宅局'):'L',('国土交通省','都市局'):'L',('国土交通省','土地・建設産業局'):'F',('国土交通省','道路局'):'F',('国土交通省','水管理・国土保全局'):'F',
 ('厚生労働省','医薬・生活衛生局'):'Q',('厚生労働省','医政局'):'Q',('厚生労働省','健康局'):'Q',('厚生労働省','老健局'):'Q',('厚生労働省','社会・援護局'):'Q',('厚生労働省','子ども家庭局'):'Q',('厚生労働省','保険局'):'Q',
 ('農林水産省',None):'A',('総務省','総合通信基盤局'):'J',('総務省','情報流通行政局'):'J',('総務省','情報通信国際戦略局'):'J',
 ('文部科学省','高等教育局'):'P',('文部科学省','初等中等教育局'):'P',('文部科学省','生涯学習政策局'):'P',('文部科学省','文化庁'):'R+S',('文部科学省','スポーツ庁'):'R+S'}
def kyind(fu,kyoku):
    k1=(kyoku or '').split('\n')[0].strip()
    return KY.get((fu,k1)) or KY.get((fu,None))
kl=collections.defaultdict(list)
for r in csv.reader(open(S+'kyo/k.csv')):
    for nm in re.split(r'[\n、]',r[6] or ''):
        nm=nm.strip()
        if nm: kl[nm].append(kyind(r[1],r[2]))
def kind_of(names):
    votes=[k for n in names for k in kl.get(n,[])]
    if not votes: return 'NOK'   # 許認可の表に無い
    c=collections.Counter(votes); k,n=c.most_common(1)[0]
    return k if (k and n*2>len(votes)) else None
def K(i,only=None):
    b=bases(i)
    if not b: return 'NA'
    names=[t for t,c in b] if only is None else [only]
    return kind_of(names)
# ---- R4：改正法の本文から改正元ごとの改正箇所を数える
cache_p=S+'honbun.json'; hc=json.load(open(cache_p)) if os.path.exists(cache_p) else {}
TC={'閣法':'09','衆法':'05','参法':'06'}
def honbun(i):
    if i in hc: return hc[i]
    k,kai,no=i.split('-')
    u=f'https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/honbun/houan/g{int(kai):03d}{TC[k]}{int(no):03d}.htm'
    try:
        t=urllib.request.urlopen(u,timeout=60).read().decode('shift_jis','ignore'); t=re.sub('<[^>]+>','',t)
    except Exception as e: t=''
    hc[i]=t; json.dump(hc,open(cache_p,'w'),ensure_ascii=False); time.sleep(0.3); return t
OPS=re.compile('改める|加える|削る|削除する')
def R4(i):
    b=bases(i)
    if not b: return 'NA',None
    if len(b)==1: return ind(b[0][1],b[0][0]),b[0][0]
    t=honbun(i)
    if not t: return 'NOTEXT',None
    # 「○○（…号）の一部を次のように改正する」で区切る
    parts=re.split(r'\n[^\n]*?([^\s「」（）]+?)（[^）]*?号[^）]*?）の一部を次のように改正する。',t)
    cnt=collections.Counter()
    for j in range(1,len(parts)-1,2):
        nm=parts[j]; body=parts[j+1]
        cnt[nm]+=len(OPS.findall(body))
    best=None;bn=-1
    for tl,c in b:
        n=max([v for k,v in cnt.items() if tl and (k==tl or k.endswith(tl))] or [-1])
        if n>bn: best,bn=(tl,c),n
    if bn<=0: return 'NOSPLIT',None
    return ind(best[1],best[0]),best[0]
def score(fn,ids):
    c=collections.Counter()
    for i in ids:
        k=gi[i]; p=fn(i)
        if p in ('NA','NOK','NOTEXT','NOSPLIT','NOFIRST'): c['対象外:'+p]+=1
        elif (k and p==k) or (not k and p is None): c['一致']+=1
        elif k and p is None: c['取りこぼし']+=1
        elif not k and p: c['誤って産業']+=1
        else: c['別の産業']+=1
    return dict(c)
ALL=list(gi); FIX=[i for i in cc if i in gi]; MUL=[i for i in gi if (bases(i) or []) and len(bases(i))>1]
cur=lambda i:(None if mf.get(i,{}).get('産業') in (None,'','_T') else mf[i]['産業'])
r4=lambda i:R4(i)[0]
def r4k(i):
    p,nm=R4(i)
    if p in ('NA','NOTEXT','NOSPLIT'): return p
    return kind_of([nm])
print('本数 全体',len(ALL),'直した',len(FIX),'改正元2本以上',len(MUL))
for name,fn in [('今の付け方',cur),('R4 条の数×法令分類',r4),('K 許認可の局（全改正元）',K),('R4×K（最多の改正元の許認可の局）',r4k)]:
    print('==',name); 
    for lab,ids in [('169本',ALL),('直した14本',FIX),('改正元2本以上66本',MUL)]: print(' ',lab,score(fn,ids))
print('直した14本の明細')
for i in FIX: print(i,gi[i],'今',cur(i),'R4',r4(i),'K',K(i),'R4K',r4k(i))
