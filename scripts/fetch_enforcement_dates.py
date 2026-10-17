#!/usr/bin/env python3
"""成立法（評価対象）の施行日を e-Gov 法令 API v2 から取る。

入力:  data/derived/bill-triage-v1/triage.csv（結果=評価対象）
       data/acquired/bill-census-full/enacted.csv（公布日・法律番号）
出力:  data/acquired/enforcement-dates/enforcement.csv
       data/acquired/enforcement-dates/manifest.csv
       docs/reports/enforcement-dates.md
原本: .local/enforcement-dates/raw/*.json（git 管理外）

方針:
- 新規の法律は法令番号（law_num）で法令を引き、law_revisions を引き、初めの版の施行日を取る。
- 改正法は題名の「〜の一部を改正する法律」の〜から現行法令を引き、その改正履歴のうち
  amendment_law_num が当該改正法の法令番号に一致する版の amendment_enforcement_date を取る。
- 日付が複数あるときは全部を候補に残し、最も多くの版が採る日が一意に決まる場合だけ主な施行日にする。
  決まらないときは空欄にして備考に書く。推測では埋めない。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://laws.e-gov.go.jp/api/2/"
USER_AGENT = "public-interest-lens/1.0 (enforcement-dates; research use)"
INTERVAL = 1.1

TRIAGE = ROOT / "data/derived/bill-triage-v1/triage.csv"
ENACTED = ROOT / "data/acquired/bill-census-full/enacted.csv"
OUT_DIR = ROOT / "data/acquired/enforcement-dates"
RAW_DIR = ROOT / ".local/enforcement-dates/raw"
REPORT = ROOT / "docs/reports/enforcement-dates.md"

ERAS = {"明治": (1, 1867), "大正": (2, 1911), "昭和": (3, 1925), "平成": (4, 1988), "令和": (5, 2018)}
DIGITS = "〇一二三四五六七八九"
MANIFEST_COLS = ["url", "local_path", "sha256", "http_status", "bytes", "fetched_at"]
OUT_COLS = ["id", "題名", "法令番号", "公布日", "施行日", "施行日の候補（; 区切り）", "取得方法", "備考", "出典URL"]


# ---------- 純粋関数 ----------

def to_kanji(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    tens, ones = divmod(rest, 10)
    out = ""
    if hundreds:
        out += ("" if hundreds == 1 else DIGITS[hundreds]) + "百"
    if tens:
        out += ("" if tens == 1 else DIGITS[tens]) + "十"
    if ones:
        out += DIGITS[ones]
    return out


def from_kanji(text: str) -> int:
    text = text.strip()
    if text == "元":
        return 1
    if text.isdigit():
        return int(text)
    total, current = 0, 0
    for ch in text:
        if ch in "百十":
            total += (current or 1) * (100 if ch == "百" else 10)
            current = 0
        elif ch in DIGITS:
            current = DIGITS.index(ch)
        else:
            raise ValueError(text)
    return total + current


def parse_wareki(text: str) -> tuple[str, int, int, int] | None:
    m = re.search(r"(明治|大正|昭和|平成|令和)\s*(元|\d+)年\s*(\d+)月\s*(\d+)日", text or "")
    if not m:
        return None
    return m.group(1), from_kanji(m.group(2)), int(m.group(3)), int(m.group(4))


def wareki_to_iso(parts: tuple[str, int, int, int]) -> str:
    era, year, month, day = parts
    return f"{ERAS[era][1] + year:04d}-{month:02d}-{day:02d}"


def parse_law_num(text: str | None) -> tuple[str, int, int] | None:
    m = re.fullmatch(r"(明治|大正|昭和|平成|令和)([元〇一二三四五六七八九十百]+)年法律第([〇一二三四五六七八九十百]+)号", text or "")
    if not m:
        return None
    return m.group(1), from_kanji(m.group(2)), from_kanji(m.group(3))


def format_law_num(era: str, year: int, num: int) -> str:
    y = "元" if year == 1 else to_kanji(year)
    return f"{era}{y}年法律第{to_kanji(num)}号"


def law_id_of(era: str, year: int, num: int) -> str:
    return f"{ERAS[era][0]}{year:02d}AC0000000{num:03d}"


def amended_titles(title: str) -> list[str] | None:
    """「〜の一部を改正する法律案」の〜部分を取り出す。該当しなければ None。"""
    m = re.fullmatch(r"(.+?)の一部を改正する(?:等の)?法律案?", title.strip())
    return [m.group(1)] if m else None


def title_candidates(stem: str) -> list[str]:
    """題名候補。全体、「〜するための」の後ろ（目的句を外した形）、それぞれ末尾の「等」を外した形。"""
    out: list[str] = []
    for text in [stem] + [stem[m.end():] for m in re.finditer("ための", stem)]:
        for cand in (text, text.removesuffix("等")):
            if cand and cand not in out:
                out.append(cand)
    return out


def pick_main(dates: list[str]) -> tuple[str, str]:
    """dates は版ごとの施行日（重複あり）。(主な施行日, 備考) を返す。"""
    if not dates:
        return "", ""
    counts = Counter(dates)
    if len(counts) == 1:
        return dates[0], ""
    ranked = counts.most_common()
    if ranked[0][1] > ranked[1][1]:
        return ranked[0][0], f"段階施行（{len(counts)}日）。最も多くの版が採る日を主な施行日とした"
    return "", f"段階施行（{len(counts)}日）で最も多くの版が採る日が一意に決まらないため空欄"


# ---------- API クライアント ----------

class Client:
    def __init__(self, raw_dir: Path, manifest_path: Path):
        self.raw_dir = raw_dir
        self.manifest_path = manifest_path
        self.last = 0.0
        self.cache: dict[str, tuple[str, int]] = {}
        raw_dir.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        if manifest_path.exists():
            with manifest_path.open(encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    path = raw_dir.parent / row["local_path"]
                    if path.exists():
                        self.cache[row["url"]] = (row["local_path"], int(row["http_status"]))
        else:
            with manifest_path.open("w", encoding="utf-8", newline="") as fh:
                csv.writer(fh, lineterminator="\n").writerow(MANIFEST_COLS)

    def get(self, path: str, params: dict | None, name: str):
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        if url in self.cache:
            rel, status = self.cache[url]
            return url, status, json.loads((self.raw_dir.parent / rel).read_text(encoding="utf-8"))
        body, status = b"", 0
        for attempt in range(4):
            wait = self.last + INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    body, status = resp.read(), resp.status
                break
            except urllib.error.HTTPError as err:
                body, status = err.read(), err.code
                if status < 500:
                    break
            except (urllib.error.URLError, TimeoutError, OSError):
                body, status = b"", 0
            time.sleep(2 * (attempt + 1))
        if status == 0 or status >= 500:
            raise RuntimeError(f"fetch failed: {url}")
        rel = f"raw/{name}.json"
        (self.raw_dir / f"{name}.json").write_bytes(body)
        row = [url, rel, hashlib.sha256(body).hexdigest(), status, len(body),
               datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")]
        with self.manifest_path.open("a", encoding="utf-8", newline="") as fh:
            csv.writer(fh, lineterminator="\n").writerow(row)
        self.cache[url] = (rel, status)
        return url, status, json.loads(body.decode("utf-8"))

    def revisions(self, law_id: str):
        return self.get(f"law_revisions/{law_id}", None, f"revisions_{law_id}")

    def find_by_num(self, own: tuple[str, int, int]):
        num = format_law_num(*own)
        name = "num_" + hashlib.sha1(num.encode("utf-8")).hexdigest()[:12]
        url, status, data = self.get("laws", {"law_num": num, "law_type": "Act", "limit": 5}, name)
        for row in data.get("laws", []) if status == 200 else []:
            if row["law_info"]["law_num"] == num:
                return url, row["law_info"]["law_id"]
        return url, None

    def find_by_title(self, title: str):
        params = {"law_title": title, "law_type": "Act", "limit": 100}
        name = "title_" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
        url, status, data = self.get("laws", params, name)
        hits = []
        if status == 200:
            for row in data.get("laws", []):
                if row.get("revision_info", {}).get("law_title") == title:
                    hits.append(row["law_info"]["law_id"])
        return url, hits


# ---------- 1本分の処理 ----------

def find_renamed(client: Client, part: str, own: tuple[str, int, int], urls: list[str]) -> list[str]:
    """改称などで現行題名と一致しないとき、題名の先頭で部分一致検索し、当該改正法の版を持つ法令を探す。"""
    if ERAS[own[0]][1] + own[1] < 2015:
        return []
    name = "prefix_" + hashlib.sha1(part[:8].encode("utf-8")).hexdigest()[:12]
    url, status, data = client.get("laws", {"law_title": part[:8], "law_type": "Act", "limit": 100}, name)
    urls.append(url)
    found = []
    if status != 200:
        return found
    for row in data.get("laws", [])[:100]:
        title = row.get("revision_info", {}).get("law_title", "")
        if not title.startswith(part[:6]):
            continue
        lid = row["law_info"]["law_id"]
        rurl, rstatus, revs = client.revisions(lid)
        urls.append(rurl)
        if rstatus == 200 and matching_dates(revs, own, include_original=False):
            found.append(lid)
        if len(found) >= 3:
            break
    return found


def matching_dates(revs: dict, own: tuple[str, int, int], include_original: bool) -> list[str]:
    out = []
    for r in revs.get("revisions", []):
        num = r.get("amendment_law_num")
        ok = parse_law_num(num) == own if num else include_original
        if ok and r.get("amendment_enforcement_date"):
            out.append(r["amendment_enforcement_date"])
    return out


def resolve_one(client: Client, bill_title: str, own: tuple[str, int, int]) -> dict:
    res = {"dates": [], "urls": [], "notes": [], "method": "", "reason": ""}
    stem = amended_titles(bill_title)
    if stem is None:
        url, law_id = client.find_by_num(own)
        res["urls"].append(url)
        status, revs = 0, {}
        if law_id:
            url, status, revs = client.revisions(law_id)
            res["urls"].append(url)
        if status != 200:
            res["reason"] = "改正法で単独の法令データがなく、題名から改正対象も特定できない（または廃止済み）"
            return res
        dates = matching_dates(revs, own, include_original=True)
        res["method"] = "新規法令の初めの版（law_revisions）"
        if not dates:
            res["reason"] = "e-Gov の保持する版に初めの版がない"
            res["method"] = ""
        res["dates"] = dates
        return res

    res["method"] = "改正履歴（law_revisions）の amendment_law_num 一致"
    stem0 = stem[0]

    def lookup(text: str):
        for cand in title_candidates(text):
            url, hits = client.find_by_title(cand)
            res["urls"].append(url)
            if hits:
                return cand, hits
        return None

    targets: list[list[str]] = []
    whole = lookup(stem0)
    if whole:
        targets = [[whole[0], whole[1][0]]]
        if len(whole[1]) > 1:
            res["notes"].append(f"同名の現行法令が複数（{whole[0]}）。先頭を採用")
    else:
        base = stem0.rsplit("ための", 1)[-1]
        parts = [p for p in re.split(r"及び|並びに|、", base) if p]
        if len(parts) <= 1:
            ren = find_renamed(client, base, own, res["urls"])
            if ren:
                res["notes"].append("現行題名と一致しないため先頭一致で検索（改称の可能性）")
                targets = [[base, lid] for lid in ren]
            else:
                res["reason"] = f"題名「{stem0}」の現行法令が e-Gov に無い（改称・廃止の可能性）"
                return res
        else:
            for part in parts:
                got = lookup(part)
                if got:
                    targets.append([got[0], got[1][0]])
                    continue
                ren = find_renamed(client, part, own, res["urls"])
                if ren:
                    res["notes"].append(f"「{part}」は現行題名と一致しないため先頭一致で検索（改称の可能性）")
                    targets += [[part, lid] for lid in ren]
                else:
                    res["notes"].append(f"改正対象「{part}」の現行法令が e-Gov に無い")
                    res["partial"] = True
            if not targets:
                res["reason"] = f"題名「{stem0}」の現行法令が e-Gov に無い（改称・廃止の可能性）"
                return res
    for name, law_id in targets:
        url, status, revs = client.revisions(law_id)
        res["urls"].append(url)
        if status != 200:
            res["notes"].append(f"{name}: 改正履歴を取得できない（HTTP {status}）")
            res["partial"] = True
            continue
        d = matching_dates(revs, own, include_original=False)
        if d:
            res["dates"] += d
            res["notes"].append(f"{name}: {len(d)}版")
        else:
            res["notes"].append(f"{name}: 改正履歴に当該改正法の版が無い（保持範囲外、または同日施行の別改正に版が統合）")
            res["partial"] = True
    if not res["dates"]:
        res["reason"] = "対象法令は見つかったが、改正履歴に当該改正法の版が無い（e-Gov の保持範囲外、または版の統合）"
    return res


def run(limit: int | None, offset: int = 0) -> int:
    triage = list(csv.DictReader(TRIAGE.open(encoding="utf-8", newline="")))
    targets = [r for r in triage if r["結果"] == "評価対象"]
    enacted = {}
    for r in csv.DictReader(ENACTED.open(encoding="utf-8", newline="")):
        enacted[(r["種別"], r["提出回次"], r["番号"])] = r
    targets = targets[offset:]
    if limit:
        targets = targets[:limit]
    client = Client(RAW_DIR, OUT_DIR / "manifest.csv")
    rows, stats = [], Counter()
    for i, t in enumerate(targets, 1):
        kind, session, no = t["id"].split("-")
        e = enacted[(kind, session, no)]
        title = e["題名"]
        pdate = parse_wareki(e["公布日"])
        if pdate is None or not e["法律番号"].strip().isdigit():
            rows.append([t["id"], title, "", "", "", "", "取得不可", "公布日または法律番号が読めない", ""])
            stats["fail:input"] += 1
            continue
        own = (pdate[0], pdate[1], int(e["法律番号"]))
        res = resolve_one(client, title, own)
        dates = res["dates"]
        main, note = pick_main(dates)
        if res.get("partial") and main:
            main, note = "", (note + "；" if note else "") + "改正対象の一部で版が取れないため主な施行日は空欄"
        cands = sorted(set(dates))
        remark = "；".join(x for x in [note, *res["notes"], "" if res["notes"] else res["reason"]] if x)
        if not cands:
            method = "取得不可"
        else:
            method = res["method"]
        rows.append([
            t["id"], title, format_law_num(*own), wareki_to_iso(pdate), main, ";".join(cands), method, remark,
            ";".join(res["urls"]),
        ])
        stats["main" if main else ("cands" if cands else "fail")] += 1
        print(f"[{i}/{len(targets)}] {t['id']} {title[:30]} -> {main or '-'} ({len(cands)}候補)", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "enforcement.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(OUT_COLS)
        w.writerows(rows)
    write_report(rows)
    print(dict(stats))
    return 0


def write_report(rows: list[list[str]]) -> None:
    total = len(rows)
    got = [r for r in rows if r[4]]
    cand_only = [r for r in rows if not r[4] and r[5]]
    fail = [r for r in rows if not r[5]]
    reasons: Counter = Counter()
    for r in fail:
        reasons[r[7].split("；")[-1] or "不明"] += 1
    # 理由は題名固有の語を落としてまとめる
    grouped: Counter = Counter()
    for reason, n in reasons.items():
        key = re.sub(r"「[^」]*」", "「…」", reason)
        key = re.sub(r"^[^：:]+: ", "（法律名）: ", key)
        grouped[key] += n
    new_total = sum(1 for r in rows if not amended_titles(r[1]))
    old_fail = sum(1 for r in fail if r[3] < "2017")
    lines = [
        "# 成立法（評価対象）の施行日 取得結果",
        "",
        "評価対象 349 本の施行日を e-Gov 法令 API v2 から取った結果。スクリプトは `scripts/fetch_enforcement_dates.py`、",
        "結果は `data/acquired/enforcement-dates/enforcement.csv`、取得記録は同 `manifest.csv`（原本 JSON は `.local/enforcement-dates/raw/` に保存、git 管理外）。",
        "",
        "## 件数",
        "",
        f"- 対象: {total} 本（題名が「〜の一部を改正する法律」の形のもの {total - new_total} 本、それ以外 {new_total} 本）",
        f"- 施行日を取れた: {len(got)} 本",
        f"- 候補はあるが主な施行日を決められず空欄: {len(cand_only)} 本（段階施行で最も多くの版が採る日が一意でない、または改正対象の一部で版が取れない）",
        f"- 取れなかった: {len(fail)} 本（うち 2016 年以前の公布 {old_fail} 本。e-Gov の改正履歴は主に 2017 年以降の版しか持たない）",
        "",
        "## 取れなかった理由",
        "",
    ]
    for key, n in grouped.most_common():
        lines.append(f"- {key}: {n} 本")
    lines += [
        "",
        "## 取り方と限界",
        "",
        "- 新規の法律は法令番号（law_num）で法令を引き、`law_revisions` の初めの版の施行日を取る。",
        "- 改正法は題名の改正対象を現行法令の題名で引き、`law_revisions` のうち `amendment_law_num` が当該改正法の法令番号と一致する版の `amendment_enforcement_date` を取る。",
        "- 日付が複数ある（段階施行）ときは全部を「施行日の候補」に残し、最も多くの版が採る日が一意に決まる場合だけ主な施行日にした。決まらないときは空欄で、備考に書いた。",
        "- e-Gov の法令 API が保持する改正履歴は一部の法令で古い版を持たず、廃止済みの法令は引けない。そのため古い改正法ほど取れない。これらは推測で埋めていない。",
        "- 改正対象が複数の法律にまたがる場合、一部でも版が取れない法律があれば主な施行日は空欄にした。",
        "- 同じ日に別の改正法が同じ法律に施行されると、版が統合され当該改正法の番号が現れないことがある（その場合は取得不可として扱った）。",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--offset", type=int, default=0)
    args = ap.parse_args(argv)
    return run(args.limit, args.offset)


if __name__ == "__main__":
    sys.exit(main())
