#!/usr/bin/env python3
"""公式ページ・PDFを取得し、原本を保存・manifest に記録・テキスト化する。
使い方: fetch_next_policies_pages.py urls.tsv   (列: id<TAB>URL)"""
from pathlib import Path
import hashlib, json, os, re, subprocess, sys, tempfile, html
src = open(os.path.join(str(Path(__file__).resolve().parent), "fetch_next_policies_laws.py")).read()
exec(src.split("LAWS = [")[0])
exec("last = [0.0]\n" + src.split("last = [0.0]")[1].split("for key, num in LAWS:")[0])
TXT = os.path.join(ROOT, ".local/next-policies-originals/text")
os.makedirs(TXT, exist_ok=True)


def totext(b, url):
    if b[:4] == b"%PDF":
        import io
        from pypdf import PdfReader
        try:
            return "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(b)).pages)
        except Exception as e:
            return ""
    for enc in ("utf-8", "shift_jis", "euc_jp"):
        try:
            t = b.decode(enc); break
        except Exception:
            t = b.decode("utf-8", "ignore")
    t = re.sub(r"(?is)<(script|style).*?</\1>", "", t)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(t)


for line in open(sys.argv[1], encoding="utf-8"):
    line = line.rstrip("\n")
    if not line.strip():
        continue
    i, u = line.split("\t")[:2]
    s, b = get(u)
    ext = "pdf" if b[:4] == b"%PDF" else "html"
    save(f"{i}.{ext}", u, s, b)
    n = 0
    if s == 200:
        t = totext(b, u)
        open(os.path.join(TXT, i + ".txt"), "w", encoding="utf-8").write(t)
        n = len(t)
    print(i, s, len(b), n, hashlib.sha256(b).hexdigest()[:10], flush=True)
