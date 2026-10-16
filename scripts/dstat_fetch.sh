#!/bin/bash
# usage: dstat_fetch.sh URL OUTNAME  -- 原本保存+manifest記録 (同一ホスト1.1秒間隔)
cd "$(dirname "$0")/.." || exit 1
D=.local/domestic-stats; mkdir -p $D/raw
URL="$1"; OUT="$D/raw/$2"
sleep 1.2
CODE=$(curl -sL -A "public-interest-lens/1.0 (research)" -o "$OUT" -w "%{http_code}" "$URL")
[ -f $D/manifest.csv ] || echo "url,file,sha256,http,fetched_at" > $D/manifest.csv
SHA=$(shasum -a 256 "$OUT" | cut -d' ' -f1)
echo "$URL,$2,$SHA,$CODE,$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> $D/manifest.csv
echo "$CODE $(wc -c < "$OUT") $2"
