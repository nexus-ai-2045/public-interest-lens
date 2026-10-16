"""e-Statのdatalistページから (表名, ダウンロードID) を列挙。python -I dstat_estat_files.py URL"""
import re, html, sys, subprocess, time

time.sleep(1.2)
b = subprocess.run(['curl', '-sL', '-A', 'public-interest-lens/1.0 (research)', sys.argv[1]], capture_output=True).stdout.decode('utf-8', 'ignore')
for m in re.finditer(r'<li[^>]*>(?:(?!</li>).)*?file-download\?statInfId=(\d+)&(?:amp;)?fileKind=(\d)(?:(?!</li>).)*?</li>', b, re.S):
    pass
# 表ごとのブロック: 「統計表」名の直後から次のfile-downloadまで
parts = re.split(r'(file-download\?statInfId=\d+&(?:amp;)?fileKind=\d)', b)
last_text = ''
for i, p in enumerate(parts):
    if p.startswith('file-download'):
        ids = re.findall(r'\d+', p)
        print(ids[0], 'kind', ids[1], '|', last_text[-110:])
    else:
        t = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', p))).strip()
        if t:
            last_text = t
