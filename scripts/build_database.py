"""リポジトリの JSON/CSV から、関係のついた1つのデータベース（SQLite、kokuzoku-db/v1）を作り直す。

設計は docs/データベース.md、表の定義は data/db/schema.sql、計算の版は設計決定0013。
入力はリポジトリの中のファイルだけで、通信はしない。同じ入力からは同じ中身ができる（作った時刻は入れない）。
毎朝の自動更新（scripts/daily_update.py）の最後に作り直し、公開サイトのグラフ用の集計 app/public/distribution/charts.json も書く。

使い方：
  python3 scripts/build_database.py                 # data/db/kokuzoku.sqlite と charts.json を作る
  python3 scripts/build_database.py --out x.sqlite  # 別の場所に作る（版を上げる前後の比較に使う。scripts/compare_db.py）
  python3 scripts/build_database.py --no-charts
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "app" / "public" / "distribution"
ACQ = ROOT / "data" / "acquired"
DERIVED = ROOT / "data" / "derived"
SCHEMA = ROOT / "data" / "db" / "schema.sql"
REGISTRY = ROOT / "data" / "db" / "source-registry.csv"
SPEC = ROOT / "app" / "src" / "method-spec.ts"
OUT = ROOT / "data" / "db" / "kokuzoku.sqlite"
CHARTS = DIST / "charts.json"
DB_SCHEMA = "kokuzoku-db/v1"

csv.field_size_limit(1 << 26)


# 読んだ入力ファイル。inputs_digest はここにあるものを全部ハッシュする（読む先を足しても漏れない）。
READ_FILES: set[Path] = set()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    READ_FILES.add(path)
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_json(path: Path):
    READ_FILES.add(path)
    return json.loads(path.read_text(encoding="utf-8"))


def wareki(text: str) -> str | None:
    """「平成10年 3月25日」→ 1998-03-25。ISO の日付はそのまま。"""
    text = (text or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    m = re.search(r"(昭和|平成|令和)\s*(\d+|元)年\s*(\d+)月\s*(\d+)日", text)
    if not m:
        return None
    base = {"昭和": 1925, "平成": 1988, "令和": 2018}[m.group(1)]
    year = (1 if m.group(2) == "元" else int(m.group(2))) + base
    return f"{year}-{int(m.group(3)):02d}-{int(m.group(4)):02d}"


def number(text: str) -> float | None:
    try:
        value = float(str(text).replace(",", ""))
    except ValueError:
        return None
    return value if value == value else None  # NaN を落とす


class Db:
    def __init__(self, path: Path):
        if path.exists():
            path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.executescript(SCHEMA.read_text(encoding="utf-8"))
        self._sources: dict[str, int] = {}
        self.counts: Counter[str] = Counter()
        self.series_url: dict[str, str] = {}

    def source(self, url: str | None) -> int | None:
        url = (url or "").strip()
        if not re.match(r"https?://", url):
            return None
        if url not in self._sources:
            cur = self.con.execute("INSERT INTO sources (url, host) VALUES (?, ?)", (url, urlsplit(url).hostname or ""))
            self._sources[url] = cur.lastrowid
        return self._sources[url]

    def insert(self, table: str, row: dict) -> None:
        cols = ", ".join(row)
        self.con.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
        self.counts[table] += 1

    def ensure(self, table: str, key: str, value: str, **extra) -> None:
        self.con.execute(f"INSERT OR IGNORE INTO {table} ({key}{''.join(', ' + k for k in extra)}) VALUES ({', '.join('?' * (1 + len(extra)))})", [value, *extra.values()])


# ---- 仕様の版 ----

def load_spec(db: Db) -> str:
    """method-spec.ts の節（id・title・version・status・code）を読む。TypeScript を実行せず、決まった書き方だけを読む。"""
    text = SPEC.read_text(encoding="utf-8")
    version = re.search(r"SPEC_VERSION = '([^']+)'", text).group(1)
    for block in re.split(r"\n  \{\n    id: ", text)[1:]:
        get = lambda key: re.search(rf"\n    {key}: '([^']*)'", "\n    id: " + block)  # noqa: E731
        code = re.search(r"\n    code: \[(.*?)\],", block, re.S)
        db.insert("method_versions", {
            "component": re.match(r"'([^']+)'", block).group(1), "version": get("version").group(1), "status": get("status").group(1),
            "title": get("title").group(1), "code": "、".join(re.findall(r"'([^']*)'", code.group(1))) if code else "",
        })
    return version


# ---- 法律 ----

def load_laws(db: Db) -> dict[str, dict]:
    enacted = read_csv(ACQ / "bill-census-full" / "enacted.csv")
    enforcement = {r["id"]: r for r in read_csv(ACQ / "enforcement-dates" / "enforcement.csv")}
    ranking = read_json(DIST / "ranking.json")
    published = {law["id"]: law for law in ranking["laws"]}
    others = {law["id"]: law for law in ranking["others"]}
    obs_counts = Counter((l["group"], l["window"], l["amountLowYen"], l["amountMedianYen"], l["amountHighYen"]) for l in published.values())
    for key, n in sorted(obs_counts.items(), key=lambda kv: [str(x) for x in kv[0]]):
        db.insert("observations", {"observation_id": obs_id(*key), "grp": key[0], "window": key[1], "low": key[2], "median": key[3], "high": key[4], "n_laws": n})
    for r in enacted:
        law_id = f"{r['種別']}-{r['提出回次']}-{r['番号']}"
        dated = enforcement.get(law_id, {})
        law = published.get(law_id)
        other = others.get(law_id, {})
        enforced = (law or {}).get("enforcedOn") or dated.get("施行日") or None
        origin = "台帳" if dated.get("施行日") else ("推定（公布日）" if law and law.get("enforcedOn") else None)
        db.insert("decisions", {
            "decision_id": law_id, "country": "JPN", "kind": "法律", "title": r["題名"], "decided_on": wareki(r["公布日"]) or dated.get("公布日") or None,
            "effective_on": enforced, "effective_origin": origin, "fiscal_year": None, "decided_by": "国会",
            "source_id": db.source(r["経過URL"]), "summary": None,
        })
        row = {"law_id": law_id, "bill_kind": r["種別"], "session": int(r["提出回次"]), "number": int(r["番号"]) if r["番号"] else None, "title": r["題名"],
               "enacted_on": wareki(r["公布日"]), "enforced_on": enforced, "outcome": "額" if law else other.get("outcome", "未分類"),
               "reason": None if law else other.get("reason"), "side": None, "certainty": None, "stage": None, "field": None, "indicator": None,
               "low": None, "median": None, "high": None, "window_from": None, "window_to": None, "lower_bound": 0, "benefit_status": None, "observation_id": None}
        if law:
            years = re.findall(r"\d{4}", law.get("window") or "")
            row.update({"side": law["side"], "certainty": law["certainty"], "stage": law.get("stage"), "field": law.get("field"), "indicator": law.get("indicator"),
                        "low": law["amountLowYen"], "median": law["amountMedianYen"], "high": law["amountHighYen"],
                        "window_from": int(years[0]) if years else None, "window_to": int(years[1]) if len(years) > 1 else None,
                        "lower_bound": int(bool(law.get("lowerBound"))), "benefit_status": law.get("benefitStatus"),
                        "observation_id": obs_id(law["group"], law["window"], law["amountLowYen"], law["amountMedianYen"], law["amountHighYen"])})
        db.insert("laws", row)
        if law:
            for note in law.get("notes", []):
                db.insert("law_notes", {"law_id": law_id, "note": note})
            for url in law.get("sources", []):
                db.insert("law_sources", {"law_id": law_id, "source_id": db.source(url)})
            for country in law.get("comparisonCountries", []):
                db.insert("law_countries", {"law_id": law_id, "country": country})
        for col, stance in (("賛成会派_衆", "賛成"), ("反対会派_衆", "反対")):
            for party in filter(None, (p.strip() for p in (r.get(col) or "").split(";"))):
                db.ensure("parties", "party_id", party)
                db.insert("law_party_stances", {"law_id": law_id, "party_id": party, "house": "衆議院", "stance": stance})
    missing = set(published) - {f"{r['種別']}-{r['提出回次']}-{r['番号']}" for r in enacted}
    if missing:
        raise ValueError(f"成立法の台帳に無い公開の法律があります: {sorted(missing)[:5]}")
    return published


def obs_id(group: str, window: str, low: int, median: int, high: int) -> str:
    return f"{group}／{window}／{low}／{median}／{high}"


# ---- 人・行動・配分 ----

def load_people_and_allocations(db: Db) -> None:
    members = read_json(DIST / "members.json")
    reference = read_json(DIST / "members-reference.json")
    # 配分 v1（allocation-v1、設計決定0014）があればその名前、無い古いデータは成立への寄与の版。
    method = "allocation-v1" if "allocation-v1" in members["rules"] else ("+".join(r for r in members["rules"] if r.startswith("causal-")) or members["rules"][0])
    for m in [*members["members"], *reference["members"]]:
        db.ensure("people", "person_id", m["id"], name=m["name"])
    # 会議録から集めた関与と、提出者の欄・参議院の賛否から機械的に作った関与（scripts/build_auto_involvements.py）の両方を入れる。
    alloc = DERIVED / "allocation-v1"
    involvements = read_csv(alloc / "involvements.csv") + read_csv(alloc / "involvements-auto.csv")
    for r in involvements:
        pid = r.get("人物ID") or r["氏名"]
        db.ensure("people", "person_id", pid, name=r["氏名"])
        db.insert("involvements", {"law_id": r["法律ID"], "person_id": pid, "house": r["院"], "action": r["行動"], "position": r["立場区分"],
                                   "title_then": r["当時の肩書"], "acted_on": r["日付"] or None, "source_id": db.source(r["証拠URL"]),
                                   "counted": int(r["算入"] == "はい"), "excluded_reason": r["除外理由"] or None})
    vote_day = {}
    for v in read_csv(alloc / "votes.csv") + read_csv(alloc / "votes-auto.csv"):
        vote_day[v["投票ID"]] = v["日付"]
        db.insert("sangiin_votes", {"law_id": v["法律ID"], "vote_id": v["投票ID"], "voted_on": v["日付"], "yes": int(v["賛成"]), "no": int(v["反対"]), "source_id": db.source(v["URL"])})
    # 参議院本会議の反対票（scripts/build_opposing_votes.py）。行動 oppose として、投票の結果のページを出典にする。
    for r in read_csv(alloc / "opposing.csv"):
        pid = r["人物ID"] or r["氏名"]
        db.ensure("people", "person_id", pid, name=r["氏名"])
        db.insert("involvements", {"law_id": r["法律ID"], "person_id": pid, "house": "参議院", "action": "oppose", "position": "other",
                                   "title_then": None, "acted_on": vote_day.get(r["投票ID"]) or None, "source_id": db.source(r["証拠URL"]),
                                   "counted": int(r["算入"] == "はい"), "excluded_reason": r["除外理由"] or None})
    sign = lambda r, side: r  # noqa: E731  額は正で持ち、向きは laws.side
    for m in members["members"]:
        for law in m["laws"]:
            if not law["fraction"]:
                continue
            role = "+".join(sorted(k for k, v in law["roles"].items() if v))
            s = sign(law["share"], law["side"])
            office = law.get("office") or {"low": 0, "median": 0, "high": 0}
            # 役職の帳簿がある行は、割合も提出者の分（roles.proposer）と残りの行動の分に分ける。
            office_fraction = law["roles"].get("proposer", 0) if any(office.values()) else 0
            # 反対票（direction: against）は役割 oppose。法律の額の配分（合計1）とは別に数え、向きは laws.side の逆。
            # 閣法の担当の大臣の分（office）は役割 office の別の行にする（点数に入れない役職の帳簿）。
            db.insert("allocations", {"method": method, "ledger": "確か", "law_id": law["lawId"], "recipient_kind": "person", "recipient_id": m["id"],
                                      "role": role, "fraction": law["fraction"] - office_fraction, "low": s["low"], "median": s["median"], "high": s["high"]})
            if any(office.values()):
                db.insert("allocations", {"method": method, "ledger": "確か", "law_id": law["lawId"], "recipient_kind": "person", "recipient_id": m["id"],
                                          "role": "office", "fraction": office_fraction, "low": office["low"], "median": office["median"], "high": office["high"]})
        db.insert("member_scores", {"method": method, "ledger": "確か", "person_id": m["id"], "rank": m["rank"],
                                    "net_low": m["net"]["low"], "net_median": m["net"]["median"], "net_high": m["net"]["high"],
                                    "loss_median": m["loss"]["median"], "credit_median": m["credit"]["median"],
                                    "chair_veto_rank": m["sensitivity"]["chairVetoRank"], "flagged": int(m["sensitivity"]["flagged"])})
    for law in members["laws"]:
        g = law["game"]
        for kind, rid, rng, frac in (("party", "衆議院の賛成会派", g["party"], g["vetoShare"]), ("unidentified", "名前不明の賛成票", g["unidentified"], None)):
            if rng["median"] == 0 and rng["low"] == 0 and rng["high"] == 0:
                continue
            total = law["amount"]["median"] / law["observationLaws"] if law["observationLaws"] else law["amount"]["median"]
            db.insert("allocations", {"method": method, "ledger": "確か", "law_id": law["id"], "recipient_kind": kind, "recipient_id": rid, "role": kind,
                                      "fraction": frac if frac is not None else (rng["median"] / total if total else 0.0),
                                      "low": round(rng["low"]), "median": round(rng["median"]), "high": round(rng["high"])})
    ref_method = "+".join(reference["rules"])
    ranked = sorted(reference["members"], key=lambda m: (m["net"]["median"], m["id"]))
    for i, m in enumerate(ranked, 1):
        db.insert("member_scores", {"method": ref_method, "ledger": "参考", "person_id": m["id"], "rank": i,
                                    "net_low": round(m["net"]["low"]), "net_median": round(m["net"]["median"]), "net_high": round(m["net"]["high"]),
                                    "loss_median": round(m["loss"]["median"]), "credit_median": round(m["credit"]["median"]), "chair_veto_rank": None, "flagged": None})


# ---- 団体の行動・判決・政策 ----

ORG_FILES = [
    # (ファイル, データセット名, 団体の列, 日付の列, 立場の列, 事項の列, 技術の列, 法令の列, 団体の種類)
    ("1_regulatory-requests/council-followup.csv", "規制改革のフォローアップ", "所管省庁", "年月日", "省庁の立場（反対・慎重・未措置）", "事項", "関連技術", "該当法令", "省庁"),
    ("1_regulatory-requests/hotline.csv", "規制改革ホットライン", "所管省庁", "受付日", "対応分類", "提案事項", "関連技術", "該当法令", "省庁"),
    ("1_regulatory-requests/hotline-h26-h27.csv", "規制改革ホットライン", "所管省庁", "受付日", "対応分類", "提案事項", "関連技術", "該当法令", "省庁"),
    ("1_regulatory-requests/hotline-h29-later.csv", "規制改革ホットライン", "所管省庁", "受付日", "対応分類", "提案事項", "関連技術", "該当法令", "省庁"),
    ("1_regulatory-requests/wg-hearings.csv", "規制改革のWG", "所管省庁", "開催日", "立場（反対・慎重）", "理由（要旨）", "関連技術", "該当法令", "省庁"),
    ("2_shingikai/data-semicon-mobility.csv", "審議会", "発言者の所属・肩書", "開催日", "立場", "要旨", "関連技術", "関連法令", "発言者の区分"),
    ("2_shingikai/finance-telecom-ai.csv", "審議会", "発言者の所属・肩書", "開催日", "立場", "要旨", "関連技術", "関連法令", "発言者の区分"),
    ("2_shingikai/medical.csv", "審議会", "発言者の所属・肩書", "開催日", "立場", "要旨", "関連技術", "関連法令", "発言者の区分"),
    ("2_shingikai/transport-tourism.csv", "審議会", "発言者の所属・肩書", "開催日", "立場", "要旨", "関連技術", "関連法令", "発言者の区分"),
    ("4_amakudari/reemployment.csv", "再就職の公表", "府省", "公表年度", "所管関係", "再就職先", "再就職先の業種", "", "省庁"),
    ("5_budget-review/review-findings.csv", "行政事業レビュー", "府省", "年度", "判定（廃止・抜本的改善など）", "事業名", "", "", "省庁"),
    ("6_local-ordinances/ordinances.csv", "条例", "自治体", "制定日", "", "条例名", "関連技術", "制限の内容（区域・期間など）", "自治体"),
]


def load_org_actions(db: Db) -> None:
    base = ACQ / "blocking-actors"
    for rel, dataset, org_col, date_col, stance_col, subject_col, tech_col, law_col, kind_col in ORG_FILES:
        for r in read_csv(base / rel):
            org = (r.get(org_col) or "").strip() or "（記載なし）"
            kind = r.get(kind_col, kind_col) if kind_col in r else kind_col
            db.ensure("organizations", "org_id", org, kind=kind or "その他")
            db.insert("org_actions", {"org_id": org, "dataset": dataset, "acted_on": wareki(r.get(date_col, "")) or (r.get(date_col) or None),
                                      "acted_on_text": r.get(date_col) or None,
                                      "stance": r.get(stance_col) or None, "subject": r.get(subject_col) or None, "technology": r.get(tech_col) or None,
                                      "law_text": r.get(law_col) or None, "source_id": db.source(r.get("出典URL")), "confidence": r.get("確度") or None})


def load_other_decisions(db: Db) -> None:
    for r in read_csv(ACQ / "court-rulings" / "rulings.csv"):
        db.insert("decisions", {"decision_id": f"判決-{r['id']}", "country": "JPN", "kind": "判決", "title": r["通称"], "decided_on": wareki(r["判決日"]),
                                "effective_on": None, "effective_origin": None, "fiscal_year": None, "decided_by": r["裁判所"],
                                "source_id": db.source(r["判例URL"]), "summary": f"{r['規制']}。{r['規制への判断']}：{r['判断の要旨']}"})
    catalog = read_json(DIST / "laws.json")
    for p in catalog.get("policies", []):
        db.insert("decisions", {"decision_id": f"国策-{p['id']}", "country": "JPN", "kind": "国策", "title": p["title"], "decided_on": f"{p['year']}-01-01" if p.get("year") else None,
                                "effective_on": None, "effective_origin": None, "fiscal_year": None, "decided_by": None, "source_id": None,
                                "summary": f"{p.get('summary', '')}（決定日は年だけ確か。月日は未取得）"})


# ---- 財政・為替介入・骨太の方針（scripts/fetch_fiscal.py） ----

FISCAL = ACQ / "fiscal"


def era_fy(year: int) -> str:
    """西暦の年度 → 「令和8年度」。"""
    for name, base in (("令和", 2018), ("平成", 1988), ("昭和", 1925)):
        if year > base:
            n = year - base
            return f"{name}{'元' if n == 1 else n}年度"
    return f"{year}年度"


def load_fiscal(db: Db) -> None:
    # 為替介入：実施日ごとに1つの決定。同じ日に売買通貨が2つあれば番号で分ける。
    seen: Counter[str] = Counter()
    for r in read_csv(FISCAL / "fx_interventions.csv"):
        seen[r["実施日"]] += 1
        did = f"為替-{r['実施日']}" + (f"-{seen[r['実施日']]}" if seen[r["実施日"]] > 1 else "")
        src = db.source(r["出典URL"])
        db.insert("decisions", {"decision_id": did, "country": "JPN", "kind": "為替", "title": f"為替介入（{r['売買通貨']}）", "decided_on": r["実施日"],
                                "effective_on": r["実施日"], "effective_origin": "台帳", "fiscal_year": None, "decided_by": "財務大臣（実務は日本銀行が代理）",
                                "source_id": src, "summary": f"外国為替平衡操作。{r['売買通貨']} {r['金額']}{r['単位']}"})
        db.insert("decision_amounts", {"decision_id": did, "item": r["売買通貨"], "amount": number(r["金額"]), "unit": r["単位"], "period": r["実施日"], "source_id": src})
    # 一般会計の予算：年度ごとに当初と補正（年度内の補正の合計）を1つずつの決定にし、主要経費別の額を財政の流れに入れる。
    flows = read_csv(FISCAL / "fiscal_flows.csv")
    budgets = {}
    for r in flows:
        if r["会計"] == "一般会計" and r["段階"] in ("当初", "補正"):
            budgets.setdefault((int(r["年度"]), r["段階"]), r["出典URL"])
    for (year, stage), url in sorted(budgets.items()):
        did = f"予算-{year}-{stage}"
        db.insert("decisions", {"decision_id": did, "country": "JPN", "kind": "予算", "title": f"{era_fy(year)} 一般会計{'当初' if stage == '当初' else '補正'}予算",
                                "decided_on": None, "effective_on": None, "effective_origin": None, "fiscal_year": year, "decided_by": "国会",
                                "source_id": db.source(url),
                                "summary": "主要経費別の額は fiscal_flows。成立日は未取得" + ("。補正は年度内のすべての補正予算の合計（純額）" if stage == "補正" else "")})
    for r in flows:
        amount = number(r["金額"])
        if amount is None:
            continue
        year, stage = int(r["年度"]), r["段階"]
        did = f"予算-{year}-{stage}" if r["会計"] == "一般会計" and (year, stage) in budgets else None
        src = db.source(r["出典URL"])
        db.insert("fiscal_flows", {"fiscal_year": year, "account": r["会計"], "stage": stage, "category": r["区分"], "item": r["項目"],
                                   "amount": amount, "unit": r["単位"], "decision_id": did, "source_id": src})
        if did and r["区分"] == "主要経費別（合計）" and r["項目"] == "合計":
            db.insert("decision_amounts", {"decision_id": did, "item": "一般会計歳出の合計（主要経費別）", "amount": amount, "unit": r["単位"],
                                           "period": era_fy(year), "source_id": src})
    for r in read_csv(FISCAL / "policies.csv"):
        db.insert("decisions", {"decision_id": f"国策-{r['id']}", "country": "JPN", "kind": "国策", "title": r["題名"], "decided_on": r["閣議決定日"] or None,
                                "effective_on": None, "effective_origin": None, "fiscal_year": None, "decided_by": "内閣（閣議決定）",
                                "source_id": db.source(r["出典URL"]), "summary": "閣議決定の日は PDF の1頁目から読んだ。数値目標は decision_targets（scripts/fetch_fiscal_more.py の2系統の照合を通ったもの）"})


# ---- 特別会計・国債・地方財政（2017年度以前）・国策の数値目標・デジタル庁の重点計画（scripts/fetch_fiscal_more.py） ----

FISCAL_MORE = ACQ / "fiscal-more"
JGB_STAGE = {"実績": "決算", "補正後": "補正", "当初": "当初"}
OKU = 1e8  # fetch_fiscal_more.py は億円。DB は load_fiscal と同じく円にそろえる


def load_monetary_decisions(db: Db) -> None:
    # 日銀の金融政策決定会合（scripts/fetch_monetary.py）。委員は声明の姓だけで people と結べないので、賛否は要旨に書き decision_votes には入れない。
    path = ACQ / "monetary-stats" / "mpm-decisions.csv"
    if not path.exists():
        return
    for r in read_csv(path):
        y, m, d = (int(x) for x in r["会合日"].split("-"))
        vote = r["賛否"] or "賛否の記載なし"
        summary = f"{r['決定の要旨']} 賛否：{vote}" + (f"（反対：{r['反対']}）" if r["反対"] else "") + "。委員ごとの賛否は monetary-stats/mpm-votes.csv"
        db.insert("decisions", {"decision_id": r["決定ID"], "country": "JPN", "kind": "金融政策", "title": f"日銀 金融政策決定会合（{y}年{m}月{d}日）：{r['題名']}",
                                "decided_on": r["会合日"], "effective_on": None, "effective_origin": None, "fiscal_year": None, "decided_by": "日本銀行政策委員会",
                                "source_id": db.source(r["出典URL"]), "summary": summary})


def load_fiscal_more(db: Db) -> None:
    """load_fiscal の後に、重ならないものだけ足す。特別会計は照合（主要経費の足し上げ＝表の合計）が「一致」の（会計・表・年度・段階）だけを入れ、
    不一致のある年度は年度ごと入れない。地方財政は load_fiscal に無い（年度・項目）だけ、国策は無い決定だけ足す。"""
    if not FISCAL_MORE.exists():
        return
    checks = read_csv(FISCAL_MORE / "checks.csv") if (FISCAL_MORE / "checks.csv").exists() else []
    accepted, failed_years, without_local = set(), set(), set()
    for c in checks:
        if c["照合"] != "予算：主要経費の足し上げ＝表の合計":
            continue
        m = re.match(r"^(\S+) (\d+)年度 (\S+)（第(\w+)表）$", c["対象"])
        if not m:
            continue
        if c["判定"] == "一致":
            accepted.add(c["対象"])
            if c.get("備考", "").startswith("表の合計は地方交付税交付金"):
                without_local.add(c["対象"])  # 平成24〜27年度の表の「合計」の定義
        elif c["判定"] == "不一致":
            failed_years.add((m.group(1), int(m.group(2))))  # 照合できない段階は、その段階だけ入れない
    ok = lambda account, year, stage, table: f"{account} {year}年度 {stage}（第{table}表）" in accepted and (account, year) not in failed_years
    made: set[str] = set()
    for r in read_csv(FISCAL_MORE / "special-budget.csv") if (FISCAL_MORE / "special-budget.csv").exists() else []:
        year = int(r["年度"])
        if not ok(r["会計"], year, r["段階"], r["表"]):
            db.counts["fiscal_more_rejected"] += 1
            continue
        did = f"予算-{r['会計']}-{year}-{r['段階']}"
        if did not in made:
            made.add(did)
            label = {"当初": "当初予算", "補正": "補正予算", "決算": "決算"}[r["段階"]]
            db.insert("decisions", {"decision_id": did, "country": "JPN", "kind": "予算", "title": f"{era_fy(year)} {r['会計']}{label}",
                                    "decided_on": None, "effective_on": None, "effective_origin": None, "fiscal_year": year, "decided_by": "国会",
                                    "source_id": db.source(r["出典URL"]),
                                    "summary": "主要経費別の額は fiscal_flows（財務省「財政統計」）。特別会計の額は純計ではない（一般会計と足さない）"
                                               + ("。補正は年度内のすべての補正予算の合計" if r["段階"] == "補正" else "")})
        inner = r["区分"] != "主要経費別"
        db.insert("fiscal_flows", {"fiscal_year": year, "account": r["会計"], "stage": r["段階"], "category": "主要経費別（内訳）" if inner else "主要経費別",
                                   "item": f"{r['主要経費']}／{r['項目']}" if inner else r["項目"], "amount": float(r["金額_億円"]) * OKU, "unit": "円",
                                   "decision_id": did, "source_id": db.source(r["出典URL"])})
    for t in read_csv(FISCAL_MORE / "special-budget-totals.csv") if (FISCAL_MORE / "special-budget-totals.csv").exists() else []:
        year = int(t["年度"])
        if ok("特別会計", year, t["段階"], t["表"]):
            db.insert("fiscal_flows", {"fiscal_year": year, "account": "特別会計", "stage": t["段階"], "category": "主要経費別（合計）",
                                       "item": "合計（地方交付税交付金・地方特例交付金・地方譲与税譲与金を除く）"
                                       if f"特別会計 {year}年度 {t['段階']}（第{t['表']}表）" in without_local else "合計",
                                       "amount": float(t["歳出_億円"]) * OKU, "unit": "円", "decision_id": f"予算-特別会計-{year}-{t['段階']}",
                                       "source_id": db.source(t["出典URL"])})
    for r in read_csv(FISCAL_MORE / "jgb.csv") if (FISCAL_MORE / "jgb.csv").exists() else []:
        # 国債の stage は数字の性格（決算＝実績、補正＝補正後の見込み、当初＝当初の見込み）。予算の「補正」（補正による増減）とは違う。
        # 国債費は当初予算の額なのでいつも当初。比率（%）は額と足さないよう区分を分ける。
        pct = r["項目"].endswith("_%")
        db.insert("fiscal_flows", {"fiscal_year": int(r["年度"]), "account": "国債（一般会計・特別会計）",
                                   "stage": "当初" if r["区分"] == "国債費" else JGB_STAGE.get(r["実績の別"], "決算"),
                                   "category": f"{r['区分']}の比率" if pct else r["区分"], "item": r["項目"].removesuffix("_%"),
                                   "amount": float(r["金額_億円"]) * (1 if pct else OKU), "unit": "%" if pct else "円", "decision_id": None,
                                   "source_id": db.source(r["出典URL"])})
    have = {(y, i) for y, i in db.con.execute("SELECT fiscal_year, item FROM fiscal_flows WHERE account = '地方（純計）'")}
    newest: dict[tuple, tuple[int, dict]] = {}
    for r in read_csv(FISCAL_MORE / "local-revenue.csv") if (FISCAL_MORE / "local-revenue.csv").exists() else []:
        e = r["白書の版"]
        order = 2018 + int(e[1:]) if e.startswith("r") else 1988 + int(e)
        key = (int(r["年度"]), r["項目"])
        if key not in newest or order > newest[key][0]:
            newest[key] = (order, r)
    for (year, item), (_, r) in sorted(newest.items()):
        if (year, item) in have:
            continue
        db.insert("fiscal_flows", {"fiscal_year": year, "account": "地方（純計）", "stage": "決算", "category": "地方財政（歳入）", "item": item,
                                   "amount": float(r["金額_億円"]) * OKU, "unit": "円", "decision_id": None, "source_id": db.source(r["出典URL"])})
    known = {d for (d,) in db.con.execute("SELECT decision_id FROM decisions WHERE kind = '国策'")}
    for r in read_csv(FISCAL_MORE / "policies.csv") if (FISCAL_MORE / "policies.csv").exists() else []:
        if r["決定ID"] in known:
            continue
        known.add(r["決定ID"])
        db.insert("decisions", {"decision_id": r["決定ID"], "country": "JPN", "kind": "国策", "title": r["題名"], "decided_on": r["決定日"],
                                "effective_on": None, "effective_origin": None, "fiscal_year": None, "decided_by": f"{r['決定の形式']}（{r['所管']}）",
                                "source_id": db.source(r["本文URL"] or r["掲載ページURL"]), "summary": None})
    for r in read_csv(FISCAL_MORE / "policy-targets.csv") if (FISCAL_MORE / "policy-targets.csv").exists() else []:
        if r["決定ID"] not in known:
            continue
        db.insert("decision_targets", {"decision_id": r["決定ID"], "indicator": r["指標"], "target_value": float(r["目標値"]), "unit": r["単位"],
                                       "target_year": int(r["目標年"]) if r["目標年"] else None,
                                       "target_year_kind": r.get("年の別") or None, "quote": r.get("原文") or None, "achieved_value": None, "achieved_year": None,
                                       "series_id": None, "achievement": None, "achievement_note": None, "source_id": db.source(r["本文URL"])})


# ---- 指標の系列 ----

DOMAINS = [("財政収支", "財政"), ("研究費", "研究"), ("CPI", "物価"), ("物価", "物価"), ("賃金", "賃金"), ("給与", "賃金"), ("雇用", "雇用"), ("就業", "雇用"), ("入職", "雇用"), ("離職", "雇用"), ("転職", "雇用"),
           ("勤続", "雇用"), ("貸出", "金融"), ("不良債権", "金融"), ("金利", "金融"), ("エネルギー", "エネルギー"), ("宿泊", "観光"), ("空港", "交通"), ("鉄道", "交通"),
           ("ブロードバンド", "通信"), ("オンライン", "行政"), ("GDP", "付加価値"), ("付加価値", "付加価値"),
           ("国内総生産", "付加価値"), ("訪日", "観光"), ("直接投資", "金融"), ("輸出額", "貿易"), ("温室効果ガス", "エネルギー"),
           ("医薬品", "医療"), ("特定健康診査", "医療"), ("特定保健指導", "医療"), ("5G", "通信"), ("スポーツ", "健康")]
PRICE = {"V": "名目", "L": "実質（前年価格）", "LR": "実質（連鎖）", "名目": "名目", "実質": "実質"}


def domain_of(label: str) -> str:
    for word, domain in DOMAINS:
        if word in label:
            return domain
    return "その他"


def period_kind(*texts: str) -> str:
    """暦年か年度か。前の引数ほど優先（区分の明示 → 備考 → 系列名）。「暦年・年度別…」のように両方を含むものは決め手にしない。"""
    for t in texts:
        t = t or ""
        cal, fy = "暦年" in t, "年度" in t
        if cal != fy:
            return "暦年" if cal else "年度"
    return "暦年"


def add_series(db: Db, seen: dict, *, sid: str, dataset: str, domain: str, country: str, label: str, breakdown: str, price: str, unit: str,
               base: str, kind: str, url: str, year, value, note: str = "") -> None:
    y, v = number(year), number(value)
    if y is None or v is None or y != int(y):
        db.counts["points_skipped"] += 1
        return
    if sid not in seen:
        seen[sid] = set()
        db.series_url[sid] = url
        db.insert("series", {"series_id": sid, "dataset": dataset, "domain": domain, "country": country, "label": label, "breakdown": breakdown,
                             "price_basis": price, "unit": unit, "base_year": base, "period_kind": kind, "source_url": url, "note": note})
    if int(y) in seen[sid]:
        # 取得元の表に同じ系列・同じ年が2回ある（SNA の「小計」、労働力調査の1973年の沖縄を含む・含まない）。先の行を使い、数を meta に残す。
        db.counts["points_duplicate"] += 1
        return
    seen[sid].add(int(y))
    # 年によって出典の資料が違う系列がある（不良債権比率は公表年ごとの xlsx）。系列の出典と違う年だけ点に出典を持たせる。
    db.insert("points", {"series_id": sid, "period": int(y), "value": v, "source_url": url if url != db.series_url[sid] else None})


def year_ranges(years: list[int]) -> str:
    """[2019, 2023, 2024, 2025] → 「2019・2023〜2025年」。"""
    ys, parts = sorted(set(years)), []
    start = prev = ys[0]
    for y in ys[1:] + [None]:
        if y is not None and y == prev + 1:
            prev = y
            continue
        parts.append(str(start) if start == prev else f"{start}〜{prev}")
        if y is not None:
            start = prev = y
    return "・".join(parts) + "年"


def load_series(db: Db) -> None:
    seen: dict[str, set] = {}
    for r in read_csv(ACQ / "oecd-industry" / "industry_va.csv"):
        add_series(db, seen, sid=f"oecd-t6:{r['国']}:{r['産業']}:{r['価格']}", dataset="oecd-industry/industry_va.csv", domain="付加価値", country=r["国"],
                   label=r["指標"], breakdown=r["産業"], price=PRICE.get(r["価格"], r["価格"]), unit=r["単位"], base=r["基準年"], kind="暦年",
                   url=r["出典URL"], year=r["年"], value=r["値"])
    for name in ("intl-stats/intl-stats.csv", "r3-series/r3-series.csv"):
        for r in read_csv(ACQ / name):
            add_series(db, seen, sid=f"{name.split('/')[0]}:{r['国']}:{r['指標']}", dataset=name, domain=domain_of(r["指標"]), country=r["国"], label=r["指標"],
                       breakdown="", price="指数" if r["単位"] == "指数" else "", unit=r["単位"], base=r.get("基準年", ""), kind="暦年", url=r["出典URL"],
                       year=r["年"], value=r["値"])
    for path in sorted((ACQ / "domestic-stats").glob("cpi_items_annual_*.csv")):
        for r in read_csv(path):
            add_series(db, seen, sid=f"cpi:{r['基準年']}:{r['品目符号']}", dataset=f"domestic-stats/{path.name}", domain="物価", country="JPN", label=f"消費者物価指数 {r['品目']}",
                       breakdown=r["品目"], price="指数", unit="指数", base=r["基準年"], kind="暦年", url=r["出典URL"], year=r["年"], value=r["値"])
    for path in sorted((ACQ / "domestic-stats").glob("sna_gdp_by_industry_*.csv")):
        for r in read_csv(path):
            add_series(db, seen, sid=f"sna:{r['基準年']}:{r['価格']}:{r['経済活動']}", dataset=f"domestic-stats/{path.name}", domain="付加価値", country="JPN",
                       label=f"国内総生産（経済活動別） {r['経済活動']}", breakdown=r["経済活動"], price=r["価格"], unit=r["単位"], base=r["基準年"], kind="暦年",
                       url=r["出典URL"], year=r["年"], value=r["値"])
    for path in sorted((ACQ / "domestic-stats").glob("lfs_employed_by_industry_*.csv")):
        for r in read_csv(path):
            add_series(db, seen, sid=f"lfs:{r['産業分類']}:{r['産業']}", dataset=f"domestic-stats/{path.name}", domain="雇用", country="JPN", label=f"就業者数 {r['産業']}",
                       breakdown=r["産業"], price="人数", unit=r["単位"], base=r["産業分類"], kind="暦年", url=r["出典URL"], year=r["年"], value=r["値"])
    for r in read_csv(ACQ / "domestic-stats" / "kanko_lodging_annual.csv"):
        add_series(db, seen, sid=f"kanko:{r['指標']}", dataset="domestic-stats/kanko_lodging_annual.csv", domain="観光", country="JPN", label=r["指標"], breakdown="",
                   price="件数", unit=r["単位"], base="", kind="暦年", url=r["出典URL"], year=r["年"], value=r["値"])
    for path in sorted((ACQ / "more-stats").glob("*.csv")):
        if path.name == "manifest.csv":
            continue
        for r in read_csv(path):
            wb = path.name.startswith("worldbank")
            add_series(db, seen, sid=f"more:{path.stem}:{r['系列']}:{r['区分']}:{r['単位']}", dataset=f"more-stats/{path.name}", domain=domain_of(r["系列"]),
                       country=r["区分"] if wb else "JPN", label=r["系列"], breakdown="" if wb else r["区分"], price="", unit=r["単位"], base="",
                       kind=period_kind(r["区分"], r.get("備考", ""), r["系列"]), url=r["出典URL"], year=r["年"], value=r["値"], note=r.get("備考", ""))
    for path in sorted((ACQ / "gap-stats").glob("*.csv")):
        if path.name in ("manifest.csv", "status.csv"):
            continue
        for r in read_csv(path):
            add_series(db, seen, sid=f"gap:{path.stem}:{r['系列']}:{r['国']}:{r['区分']}:{r['単位']}", dataset=f"gap-stats/{path.name}", domain=domain_of(r["系列"]),
                       country=r["国"], label=r["系列"], breakdown=r["区分"], price="", unit=r["単位"], base="",
                       kind=period_kind(r["区分"], r.get("備考", ""), r["系列"]), url=r["出典URL"], year=r["年"], value=r["値"], note=r.get("備考", ""))
    # 金融政策と海外比較（scripts/fetch_monetary.py：日本銀行・BIS・IMF・FRED）。領域は取り込み側で決めてある
    for path in sorted((ACQ / "monetary-stats").glob("*.csv")):
        if path.name in ("manifest.csv", "checks.csv") or path.name.startswith("mpm-"):
            continue
        for r in read_csv(path):
            add_series(db, seen, sid=f"monetary:{path.stem}:{r['系列']}:{r['国']}:{r['区分']}", dataset=f"monetary-stats/{path.name}", domain=r["領域"],
                       country=r["国"], label=r["系列"], breakdown=r["区分"], price="", unit=r["単位"], base="", kind="暦年", url=r["出典URL"],
                       year=r["年"], value=r["値"], note=r["備考"])
    for path in sorted(TARGET_SERIES.glob("*.csv")):
        if path.name in ("manifest.csv", "target-links.csv"):
            continue
        rows = read_csv(path)
        # 注記が年で違う系列（試算値の年・定義の変わった年）は、どの年の注記かを付けて全部を系列の注記に残す
        notes: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
        for r in rows:
            if number(r["年"]) is not None:
                notes[r["系列ID"]][r["備考"]].append(int(number(r["年"])))
        for r in rows:
            by_note = notes[r["系列ID"]]
            note = r["備考"] if len(by_note) == 1 else " / ".join(f"{year_ranges(ys)}：{n}" for n, ys in sorted(by_note.items(), key=lambda kv: min(kv[1])))
            add_series(db, seen, sid=r["系列ID"], dataset=f"target-series/{path.name}", domain=domain_of(r["系列"]), country="JPN", label=r["系列"],
                       breakdown="", price="", unit=r["単位"], base="", kind=r["年の別"], url=r["出典URL"], year=r["年"], value=r["値"], note=note)
    world = read_json(DIST / "world-gdp.json")
    # 取得元・推計の注意（台湾の IMF の値は最新年が推計を含む など）を系列の注記に残す。
    world_note = " ".join(world.get("notes", []))
    for c in world["countries"]:
        for key, points in c["series"].items():
            for year, value in points:
                add_series(db, seen, sid=f"world-gdp:{c['code']}:{key}", dataset="app/public/distribution/world-gdp.json", domain="世界", country=c["code"],
                           label=f"GDP（{key}）", breakdown="", price=WORLD_GDP_KIND[key][0], unit=WORLD_GDP_KIND[key][1],
                           base="", kind="暦年", url=c["sourceUrls"][key], year=year, value=value,
                           note=f"取得元：{c['provider']}。{world_note}")


# ---- 国策の数値目標の達成状況（scripts/fetch_target_series.py。系列は load_series で入れたあと） ----

TARGET_SERIES = ACQ / "target-series"


def load_target_progress(db: Db) -> None:
    path = TARGET_SERIES / "target-links.csv"
    if not path.exists():
        return
    known = {s for (s,) in db.con.execute("SELECT series_id FROM series")}
    missed = []
    for r in read_csv(path):
        sid = r["系列ID"] if r["系列ID"] in known else None
        linked = sid is not None
        done = db.con.execute(
            """UPDATE decision_targets SET achieved_value = ?, achieved_year = ?, series_id = ?, achievement = ?, achievement_note = ?
               WHERE decision_id = ? AND indicator = ? AND target_value = ? AND unit = ? AND target_year IS ?""",
            (float(r["達成の値"]) if linked and r["達成の値"] else None, int(r["達成の年"]) if linked and r["達成の年"] else None, sid,
             r["判定"] if linked or r["判定"] == "結ばない" else "値なし", r["理由"] if linked or r["判定"] == "結ばない" else f"{r['理由']}（系列が DB に無い）",
             r["決定ID"], r["指標"], float(r["目標値"]), r["単位"], int(r["目標年"]) if r["目標年"] else None))
        if done.rowcount == 0:
            missed.append(f"{r['決定ID']} {r['指標']}")
    if missed:
        # policy-targets.csv と target-links.csv がずれた（数値目標を取り直したのに結び付けを作り直していない）
        raise ValueError(f"達成状況の行が数値目標に当たらない（fetch_target_series.py link を回し直す）: {missed[:5]}")


# world-gdp.json の系列キー → （価格の基準, 単位）。app/src/world-gdp.ts の表示（formatRate・formatPpp）と同じ。
WORLD_GDP_KIND = {
    "nominalUsd": ("名目（米ドル）", "米ドル"),
    "realGrowth": ("実質の伸び率", "％"),
    "perCapitaPpp": ("1人当たり・購買力平価（実質）", "国際ドル"),
}


def load_registry(db: Db) -> None:
    for r in read_csv(REGISTRY):
        db.insert("source_registry", {k: r[k] for k in ("name", "category", "host", "url", "target_table", "status", "checked_on", "note")})


def inputs_digest(files: set[Path] | None = None) -> str:
    """入力ファイルと仕様の正本の SHA-256。既定は実際に読んだ全ファイル（READ_FILES）と表の定義。"""
    h = hashlib.sha256()
    for f in sorted((READ_FILES | {SCHEMA} if files is None else files) | {SPEC}):
        h.update(str(f.relative_to(ROOT)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


# グラフ（charts.json）が使う入力。指標の CSV だけが変わったときに、ほかの作業の charts.json を古くしない。
CHART_INPUTS = {DIST / "ranking.json", DIST / "members.json", DIST / "members-reference.json", DIST / "laws.json",
                ACQ / "bill-census-full" / "enacted.csv", ACQ / "enforcement-dates" / "enforcement.csv",
                DERIVED / "allocation-v1" / "involvements.csv", DERIVED / "allocation-v1" / "votes.csv"}


# ---- グラフ用の集計（公開サイトの /numbers） ----

def charts(con: sqlite3.Connection, spec_version: str) -> dict:
    q = lambda sql, *a: con.execute(sql, a).fetchall()  # noqa: E731
    # 額の分布：桁（10^k 円）ごとの本数。同じ観測を共有する法律は観測1つとして数える（代表の行）。
    dist = defaultdict(lambda: {"loss": 0, "benefit": 0})
    for median, side in q("SELECT o.median, l.side FROM observations o JOIN laws l ON l.observation_id = o.observation_id GROUP BY o.observation_id"):
        if median and median > 0:
            dist[len(str(int(median))) - 1][side] += 1
    histogram = [{"exp": k, **dist[k]} for k in range(min(dist), max(dist) + 1)] if dist else []
    by_certainty = [{"certainty": c, "loss": lo, "benefit": be, "laws": n} for c, lo, be, n in q(
        "SELECT certainty, SUM(side='loss'), SUM(side='benefit'), COUNT(*) FROM laws WHERE outcome='額' GROUP BY certainty ORDER BY CASE certainty WHEN '高' THEN 1 WHEN '中' THEN 2 WHEN '低' THEN 3 ELSE 4 END")]
    # 時系列：施行年ごとの本数と、確かな額（高・中・低）の観測の合計。観測を共有する法律は本数で割った分を足す。
    years = defaultdict(lambda: {"laws": 0, "confirmedLoss": 0, "confirmedBenefit": 0, "referenceLoss": 0, "referenceBenefit": 0})
    for year, side, certainty, median, n in q(
            "SELECT CAST(substr(l.enforced_on,1,4) AS INTEGER), l.side, l.certainty, l.median, o.n_laws FROM laws l JOIN observations o ON o.observation_id = l.observation_id WHERE l.outcome='額' AND l.enforced_on IS NOT NULL"):
        y = years[year]
        y["laws"] += 1
        key = ("confirmed" if certainty != "参考" else "reference") + ("Loss" if side == "loss" else "Benefit")
        y[key] += median // n
    timeline = [{"year": y, **years[y]} for y in sorted(years)]
    members = [{"id": pid, "name": name, "rank": rank, "net": net, "low": lo, "high": hi, "loss": loss, "credit": credit} for pid, name, rank, net, lo, hi, loss, credit in q(
        "SELECT s.person_id, p.name, s.rank, s.net_median, s.net_low, s.net_high, s.loss_median, s.credit_median FROM member_scores s JOIN people p USING (person_id) WHERE s.ledger='確か' ORDER BY s.rank")]
    # 法律の額の配り先（合計＝法律の額）。反対票（oppose）は額の配分とは別に数えるので入れない（設計決定0014）。
    roles = [{"role": role, "kind": kind, "loss": loss or 0, "benefit": benefit or 0} for role, kind, loss, benefit in q(
        "SELECT a.role, a.recipient_kind, SUM(CASE WHEN l.side='loss' THEN a.median END), SUM(CASE WHEN l.side='benefit' THEN a.median END) FROM allocations a JOIN laws l USING (law_id) WHERE a.ledger='確か' AND a.role != 'oppose' GROUP BY a.role, a.recipient_kind ORDER BY a.recipient_kind, a.role")]
    parties = [{"party": party, "laws": n, "loss": loss or 0, "benefit": benefit or 0} for party, n, loss, benefit in q(
        """SELECT s.party_id, COUNT(*), SUM(CASE WHEN l.side='loss' THEN l.median / o.n_laws END), SUM(CASE WHEN l.side='benefit' THEN l.median / o.n_laws END)
           FROM law_party_stances s JOIN laws l USING (law_id) JOIN observations o ON o.observation_id = l.observation_id
           WHERE s.stance='賛成' AND l.certainty IN ('高','中','低') GROUP BY s.party_id ORDER BY COUNT(*) DESC, s.party_id""")]
    return {"schema": "public-charts/v1", "spec": spec_version, "histogram": histogram, "byCertainty": by_certainty, "timeline": timeline,
            "members": members, "roles": roles, "parties": parties}


def build(out: Path, write_charts: bool) -> dict:
    READ_FILES.clear()
    db = Db(out)
    spec_version = load_spec(db)
    load_registry(db)
    load_laws(db)
    load_people_and_allocations(db)
    load_org_actions(db)
    load_other_decisions(db)
    load_fiscal(db)
    load_fiscal_more(db)
    load_monetary_decisions(db)
    load_series(db)
    load_target_progress(db)
    digest = inputs_digest()
    for key, value in (("schema", DB_SCHEMA), ("spec", spec_version), ("inputs_sha256", digest),
                       ("points_duplicate", str(db.counts["points_duplicate"])), ("points_skipped", str(db.counts["points_skipped"]))):
        db.insert("meta", {"key": key, "value": value})
    db.con.commit()
    problems = db.con.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise ValueError(f"外部キーの食い違い: {problems[:5]}")
    summary = {"spec": spec_version, **{k: v for k, v in sorted(db.counts.items())}}
    if write_charts:
        payload = charts(db.con, spec_version)
        payload["inputs"] = inputs_digest(CHART_INPUTS)
        CHARTS.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    db.con.close()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--no-charts", action="store_true", help="charts.json を書かない")
    args = parser.parse_args()
    print(json.dumps(build(args.out, not args.no_charts), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
