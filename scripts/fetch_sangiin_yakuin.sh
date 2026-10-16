#!/bin/bash
# 参議院 国会回次ごとの役員等一覧（常任委員長を含む）を取得。存在する回次だけ保存。
cd "$(dirname "$0")/.." || exit 1
R=.local/office-holders; mkdir -p $R/raw/sangiin
[ -f $R/manifest.csv ] || echo "url,file,sha256,http,fetched_at" > $R/manifest.csv
for n in $(seq 222 -1 1); do
  u=https://www.sangiin.go.jp/japanese/joho1/kousei/giin/$n/yakuin.htm; f=$R/raw/sangiin/yakuin_$n.htm
  code=$(curl -sSL -A "public-interest-lens" -m 40 -o "$f" -w "%{http_code}" "$u")
  if [ "$code" = 200 ]; then h=$(shasum -a 256 "$f"|cut -d' ' -f1); else h=""; rm -f "$f"; fi
  echo "$u,$( [ $code = 200 ] && echo yakuin_$n.htm),$h,$code,$(date -u +%FT%TZ)" >> $R/manifest.csv; sleep 1.2
done
echo done > $R/sangiin.done
