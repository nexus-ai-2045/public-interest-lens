"""e-Statのファイル一覧ページ(tstat)から「年平均」リンク先を列挙。python -I dstat_estat_list.py TSTAT"""
import re, html, sys, subprocess, time

UA = 'public-interest-lens/1.0 (research)'


def get(url):
    time.sleep(1.2)
    return subprocess.run(['curl', '-sL', '-A', UA, url], capture_output=True).stdout.decode('utf-8', 'ignore')


t = sys.argv[1]
top = get('https://www.e-stat.go.jp/stat-search/files?tstat=%s' % t)
print(re.search(r'<title>([^<]*)', top).group(1)[:80])
seen = set()
for m in re.finditer(r'<a [^>]*href="([^"]*tstat=%s[^"]*layout=datalist[^"]*)"[^>]*>(.*?)</a>' % t, top, re.S):
    u = html.unescape(m.group(1))
    txt = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', m.group(2)))
    if u in seen:
        continue
    seen.add(u)
    print('LINK', txt[:50], u)
