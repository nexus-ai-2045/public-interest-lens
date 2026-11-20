"""類型の照合（type-crosscheck-v1、2026-11-20）。サイトの類型を、法律案の本文から決定論の規則で出した類型と突き合わせる。AI は呼ばない。

  python3 scripts/type_crosscheck.py fetch [--limit N]   本文（衆議院の議案本文）と改正元（e-Gov 法令 API v2）を .local/type-crosscheck-v1/ に取る
  python3 scripts/type_crosscheck.py build              取ったものから data/derived/type-crosscheck-v1/crosscheck.csv と summary.json を作る

背景：/mnt/project-files/analysis/確立理論で数え方の穴を洗い出す_2026-11-19.md の 6-4・6-5。
  標本（既存の裁定だけを正解）では、規則とサイトの値が一致した143本中139本が正しく、
  食い違いに既知の誤り27本中23本が入った。規則だけで置き換えると今の付け方より悪い（196本中157本 対 169本）。
  そのため「置き換え」ではなく「独立した2つ目の判定源」として使う。

規則（本文と改正元の法令分類だけを見る）：
  1. 本則が「○○の一部を次のように改正する」で始まらない新規の法律 → 新規
  2. 改正元（e-Gov）の法令分類がすべて ORG_CATEGORIES → 組織手続
  3. 本則に改正の指示が無い（附則だけ）、または「加える」が無く置き換えがすべて数・日付どうし → 定型改正
  4. それ以外 → 実質改正
新規はサイトの値も同じ情報（新規か改正か）で決まるので、一致しても確かさは上がらない（照合の対象外として印を付ける）。
このスクリプトは照合の結果を出すだけで、順位・配分・額にはまだつながない（つなぎ込みは別の PR）。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from primary_source_corrections import load_layered, value

ENACTED = ROOT / "data" / "acquired" / "bill-census-full" / "enacted.csv"
TRIAGE = ROOT / "data" / "derived" / "bill-triage-v1" / "triage.csv"
OUT = ROOT / "data" / "derived" / "type-crosscheck-v1"
LOCAL = ROOT / ".local" / "type-crosscheck-v1"
HONBUN = LOCAL / "honbun.jsonl"
EGOV = LOCAL / "egov.jsonl"
METHOD_VERSION = "type-crosscheck-v1"
EGOV_API = "https://laws.e-gov.go.jp/api/2/laws?"
HONBUN_URL = "https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/honbun/houan/g{kai:03d}{tc}{no:03d}.htm"
KIND_CODE = {"閣法": "09", "衆法": "05", "参法": "06"}
ERA = {"平成": "4", "令和": "5"}
ORG_CATEGORIES = frozenset({"行政組織", "国家公務員", "国会", "行政手続", "地方自治"})
NEW, SUBST, ROUTINE, ORG = "新規", "実質改正", "定型改正", "組織手続"
SLEEP = 0.5  # 照会の間隔（秒）。相手に負荷をかけない

NUM = r"[〇一二三四五六七八九十百千万億兆０-９0-9]+"
NUMERIC = re.compile(r"^(平成|令和|昭和)?(" + NUM + r"年)?(" + NUM + r"月)?(" + NUM + r"日)?(度)?$|^" + NUM
                     + r"(円|分の" + NUM + r"|人|年|月|日|パーセント)?$")
REPLACE = re.compile(r"「([^「」]{0,80})」を「([^「」]{0,80})」に")
OPS = re.compile("改める|加える|削る|削除する")
HEADER = re.compile(r"第[一二三四五六七八九十百〇]+回 [閣衆参]第[一二三四五六七八九十百〇]+号")


def law_key(r: dict) -> str:
    return f"{r['種別']}-{r['提出回次']}-{r['番号']}"


def egov_law_id(r: dict) -> str | None:
    """法律番号と公布日から e-Gov の law_id を組む。閣法は AC0、衆法・参法は AC1。"""
    m = re.match(r"(平成|令和)\s*(元|\d+)年", r["公布日"].strip())
    n = r["法律番号"].strip()
    if not m or not n.isdigit():
        return None
    y = 1 if m.group(2) == "元" else int(m.group(2))
    pre = "0" if r["種別"] == "閣法" else "1"
    return f"{ERA[m.group(1)]}{y:02d}AC{pre}{int(n):09d}"


def honbun_url(key: str) -> str | None:
    kind, kai, no = key.split("-")
    if kind not in KIND_CODE or not (kai.isdigit() and no.isdigit()):
        return None
    return HONBUN_URL.format(kai=int(kai), tc=KIND_CODE[kind], no=int(no))


def read_jsonl(p: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                o = json.loads(line)
                out[o["id"]] = o
    return out


def _get(url: str, decode: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as res:
        return res.read().decode(decode, "ignore")


def first_amended_name(title: str) -> str | None:
    t = re.sub(r"案$", "", title)
    m = re.match(r"^(.+?)(等)?の一部を改正する法律$", t)
    return re.split(r"及び|並びに|、", m.group(1))[0] if m else None


def fetch_egov(r: dict) -> dict:
    """改正元の法令分類。改正履歴（amendment_law_id）→ 本体（law_id）→ 題名の先頭の法律名の完全一致、の順。"""
    lid = egov_law_id(r)
    if not lid:
        return {"law_id": None, "bases": [], "how": "番号なし"}
    q = {"omit_current_revision_info": "true"}
    d = json.loads(_get(EGOV_API + urllib.parse.urlencode({**q, "amendment_law_id": lid, "limit": 500}), "utf-8"))
    bases = [L for L in d.get("laws", []) if L["law_info"]["law_id"] != lid]
    how = "改正履歴"
    if not bases:
        time.sleep(SLEEP)
        d = json.loads(_get(EGOV_API + urllib.parse.urlencode({**q, "law_id": lid, "limit": 5}), "utf-8"))
        bases = [L for L in d.get("laws", []) if L["law_info"]["law_id"] == lid]
        how = "本体"
    if not bases and (name := first_amended_name(r["題名"])):
        time.sleep(SLEEP)
        d = json.loads(_get(EGOV_API + urllib.parse.urlencode({**q, "law_title": name, "law_type": "Act", "limit": 50}), "utf-8"))
        hit = [L for L in d.get("laws", []) if (L.get("revision_info") or {}).get("law_title") == name]
        bases, how = (hit, "題名の完全一致") if len(hit) == 1 else ([], "結び付かない")
    return {"law_id": lid, "how": how if bases else "結び付かない",
            "bases": [{"law_id": L["law_info"]["law_id"], "title": (L.get("revision_info") or {}).get("law_title"),
                       "category": (L.get("revision_info") or {}).get("category")} for L in bases]}


def cmd_fetch(a: argparse.Namespace) -> int:
    LOCAL.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(ENACTED.open(encoding="utf-8")))
    # 取れなかった記録（本文が空・照会の失敗）は持っていない扱いにして、次の fetch で取り直す
    have_h = {k for k, o in read_jsonl(HONBUN).items() if o.get("text")}
    have_e = {k for k, o in read_jsonl(EGOV).items() if not str(o.get("how", "")).startswith("照会の失敗")}
    n = 0
    with HONBUN.open("a", encoding="utf-8") as fh, EGOV.open("a", encoding="utf-8") as fe:
        for r in rows:
            key = law_key(r)
            if a.limit and n >= a.limit:
                break
            if key not in have_h:
                url = honbun_url(key)
                try:
                    text = re.sub("<[^>]+>", "", _get(url, "shift_jis")) if url else ""
                except Exception as e:  # noqa: BLE001 書かずに先へ進む（次の fetch で取り直す）
                    text = ""
                    print(f"本文を取れない {key}: {e}", file=sys.stderr)
                if text:
                    fh.write(json.dumps({"id": key, "url": url, "text": text}, ensure_ascii=False) + "\n")
                n += 1
                time.sleep(SLEEP)
            if key not in have_e:
                try:
                    o = fetch_egov(r)
                except Exception as e:  # noqa: BLE001 書かずに先へ進む（次の fetch で取り直す）
                    print(f"改正元を照会できない {key}: {e}", file=sys.stderr)
                    time.sleep(SLEEP)
                    continue
                fe.write(json.dumps({"id": key, **o}, ensure_ascii=False) + "\n")
                time.sleep(SLEEP)
    print(f"取得 {n} 本（本文）。置き場 {LOCAL.relative_to(ROOT)}")
    return 0


def main_part(text: str) -> tuple[str, str]:
    """本文から本則と附則を取り出す（議案番号の行から「理由」の前まで）。"""
    t = re.sub(r"\s+", " ", text)
    if m := HEADER.search(t):
        t = t[m.start():]
    t = t.split("理 由")[0].split("理　由")[0]
    p = re.split(r" 附 則 | 附　則 ", t, maxsplit=1)
    return p[0], (p[1] if len(p) > 1 else "")


def rule_type(text: str, is_new_in_census: bool, base_categories: list[str]) -> tuple[str, dict]:
    """規則で類型を決める。戻り値は（類型, 根拠の数）。本文が空なら（"", {}）。"""
    if not text.strip():
        return "", {}
    body, _ = main_part(text)
    reps = REPLACE.findall(body)
    ev = {"改正の指示": len(OPS.findall(body)), "加える": body.count("加える"), "置き換え": len(reps),
          "数・日付の置き換え": sum(1 for x, y in reps if NUMERIC.match(x.replace(" ", "")) and NUMERIC.match(y.replace(" ", "")))}
    if is_new_in_census and "の一部を次のように改正する" not in body[:400]:
        return NEW, ev
    cats = set(base_categories)
    if cats and cats <= ORG_CATEGORIES:
        return ORG, ev
    if ev["改正の指示"] == 0:
        return ROUTINE, ev
    if ev["加える"] == 0 and ev["数・日付の置き換え"] == ev["置き換え"] == ev["改正の指示"]:
        return ROUTINE, ev
    return SUBST, ev


def site_types() -> dict[str, str]:
    """サイトの類型：振り分け（triage.csv の種類）に、訂正表と当て直しを重ねた値。"""
    corr = load_layered()
    out = {}
    for r in csv.DictReader(TRIAGE.open(encoding="utf-8")):
        out[r["id"]] = value(corr, r["id"], "類型") or r["種類"]
    for law_id in corr:
        if law_id not in out and (v := value(corr, law_id, "類型")):
            out[law_id] = v
    return out


def status(site: str, rule: str) -> str:
    if not rule:
        return "照合できない（本文なし）"
    if not site or site not in (NEW, SUBST, ROUTINE, ORG):
        return "照合できない（サイトの値なし）"
    if site == NEW and rule == NEW:
        return "一致（新規は同じ情報のため照合の意味なし）"
    return "一致" if site == rule else "食い違い"


def cmd_build(a: argparse.Namespace) -> int:
    rows = list(csv.DictReader(ENACTED.open(encoding="utf-8")))
    hon, eg = read_jsonl(HONBUN), read_jsonl(EGOV)
    missing = [law_key(r) for r in rows if not hon.get(law_key(r), {}).get("text")]
    if missing:
        # 本文ページが無い法律（番号の欠け・未掲載）は「照合できない（本文なし）」として出す
        print(f"本文の無い法律が {len(missing)} 本（照合できないとして出す）。取り直すなら fetch を回す", file=sys.stderr)
    site = site_types()
    out = []
    for r in rows:
        key = law_key(r)
        h, e = hon.get(key, {"url": honbun_url(key), "text": ""}), eg.get(key, {"bases": [], "how": "未照会"})
        cats = [b["category"] for b in e.get("bases", []) if b.get("category")]
        rt, ev = rule_type(h["text"], r["新規か改正か"] != "改正", cats)
        s = site.get(key, "")
        out.append({"id": key, "サイトの類型": s, "規則の類型": rt, "照合": status(s, rt),
                    "改正元の結び付き": e.get("how", ""), "改正元の法令分類": "|".join(cats),
                    **{k: ev.get(k, "") for k in ("改正の指示", "加える", "置き換え", "数・日付の置き換え")},
                    "本文URL": h.get("url") or "", "本文sha256": hashlib.sha256(h["text"].encode()).hexdigest()[:16] if h["text"] else ""})
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "crosscheck.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    c = Counter(x["照合"] for x in out)
    by_site = {t: {"本数": sum(1 for x in out if x["サイトの類型"] == t),
                   "一致": sum(1 for x in out if x["サイトの類型"] == t and x["照合"].startswith("一致"))}
               for t in (NEW, SUBST, ROUTINE, ORG)}
    summary = {"method": METHOD_VERSION, "法律の本数": len(out), "照合": dict(c), "サイトの類型ごと": by_site,
               "定義": "一致＝サイトの類型と規則の類型が同じ。新規どうしの一致は照合の意味がない（同じ情報）。"}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="本文と改正元を .local に取る（読み取りだけ）")
    f.add_argument("--limit", type=int, default=0, help="本文を取る本数の上限（0＝全部）")
    f.set_defaults(fn=cmd_fetch)
    b = sub.add_parser("build", help="照合の結果を data/derived/type-crosscheck-v1/ に書く")
    b.set_defaults(fn=cmd_build)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
