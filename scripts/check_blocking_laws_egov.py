#!/usr/bin/env python3
"""技術を止めた側のデータ（data/acquired/blocking-actors/）に書かれた「該当法令」を、e-Gov 法令 API v2 で確かめる。

要旨そのものの照合（scripts/verify_blocking_actors.py）とは別の、法令の引用だけの照合。
行ごとに、書かれた法令名が実在する法令に特定できるか、条番号が書かれていればその条が現行の法令にあるかを見る。

- 法令名は、題名の完全一致か、e-Gov の略称（abbrev、例: 薬機法・番号法）の一致で特定する。
  「個人情報保護法」のような通称で略称に無いものは ALIASES で正式名に直す。
- 条番号は現行の条文で見る（改正で条が動いた・削られたものは「条が見つからない」になる）。
- 結果は data/acquired/blocking-actors/verify/laws.csv（行ハッシュごと、氏名なし、e-Gov を見た観測時刻つき）。
- 附則の条と条例は e-Gov の本則の条では確かめられないので「一部未確認」にする。

相手への負荷: 法令一覧は1回だけ取り、条文は法令ごとに1回、1リクエストごとに1秒あける。
使い方: python3 scripts/check_blocking_laws_egov.py
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_blocking_actors import DATA, load_rows, norm, row_hash  # noqa: E402

API = "https://laws.e-gov.go.jp/api/2"
OUT = DATA / "verify" / "laws.csv"
LAW_COLUMNS = ("該当法令", "関連法令")
# e-Gov の略称に無い通称 → 正式な題名
ALIASES = {
    "個人情報保護法": "個人情報の保護に関する法律",
    "犯罪収益移転防止法": "犯罪による収益の移転防止に関する法律",
    "犯収法": "犯罪による収益の移転防止に関する法律",
    "資金決済法": "資金決済に関する法律",
    "景品表示法": "不当景品類及び不当表示防止法",
    "景表法": "不当景品類及び不当表示防止法",
    "独占禁止法": "私的独占の禁止及び公正取引の確保に関する法律",
    "独禁法": "私的独占の禁止及び公正取引の確保に関する法律",
    "国家戦略特区法": "国家戦略特別区域法",
    "外為法": "外国為替及び外国貿易法",
    "番号法": "行政手続における特定の個人を識別するための番号の利用等に関する法律",
    "マイナンバー法": "行政手続における特定の個人を識別するための番号の利用等に関する法律",
    "金商法": "金融商品取引法",
    "民泊新法": "住宅宿泊事業法",
    "派遣法": "労働者派遣事業の適正な運営の確保及び派遣労働者の保護等に関する法律",
    "労働者派遣法": "労働者派遣事業の適正な運営の確保及び派遣労働者の保護等に関する法律",
    "医薬品医療機器等法": "医薬品、医療機器等の品質、有効性及び安全性の確保等に関する法律",
    "電子帳簿保存法": "電子計算機を使用して作成する国税関係帳簿書類の保存方法等の特例に関する法律",
    # 2026年1月の改正施行で題名が変わった（法令IDは同じ 331AC0000000120）
    "下請法": "製造委託等に係る中小受託事業者に対する代金の支払の遅延等の防止に関する法律",
    "下請代金支払遅延等防止法": "製造委託等に係る中小受託事業者に対する代金の支払の遅延等の防止に関する法律",
    "建築士法": "建築士法",
    "割賦販売法": "割賦販売法",
    "特定商取引法": "特定商取引に関する法律",
    "特商法": "特定商取引に関する法律",
    "農地中間管理事業法": "農地中間管理事業の推進に関する法律",
    "公益認定法": "公益社団法人及び公益財団法人の認定等に関する法律",
    "難民認定法": "出入国管理及び難民認定法",
    "入管法": "出入国管理及び難民認定法",
    "振替法": "社債、株式等の振替に関する法律",
    "一般社団法": "一般社団法人及び一般財団法人に関する法律",
    "一般財団法": "一般社団法人及び一般財団法人に関する法律",
    "労基法": "労働基準法",
    "労災保険法": "労働者災害補償保険法",
    "廃棄物処理法": "廃棄物の処理及び清掃に関する法律",
    "未成年者飲酒禁止法": "二十歳未満ノ者ノ飲酒ノ禁止ニ関スル法律",
}
NO_LAW = {"", "記載なし", "不明"}
NON_LAW_RE = re.compile(r"告示|通達|通知|指針|ガイドライン|マニュアル|要綱|要領|Q&A|Ｑ＆Ａ")
KANJI = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def kanji_int(s: str) -> int | None:
    if s.isdigit():
        return int(s)
    if not s or any(c not in KANJI and c not in "十百千" for c in s):
        return None
    total, cur = 0, 0
    for c in s:
        if c in KANJI:
            cur = KANJI[c]
        else:
            unit = {"十": 10, "百": 100, "千": 1000}[c]
            total += (cur or 1) * unit
            cur = 0
    return total + cur


LAW_RE = re.compile(r"([^\s、,，・／/（）()「」。；;]+(?:法律|法|令|規則|基準|条例))")
SUPPL = "附則"
ART_RE = re.compile(r"第?([0-9一二三四五六七八九十百千〇]+)条(?:の([0-9一二三四五六七八九十〇]+))?")
# 条のほかに引用に書かれてよいもの（項・号・附則・範囲・ただし書など）。これ以外が残れば確かめきれない部分がある
ITEM_RE = re.compile(r"第?[0-9一二三四五六七八九十百千〇]+(?:項|号)(?:の[0-9一二三四五六七八九十〇]+)?|附則|[〜～~\-－ー]|\s|ただし書|前段|後段|本文|各号|柱書")


DRAFT_RE = re.compile(r"(?:[^\s]{0,6}?(?:改正|法律|法|省令|政令|規則|条例|府令|告示))?(?:原?案|素案|草案|試案)")


def unconsumed(part: str) -> str:
    """法令名・条・項などを除いた残り（「等」「改正案」「について」「別表」など）。"""
    return ITEM_RE.sub("", ART_RE.sub("", LAW_RE.sub("", part)))


def parse_citation(s: str, leftovers: list | None = None) -> list[tuple[str, str | None]]:
    """「番号法第19条、金融商品取引法第33条第2項」→ [("番号法","19"), ("金融商品取引法","33")]。条の指定が無ければ None。"""
    s = unicodedata_nfkc(s)
    def bracket(m):
        if "条" in m.group(0):
            return " " + m.group(0)
        inner = m.group(0)[1:-1]
        # 「住宅宿泊事業法（案）」「（改正案）」のような草案の印や、括弧の中の別の省令は、現行の法令の実在だけでは確かめきれない。
        # 「（提案名）」「（答申案件）」のように「案」を含むだけの語は草案の印ではない
        if leftovers is not None and (DRAFT_RE.fullmatch(inner.strip()) or LAW_RE.search(inner)):
            leftovers.append(m.group(0))
        return " "
    s = re.sub(r"（[^）]*）|\([^)]*\)", bracket, s)
    out = []
    for part in re.split(r"[、,，／/・。；;]|及び|および|並びに", s):
        part = part.strip()
        laws = list(LAW_RE.finditer(part))
        if laws:
            # 1つの区切りに法令が2つ以上あっても（「A法第1条とB法第2条」）、それぞれの条を拾う
            spans = [(m.group(1), part[m.end():(laws[k + 1].start() if k + 1 < len(laws) else len(part))])
                     for k, m in enumerate(laws)]
            # 「介護保険法等」「薬機法改正案」「別表第一」のような残りは、法令の実在だけでは確かめきれない
            if leftovers is not None and unconsumed(part):
                leftovers.append(part)
        elif out and part.startswith(("第", "附則")):
            if not ART_RE.search(part) and "附則" not in part:
                continue  # 「第4条第1項・第4項」の「第4項」は直前の条の項。新しい引用にしない
            spans = [(out[-1][0], part)]  # 「農地法第2条、第3条」の2つ目は前の法令の条
            if leftovers is not None and unconsumed(part):
                leftovers.append(part)  # 「第195条第8項等」の「等」はほかの条を含むので確かめきれない
        else:
            if part and part not in NO_LAW and leftovers is not None:
                leftovers.append(part)  # 法令として読めなかった部分（制度名・税目・サービス名など）
            continue
        for name, rest in spans:
            arts = list(ART_RE.finditer(rest))
            if not arts:
                out.append((name, None))
                continue
            last, expanded = 0, False
            for a in arts:
                # 「民法第7条〜第9条」の「第9条」は直前の範囲の展開で入れたので、ここでは飛ばす
                if expanded and re.fullmatch(r"\s*[〜～~\-－ー]\s*", rest[last:a.start()]):
                    last, expanded = a.end(), False
                    continue
                expanded = False
                if "附則" in rest[last:a.start()]:
                    out.append((name, SUPPL))  # 附則の条は本則と番号が別。今は確かめない
                    last = a.end()
                    continue
                last = a.end()
                main, sub = kanji_int(a.group(1)), kanji_int(a.group(2) or "")
                if main is None:
                    out.append((name, None))
                    continue
                out.append((name, f"{main}_{sub}" if sub else str(main)))
                # 「民法第7条〜第9条」は間の条も全部確かめる
                r = re.match(r"\s*[〜～~\-－ー]\s*" + ART_RE.pattern, rest[a.end():])
                if r and not sub and not r.group(2):
                    end = kanji_int(r.group(1))
                    if end is not None and main < end <= main + 2000:
                        out += [(name, str(n)) for n in range(main + 1, end + 1)]
                        expanded = True
    return out


def unicodedata_nfkc(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKC", s or "")


def get_json(path: str, params: dict, sleep: float) -> dict:
    url = f"{API}/{path}?" + urllib.parse.urlencode(params)
    for i in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                b = r.read()
            time.sleep(sleep)
            return json.loads(b)
        except Exception:  # noqa: BLE001
            if i == 3:
                raise
            time.sleep(sleep * (2 ** (i + 1)))
    return {}


def law_catalog(cache: Path, sleep: float, max_age_days: float = 7) -> tuple[list[dict], str]:
    """(法令一覧, 一覧を e-Gov から取った時刻)。保存から max_age_days を超えた一覧は取り直す。"""
    if cache.exists() and time.time() - cache.stat().st_mtime < max_age_days * 86400:
        d = json.loads(cache.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            return d["laws"], d["observed"]
        return d, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(cache.stat().st_mtime))
    out, offset = [], 0
    while True:
        d = get_json("laws", {"limit": 1000, "offset": offset, "response_format": "json"}, sleep)
        for l in d.get("laws", []):
            ri = l.get("current_revision_info") or l["revision_info"]
            out.append({"id": l["law_info"]["law_id"], "type": l["law_info"]["law_type"],
                        "title": ri["law_title"], "abbrev": [a for a in (ri.get("abbrev") or "").split(",") if a],
                        "repeal": ri.get("repeal_status")})
        if not d.get("next_offset"):
            break
        offset = d["next_offset"]
    cache.parent.mkdir(parents=True, exist_ok=True)
    observed = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cache.write_text(json.dumps({"observed": observed, "laws": out}, ensure_ascii=False), encoding="utf-8")
    return out, observed


# 改題前の正式名 → 法令ID。過去の資料は当時の題名で引用する。e-Gov の法令履歴（law_revisions）にその題名があるときだけ使う
OLD_TITLES = {
    "住民基本台帳の一部の写しの閲覧及び住民票の写し等の交付に関する省令": "360M50000008028",
}


def add_old_titles(cat: list[dict], cache_dir: Path, sleep: float) -> None:
    """OLD_TITLES の旧題名を、e-Gov の履歴で確かめてから一覧に足す（同じ法令IDを指す）。"""
    by_id = {l["id"]: l for l in cat}
    for old, law_id in OLD_TITLES.items():
        cur = by_id.get(law_id)
        if cur is None:
            continue
        p = cache_dir / f"egov-law-revisions-{law_id}.json"
        if p.exists() and time.time() - p.stat().st_mtime < 7 * 86400:
            titles = json.loads(p.read_text(encoding="utf-8"))
        else:
            d = get_json(f"law_revisions/{law_id}", {"response_format": "json"}, sleep)
            titles = sorted({r.get("law_title", "") for r in d.get("revisions", [])})
            p.write_text(json.dumps(titles, ensure_ascii=False), encoding="utf-8")
        if old in titles:
            cat.append({**cur, "title": old, "abbrev": [], "old_title_of": cur["title"]})


def resolve(name: str, cat: list[dict]) -> dict | None:
    title = ALIASES.get(name, name)
    prio = {"Act": 0, "CabinetOrder": 1, "MinisterialOrdinance": 2}
    hits = [l for l in cat if l["title"] == title] or [l for l in cat if name in l["abbrev"]]
    if not hits and len(name) >= 4:
        # 題名の一部（「…清掃に関する法律」など）で1本に決まるときだけ使う
        part = [l for l in cat if name in l["title"] and l["type"] == "Act" and l["repeal"] in (None, "None")]
        hits = part if len(part) == 1 else []
    hits.sort(key=lambda l: (l["repeal"] not in (None, "None"), prio.get(l["type"], 9)))
    return hits[0] if hits else None


def articles(law_id: str, cache: dict, sleep: float) -> set[str]:
    if law_id not in cache:
        d = get_json(f"law_data/{law_id}", {"response_format": "json", "law_full_text_format": "json"}, sleep)
        nums: set[str] = set()

        def walk(n):
            if isinstance(n, dict):
                if n.get("tag") == "SupplProvision":
                    return  # 附則の条は本則の条番号と別なので数えない
                if n.get("tag") == "Article":
                    nums.add(str(n.get("attr", {}).get("Num", "")))
                for c in n.get("children", []):
                    walk(c)
        walk(d.get("law_full_text", {}))
        cache[law_id] = nums
        cache[("観測", law_id)] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return cache[law_id]


def art_label(art: str) -> str:
    main, _, sub = art.partition("_")
    return f"第{main}条" + (f"の{sub}" if sub else "")


def check_row(text: str, cat: list[dict], art_cache: dict, sleep: float,
              fetched: list | None = None) -> tuple[str, str]:
    """(照合, 内訳)。fetched を渡すと、条文を実際に取れた法令の観測時刻を足していく。"""
    if norm(text) in NO_LAW or re.fullmatch(r"（.*(明示なし|記載なし|要確認).*）", text.strip()):
        return "法令の明示なし", ""
    # 題名に「、」「及び」を含む法令（医薬品、医療機器等の…）は区切りで割れるので、先に印へ置き換える
    keep = {}
    for t in sorted((l["title"] for l in cat if re.search(r"[、,，]|及び|並びに", l["title"])), key=len, reverse=True):
        if t in text:
            k = f"KEEP{len(keep)}法"
            keep[k] = t
            text = text.replace(t, k)
    rest: list[str] = []
    cites = [(keep.get(n, n), a) for n, a in parse_citation(text, rest)]
    for k, t in keep.items():
        rest = [r.replace(k, t) for r in rest]  # 印を題名に戻してから残す
    if not cites:
        return "法令以外（指針・制度名など）", text[:60]
    notes, worst = [], 0
    rank = ["実在（条も確認）", "実在（条の指定なし）", "一部未確認（条例・附則・告示など）", "条が見つからない", "法令が特定できない"]
    prev = None  # 「同法」「同施行規則」が指す前の法令の名前
    for name, art in cites:
        if name.endswith("条例"):
            worst = max(worst, 2)  # 条例は e-Gov に無いので確かめられない
            notes.append(f"{name}=e-Gov対象外")
            continue
        if name.startswith("同"):
            if prev is None:
                worst = max(worst, 4)
                notes.append(f"{name}=前の法令が無い")
                continue
            # 同法→前の法令。同施行規則→「前の法令の題名＋施行規則」（職業安定法施行規則）。
            # 同規則→「法」を除いた題名＋規則（労働安全衛生法→労働安全衛生規則）。実在する名前を順に試す
            sub = re.sub(r"^(法律|法)", "", name[1:])  # 同法施行令 → 施行令
            if not sub:
                name = prev
            else:
                stem = re.sub(r"(に関する法律|法律|法)$", "", prev)
                cands = [prev + sub, stem + sub, prev + "施行" + sub]
                if sub.endswith("省令"):
                    # 同省令→その法の省令（労働安全衛生法→労働安全衛生規則・○○法施行規則）
                    cands += [stem + "規則", prev + "施行規則", stem + "施行規則"]
                name = next((n for n in cands if resolve(n, cat)), cands[0])
        law = resolve(name, cat)
        if law and law["type"] == "Act":
            prev = law["title"]
        if not law:
            worst = max(worst, 4)
            notes.append(f"{name}=特定できない")
            continue
        if art is None:
            worst = max(worst, 1)
            notes.append(f"{name}=○")
            continue
        if art == SUPPL:
            worst = max(worst, 2)
            notes.append(f"{name}附則=未確認")
            continue
        try:
            nums = articles(law["id"], art_cache, sleep)
        except Exception:  # noqa: BLE001  1本の取得失敗で全体を止めない
            worst = max(worst, 4)
            notes.append(f"{name}=条文の取得失敗")
            continue
        if fetched is not None and ("観測", law["id"]) in art_cache:
            fetched.append(art_cache[("観測", law["id"])])
        if art in nums:
            notes.append(f"{name}{art_label(art)}=○")
        else:
            worst = max(worst, 3)
            notes.append(f"{name}{art_label(art)}=現行に無い")
    if not notes:
        return "法令以外（指針・制度名など）", text[:60]
    other = NON_LAW_RE.findall(text)
    if other or rest:
        # 告示・通達・指針や、法令として読めなかった部分（制度名・税目など）は e-Gov の法令一覧で確かめられない。
        # 法令と並んでいても、行全体を確認済みにしない
        worst = max(worst, 2)
        notes.append(f"{'・'.join(dict.fromkeys(other + [r[:20] for r in rest]))}=未確認")
    return rank[worst], "・".join(notes)[:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=Path("/tmp/egov-law-catalog.json"))
    ap.add_argument("--sleep", type=float, default=1.0)
    a = ap.parse_args()
    cat, catalog_observed = law_catalog(a.cache, a.sleep)
    add_old_titles(cat, a.cache.parent, a.sleep)
    art_cache: dict = {}
    rows = []
    for rel, i, r in load_rows():
        text = next((r[c] for c in LAW_COLUMNS if c in r), None)
        if text is None:
            continue
        fetched: list = []
        verdict, note = check_row(text, cat, art_cache, a.sleep, fetched)
        rows.append({"行ハッシュ": row_hash(rel, r), "ファイル": rel, "行": i, "該当法令": text,
                     "法令照合": verdict, "内訳": note, "法令一覧の観測時刻": catalog_observed,
                     "条文の観測時刻": max(fetched) if fetched else ""})  # 条文を取っていない行は空
    if not rows:
        raise SystemExit("法令の列がある行が無い")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(Counter(r["法令照合"] for r in rows))


if __name__ == "__main__":
    main()
