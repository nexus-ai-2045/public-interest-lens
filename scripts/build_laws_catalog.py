"""全法律の一覧 `app/public/distribution/laws.json` を作る（表示用）。

成立した全法律（bill-census-full/enacted.csv）を1本ずつ並べる。額・確かさ・印・額が出ない理由は
公開ランキング（ranking.json、public-ranking/v2）をそのまま使い、計算の流れは全法律の台帳
（all-laws-v1/outcomes.csv）から付ける。関わった議員は members.json、政策は case.json から。

入力はリポジトリ内の派生データと公開済みの配布データだけ。中身は変えず、読み替えて並べるだけ。
"""

from __future__ import annotations

import csv
from collections import Counter
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived"
ACQUIRED = ROOT / "data" / "acquired"
DIST = ROOT / "app" / "public" / "distribution"
OUTPUT = DIST / "laws.json"
DETAIL_DIR = DIST / "laws-detail"
# 議員ページなど laws.json を読まない画面のための、法律の「何をする」の一文だけの表（id → 一文、無いものは理由の印）。
NAMES_OUTPUT = DIST / "law-names.json"
# 一覧の1行に要る項目。残り（因果の鎖・一次資料・関わった議員など）は開いた時に laws-detail/<束>.json から読む。
INDEX_KEYS = ("id", "kind", "title", "year", "field", "side", "amount", "certainty", "marks", "step", "what", "whatWithheld", "summary", "membersTotal", "href", "observation", "scale")

INPUTS = {
    "enacted": ACQUIRED / "bill-census-full" / "enacted.csv",
    "outcomes": DERIVED / "all-laws-v1" / "outcomes.csv",
    "fieldEstimate": DERIVED / "field-expansion-estimate" / "estimate.csv",
    "ranking": DIST / "ranking.json",
    "members": DIST / "members.json",
    "case": DIST / "case.json",
    "speeches": ACQUIRED / "bill-speeches" / "speeches.csv",
    "overviews": DERIVED / "law-overviews-v1" / "overviews.csv",
    # まとめて説明された法案の、その法案の部分（どの発言を「区別できない」とするかが変わるので、入力として記録する）
    "segments": ACQUIRED / "bill-speeches" / "segments.csv",
    "industryVa": ACQUIRED / "oecd-industry" / "industry_va.csv",
}
# 無くても一覧は作れる入力（概要の原料と、その AI 要約、桁外れの印に使う日本の付加価値）
OPTIONAL = {"speeches", "overviews", "segments", "industryVa"}
# 額が日本の全産業の付加価値1年分を超えるときの印（額は変えず、順位からも外さない。印と倍率だけ付ける）
OUTLIER_MARK = "額が日本の付加価値1年分を超える（桁外れ。参考にとどめる）"
# OECD 表6の単位 → 円
VA_UNIT = {"百万JPY": 1_000_000}
ERAS = {"昭和": 1925, "平成": 1988, "令和": 2018}
ERA_DATE = re.compile(r"(昭和|平成|令和)\s*(元|\d+)年\s*(\d+)月\s*(\d+)日")
CERTAINTY = {
    "高": "確かさ：高（段階3）",
    "中": "確かさ：中（段階2）",
    "低": "確かさ：低（段階1。経済全体では未確認）",
    "参考": "参考の額",
}
# 額が出ない法律の結果 → どこまで進んだか
OUTCOME_STEP = {"評価対象外": "enacted", "保留（振り分け）": "enacted", "施行日が未確定": "evaluated", "保留（影響の判定）": "dated", "未測定（系列・比較群が足りない）": "staged"}
# 確かさ高・中の法律で、関わった議員の記録（提出・参議院の賛否）がまだそろわず議員ページに入っていないものの印。
MEMBERS_PENDING = "関わった議員の記録を集めている途中（議員ランキングにはまだ入っていない）"
STEPS = ["enacted", "evaluated", "dated", "staged", "amounted", "published"]


