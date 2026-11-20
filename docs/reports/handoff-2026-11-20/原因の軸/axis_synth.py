"""原因の軸の額：合成対照版（2026-10-24）。axis_loss.py（比較国の中央値）の感度・置き換え候補。
- 結果 y = ln(産業の実質の伸び) − ln(全体の実質の伸び)（産業固有）。経済全体は ln(就業者1人当たり実質)。
- 合成の日本 = 比較国の重みつき平均（重み≥0、合計1）。重みは 1995〜2000 年の y の当てはまりで決める。
- その年の差（名目円）= 日本の名目 × (exp(Δy_合成 − Δy_日本) − 1)。Δ は 2000 年からの変化。2001〜2023 年を累計。
- 比較国の決まり：2000年の就業者1人当たりGDP（PPP）が日本の8割未満の国は外す（仕様 v1.0 cause-axis-v1）。
  アイルランドは多国籍企業の計上で IT の付加価値がゆがむので外す。
  「外生を除く」版は、他国の産業政策の表で外生（差し引く）とされた国の支援が強い産業（C26・J61 の韓国）から韓国を外す。
- 置換検定：比較国を1つずつ「日本の役」にして同じ計算をし、日本の差が何番目かを出す。
"""
import csv, collections, math, json, sys
import numpy as np
from scipy.optimize import minimize
D="./oecd/"
v=collections.defaultdict(dict)
for x in csv.DictReader(open(D+'stan_donor.csv')):
    if x['OBS_VALUE']: v[(x['REF_AREA'],x['ACTIVITY'],x['PRICE_BASE'])][int(x['TIME_PERIOD'])]=float(x['OBS_VALUE'])
emp=collections.defaultdict(dict)
for x in csv.DictReader(open(D+'emp_donor.csv')):
    if x['OBS_VALUE']: emp[x['REF_AREA']][int(x['TIME_PERIOD'])]=float(x['OBS_VALUE'])
g=({x['REF_AREA']:float(x['OBS_VALUE']) for x in csv.DictReader(open(D+'gdp2000_donor.csv'))})
prod={c:g[c]/emp[c][2000] for c in g if 2000 in emp[c]}
ELIG=[c for c in prod if c!='JPN' and prod[c]>=0.8*prod['JPN'] and c!='IRL']
PRE=range(1995,2001); POST=range(2001,2024); YRS=range(1995,2024)
def real(c,a):
    L=v.get((c,a,'L'))
    if L and all(t in L for t in YRS): return L
    if c=='JPN':
        par='J' if a.startswith('J') else '_T'
        Vp,Lp,Va=v[(c,par,'V')],v[(c,par,'L')],v[(c,a,'V')]
        if all(t in Va and t in Vp and t in Lp for t in YRS): return {t:Va[t]/(Vp[t]/Lp[t]) for t in YRS}
    return None
def y(c,a):
    if a=='_T_emp':
        T=v.get((c,'_T','L'))
        if not T or not all(t in T and t in emp[c] for t in YRS): return None
        return {t:math.log(T[t]/emp[c][t]) for t in YRS}
    I=real(c,a); T=v.get((c,'_T','L'))
    if I is None or not T or not all(t in T for t in YRS): return None
    return {t:math.log(I[t]/I[1995])-math.log(T[t]/T[1995]) for t in YRS}
def synth(target,donors,a):
    yt=y(target,a); ys={d:y(d,a) for d in donors}; ys={d:s for d,s in ys.items() if s}
    ds=sorted(ys); X=np.array([[ys[d][t]-ys[d][1995] for d in ds] for t in PRE]); z=np.array([yt[t]-yt[1995] for t in PRE])
    n=len(ds); f=lambda w: float(((X@w-z)**2).sum())
    r=minimize(f,np.ones(n)/n,bounds=[(0,1)]*n,constraints=[{'type':'eq','fun':lambda w:w.sum()-1}],method='SLSQP')
    w=r.x; cf={t:sum(w[i]*ys[ds[i]][t] for i in range(n)) for t in YRS}
    rmse=math.sqrt(f(w)/len(PRE))
    return cf,yt,{ds[i]:round(w[i],3) for i in range(n) if w[i]>0.005},rmse,ds
def loss(target,a,cf,yt):
    NV=v[(target,'_T' if a=='_T_emp' else a,'V')]; tot=0
    for t in POST:
        if t in NV: tot+=NV[t]*(math.exp((cf[t]-cf[2000])-(yt[t]-yt[2000]))-1)
    return tot
def median_loss(a,donors):
    yt=y('JPN',a); ys=[y(d,a) for d in donors]; ys=[s for s in ys if s]; NV=v[('JPN','_T' if a=='_T_emp' else a,'V')]; tot=0
    for t in POST:
        m=float(np.median([s[t]-s[2000] for s in ys])); tot+=NV[t]*(math.exp(m-(yt[t]-yt[2000]))-1)
    return tot
out={}
for a in ['J','J62_63','J58T60','J61','C26','M72','_T_emp']:
    donors=[c for c in ELIG if y(c,a)]
    res={'donors':sorted(donors)}
    for tag,dn in [('合成_韓国あり',donors),('合成_外生を除く',[d for d in donors if not (d=='KOR' and a in('C26','J61'))])]:
        cf,yt,w,rmse,ds=synth('JPN',dn,a)
        L=loss('JPN',a,cf,yt)
        # 置換検定：差の大きさを 2023 年の Δy の差で比べる
        jgap=(cf[2023]-cf[2000])-(yt[2023]-yt[2000])
        plac=[]
        for d in ds:
            cfd,ytd,_,_,_=synth(d,[x for x in ds if x!=d],a); plac.append((cfd[2023]-cfd[2000])-(ytd[2023]-ytd[2000]))
        rank=1+sum(1 for p in plac if p>=jgap)
        res[tag]={'累計兆円':round(L/1e6,1),'重み':w,'事前RMSE':round(rmse,4),'2023のΔyの差':round(jgap,3),'置換検定_順位':f"{rank}/{len(plac)+1}"}
    res['中央値_広い比較国']={'累計兆円':round(median_loss(a,donors)/1e6,1)}
    out[a]=res
print(json.dumps(out,ensure_ascii=False,indent=1))
