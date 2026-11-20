"""合成コントロールの試作（測定だけ）。OECD 表6 の実質付加価値（LR）で、日本の産業×窓について
合成対照との差と、今の基準（比較国の中央値）との差を並べる。numpy なしの純 Python。"""
import csv,math,statistics,sys,json,collections
P=sys.argv[1]
d=collections.defaultdict(dict)
for x in csv.DictReader(open(P)):
    if x['価格']=='LR' and x['値']:
        d[(x['国'],x['産業'])][int(x['年'])]=float(x['値'])
def fit(Y0,y1,it=3000):
    # 単体（重み≥0、和1）上で二乗誤差を最小化：指数勾配法
    k=len(Y0); w=[1/k]*k; eta=0.5
    T=len(y1)
    for _ in range(it):
        pred=[sum(w[j]*Y0[j][t] for j in range(k)) for t in range(T)]
        g=[2*sum((pred[t]-y1[t])*Y0[j][t] for t in range(T)) for j in range(k)]
        m=max(abs(v) for v in g) or 1
        w=[w[j]*math.exp(-eta*g[j]/m) for j in range(k)]; s=sum(w); w=[v/s for v in w]
    return w
def series(c,i,years,base):
    s=d.get((c,i),{})
    if any(y not in s for y in years) or base not in s: return None
    return [math.log(s[y])-math.log(s[base]) for y in years]
inds=sorted({i for c,i in d if c=='JPN' and i!='_T'})+['_T']
out=[]
for T0 in (2000,2005,2010,2015):
    pre=list(range(T0-6,T0)); post=list(range(T0,min(T0+10,2024)))
    for i in inds:
        y=series('JPN',i,pre+post,T0-1)
        if not y: continue
        donors={c:series(c,i,pre+post,T0-1) for c,_ in d if c!='JPN' and _==i}
        donors={c:v for c,v in donors.items() if v}
        if len(donors)<4: continue
        cs=sorted(donors); Y=[donors[c] for c in cs]; npre=len(pre)
        def run(target,pool):
            w=fit([p[:npre] for p in pool],target[:npre])
            sc=[sum(w[j]*pool[j][t] for j in range(len(pool))) for t in range(len(target))]
            pre_rmse=math.sqrt(statistics.mean((target[t]-sc[t])**2 for t in range(npre)))
            post_rmse=math.sqrt(statistics.mean((target[t]-sc[t])**2 for t in range(npre,len(target))))
            gap=target[-1]-sc[-1]
            return w,gap,pre_rmse,post_rmse
        w,gap,pr,po=run(y,Y)
        med=y[-1]-statistics.median(v[-1] for v in Y)
        ratio=po/pr if pr>0 else float('inf')
        pl=[]
        for j,c in enumerate(cs):
            pool=[Y[k] for k in range(len(cs)) if k!=j]+[y]
            _,_,a,b=run(Y[j],pool); pl.append(b/a if a>0 else float('inf'))
        p=(1+sum(1 for r in pl if r>=ratio))/(1+len(pl))
        out.append({'窓の始め':T0,'窓の終わり':post[-1],'産業':i,'比較国の数':len(cs),'合成対照との差':round(gap,4),'中央値との差':round(med,4),
                    '符号が同じ':(gap>0)==(med>0),'処置前のRMSE':round(pr,4),'置換のp値':round(p,3),
                    '重み上位':';'.join(f'{cs[j]}:{w[j]:.2f}' for j in sorted(range(len(cs)),key=lambda j:-w[j])[:3])})
w=csv.DictWriter(open(sys.argv[2],'w',newline=''),fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
n=len(out); same=sum(o['符号が同じ'] for o in out)
sig=sum(1 for o in out if o['置換のp値']<=0.1)
goodfit=sum(1 for o in out if o['処置前のRMSE']<=0.02)
print(json.dumps({'産業×窓':n,'符号が中央値と同じ':same,'置換のp値≤0.1':sig,'処置前RMSE≤0.02':goodfit,
 '差の中央値（合成）':round(statistics.median(o['合成対照との差'] for o in out),4),'差の中央値（中央値基準）':round(statistics.median(o['中央値との差'] for o in out),4),
 '差の絶対値の中央値の比（合成/中央値）':round(statistics.median(abs(o['合成対照との差']) for o in out)/statistics.median(abs(o['中央値との差']) for o in out),3)},ensure_ascii=False))
