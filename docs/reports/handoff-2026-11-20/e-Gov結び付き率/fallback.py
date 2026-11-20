import csv,json,re,sys,time,urllib.request,urllib.parse
r=[x for x in csv.DictReader(open('result.csv')) if x['err']=='' and x['新規か改正か']=='改正' and x['改正元の数']=='0']
w=csv.writer(open('fallback.csv','w',newline='')); w.writerow(['id','題名','名前','形','一致数','category'])
for x in r:
    t=re.sub(r'案$','',x['題名'])
    m=re.match(r'^(.+?)(等)?の一部を改正する法律$',t)
    if not m: w.writerow([x['id'],x['題名'],'','形外',0,'']); continue
    name=m.group(1); form='単独' if not m.group(2) and '及び' not in name else '複数'
    first=re.split(r'及び|並びに|、',name)[0]
    q='https://laws.e-gov.go.jp/api/2/laws?'+urllib.parse.urlencode({'law_title':first,'law_type':'Act','omit_current_revision_info':'true','limit':50})
    try: d=json.loads(urllib.request.urlopen(q,timeout=60).read())
    except Exception as e: d={'laws':[]}
    hits=[l for l in d.get('laws',[]) if (l.get('revision_info') or {}).get('law_title')==first]
    w.writerow([x['id'],x['題名'],first,form,len(hits),'|'.join(l['revision_info'].get('category') or '' for l in hits)]); time.sleep(0.15)
