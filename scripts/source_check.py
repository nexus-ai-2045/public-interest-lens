"""出典チェック：公開ランキングに載せた数字を、一次資料（台帳と公的統計）から別系統で突き合わせる。

`build_public_ranking.py` が作った `ranking.json` を読み、公開している法律ごとに次を確かめる。
判定ルールのコード（app/src の TypeScript）は使わず、元の表だけから Python で独立に計算し直す。

- 出典URL：官公庁・国際機関のドメインだけで、台帳（衆議院の経過、e-Gov の改正履歴）に記録された URL と一致する
- 題名：衆議院の議案台帳（bill-census-full）の題名と一致する
- 施行日：施行日台帳と一致し、施行期日の原文があり、公布日（議案台帳の和暦）より前でない
- 統計の原値：損失表に書いた「開始前最後の年の名目付加価値」が OECD 表6 の値と一致する
- 再計算：比較国・窓・産業を公開値から読み、OECD 表6 の連鎖実質から額の中央値と幅を計算し直して一致する
- 原本：取得記録（manifest.csv）の原本ファイルが手元にあれば、ハッシュが一致する（クラウドには原本が無いので「原本なし」）

1つでも「不一致」があれば、その法律を公開から外し、保留（理由コード SOURCE）に移す。
「対象外」（例：OECD 表6 以外の指標で再計算が未対応）は外さず、件数を報告に出す。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DERIVED = ROOT / "data" / "derived"
ACQUIRED = ROOT / "data" / "acquired"
RANKING = ROOT / "app" / "public" / "distribution" / "ranking.json"
MEMBERS = ROOT / "app" / "public" / "distribution" / "members.json"
REPORT_DIR = DERIVED / "source-check"

PRIMARY_HOSTS = ("go.jp", "oecd.org", "worldbank.org", "imf.org", "un.org")
REASON = "出典チェックで一次資料と食い違いがあったため、確認がとれるまで額を公開しない"
ERAS = {"明治": 1867, "大正": 1911, "昭和": 1925, "平成": 1988, "令和": 2018}
KANJI = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
OK, NG, NA = "一致", "不一致", "対象外"
TOLERANCE_YEN = 1


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def wareki_to_iso(text: str) -> str | None:
    """「平成26年11月12日」「平成二十六年十一月十二日」を ISO 日付にする。読めなければ None。"""
    text = re.sub(r"\s", "", text)
    match = re.fullmatch(r"(明治|大正|昭和|平成|令和)(元|\d+)年(\d+)月(\d+)日", text)
    if not match:
        return None
    era, year, month, day = match.groups()
    year_num = 1 if year == "元" else int(year)
    try:
        return date(ERAS[era] + year_num, int(month), int(day)).isoformat()
    except ValueError:
        return None


def is_primary(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    return parsed.scheme == "https" and any(host == h or host.endswith("." + h) for h in PRIMARY_HOSTS)


def _quantile(values: list[float], q: float) -> float:
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


class Oecd:
    """OECD 表6（産業別の総付加価値）。国・産業・価格ごとに年→値。"""

    def __init__(self, path: Path):
        self.series: dict[tuple[str, str, str], dict[int, float]] = {}
        if path.exists():
            for row in _read(path):
                if row["値"].strip():
                    self.series.setdefault((row["国"], row["産業"], row["価格"]), {})[int(row["年"])] = float(row["値"])

    def get(self, country: str, industry: str, price: str) -> dict[int, float]:
        return self.series.get((country, industry, price), {})


def recompute(oecd: Oecd, industry: str, start: str, end_year: int, countries: list[str]) -> dict | None:
    """開始前の伸びの差を織り込んだ反実仮想との差（円、累積）。loss-rule-v1 と同じ定義を、元の表から独立に計算する。"""
    jp = oecd.get("JPN", industry, "LR")
    nominal = oecd.get("JPN", industry, "V")
    start_year = int(start[:4])
    # 年の観測は年末（YYYY-12-31）扱い。開始日より前の年が「開始前」。
    pre = sorted(y for y in jp if f"{y}-12-31" < start)
    if len(pre) < 3:
        return None
    base, first = pre[-1], pre[max(0, len(pre) - 5)]
    span = base - first
    post = [y for y in sorted(jp) if f"{y}-12-31" >= start][:10]
    post = [y for y in post if y <= end_year]
    controls = [oecd.get(c, industry, "LR") for c in countries]
    if not post or base not in nominal or len(controls) < 3:
        return None
    if any(not all(y in c for y in [first, base, *post]) for c in controls):
        return None
    growth = lambda a, b: math.log(b / a) / span  # noqa: E731
    drift = growth(jp[first], jp[base]) - _quantile([growth(c[first], c[base]) for c in controls], 0.5)
    base_yen = nominal[base] * 1_000_000  # OECD 表6 の JPN は百万円
    sums = {}
    for key, q in (("low", 0.25), ("median", 0.5), ("high", 0.75)):
        total = 0.0
        for y in post:
            cf = jp[base] * _quantile([c[y] / c[base] for c in controls], q) * math.exp(drift * (y - base))
            total += (cf - jp[y]) / jp[base] * base_yen
        sums[key] = round(total)
    return {"base_year": base, "base_nominal_million": nominal[base], "years": post, "start_year": start_year, **sums}


def _manifest_hashes(acquired: Path, local_root: Path) -> tuple[dict[str, list[tuple[Path, str]]], int]:
    """URL → [(原本の置き場所, sha256)]。原本が手元にある件数も返す。"""
    by_url: dict[str, list[tuple[Path, str]]] = {}
    present = 0
    for manifest in sorted(acquired.glob("*/manifest.csv")):
        for row in _read(manifest):
            rel = row.get("path") or row.get("local_path") or ""
            digest = row.get("sha256", "")
            if not rel or not digest:
                continue
            candidate = local_root / rel if rel.startswith(".local") else manifest.parent / rel
            if candidate.exists():
                present += 1
            by_url.setdefault(row.get("url", ""), []).append((candidate, digest))
    return by_url, present


def check_law(law: dict, ctx: dict) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(item: str, published, primary, result: str, note: str = "") -> None:
        rows.append({"id": law["id"], "項目": item, "公開値": str(published), "一次資料の値": str(primary), "結果": result, "備考": note})

    census = ctx["census"].get(law["id"])
    enforcement = ctx["enforcement"].get(law["id"])
    loss = ctx["loss"].get(law["id"])

    # 出典URL
    recorded = set()
    if census:
        recorded.add(census.get("経過URL", ""))
    if enforcement:
        for url in enforcement.get("出典URL", "").split(";"):
            m = re.fullmatch(r"https://laws\.e-gov\.go\.jp/api/2/law_revisions/([0-9A-Z]+)", url)
            recorded.add(f"https://laws.e-gov.go.jp/law/{m.group(1)}" if m else url)
    for url in law.get("sources", []):
        if not is_primary(url):
            add("出典URL", url, "官公庁・国際機関のドメイン", NG, "一次資料でないドメイン")
        elif url not in recorded:
            add("出典URL", url, "台帳に記録なし", NG, "台帳の URL と一致しない")
        else:
            add("出典URL", url, url, OK)

    # 題名
    if not census:
        add("題名", law["title"], "議案台帳に無い", NG)
    else:
        add("題名", law["title"], census["題名"], OK if census["題名"] == law["title"] else NG)

    # 施行日
    if not enforcement:
        add("施行日", law["enforcedOn"], "施行日台帳に無い", NG)
    else:
        same = enforcement["施行日"] == law["enforcedOn"]
        add("施行日", law["enforcedOn"], enforcement["施行日"], OK if same else NG)
        add("施行期日の原文", "あり", "あり" if enforcement.get("施行期日の原文", "").strip() else "なし",
            OK if enforcement.get("施行期日の原文", "").strip() else NG)
        promulgated = wareki_to_iso(census["公布日"]) if census else None
        if promulgated is None:
            add("公布日との順序", law["enforcedOn"], census["公布日"] if census else "", NA, "議案台帳の公布日を読めない")
        else:
            add("公布日との順序", law["enforcedOn"], promulgated, OK if law["enforcedOn"] >= promulgated else NG, "施行日は公布日より前にならない")
            if enforcement.get("公布日"):
                add("公布日", enforcement["公布日"], promulgated, OK if enforcement["公布日"] == promulgated else NG, "施行日台帳と議案台帳")

    # 統計の原値と再計算（OECD 表6）
    formula = loss.get("計算式の要素", "") if loss else ""
    m = re.search(r"OECD 表6 JPN [^（]*（([A-Z_]+)）", formula)
    if not m:
        add("再計算", law["amountMedianYen"], "", NA, "OECD 表6 以外の指標は再計算が未対応")
        return rows
    industry = m.group(1)
    nominal = re.search(r"開始前最後の年（(\d{4})年）の名目付加価値 (\d+)百万円", formula)
    if nominal:
        year, value = int(nominal.group(1)), float(nominal.group(2))
        actual = ctx["oecd"].get("JPN", industry, "V").get(year)
        add("名目付加価値（開始前最後の年）", f"{value:.0f}百万円", "無し" if actual is None else f"{actual:.0f}百万円",
            OK if actual == value else NG, f"OECD 表6 JPN {industry} V {year}年")
    window = re.fullmatch(r"(\d{4})〜(\d{4})年", law["window"])
    if not window:
        add("再計算", law["amountMedianYen"], "窓を読めない", NG)
        return rows
    result = recompute(ctx["oecd"], industry, law["enforcedOn"], int(window.group(2)), law["comparisonCountries"])
    if result is None:
        add("再計算", law["amountMedianYen"], "計算できない", NG, "比較国か年の観測が足りない")
        return rows
    if str(result["years"][0]) != window.group(1):
        add("額の窓", law["window"], f"{result['years'][0]}〜{result['years'][-1]}年", NG)
    # 元の値は正が損失・負が便益。公開値は側ごとの大きさ。純額の差し引き（測った便益）がある法律は、損失表の額を経由して照合する。
    sign = -1 if law["side"] == "benefit" else 1
    recomputed = sorted(sign * result[k] for k in ("low", "median", "high"))
    published = [law["amountLowYen"], law["amountMedianYen"], law["amountHighYen"]]
    measured_offset = "円換算済み" in law.get("benefitStatus", "")
    for label, pub, rec in zip(("額の下端", "額の中央値", "額の上端"), published, recomputed):
        if measured_offset:
            add(label, pub, rec, NA, "測った便益を差し引いた純額のため、総額だけを再計算した")
        else:
            add(label, pub, rec, OK if abs(pub - rec) <= TOLERANCE_YEN else NG, f"OECD 表6 {industry} LR、比較国{len(law['comparisonCountries'])}か国")

    # 原本（手元にあるときだけ）
    urls = {url for url in recorded if url}
    urls |= {row.get("出典URL", "") for row in ctx["oecd_rows"] if row["産業"] == industry}
    for url in sorted(urls):
        for path, digest in ctx["manifest"].get(url, []):
            if path.exists():
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                add("原本のハッシュ", digest[:12], actual[:12], OK if actual == digest else NG, url)
    return rows


def context(acquired: Path = ACQUIRED, derived: Path = DERIVED, local_root: Path = ROOT) -> dict:
    census = {f"{r['種別']}-{r['提出回次']}-{r['番号']}": r for r in _read(acquired / "bill-census-full" / "enacted.csv")}
    enforcement = {r["id"]: r for r in _read(acquired / "enforcement-dates" / "enforcement.csv")}
    loss_path = derived / "loss-v1-triage-v2" / "loss.csv"
    loss = {r["id"]: r for r in _read(loss_path)} if loss_path.exists() else {}
    oecd_path = acquired / "oecd-industry" / "industry_va.csv"
    manifest, present = _manifest_hashes(acquired, local_root)
    return {
        "census": census, "enforcement": enforcement, "loss": loss,
        "oecd": Oecd(oecd_path), "oecd_rows": _read(oecd_path) if oecd_path.exists() else [],
        "manifest": manifest, "raw_present": present,
    }


def check(ranking: dict, ctx: dict) -> tuple[list[dict[str, str]], dict]:
    rows = [row for law in ranking["laws"] for row in check_law(law, ctx)]
    summary = {
        "checkedLaws": len(ranking["laws"]),
        "items": len(rows),
        "match": sum(r["結果"] == OK for r in rows),
        "mismatch": sum(r["結果"] == NG for r in rows),
        "notApplicable": sum(r["結果"] == NA for r in rows),
        "heldOut": sorted({row["id"] for row in rows if row["結果"] == NG}),
        "rawFilesPresent": ctx["raw_present"],
    }
    return rows, summary


def check_members(members: dict, ranking: dict) -> list[dict[str, str]]:
    """議員ページ：法律の額が公開ランキングと同じか、証拠が一次資料か、個人の配分の合計が額×帰属率を超えないか。"""
    rows: list[dict[str, str]] = []

    def add(subject: str, item: str, published, primary, result: str, note: str = "") -> None:
        rows.append({"id": subject, "項目": item, "公開値": str(published), "一次資料の値": str(primary), "結果": result, "備考": note})

    published = {law["id"]: law for law in ranking["laws"]}
    held = {item["id"] for item in ranking["held"] if item["reasonCode"] == "SOURCE"}
    for law in members["laws"]:
        if law["id"] in held:
            add(law["id"], "議員ページの法律", "載っている", "出典チェックで外した法律", NG)
        elif law["id"] in published:
            want = published[law["id"]]
            got = (law["amount"]["low"], law["amount"]["median"], law["amount"]["high"])
            exp = (want["amountLowYen"], want["amountMedianYen"], want["amountHighYen"])
            add(law["id"], "議員ページの額", got, exp, OK if got == exp else NG, "公開ランキングの額")
    shares: dict[str, list[int]] = {}
    bad_urls = 0
    for member in members["members"]:
        for law in member["laws"]:
            shares.setdefault(law["lawId"], []).append(abs(law["share"]["median"]))
            bad_urls += sum(not is_primary(e["url"]) for e in law["evidence"])
    add("議員ページ", "証拠URL", "一次資料以外の URL の数", bad_urls, OK if bad_urls == 0 else NG, "国会会議録・衆参の議案情報だけ")
    amounts = {law["id"]: abs(law["amount"]["median"]) for law in members["laws"]}
    for law_id, values in shares.items():
        cap = amounts.get(law_id, 0) * members["rate"]
        add(law_id, "個人の配分の合計", sum(values), f"{cap:.0f} 以下", OK if sum(values) <= cap + len(values) else NG, "額×帰属率を超えない（丸め誤差は1人1円まで）")
    return rows


def write_report(rows: list[dict[str, str]], summary: dict, report_dir: Path = REPORT_DIR) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    with (report_dir / "check.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "項目", "公開値", "一次資料の値", "結果", "備考"])
        writer.writeheader()
        writer.writerows(rows)
    # 原本の有無は環境（クラウドか Mac か）で変わるので、公開の記録には残さない。
    stable = {key: value for key, value in summary.items() if key != "rawFilesPresent"}
    (report_dir / "summary.json").write_text(json.dumps(stable, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rebuild(approved: list[str], approved_at: str, ranking_path: Path = RANKING, write: bool = True) -> dict:
    """出典チェックを外した状態で作り、全件を照合し、不一致を外して作り直す。"""
    from scripts import build_public_ranking as ranking_builder

    candidate = ranking_builder.build(approved, approved_at, held_by_check=set())
    rows, summary = check(candidate, context())
    payload = ranking_builder.build(approved, approved_at, held_by_check=set(summary["heldOut"]))
    if MEMBERS.exists():
        member_rows = check_members(json.loads(MEMBERS.read_text(encoding="utf-8")), payload)
        rows += member_rows
        summary["memberMismatch"] = sum(r["結果"] == NG for r in member_rows)
        summary["items"] = len(rows)
        summary["match"] = sum(r["結果"] == OK for r in rows)
    if write:
        write_report(rows, summary)
        ranking_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ranking", type=Path, default=RANKING)
    parser.add_argument("--dry-run", action="store_true", help="ranking.json と報告を書き換えない")
    args = parser.parse_args()
    current = json.loads(args.ranking.read_text(encoding="utf-8"))
    # 前回の出典チェックで外した法律も承認済みとして照合し直す（直っていれば公開に戻る）。
    from scripts import build_public_ranking as ranking_builder
    approved = sorted(set(current["approval"]["approvedLaws"]) | ranking_builder.source_held())
    approved_at = current["approval"]["approvedAt"] or (str(date.today()) if approved else "")
    summary = rebuild(approved, approved_at, args.ranking, write=not args.dry_run)
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if summary["mismatch"] or summary.get("memberMismatch") else 0


if __name__ == "__main__":
    sys.exit(main())
