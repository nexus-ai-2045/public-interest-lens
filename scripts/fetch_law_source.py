"""法律の一次資料（衆議院の議案本文、国会会議録）を読みやすい文字にして標準出力へ出す。再判定の読み手（AI）が使う。

  python3 scripts/fetch_law_source.py honbun 閣法-180-38          議案本文（衆議院）。理由の節と本文の先頭
  python3 scripts/fetch_law_source.py kokkai "棚田地域振興法 提案" 217   会議録の発言検索（語, 回次）。発言の先頭を並べる
  python3 scripts/fetch_law_source.py url https://...               任意の URL を文字にする

取得できないときは「取得できない：理由」を出して 1 で終わる（読めたふりをしない）。
"""
from __future__ import annotations

import html
import json
import re
import sys
import urllib.parse
import urllib.request

KIND_CODE = {"閣法": "09", "衆法": "05", "参法": "06"}
HONBUN = "https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/honbun/houan/g{session:03d}{code}{number:03d}.htm"
KOKKAI = "https://kokkai.ndl.go.jp/api/speech"
TIMEOUT = 40


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "law-source-reader"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return res.read()


def to_text(raw: bytes) -> str:
    for enc in ("utf-8", "cp932", "euc_jp"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("cp932", errors="replace")
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def honbun_url(law_id: str) -> str:
    kind, session, number = law_id.split("-")
    return HONBUN.format(session=int(session), code=KIND_CODE[kind], number=int(number))


def honbun(law_id: str, head: int = 6000) -> str:
    url = honbun_url(law_id)
    text = to_text(get(url))
    at = text.rfind("理　由")
    reason = text[at:at + 1500] if at >= 0 else "（理由の節が見つからない）"
    return f"出典：{url}\n全体 {len(text)} 字\n\n【理由】\n{reason}\n\n【本文の先頭 {head} 字】\n{text[:head]}"


def kokkai(words: str, session: str = "", records: int = 6, head: int = 1800) -> str:
    q = {"any": words, "recordPacking": "json", "maximumRecords": str(records)}
    if session:
        q["sessionFrom"] = q["sessionTo"] = session
    url = KOKKAI + "?" + urllib.parse.urlencode(q)
    data = json.loads(get(url))
    out = [f"検索：{url}", f"該当 {data.get('numberOfRecords', 0)} 件（先頭 {records} 件まで）"]
    for r in data.get("speechRecord", []):
        out.append(f"\n--- {r['date']} {r['nameOfHouse']}{r['nameOfMeeting']} {r['speaker']} {r['speechURL']}\n{r['speech'][:head]}")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    try:
        if argv[0] == "honbun":
            print(honbun(argv[1]))
        elif argv[0] == "kokkai":
            print(kokkai(argv[1], argv[2] if len(argv) > 2 else ""))
        elif argv[0] == "url":
            print(to_text(get(argv[1]))[:12000])
        else:
            print(__doc__)
            return 2
    except Exception as e:  # noqa: BLE001 読めない理由をそのまま読み手に返す
        print(f"取得できない：{type(e).__name__} {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