def _rows(name: str) -> list[dict[str, str]]:
    if name in OPTIONAL and not INPUTS[name].exists():
        return []
    with INPUTS[name].open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _json(name: str) -> dict:
    return json.loads(INPUTS[name].read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def era_date(text: str) -> str | None:
    match = ERA_DATE.search(text or "")
    if not match:
        return None
    era, year, month, day = match.groups()
    return f"{ERAS[era] + (1 if year == '元' else int(year)):04d}-{int(month):02d}-{int(day):02d}"


def first_clause(text: str, limit: int = 90) -> str:
    """理由の最初の一節だけを一言にする（全文は detail に残す）。"""
    head = re.split(r"[／。]", text or "", maxsplit=1)[0].strip()
    return head if len(head) <= limit else head[: limit - 1] + "…"


def member_links(members: dict) -> dict[str, list[dict]]:
    by_law: dict[str, list[dict]] = defaultdict(list)
    for member in members["members"]:
        for entry in member["laws"]:
            by_law[entry["lawId"]].append({
                "id": member["id"],
                "name": member["name"],
                "median": entry["share"]["median"],
                "roles": sorted(entry.get("roles", {})),
            })
    for law_id, items in by_law.items():
        items.sort(key=lambda item: -abs(item["median"]))
    return by_law



def source_links(urls: list[str]) -> list[dict[str, str]]:
    def label(url: str) -> str:
        if "laws.e-gov.go.jp" in url:
            return "e-Gov 法令（条文）"
        if "itdb_housei.nsf" in url:
            return "衆議院 制定法律"
        if "kokkai.ndl.go.jp" in url:
            return "国会会議録"
        if "sangiin.go.jp" in url:
            return "参議院の資料"
        return "国会の議案情報（審議の経過）"
    return [{"label": label(url), "url": url} for url in urls]


def outcome_chain(row: dict[str, str] | None) -> list[dict[str, str]]:
    if not row:
        return []
    chain = [{"step": "振り分け", "result": f"{row['種類'] or '—'}・{row['分野'] or '分野なし'}", "note": f"経路：{row['経路']}" + (f"／指標：{row['指標']}" if row["指標"] else "")}]
    if row["施行日"]:
        chain.append({"step": "施行日", "result": row["施行日"], "note": ""})
    if row["段階"]:
        chain.append({"step": "影響の段階", "result": f"{row['段階']}・{row['向き']}".rstrip("・"), "note": row["指標の系列"]})
    chain.append({"step": "台帳の結果", "result": row["結果"] + (f"（確かさ：{row['確かさ']}）" if row["確かさ"] else ""), "note": row["理由"]})
    if row["損失または便益の額"]:
        chain.append({"step": "額の計算", "result": row["単位"], "note": row["損失または便益の額"]})
    return chain


def passage(census: dict[str, str]) -> str:
    """誰が出して、衆参でどう決まったか（衆議院の議案情報の事実だけ）。"""
    proposer = re.sub(r"君外", "ほか", census["提出者"].strip().replace(" ", "")).removesuffix("君")
    if census["種別"] == "閣法":
        who = "内閣が提出"
    else:
        who = f"{proposer or '議員'}が提出（{'衆議院' if census['種別'] == '衆法' else '参議院'}の議員立法）"
    steps = []
    for house in ("衆", "参"):
        result, day = census.get(f"議決結果_{house}", "").strip(), era_date(census.get(f"議決日_{house}", ""))
        if result:
            verb = "修正して可決" if result == "修正" else result
            steps.append((day or "9999", f"{house}院で{verb}" + (f"（{day}）" if day else "")))
    promulgated = era_date(census["公布日"])
    if promulgated:
        steps.append((promulgated, f"{promulgated}に公布"))
    flow = "→".join(text for _, text in sorted(steps))
    return f"{who}。{flow}" if flow else who


def parties(census: dict[str, str]) -> dict[str, list[str]] | None:
    yes = [name.strip() for name in census.get("賛成会派_衆", "").split(";") if name.strip()]
    no = [name.strip() for name in census.get("反対会派_衆", "").split(";") if name.strip()]
    return {"yes": yes, "no": no} if yes or no else None


def overview(census: dict[str, str], speech: dict[str, str] | None, written: dict[str, str] | None, result: str, ambiguous: frozenset[str] = frozenset()) -> dict:
    """冒頭の概要。事実（議案情報）・AI 要約（会議録の発言から）・機械計算（このサイトの額）を分けて持つ。"""
    view: dict = {"passage": passage(census), "result": result}
    if party := parties(census):
        view["parties"] = party
    # 概要の台帳にまだ行が無い（発言を取った後、要約と照合がまだ）法律は、見つかった発言を確かめていない
    unverified = written is None
    written = written or {}
    speech = speech or {}
    for key, column, source in (("what", "何をする", "説明のURL"), ("aim", "狙い", "説明のURL"), ("concern", "反対側の心配", "反対のURL")):
        if not speech.get(source):
            continue
        quote = {"text": written.get(column, ""), "url": speech[source], "speaker": speech[source.replace("URL", "発言者")], "date": speech[source.replace("URL", "日付")]}
        if not quote["text"]:
            # 要約しなかった理由：ほかの法案と同じ発言でどの法案の話か決められない（shared）か、
            # 見つかった発言が予算・動議・別の法案などについてのもの（other）か、抜粋から中身を読み取れなかった（unread）か
            kind = "説明" if source == "説明のURL" else "反対"
            if unverified:
                quote = {"text": "", "withheld": "unchecked"}
            elif kind in written.get("別の議題の発言", "").split("・"):
                # この法律の発言ではないので、URL を出典として出さない
                quote = {"text": "", "withheld": "other"}
            elif kind in written.get("確かめていない発言", "").split("・"):
                # 見つかった発言がこの法律の説明・反対討論か、別の読み手がまだ確かめていない
                quote = {"text": "", "withheld": "unchecked"}
            else:
                quote["withheld"] = "shared" if source in ambiguous else "unread"
        # 発言は見つかったが、どの法案の話か決められず要約しなかったもの。「見つからない」とは言わずに、発言だけ示す
        if quote["text"] or key != "aim":
            view[key] = quote
    return view


def japan_value_added() -> dict[int, float]:
    """日本の全産業（_T）の名目付加価値（円）。年 → 円。価格列が名目（V）の行だけ。"""
    result: dict[int, float] = {}
    for row in _rows("industryVa"):
        if row["国"] == "JPN" and row["産業"] == "_T" and row["価格"] == "V" and row["単位"] in VA_UNIT:
            result[int(row["年"])] = float(row["値"]) * VA_UNIT[row["単位"]]
    return result


def start_year(window: str) -> int | None:
    match = re.match(r"\s*(\d{4})\s*〜", window or "")
    return int(match.group(1)) if match else None


# 代表を選ぶ順（確かな額が参考の額の陰に隠れないように）。
CERTAINTY_ORDER = {"高": 0, "中": 1, "低": 2, "参考": 3}


def mark_observations(items: list[dict]) -> int:
    """同じ観測（group＋window）を共有する法律をまとめ、確かさの高い順・id 昇順の先頭を代表にする。観測の数を返す。"""
    members: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        if item.get("amount") and item.get("group") and item.get("window"):
            members[f"{item['group']}／{item['window']}"].append(item)
    for key, group in members.items():
        group.sort(key=lambda item: (CERTAINTY_ORDER.get(item.get("certainty") or "", len(CERTAINTY_ORDER)), item["id"]))
        for item in group:
            item["observation"] = {"key": key, "size": len(group), "representative": item is group[0]}
            if item is not group[0]:
                item["observation"]["representativeId"] = group[0]["id"]
    return len(members)


def mark_outliers(items: list[dict], value_added: dict[int, float]) -> int:
    """額（中央値）が窓の開始前最後の年の日本の付加価値1年分を超える法律に印と倍率を付ける。年が無ければ付けない。"""
    count = 0
    for item in items:
        year = start_year(item.get("window", ""))
        base = value_added.get(year - 1) if year and item.get("amount") else None
        if base and abs(item["amount"]["median"]) > base:
            item["marks"].append(OUTLIER_MARK)
            item["scale"] = round(abs(item["amount"]["median"]) / base, 2)
            count += 1
    return count


def build() -> dict:
    outcomes = {row["id"]: row for row in _rows("outcomes")}
    estimate = {row["id"]: row for row in _rows("fieldEstimate")}
    ranking = _json("ranking")
    amounted = {law["id"]: law for law in ranking["laws"]}
    others = {item["id"]: item for item in ranking["others"]}
    members = _json("members")
    linked = member_links(members)
    member_law = {law["id"]: law for law in members["laws"]}
    speeches = {row["id"]: row for path in sorted(INPUTS["speeches"].parent.glob("speeches*.csv")) for row in csv.DictReader(path.open(encoding="utf-8"))}
    written = {row["id"]: row for row in _rows("overviews")}
    # 1つの発言を2本以上の法案が材料にしていて、この法案の部分を切り出せなかったもの（どの法案の話か決められない）
    uses = Counter(row[source] for row in speeches.values() for source in ("説明のURL", "反対のURL") if row[source])
    segments = INPUTS["segments"]
    # 切り出しは、いまの発言 URL から切り出したものだけ数える（発言を取り直して URL が変わったら、古い切り出しは使わない）
    split = {(row["id"], row["区分"], row["URL"]) for row in csv.DictReader(segments.open(encoding="utf-8"))} if segments.exists() else set()
    def ambiguous(law_id: str) -> frozenset[str]:
        row = speeches.get(law_id, {})
        return frozenset(source for source, kind in (("説明のURL", "説明"), ("反対のURL", "反対"))
                         if row.get(source) and uses[row[source]] > 1 and (law_id, kind, row[source]) not in split)

    items = []
    for census in _rows("enacted"):
        law_id = f"{census['種別']}-{census['提出回次']}-{census['番号']}"
        out, est, law, other = outcomes.get(law_id), estimate.get(law_id), amounted.get(law_id), others.get(law_id)
        promulgated = era_date(census["公布日"])
        field = (law or {}).get("field") or (out or {}).get("分野") or (est or {}).get("新分野", "")
        field = field.replace("（既存の規則で）", "").strip()
        item: dict = {
            "id": law_id,
            "kind": census["種別"],
            "title": census["題名"],
            "session": int(census["回次"]),
            "year": int(promulgated[:4]) if promulgated else None,
            "promulgatedOn": promulgated,
            "amend": census["新規か改正か"] == "改正",
            "proposer": census["提出者"].strip(),
            "field": field if field and field != "対応表なし" else "その他",
            "side": None,
            "amount": None,
            "marks": [],
            "step": "enacted",
            "summary": "",
            "chain": outcome_chain(out),
            "sources": [],
            "members": linked.get(law_id, [])[:12],
            "membersTotal": len(linked.get(law_id, [])),
        }
        if census.get("経過URL", "").startswith("https://"):
            item["sources"].append({"label": "国会の議案情報（審議の経過）", "url": census["経過URL"]})
        if law:
            item.update({
                "side": law["side"],
                "amount": {"median": law["amountMedianYen"], "low": law["amountLowYen"], "high": law["amountHighYen"]},
                "certainty": law["certainty"],
                "marks": [CERTAINTY[law["certainty"]]] + (["下限（未測定の便益を0として数えた）"] if law["lowerBound"] else []) + law["notes"],
                "step": "amounted" if law["certainty"] == "参考" else "published",
                "indicator": law["indicator"],
                "stage": law["stage"],
                "enforcedOn": law["enforcedOn"],
                "window": law["window"],
                "comparison": law["comparisonCountries"],
                "group": law["group"],
                "benefitStatus": law["benefitStatus"],
            })
            if law["amountLowYen"] < 0 < law["amountHighYen"]:
                item["marks"].append("向きが定まらない（幅が0をまたぐ）")
            item["summary"] = ("損失" if law["side"] == "loss" else "便益") + f"の推計（{law['window']}・{law['indicator']}）"
            known = {source["url"] for source in item["sources"]}
            item["sources"] += [link for link in source_links(law["sources"]) if link["url"] not in known]
            if law_id in member_law and member_law[law_id].get("attributed"):
                item["attributed"] = member_law[law_id]["attributed"]
            if law["certainty"] in ("高", "中") and law_id not in member_law:
                item["marks"].append(MEMBERS_PENDING)
        elif other:
            item["step"] = OUTCOME_STEP.get(other["outcome"], "enacted")
            item["summary"] = f"{other['outcome']}：{first_clause(other['reason'], 70)}"
            item["chain"].append({"step": "公開の結果", "result": other["outcome"], "note": other["reason"]})
        else:
            item["summary"] = "公開ランキングに結果がまだない"
        if out and out["指標"] and "indicator" not in item:
            item["indicator"] = out["指標"]
        if not item["sources"]:
            item["sources"].append({"label": "衆議院 成立した法律の一覧", "url": census["出典URL"]})
        if law:
            result = ("損失" if law["side"] == "loss" else "便益") + f"の推計 {yen(law['amountMedianYen'])}（幅 {yen(law['amountLowYen'])}〜{yen(law['amountHighYen'])}、{CERTAINTY[law['certainty']]}）"
        else:
            result = item["summary"]
        item["overview"] = overview(census, speeches.get(law_id), written.get(law_id), result, ambiguous(law_id))
        if item["overview"].get("what", {}).get("text"):
            item["what"] = item["overview"]["what"]["text"]
        else:
            # 一文が無い理由（画面は題名から作らず、正式名だけを理由つきで出す）。none＝提案理由の説明が見つからなかった。
            item["whatWithheld"] = item["overview"].get("what", {}).get("withheld", "none")
        for key, label in (("what", "国会会議録（提案理由の説明）"), ("concern", "国会会議録（反対討論）")):
            if item["overview"].get(key, {}).get("url") and item["overview"][key]["url"] not in {source["url"] for source in item["sources"]}:
                item["sources"].append({"label": label, "url": item["overview"][key]["url"]})
        items.append(item)

    observations = mark_observations(items)
    outliers = mark_outliers(items, japan_value_added())
    policies = [policy_from_case(_json("case"))]
    counts = {step: sum(1 for item in items if STEPS.index(item["step"]) >= STEPS.index(step)) for step in STEPS}
    return {
        "schema": "public-laws/v1",
        "inputs": {name: _digest(path) for name, path in INPUTS.items()},
        "counts": counts,
        # 公開ランキングの段階ごとの本数（全体指標の参考の額は段階を通っていないので含まない）。/ranking の注記に出す。
        "strict": {key: ranking["counts"][key] for key in ("evaluated", "dated", "staged")},
        # 同じ観測（group＋window）の数と、桁外れの印の本数。一覧は観測ごとに代表1本を並べる。
        "observations": {"count": observations, "outliers": outliers},
        "fields": sorted({item["field"] for item in items}),
        "laws": items,
        "policies": policies,
    }


def yen(value: float) -> str:
    """画面の formatYen と同じ丸め（兆円は小数1桁、億円は整数）。"""
    if value < 0:
        return "−" + yen(-value)
    if value >= 1e12:
        return f"{value / 1e12:,.1f}".rstrip("0").rstrip(".") + "兆円"
    return f"{value / 1e8:,.0f}億円"


def policy_from_case(case: dict) -> dict:
    sources = [{"label": item["title"], "url": item["url"]} for item in case.get("citations", [])[:6]]
    return {
        "id": case["caseId"],
        "kind": "政策",
        "title": case["title"],
        "year": int(case["observationFrom"][:4]),
        "field": "金融",
        "side": None,
        "amount": None,
        "marks": ["額は保留（前後の変化だけで、比べる相手がない）"],
        "step": "evaluated",
        "summary": first_clause(case.get("holdReason", ""), 80),
        "chain": [{"step": "実施", "result": item["date"], "note": item["text"]} for item in case.get("implementations", [])]
        + [{"step": "観測", "result": item.get("method", ""), "note": item["text"]} for item in case.get("observations", [])]
        + [{"step": "判定", "result": "保留", "note": case.get("holdReason", "")}],
        "sources": sources,
        "people": [{"name": actor["label"], "note": actor["action"]} for actor in case.get("actors", [])],
        "href": "/policies",
    }


def law_names(index: dict) -> dict:
    """法律ごとの「何をする」の一文（laws.json と同じ文）と、無いものの理由。"""
    laws = index["laws"]
    return {
        "schema": "public-law-names/v1",
        "what": {item["id"]: item["what"] for item in laws if item.get("what")},
        "withheld": {item["id"]: item["whatWithheld"] for item in laws if not item.get("what")},
    }


def bundle_of(item_id: str) -> str:
    """詳細を分ける束の名前。法律は提出回次ごと、政策は policy。画面側 detailBundle と同じ規則。"""
    match = re.fullmatch(r"(?:閣法|衆法|参法)-(\d+)-\d+", item_id)
    return match.group(1) if match else "policy"


def split(payload: dict) -> tuple[dict, dict[str, dict]]:
    """一覧（軽い）と詳細（開いた時に、その束だけ読む）に分ける。"""
    index = {**payload, "laws": [], "policies": []}
    bundles: dict[str, dict] = defaultdict(dict)
    for key in ("laws", "policies"):
        for item in payload[key]:
            index[key].append({name: item[name] for name in INDEX_KEYS if name in item})
            bundles[bundle_of(item["id"])][item["id"]] = {name: value for name, value in item.items() if name not in INDEX_KEYS}
    return index, {name: {"schema": "public-laws-detail/v1", "items": items} for name, items in bundles.items()}


def main() -> int:
    index, bundles = split(build())
    OUTPUT.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    DETAIL_DIR.mkdir(exist_ok=True)
    for stale in DETAIL_DIR.glob("*.json"):
        if stale.stem not in bundles:
            stale.unlink()
    for name, bundle in bundles.items():
        (DETAIL_DIR / f"{name}.json").write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    NAMES_OUTPUT.write_text(json.dumps(law_names(index), ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(index["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
