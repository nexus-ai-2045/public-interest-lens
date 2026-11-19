#!/bin/bash
# 首相官邸 歴代内閣ページの取得（1.1秒以上あける）。manifest.csv に記録する。
cd "$(dirname "$0")/.." || exit 1
R=.local/office-holders; mkdir -p $R/raw
[ -f $R/manifest.csv ] || echo "url,file,sha256,http,fetched_at" > $R/manifest.csv
get(){ u="$1"; f="$R/raw/$2"; code=$(curl -sSL -A "public-interest-lens" -m 40 -o "$f" -w "%{http_code}" "$u"); h=$(shasum -a 256 "$f"|cut -d' ' -f1); echo "$u,$2,$h,$code,$(date -u +%FT%TZ)" >> $R/manifest.csv; sleep 1.2; }
for n in $(seq 67 105); do p=$(printf %03d $n); get https://www.kantei.go.jp/jp/rekidainaikaku/$p.html c$p.html; done
for n in 102 103 104 105; do for s in index fukudaijin seimukan sourihosakan; do get https://www.kantei.go.jp/jp/$n/meibo/$s.html m${n}_$s.html; done; done
get https://www.kantei.go.jp/jp/rekidainaikaku/index.html rekidainaikaku_index.html
# 氏名が外字の画像で書かれた行がある。画像が一次資料なので取っておく（読み取った氏名は data/acquired/office-holders/cabinet-gaiji.csv）。
mkdir -p $R/raw/gaiji
# src の書き方（./ ../ / で始まる）によらず、gaiji/ の後のファイル名で拾う（parse_cabinet.py もファイル名で引く）。
for g in $(grep -oh "<img[^>]*gaiji[^>]*>" $R/raw/c*.html | grep -o "gaiji/[^\"']*" | sed 's/^gaiji\///' | sort -u); do get https://www.kantei.go.jp/jp/rekidainaikaku/img/gaiji/$g gaiji/$g; done
echo done > $R/fetch.done
