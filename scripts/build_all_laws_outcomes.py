"""成立した全ての法律（3,415本）に、必ず1つの結果を付けた一覧 data/derived/all-laws-v1/outcomes.csv を作る。

入力（全てリポジトリ内。ここでは数値を作らない）：
  data/acquired/bill-census-full/enacted.csv        全法律の題名
  data/derived/bill-triage-v1/triage.csv            全法律の振り分け（系統A・B）。並びと母集団はこの表
  data/acquired/enforcement-dates/enforcement.csv   施行日（取れた行だけ。後から行が増えてよい）
  data/derived/bill-triage-v2/agreement.csv         施行日のある行の2系統の一致（v2）
  data/derived/{impact,loss,benefit,publish}-v1-triage-v2/  v2 の後段の出力（無ければその段は「未実行」として扱う）
  data/acquired/domestic-stats/                     マクロ指標の系列（存在を確かめるだけ）

結果は次の5つのどれか。理由は「額あり」以外で必ず書く。
  額あり         損失または便益の額が出ている（参考フラグ・公開可否は別の列）
  保留           市場への経路はあるが、いま結論を出せない（施行日が未取得、2系統の振り分けが不一致、影響の判定が保留、
                 マクロ指標を割り当てたが影響の計算は未実装、など）
  効果なし（定例） 題名の語の規則（RT1〜RT8）で定例の改正と判定
  測定できない   市場の影響の系列が無い、または題名の語から代理指標を決められない
  評価対象外     振り分けの定義上、評価の対象でない（種類が定型改正・組織手続で、代理指標の規則にも当たらない）

規則は全て機械的な題名の語の規則で、1本ごとの人の判断は入れない。語の表は下の ROUTINE_RULES・MACRO_RULES と
data/derived/all-laws-v1/spec.md が同じ内容。

使い方（リポジトリのルートで）：python3 scripts/build_all_laws_outcomes.py
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACQUIRED = ROOT / "data" / "acquired"
DERIVED = ROOT / "data" / "derived"
OUT = DERIVED / "all-laws-v1" / "outcomes.csv"

HEADER = ["id", "題名", "分野", "指標", "確かさ", "結果", "理由", "経路", "施行日", "種類", "段階", "向き",
          "損失または便益の額", "単位", "公開可否", "指標の系列"]
OUTCOMES = ("額あり", "保留", "効果なし（定例）", "測定できない", "評価対象外")
NO_FIELD = "対応表なし"
OUT_KINDS = {"定型改正", "組織手続"}
MACRO_CONFIDENCE = "低（マクロ指標で代理）"
UNDATED = "施行日が未取得"

# 定例の改正（題名の語）。上から当て、最初に当たった行で決める。
ROUTINE_RULES = [
    ("RT1", "給与・報酬・歳費などの定例改定", (
        "一般職の職員の給与", "特別職の職員の給与", "防衛省の職員の給与", "防衛庁の職員の給与", "検察官の俸給", "裁判官の報酬",
        "国会議員の秘書の給与", "国会議員の歳費", "外務公務員の給与", "国家公務員の給与の改定")),
    ("RT2", "地方交付税の定例改正", ("地方交付税法", "地方交付税の総額の特例")),
    ("RT3", "公債の発行の特例（年度ごとの定例）", ("公債の発行の特例",)),
    ("RT4", "決算上の剰余金の処理の特例（年度ごとの定例）", ("決算上の剰余金の処理の特例",)),
    ("RT5", "年金・手当の額の改定の特例（年度ごとの定例）", ("の額等の改定の特例",)),
    ("RT6", "用語・字句の整理だけ", ("用語の整理",)),
    ("RT7", "選挙の執行経費の基準の定例改正", ("執行経費の基準",)),
]
# RT8：時限の特別措置法の改正で、振り分けの両系統が種類=定型改正（期限の延長だけ）としたもの。
RT8 = ("RT8", "時限の特別措置法の改正で両系統とも定型改正（期限の延長だけ）",
       ("臨時措置法", "特別措置法", "特別措置に関する法律", "緊急措置法", "臨時特例"))

# 代理に使うマクロ指標。系列は data/acquired/domestic-stats にある既存の系列だけ（tests/test_all_laws_outcomes.py が存在を確かめる）。
SNA = "data/acquired/domestic-stats/sna_gdp_by_industry_2020base.csv"
LFS = "data/acquired/domestic-stats/lfs_employed_by_industry_jsic12-14.csv"
MACRO_INDICATORS = {
    "実質GDP": (SNA, {"経済活動": "合計", "価格": "実質(連鎖方式)"}),
    "公務の付加価値（実質）": (SNA, {"経済活動": "13.公務", "価格": "実質(連鎖方式)"}),
    "教育の付加価値（実質）": (SNA, {"経済活動": "14.教育", "価格": "実質(連鎖方式)"}),
    "保健衛生・社会事業の付加価値（実質）": (SNA, {"経済活動": "15.保健衛生・社会事業", "価格": "実質(連鎖方式)"}),
    "農林水産業の付加価値（実質）": (SNA, {"経済活動": "1.農林水産業", "価格": "実質(連鎖方式)"}),
    "建設業の付加価値（実質）": (SNA, {"経済活動": "5.建設業", "価格": "実質(連鎖方式)"}),
    "就業者数": (LFS, {"産業": "総数"}),
}
# 市場の産業がない法律（司法・選挙・防衛・年金・行政組織など）の代理指標。上から当て、最初に当たった行で決める。
MACRO_RULES = [
    ("MA1", "出入国・外国人", ("出入国", "外国人", "入管"), "就業者数"),
    ("MA2", "司法・治安", ("裁判", "検察", "刑事", "刑法", "民事", "訴訟", "少年", "警察", "犯罪", "司法", "法務", "矯正", "暴力団", "公証",
      "消防", "銃砲刀剣", "風俗", "ストーカー", "暴力の防止", "拉致", "憲法", "法律支援", "弁護士", "行政書士", "公益通報"), "公務の付加価値（実質）"),
    ("MA3", "選挙・政治", ("選挙", "政治資金", "政党", "国会", "国民投票", "議院"), "公務の付加価値（実質）"),
    ("MA4", "防衛・安全保障", ("防衛", "自衛隊", "安全保障", "武力攻撃", "国際平和", "駐留軍", "日米"), "公務の付加価値（実質）"),
    ("MA5", "医療・福祉", ("医療", "医師", "病院", "薬", "保健", "介護", "福祉", "障害者", "児童", "母子", "感染症", "予防接種", "健康保険", "国民健康", "生活保護",
      "子ども", "子育て", "健康", "衛生", "母体", "自殺", "公害健康", "石綿", "ハンセン", "血液", "製剤"), "保健衛生・社会事業の付加価値（実質）"),
    ("MA6", "年金・社会保障", ("年金", "恩給", "社会保険", "社会保障", "援護", "戦没者", "戦傷病者", "遺族", "弔慰金", "給付金"), "実質GDP"),
    ("MA7", "教育", ("教育", "学校", "大学", "学習", "教員", "学位"), "教育の付加価値（実質）"),
    ("MA8", "農林水産", ("農業", "農林", "農地", "農村", "農産物", "林業", "森林", "水産", "漁業", "漁港", "食料", "畜産", "土地改良",
      "家畜", "種苗", "植物防疫", "肥料", "食糧", "農作物", "農産", "就農", "国有林", "養殖"), "農林水産業の付加価値（実質）"),
    ("MA9", "建設・住宅・土地", ("建築", "住宅", "建設", "土地", "都市計画", "河川", "砂防", "下水道", "宅地", "区分所有", "公共工事",
      "公共施設", "海岸", "港湾", "道路", "災害復旧"), "建設業の付加価値（実質）"),
    ("MA10", "行政組織・公務員・地方自治", ("設置法", "国家行政組織", "公務員", "定員", "行政機関", "独立行政法人", "整備法", "関係法律の整備", "地方自治", "地方公共団体", "行政不服", "情報公開", "国有財産",
      "住民基本台帳", "戸籍", "旅券", "祝日", "市町村の合併"), "公務の付加価値（実質）"),
    ("MA11", "租税・財政", ("税", "予算", "公債", "財政", "会計", "決算", "交付金"), "実質GDP"),
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def law_id(row: dict[str, str]) -> str:
    return f"{row['種別']}-{row['提出回次']}-{row['番号']}"


def routine_rule(title: str, kinds: tuple[str, str]) -> tuple[str, str] | None:
    """定例の改正か。当たれば (規則の符号, 説明)。"""
    for sign, label, words in ROUTINE_RULES:
        for w in words:
            if w in title:
                return sign, f"{label}（題名の語「{w}」）"
    sign, label, words = RT8
    if kinds[0] == kinds[1] == "定型改正":
        for w in words:
            if w in title:
                return sign, f"{label}（題名の語「{w}」）"
    return None


def macro_rule(title: str) -> tuple[str, str, str, str] | None:
    """代理のマクロ指標。当たれば (規則の符号, 説明, 指標, 語)。"""
    for sign, label, words, indicator in MACRO_RULES:
        for w in words:
            if w in title:
                return sign, label, indicator, w
    return None


def macro_series(indicator: str) -> str:
    path, key = MACRO_INDICATORS[indicator]
    return f"{path}（{'・'.join(f'{k}={v}' for k, v in key.items())}）"


def short(text: str, n: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def hold_segment(reason: str) -> str:
    """損失の理由（／区切り）から、額が出ない理由にあたる部分を取る。"""
    for seg in reason.split("／"):
        if any(k in seg for k in ("保留", "対応がない", "できない")):
            return seg
    return "損失の額が空（理由は loss.csv を参照）"


class Stages:
    """v2 の後段の出力を id で引く。"""

    def __init__(self, derived: Path = DERIVED, version_dir: str = "-triage-v2"):
        def by_id(stage: str, name: str) -> dict[str, dict[str, str]]:
            return {r["id"]: r for r in read_csv(derived / f"{stage}-v1{version_dir}" / name)}
        self.agreement = {r["id"]: r for r in read_csv(derived / "bill-triage-v2" / "agreement.csv")}
        lines = derived / "bill-triage-v2" / "tiebreak-lines.csv"
        # TB2 で採用した行は、第3の判定者が選んだ系統の判定・分野・指標を使う（系統1とは限らない）
        self.line_pick = {r["id"]: r["採用"] for r in read_csv(lines)} if lines.exists() else {}
        # 選んだ系統の種類（表示・定例の判定・種類による対象外に使う）
        v2 = derived / "bill-triage-v2"
        self.line_kind = {
            "系統1": {r["id"]: r["種類"] for r in read_csv(v2 / "labels-line1.csv")} if (v2 / "labels-line1.csv").exists() else {},
            "系統2": {r["id"]: r["系統2_種類"] for r in read_csv(v2 / "labels-line2.csv")} if (v2 / "labels-line2.csv").exists() else {},
        }
        self.impact = by_id("impact", "impact.csv")
        self.loss = by_id("loss", "loss.csv")
        self.benefit = by_id("benefit", "benefit.csv")
        self.publish = by_id("publish", "publish.csv")
        covid = derived / "covid-response-v1" / "labels.csv"
        # コロナ対応の法律は、施行後の窓がコロナの落ち込みと重なる。市場の損失の額は付けず、費用便益（covid-benefit-v1）で扱う
        # 経済への直接効果の判定（econ-relevance-v1）：2系統が一致した「国・自治体の制度で民間のお金の流れを直接変えない」法律
        rel = derived / "econ-relevance-v1" / "labels.csv"
        self.institutional = {r["id"]: r["理由"] for r in read_csv(rel) if r["区分"] == "制度"} if rel.exists() else {}
        self.covid = {r["id"] for r in read_csv(covid) if r.get("コロナ対応") == "はい"} if covid.exists() else set()


def no_market(t: dict[str, str]) -> bool:
    """v1 の振り分けで、市場の経路がない法律：両系統とも評価対象外、または両系統とも分野が対応表なし。"""
    return t["結果"] == "評価対象外" or (t["A_分野"] == NO_FIELD and t["B_分野"] == NO_FIELD)


def market_fields(t: dict[str, str]) -> tuple[str, str]:
    return t["分野"], t["指標"]


def decide(law: dict[str, str], t: dict[str, str], date: str, st: Stages) -> dict[str, str]:
    """1本の結果。law は enacted の行、t は triage の行、date は施行日（無ければ空）。"""
    title = law["題名"]
    ag = st.agreement.get(t["id"]) if date else None
    tb2 = ag is not None and ag.get("結果") == "採用" and ag.get("解消規則") == "TB2"
    side = st.line_pick.get(t["id"], "系統1") if tb2 else "系統1"
    if tb2 and st.line_kind[side].get(t["id"]):  # TB2：第3の判定者が選んだ系統の種類を、v1 の A・B の種類の代わりに使う
        kind = st.line_kind[side][t["id"]]
        t = {**t, "種類": kind, "A_種類": kind, "B_種類": kind}
    kinds = (t["A_種類"], t["B_種類"])
    out = {c: "" for c in HEADER}
    out.update(id=t["id"], 題名=title, 施行日=date, 種類=t["種類"])

    if ag is not None:  # 施行日があり、v2 の一致の表に載っている行：v2 の系統1・系統2の一致で決める（TB2 は選んだ系統）。
        market = not (ag["結果"] == "採用" and ag[f"{side}_判定"] == "評価対象外")
        if ag["結果"] == "採用":
            out["分野"], out["指標"] = ag[f"{side}_分野"], ag[f"{side}_指標"]
    else:
        market = not no_market(t)
        out["分野"], out["指標"] = market_fields(t)

    imp = st.impact.get(t["id"]) if date else None
    loss = st.loss.get(t["id"])
    pub = st.publish.get(t["id"])
    has_amount = bool(market and imp and loss and loss["損失または便益の額"].strip())

    # 0) コロナ対応の法律：市場の損失の額は付けない（窓がコロナ期と重なる）。費用便益は全体指標の表（covid-benefit-v1）に出る
    if has_amount and t["id"] in st.covid:
        out.update(結果="保留", 経路="市場（コロナ対応）", 段階=loss["段階"], 向き=loss["向き"], 公開可否=pub["公開可否"] if pub else "",
                   理由="コロナ対応の法律：施行後の窓がコロナの落ち込みと重なり、市場の損失の額はこの法律の効果と分けられない。額は費用便益（covid-benefit-v1）で扱う")
        return out

    # 1) 額あり（後段の出力が優先。題名の規則で打ち消さない）
    if has_amount:
        out.update(結果="額あり", 経路="市場（v2の後段）", 段階=loss["段階"], 向き=loss["向き"],
                   損失または便益の額=loss["損失または便益の額"], 単位=loss["単位"],
                   公開可否=pub["公開可否"] if pub else "", 確かさ=imp["判定"] + ("・参考" if loss["参考フラグ"] else ""),
                   理由=f"{loss['段階']}の{loss['向き']}。損失または便益の額を計算済み"
                        + ("（参考値。合計・公開・配分には使わない）" if loss["参考フラグ"] else ""))
        return out

    # 2) 定例の改正（題名の語）
    rt = routine_rule(title, kinds)
    if rt:
        out.update(結果="効果なし（定例）", 経路=rt[0], 分野=out["分野"] or NO_FIELD,
                   理由=f"{rt[1]}。毎年・毎回の定例の改正で、市場の産業への新たな効果を測る対象にしない")
        return out

    # 3) 市場の経路がある法律
    if market:
        if not date:
            out.update(結果="保留", 経路="市場（施行日待ち）", 理由=f"{UNDATED}。台帳（enforcement.csv）に施行日が入れば、v2 の振り分けと影響の計算に載る"
                       + (f"（振り分け：{t['結果']}）" if t["結果"] != "評価対象" else ""))
            return out
        if imp is None:
            out.update(結果="保留", 経路="市場（v2未反映）", 理由="施行日はあるが、v2 の影響の表にまだ載っていない（v2 の一連の再実行が要る）")
            return out
        out.update(経路="市場（v2の後段）", 確かさ=imp["判定"] if imp["判定"].startswith("段階") else "")
        if not out["分野"]:  # 2系統が一致せず分野が決まらない行は、影響の表が使った分野・指標を載せる
            out.update(分野=imp["分野"], 指標=imp["指標"])
        if loss:  # 段階はあるが額が出ていない
            out.update(結果="保留", 段階=loss["段階"], 向き=loss["向き"], 公開可否=pub["公開可否"] if pub else "",
                       理由=f"{loss['段階']}だが損失または便益の額を出せない：{short(hold_segment(loss['理由']))}")
        elif imp["判定"] in ("系列なし", "国内系列なし", "比較群なし"):
            out.update(結果="測定できない", 理由=short(imp["理由"]))
        else:
            out.update(結果="保留", 理由=short(imp["理由"]) or f"影響の判定「{imp['判定']}」")
        return out

    # 4) 市場の産業がない法律：マクロ指標の代理 → 評価対象外 → 測定できない
    out["分野"] = out["分野"] or NO_FIELD
    if t["id"] in st.institutional and t["id"] not in st.covid:  # コロナ対応は費用便益の表に載せる
        out.update(結果="評価対象外", 経路="経済への直接効果なし",
                   理由=f"国・自治体の制度の法律で、民間の売上・費用・給付・税・規制の負担を直接は変えない（AI 2系統の判定：{st.institutional[t['id']]}）。経済に絞る方針の外")
        return out
    mr = macro_rule(title)
    if mr:
        sign, label, indicator, word = mr
        tail = (f"{UNDATED}。" if not date else "") + "マクロ指標の影響の計算は未実装（影響の指標表にない）"
        out.update(結果="保留", 経路=sign, 指標=indicator, 確かさ=MACRO_CONFIDENCE, 指標の系列=macro_series(indicator),
                   理由=f"{label}（題名の語「{word}」）。代理指標「{indicator}」を機械的に割り当てた（確かさ：低）。{tail}")
        return out
    if t["種類"] in OUT_KINDS or set(kinds) <= OUT_KINDS:
        out.update(結果="評価対象外", 経路="種類による対象外",
                   理由=f"種類が{t['種類'] or '／'.join(kinds)}で、振り分けの定義上評価の対象でない。題名の語から代理指標も決められない")
        return out
    out.update(結果="測定できない", 経路="代理指標なし",
               理由="市場の産業の対応表がなく、題名の語からマクロの代理指標も決められない（規則 MA1〜MA11 のどれにも当たらない）")
    return out


def build(root: Path = ROOT) -> list[dict[str, str]]:
    derived, acquired = root / "data" / "derived", root / "data" / "acquired"
    enacted = {law_id(r): r for r in read_csv(acquired / "bill-census-full" / "enacted.csv")}
    triage = read_csv(derived / "bill-triage-v1" / "triage.csv")
    dates = {r["id"]: r["施行日"].strip() for r in read_csv(acquired / "enforcement-dates" / "enforcement.csv")}
    st = Stages(derived)
    rows = [decide(enacted[t["id"]], t, dates.get(t["id"], ""), st) for t in triage]
    return apply_exclusion_overrides(rows, read_csv(derived / "all-laws-v1" / "exclusion-overrides.csv") if (derived / "all-laws-v1" / "exclusion-overrides.csv").exists() else [])


REEXAMINED = "再判定（実質変更）"


def apply_exclusion_overrides(rows: list[dict[str, str]], overrides: list[dict[str, str]]) -> list[dict[str, str]]:
    """定例・対象外と決めた法律のうち、AI 3段の再判定で実質的な制度変更を含むとされたものを、保留に戻す。

    保留に戻した行は macro-v1（全体指標の参考の額）が拾う。規則 RT1〜RT8 と種類による対象外の語は変えない
    （規則の誤りを1本ずつ直さず、再判定の表 exclusion-overrides.csv を1か所の根拠にする）。
    """
    reason = {r["id"]: r["理由"] for r in overrides}
    for out in rows:
        if out["id"] in reason and out["結果"] in ("効果なし（定例）", "評価対象外"):
            out.update(結果="保留", 経路=REEXAMINED, 理由=f"{reason[out['id']]}（旧：{out['結果']}・{out['経路']}）。実質的な制度変更を含むと再判定したので、全体指標の参考の額で測る")
    return rows


def write(rows: list[dict[str, str]], path: Path = OUT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    result = build()
    write(result)
    count = Counter(r["結果"] for r in result)
    print(f"all-laws-v1: {len(result)} 本 " + " ".join(f"{k}={count.get(k, 0)}" for k in OUTCOMES))
