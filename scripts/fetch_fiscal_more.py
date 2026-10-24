#!/usr/bin/env python3
"""scripts/fetch_fiscal.py（一般会計の予算・決算・歳入、為替介入、地方の歳入 2018年度〜、骨太 2015年〜）の残りを、官公庁の一次資料から取り込む（*.go.jp）。

段（それぞれ単独で回せる。毎朝の自動更新は --monthly で段ごとに月1回。どれも年1回か四半期の公表）
- special：財務省「財政統計」の第21表（特別会計 主要経費別 当初・補正）・第22表（同 決算）。千円 → 億円。
- jgb：財務省「国債発行額の推移（実績ベース）」（hakkou02.pdf）と「最近20年間の各年度末の国債残高の推移」（zandaka01.pdf）。
- local：総務省「地方財政白書」資料編の「歳入決算額の状況 その2 推移」（各版の CSV。純計の決算額）。DB には fetch_fiscal.py に無い年度（2017年度以前）だけ入れる。
- policies：内閣府の骨太の方針の一覧（2013年〜）とデジタル庁の重点計画（閣議決定日・本文 PDF）。DB には fetch_fiscal.py に無い決定だけ足す。
- texts：本文 PDF を文字にする（数値目標の読み手に渡す）。
- targets：国策の数値目標。AI の読み手2系統の結果（.local/fiscal-more/targets/{a,b}/）を突き合わせる。
- check：2系統の照合（下の「照合」）を回し、checks.csv に書く。
- all：上の段を順に。

照合（同じ数字を別の表・別の版・別の取り込みから取り直して突き合わせる）
- 特別会計：主要経費の足し上げ＝表の「合計」行。DB には一致した（会計・表・年度・段階）だけ入れる。
- 国債：発行額の「計」＝小計＋各債、「小計」＝4条債＋特例債、発行の無い年度の欄が空。普通国債残高（hakkou02）＝残高の推移（zandaka01）。
- 地方財政：同じ年度を載せた白書の版どうし、と fetch_fiscal.py の取り込み（2018年度〜）と。
- 骨太の方針：閣議決定日を fetch_fiscal.py（PDF の1頁目から）と一覧の題名から読んだ日で。

出力は data/acquired/fiscal-more/ の CSV（Git に入れる）。原本は .local/fiscal-more/raw/ に置き、manifest.csv に URL・sha256・取得日を残し、
データの原本（PDF・xlsx・CSV）は .local/external-materials/fiscal-more/ にも外部資料として登録する（AGENTS.md、中身の確かさは unverified から）。
DB への取り込みは scripts/build_database.py の load_fiscal_more。

使い方：python3 scripts/fetch_fiscal_more.py all [--monthly] [--dry-run] [--offline]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import subprocess
import sys
import time
import unicodedata
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "acquired" / "fiscal-more"
MAIN_FISCAL = ROOT / "data" / "acquired" / "fiscal"  # scripts/fetch_fiscal.py の出力（照合の相手）
RAW = ROOT / ".local" / "fiscal-more" / "raw"
TEXT = ROOT / ".local" / "fiscal-more" / "text"
LAST_FETCH = OUT / "last-fetch.txt"
MONTHLY_DAYS = 28
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

MOF_STAT = "https://www.mof.go.jp/policy/budget/reference/statistics/"
LOCAL_TRANSFERS = ("地方交付税交付金", "地方特例交付金", "地方譲与税譲与金")
TOTAL_WITHOUT_LOCAL = "表の合計は地方交付税交付金・地方特例交付金・地方譲与税譲与金を含まない（足し上げからこの3つを除いて一致）"
SPECIAL_TABLES = ["21", "22"]  # 取るのは特別会計だけ（一般会計の第19・20表は scripts/fetch_fiscal.py）
BUDGET_TABLES = {  # 表番号: (会計, 段階の列, 説明)。読み方は表の形が同じなので一般会計の表でも試す（tests）
    "19a": ("一般会計", "当初・補正", "第19表(1) 主（重）要経費別 一般会計歳出 当初予算及び補正予算（昭和24〜59年度）"),
    "19b": ("一般会計", "当初・補正", "第19表(2) 主要経費別 一般会計歳出 当初予算及び補正予算（昭和60年度〜）"),
    "20": ("一般会計", "決算", "第20表 主要経費別 一般会計歳出 予算現額及び決算額（昭和42年度〜）"),
    "21": ("特別会計", "当初・補正", "第21表 主要経費別 特別会計歳出 当初予算及び補正予算（平成20年度〜）"),
    "22": ("特別会計", "決算", "第22表 主要経費別 特別会計歳出 予算現額及び決算額（平成20年度〜）"),
}
JGB_ISSUE = "https://www.mof.go.jp/jgbs/reference/appendix/hakkou02.pdf"
JGB_BALANCE = "https://www.mof.go.jp/jgbs/reference/appendix/zandaka01.pdf"
HAKUSYO_INDEX = "https://www.soumu.go.jp/menu_seisaku/hakusyo/index.html"
HONEBUTO_INDEX = "https://www5.cao.go.jp/keizai-shimon/kaigi/cabinet/honebuto/honebuto-index.html"
DIGITAL_PAGES = ["https://www.digital.go.jp/policies/priority-policy-program",
                 "https://www.digital.go.jp/policies/priority-policy-program-past"]

BUDGET_HEADER = ["年度", "会計", "段階", "区分", "主要経費", "項目", "金額_億円", "表", "シート", "出典URL"]
TOTAL_HEADER = ["年度", "段階", "歳出_億円", "表", "出典URL"]
JGB_HEADER = ["年度", "区分", "項目", "金額_億円", "実績の別", "出典URL"]
LOCAL_HEADER = ["年度", "項目", "金額_億円", "白書の版", "出典URL"]
POLICY_HEADER = ["決定ID", "題名", "決定日", "決定の形式", "所管", "本文URL", "掲載ページURL"]
CHECK_HEADER = ["照合", "対象", "系統A", "系統B", "差", "判定", "備考"]
MANIFEST_HEADER = ["URL", "sha256", "bytes", "取得日", "保存先"]

ERA = {"明治": 1867, "大正": 1911, "昭和": 1925, "平成": 1988, "令和": 2018,
       "S": 1925, "H": 1988, "R": 2018}


# ---------- 共通 ----------

def nfkc(text) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).strip()


def squash(text) -> str:
    return re.sub(r"\s+", "", nfkc(text))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in header})


RETRY_DAYS = 7  # 落ちた段は毎朝ではなく1週間おきに取り直す


def _stamps(stamp: Path) -> dict[str, tuple[date, str]]:
    """last-fetch.txt：1行に「段 日付 ok|failed」。古い形（日付だけの1行）は全段の成功として読む。"""
    out: dict[str, tuple[date, str]] = {}
    if not stamp.exists():
        return out
    for line in stamp.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        try:
            if len(parts) == 1:
                return {p: (date.fromisoformat(parts[0]), "ok") for p in FETCH_PHASES}
            if len(parts) == 3:
                out[parts[0]] = (date.fromisoformat(parts[1]), parts[2])
        except ValueError:
            continue
    return out


def due(today: date | None = None, stamp: Path = LAST_FETCH, days: int = MONTHLY_DAYS, phase: str | None = None) -> bool:
    """その段（phase を省くとどれか1つの段）の前回の取得から days 日以上たったか。落ちた段は RETRY_DAYS 日で取り直す。記録が無ければ取る。"""
    today = today or date.today()
    stamps = _stamps(stamp)
    for p in ([phase] if phase else FETCH_PHASES):
        if p not in stamps:
            return True
        last, status = stamps[p]
        if (today - last).days >= (days if status == "ok" else RETRY_DAYS):
            return True
    return False


def record_fetch(results: dict[str, bool], stamp: Path = LAST_FETCH, today: date | None = None) -> None:
    stamps = _stamps(stamp)
    for p, ok in results.items():
        stamps[p] = (today or date.today(), "ok" if ok else "failed")
    stamp.write_text("".join(f"{p} {d.isoformat()} {s}\n" for p, (d, s) in sorted(stamps.items())), encoding="utf-8")


def wareki_year(text: str) -> int | None:
    """「令和８年度」「Ｈ元」「昭和42」「R8」→ 西暦の年度。"""
    t = squash(text).replace("年度", "").replace("年", "")
    m = re.match(r"(明治|大正|昭和|平成|令和|S|H|R)(元|\d+)", t)
    if not m:
        return None
    n = 1 if m.group(2) == "元" else int(m.group(2))
    return ERA[m.group(1)] + n


def number(value) -> float | None:
    """表の数値。「△」「▲」は負、「－」「-」は 0、文字は None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    t = nfkc(value).replace(",", "").replace(" ", "")
    if t in {"-", "－", "―", "‐", "−"}:
        return 0.0
    sign = -1.0 if t[:1] in {"△", "▲"} else 1.0
    t = t.lstrip("△▲")
    t = t.strip("()（）<>＜＞[]［］")
    try:
        return sign * float(t)
    except ValueError:
        return None


class Fetcher:
    """原本を .local/fiscal-more/raw/ に保存し、manifest.csv に記録する。データの原本は外部資料としても登録する。--offline は保存済みの原本だけを読む。"""

    def __init__(self, offline: bool = False, wait: float = 0.5):
        self.offline = offline
        self.wait = wait
        self.manifest = {r["URL"]: r for r in read_csv(OUT / "manifest.csv")}

    def path(self, url: str) -> Path:
        parts = urlsplit(url)
        name = parts.path.lstrip("/") or "index.html"
        if name.endswith("/"):
            name += "index.html"
        return RAW / parts.netloc / name

    def get(self, url: str) -> bytes:
        target = self.path(url)
        if self.offline:
            return target.read_bytes()
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
        time.sleep(self.wait)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        self.manifest[url] = {"URL": url, "sha256": hashlib.sha256(body).hexdigest(), "bytes": str(len(body)),
                              "取得日": date.today().isoformat(), "保存先": str(target.relative_to(ROOT))}
        register(target, url)  # 判断に使う一覧の HTML（題名・閣議決定日・本文URL を読む）も原本として登録する
        return body

    def text(self, url: str) -> str:
        body = self.get(url)
        head = body[:3000].lower()
        if b"shift_jis" in head or b"shift-jis" in head or b"x-sjis" in head:
            return body.decode("cp932", "replace")
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            return body.decode("cp932", "replace")

    def save_manifest(self) -> None:
        write_csv(OUT / "manifest.csv", MANIFEST_HEADER, [self.manifest[k] for k in sorted(self.manifest)])


def register(path: Path, url: str) -> None:
    """データの原本を .local/external-materials/fiscal-more/ に登録する（AGENTS.md）。同じ日・同じ URL・同じ中身は登録し直さない。"""
    from scripts.register_external_material import register_once

    register_once(input_path=path, source_url=url, task_id="fiscal-more", title=f"財政・国策の原本（{path.name}）",
                  purpose="データベースの財政の流れ・国策の数値目標の表に入れる", storage_root=ROOT / ".local" / "external-materials",
                  observed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))


def links(html: str, base: str) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(r'<a\b[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        out.append((urljoin(base, m.group(1).strip()), re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip()))
    return out


def has_japanese(text: str) -> bool:
    """日本語の文字（かな・漢字）が1字でもあるか（CMap が無いと行番号と罫線だけになる）。"""
    return re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", text) is not None


def pdf_text(path: Path) -> str:
    done = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, check=True)
    # 日本語フォントを埋め込んでいない PDF（骨太 2018・2020 など）は、poppler-data（Adobe-Japan1 の CMap）が無いと
    # 行番号だけの空の本文になる。空の本文を置くと読み手待ちにも出ないので、ここで止める
    if not has_japanese(done.stdout):
        raise RuntimeError(f"{path.name}：日本語の文字が取れない（poppler-data を入れてから取り直す）")
    return done.stdout


def _not_empty(phase: str, rows: list) -> None:
    """取れた行が0なら書き出さない（サイトの作りが変わった日に、前回の取得結果を空で上書きしない）。"""
    if not rows:
        raise RuntimeError(f"{phase}：行が取れない（前回の取得結果を残す）")


# ---------- 予算（財務省 財政統計） ----------

def _header(rows: list[list]) -> tuple[int, dict[str, int]] | None:
    """「当初予算・補正予算」か「予算現額・決算額」の列を見つける。"""
    for i, row in enumerate(rows[:20]):
        cols = {}
        for j, cell in enumerate(row):
            t = squash(cell)
            if t in {"当初予算"}:
                cols["当初"] = j
            elif t in {"補正予算"}:
                cols["補正"] = j
            elif t == "決算額":
                cols["決算"] = j
        if "当初" in cols or "決算" in cols:
            return i, cols
    return None


def _fiscal_year(rows: list[list], sheet: str) -> int | None:
    for row in rows[:15]:
        for cell in row:
            t = squash(cell)
            if "年度" in t and re.search(r"(明治|大正|昭和|平成|令和)", t):
                y = wareki_year(t[re.search(r"(明治|大正|昭和|平成|令和)", t).start():])
                if y:
                    return y
    s = squash(sheet)
    if s.isdigit():  # 第21表・第22表のシート名「20」「２」は平成・令和の数字だけ
        n = int(s)
        return 1988 + n if n >= 20 else 2018 + n
    return wareki_year(s.replace("令和元年", "令和元"))


NUMBERING = re.compile(r"^\d+\.?$")
SUB_NUMBERING = re.compile(r"^[(（]\d+[)）]$")


def parse_budget_sheet(rows: list[list], sheet: str, table: str, url: str) -> tuple[list[dict], list[dict], list[str]]:
    """1シート（1年度）を行にする。返り値：(主要経費の行, 合計の行, 読めなかった行の注記)。"""
    account, _, _ = BUDGET_TABLES[table]
    header = _header(rows)
    year = _fiscal_year(rows, sheet)
    if header is None or year is None:
        return [], [], [f"{table}/{sheet}: 見出しか年度が読めない"]
    start, cols = header
    first_num = min(cols.values())
    stages = {k: v for k, v in cols.items() if k in {"当初", "補正", "決算"}}
    out, totals, notes = [], [], []
    group, group_col = None, None      # 数値の無い見出し（社会保障関係費など）。「計」で閉じる
    parent, parent_col = None, None    # 数値のある主要経費。下の段の番号（(1) など）や一段深い列はその内訳
    children: dict[str, float] = {}     # 見出しの内訳の足し上げ（「計」の行の無い見出し用）
    closed = {"計": False}

    def close_group():
        # 「計」の行が無いまま閉じた見出し（地方財政関係費の下に地方交付税交付金だけ、など）は内訳の足し上げを主要経費にする
        if group is not None and not closed["計"] and children:
            for stage, v in children.items():
                out.append({"年度": year, "会計": account, "段階": stage, "区分": "主要経費別", "主要経費": group, "項目": group,
                            "金額_億円": round(v, 5), "表": table, "シート": sheet, "出典URL": url})
        children.clear()
        closed["計"] = False

    for row in rows[start + 1:]:
        cells = list(row) + [None] * (first_num + 1 - len(row))
        texts = [(j, nfkc(c)) for j, c in enumerate(cells[:first_num]) if c is not None and nfkc(c) and not isinstance(c, (int, float))]
        sub_numbered = any(SUB_NUMBERING.match(t) for _, t in texts)
        numbered = sub_numbered or any(NUMBERING.match(t) for _, t in texts)
        labels = [(j, t) for j, t in texts if not NUMBERING.match(t) and not SUB_NUMBERING.match(t)]
        values = {k: number(cells[v]) if v < len(cells) else None for k, v in stages.items()}
        has_values = any(v is not None for v in values.values())
        if not labels:
            if has_values:
                notes.append(f"{table}/{sheet}: 見出しの無い数値の行を飛ばした {[cells[v] for v in stages.values()]}")
            continue
        col, label = labels[-1]
        name = squash(label).strip("()（）")
        if name.startswith("注") or name.startswith("(注"):
            break
        bracketed = bool(re.fullmatch(r"[(（].+[)）]", squash(label)))
        if not has_values:
            if group is not None and col > group_col and not bracketed:
                continue  # 見出しの下の、額の入っていない内訳（介護給付費が空の年など）
            close_group()
            # 第20表の「（社会保障関係費）」は内訳と同じ列に置かれるので、「計」まで列に関係なく内訳とする
            group, group_col, parent = name, (-1 if bracketed else col), None
            continue
        if name in {"合計", "総合計"}:
            close_group()
            # 「合計」の後に決算不足補てん繰戻などを足した「総合計」があれば、そちらを表の合計にする
            for k, v in values.items():
                if v is not None:
                    totals = [t for t in totals if not (t["段階"] == k and name == "総合計")]
                    if name == "合計" and any(t["段階"] == k for t in totals):
                        continue
                    totals.append({"年度": year, "段階": k, "歳出_億円": round(v / 1e5, 5), "表": table, "出典URL": url})
            group, group_col, parent = None, None, None
            continue
        if name in {"重要経費計", "主要経費計"}:
            continue
        if name == "計" or name.startswith("小計"):
            if group is None or (name.startswith("小計") and not re.search(r"\d", name) and table not in {"19a"}):
                # 公共事業関係費の中の「小計」（災害復旧の前）は内訳の途中の足し上げなので採らない
                continue
            kind, major, item = "主要経費別", group, group
            children.clear()
            group, group_col, parent = None, None, None
        elif group is not None and (numbered or col > group_col):
            kind, major, item = "主要経費別の内訳", group, name
            for stage, v in values.items():
                if v is not None:
                    children[stage] = children.get(stage, 0.0) + v / 1e5
        elif parent is not None and (sub_numbered or col > parent_col):
            kind, major, item = "主要経費別の内訳", parent, name
        else:
            close_group()
            group, group_col = None, None
            parent, parent_col = name, col
            kind, major, item = "主要経費別", name, name
        for stage, v in values.items():
            if v is None:
                continue
            out.append({"年度": year, "会計": account, "段階": stage, "区分": kind, "主要経費": major, "項目": item,
                        "金額_億円": round(v / 1e5, 5), "表": table, "シート": sheet, "出典URL": url})
    return out, totals, notes


def fetch_special(fetcher: Fetcher) -> dict:
    from scripts.dstat_xl import sheets

    rows, totals, notes = [], [], []
    for table in SPECIAL_TABLES:
        url = MOF_STAT + f"{table}.xlsx"
        fetcher.get(url)
        for sheet, data in sheets(str(fetcher.path(url))):
            r, t, n = parse_budget_sheet(data, sheet, table, url)
            rows += r
            totals += t
            notes += n
    _not_empty("special", rows)
    # 同じ見出しの内訳が表に2行ある年（特別会計 令和3年度の港湾空港鉄道等整備事業費など）は足して1行にする
    merged: dict[tuple, dict] = {}
    for r in rows:
        key = (r["年度"], r["会計"], r["段階"], r["区分"], r["主要経費"], r["項目"], r["表"])
        if key in merged:
            merged[key]["金額_億円"] = round(merged[key]["金額_億円"] + r["金額_億円"], 5)
        else:
            merged[key] = dict(r)
    rows = list(merged.values())
    rows.sort(key=lambda r: (r["会計"], r["年度"], r["段階"], r["区分"], r["主要経費"], r["項目"]))
    write_csv(OUT / "special-budget.csv", BUDGET_HEADER, rows)
    write_csv(OUT / "special-budget-totals.csv", TOTAL_HEADER, sorted(totals, key=lambda r: (r["表"], r["年度"], r["段階"])))
    (OUT / "special-budget-notes.txt").write_text("\n".join(notes) + ("\n" if notes else ""), encoding="utf-8")
    return {"行": len(rows), "合計の行": len(totals), "飛ばした行": len(notes)}


# ---------- 国債（財務省 国債等関係諸資料） ----------

# 列の並び（左から）。PDF の見出しは段がずれて読めるので、行の足し算（計）と発行の始まった年度で確かめた並び：
# 年金特例債は平成24〜25年度、復興債は平成23年度から、GX は令和5年度から、子どもは令和6年度から、半導体・AI は令和7年度から。
JGB_COLUMNS = ["新規国債（小計）", "4条債（建設国債）", "特例債", "年金特例債", "復興債", "GX経済移行債", "子ども特例債", "半導体・AI債",
               "財投債", "借換債", "国債発行額の計", "国債依存度_%", "普通国債残高", "普通国債残高のGDP比_%", "国債費（当初）", "国債費の一般会計比_%"]
JGB_ISSUED = {"年金特例債": (2012, 2013), "復興債": (2011, 9999), "GX経済移行債": (2023, 9999), "子ども特例債": (2024, 9999),
              "半導体・AI債": (2025, 9999)}
BRACKET_KIND = {"(": "うち臨時特別公債", "（": "うち臨時特別公債", "<": "うち減税特例公債", "＜": "うち減税特例公債",
                "[": "うち震災特例公債", "［": "うち震災特例公債"}
TOKEN = re.compile(r"[<(\[＜（［]?[\d,]+(?:\.\d+)?[>)\]＞）］]?|(?<!\S)-(?!\S)")


def _jgb_year(head: str, era: str | None) -> tuple[int | None, str | None]:
    m = re.match(r"^(昭和|平成|令和)?\s*(元|\d+)(?:（見込\)?)?$", head)
    if not m:
        return None, era
    era = m.group(1) or era
    if era is None:
        return None, era
    n = 1 if m.group(2) == "元" else int(m.group(2))
    return ERA[era] + n, era


def parse_jgb_issue(text: str, url: str) -> tuple[list[dict], list[str]]:
    """hakkou02 の各行。列は右端の位置で決める（空欄の列があるため、数の並びだけでは決まらない）。"""
    rows, notes = [], []
    era = "昭和"
    pages = text.split("\f")
    for page in pages:
        lines = page.splitlines()
        parsed = []
        extra: dict[int, list[tuple[int, str]]] = {}  # 年度の行の下の段（平成6年度の［8,106］など）
        for line in lines:
            m = re.match(r"^\s*((?:昭和|平成|令和)?\s*(?:元|\d{1,2}))\s{2,}(.*)$", line)
            if not m:
                if parsed and re.match(r"^\s+[<\[(＜［（]?[\d,]+[>\])＞］）]?\s*$", line[:60]):
                    t = TOKEN.search(line)
                    extra.setdefault(len(parsed) - 1, []).append((t.end(), t.group()))
                continue
            year, era = _jgb_year(m.group(1).replace(" ", ""), era)
            if year is None:
                continue
            body_start = m.start(2)
            tokens = [(t.end() + body_start, t.group()) for t in TOKEN.finditer(m.group(2))]
            parsed.append((year, tokens))
        # 16列そろった行から、列ごとの右端の位置を覚える
        full = [t for _, t in parsed if len(t) >= 16 and _all_numeric(t[:16])]
        if not full:
            continue
        edges = [sorted(row[i][0] for row in full)[len(full) // 2] for i in range(16)]
        for idx, (year, tokens) in enumerate(parsed):
            values: dict[int, str] = {}
            for end, tok in tokens:
                col = min(range(16), key=lambda i: abs(edges[i] - end))
                if abs(edges[col] - end) > 4 or col in values:
                    continue
                values[col] = tok
            if len(values) < 12:
                notes.append(f"{year}年度：列が読めない（{len(values)}列）")
                continue
            status = _jgb_status(year, text)
            # 特例債の欄の（ ）＜＞［ ］書きは臨時特別公債・減税特例公債・震災特例公債（外数）。下の段に分かれることもある。
            # 特例債はそれらを含めた「小計 − 4条債」とし、括弧書きは「うち」の内訳として別に残す。
            special = [values.get(2)] + [tok for end, tok in extra.get(idx, []) if abs(edges[2] - end) <= 4]
            bracketed = [tok for tok in special if tok and tok[0] in BRACKET_KIND]
            for tok in bracketed:
                rows.append({"年度": year, "区分": "国債発行額の内訳", "項目": BRACKET_KIND[tok[0]], "金額_億円": number(tok),
                             "実績の別": status, "出典URL": url})
            for i, name in enumerate(JGB_COLUMNS):
                v = number(values.get(i)) if i in values else 0.0
                if i == 2 and bracketed:
                    v = round(number(values.get(0)) - number(values.get(1)), 5)
                if v is None:
                    continue
                kind = "国債残高" if name.startswith("普通国債残高") else ("国債費" if name.startswith("国債費") else "国債発行額")
                rows.append({"年度": year, "区分": kind, "項目": name, "金額_億円": v, "実績の別": status, "出典URL": url})
    return rows, notes


def _jgb_status(year: int, text: str) -> str:
    """注記「令和６年度までは実績。令和７年度は補正後、令和８年度は当初」から、その年度の数字の性格を決める。"""
    m = re.search(r"(令和|平成)\s*(\d+|元)\s*年度までは実績", nfkc(text))
    if not m:
        return "実績"
    last = ERA[m.group(1)] + (1 if m.group(2) == "元" else int(m.group(2)))
    if year <= last:
        return "実績"
    return "補正後" if year == last + 1 else "当初"


def _all_numeric(tokens) -> bool:
    return all(number(t) is not None for _, t in tokens)


def parse_jgb_balance(text: str, url: str) -> list[dict]:
    """zandaka01 の1ページ目：普通国債の「計」（額面、億円）。"""
    out, era = [], None
    for line in text.split("\f")[0].splitlines():
        m = re.match(r"^\s*((?:平成|令和)?\s*(?:元|\d{1,2}))(?:（見込\)?)?\s+([\d,]+)\s", line)
        if not m:
            continue
        year, era = _jgb_year(m.group(1).replace(" ", ""), era)
        if year and all(r["年度"] != year for r in out):  # 1ページ目は普通国債・建設国債・特例国債…と表が続くので最初の表（計）だけ
            out.append({"年度": year, "区分": "国債残高", "項目": "普通国債残高（残高の推移）", "金額_億円": number(m.group(2)),
                        "実績の別": "見込" if "見込" in line else "実績", "出典URL": url})
    return out


def fetch_jgb(fetcher: Fetcher) -> dict:
    fetcher.get(JGB_ISSUE)
    fetcher.get(JGB_BALANCE)
    rows, notes = parse_jgb_issue(pdf_text(fetcher.path(JGB_ISSUE)), JGB_ISSUE)
    balance = parse_jgb_balance(pdf_text(fetcher.path(JGB_BALANCE)), JGB_BALANCE)
    _not_empty("jgb", rows)
    write_csv(OUT / "jgb.csv", JGB_HEADER, sorted(rows, key=lambda r: (r["年度"], (JGB_COLUMNS + list(dict.fromkeys(BRACKET_KIND.values()))).index(r["項目"]))))
    write_csv(OUT / "jgb-balance.csv", JGB_HEADER, balance)
    (OUT / "jgb-notes.txt").write_text("\n".join(notes) + ("\n" if notes else ""), encoding="utf-8")
    return {"行": len(rows), "残高の行": len(balance), "読めない年度": len(notes)}


# ---------- 地方財政（総務省 地方財政白書 資料編） ----------

LOCAL_ITEMS = {"地方税", "地方譲与税", "地方特例交付金等", "地方特例交付金", "地方交付税", "小計(一般財源)", "国庫支出金", "地方債", "歳入合計"}


def parse_local_trend(text: str, url: str, edition: str) -> list[dict]:
    """「歳入決算額の状況 その2 推移」の CSV。見出しの年度の並びを読んで、決算額（百万円）の列だけ採る。"""
    rows = list(csv.reader(text.splitlines()))
    years, era, out = [], None, []
    for row in rows[:8]:
        cells = [squash(c) for c in row]
        if any(re.match(r"(平成|令和)(元|\d+)年度", c) for c in cells):
            for j, c in enumerate(cells[1:], start=1):
                m = re.match(r"(平成|令和)?(元|\d+)年度$", c)
                if not m:
                    if years:
                        break
                    continue
                era = m.group(1) or era
                years.append((j, ERA[era] + (1 if m.group(2) == "元" else int(m.group(2)))))
            break
    if not years:
        return out
    for row in rows:
        label = squash(row[0]) if row else ""
        label = label.replace("（", "(").replace("）", ")")
        if label not in LOCAL_ITEMS:
            continue
        # 推移の表の「国庫支出金」は交通安全対策特別交付金と国有提供施設等所在市町村助成交付金を含む（表の注）。
        # fetch_fiscal.py が単年度の表から取る「国庫支出金」（含まない、年に約500億円少ない）と名前を分ける
        name = {"小計(一般財源)": "一般財源（小計）", "地方特例交付金": "地方特例交付金等",
                "国庫支出金": "国庫支出金（交通安全対策特別交付金等を含む）"}.get(label, label)
        for j, year in years:
            v = number(row[j]) if j < len(row) else None
            if v is not None:
                out.append({"年度": year, "項目": name, "金額_億円": round(v / 100, 3), "白書の版": edition, "出典URL": url})
    return out


def _find_local_trend(fetcher: Fetcher, start: str, edition: str, limit: int = 40) -> list[dict]:
    """白書の版の目次から資料編のページをたどり、「歳入決算額の状況 その2 推移」の CSV を探して読む（同じ版のフォルダの下だけ）。
    表の番号は版で変わる（令和7年版から s-010-2 は「繰越額等」）ので、CSV の見出しで確かめる。「歳入」のページを先に読む。"""
    root = start.rsplit("/", 1)[0] + "/"
    seen, queue, tried = set(), [start], set()
    while queue and len(seen) < limit:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            html = fetcher.text(url)
        except Exception:
            continue
        for href, label in links(html, url):
            if not href.startswith(root):
                continue
            if href.lower().endswith(".csv"):
                if not re.search(r"s-0?\d\d-2\.csv$", href) or href in tried:
                    continue
                tried.add(href)
                try:
                    text = fetcher.text(href)
                except Exception:
                    continue
                if "歳入決算額" in text[:200] and "推" in text[:300]:
                    rows = parse_local_trend(text, href, edition)
                    if rows:
                        return rows
            elif href.lower().endswith((".html", ".htm")) and re.search(r"czs|mokuji|index|data/", href) and href not in seen:
                if "歳入" in nfkc(label):
                    queue.insert(0, href)
                else:
                    queue.append(href)
    return []


def fetch_local(fetcher: Fetcher) -> dict:
    index = fetcher.text(HAKUSYO_INDEX)
    editions = sorted({href for href, _ in links(index, HAKUSYO_INDEX)
                       if re.search(r"/hakusyo/chihou/(r\d\d|\d\d)data/index(-czs)?\.html$", href)})
    rows, skipped = [], []
    for start in editions:
        edition = re.search(r"/chihou/(r?\d\d)data/", start).group(1)
        picked = _find_local_trend(fetcher, start, edition)
        if picked:
            rows += picked
        else:
            skipped.append(edition)
    _not_empty("local", rows)
    # 取れなかった版（通信の失敗など）は前回の行を残す。成功した版だけで書き直すと、その版にしかない年度が消える
    previous = read_csv(OUT / "local-revenue.csv") if (OUT / "local-revenue.csv").exists() else []
    kept = [r for r in previous if r["白書の版"] in skipped]
    rows += kept
    write_csv(OUT / "local-revenue.csv", LOCAL_HEADER, sorted(rows, key=lambda r: (int(r["年度"]), r["項目"], r["白書の版"])))
    (OUT / "local-notes.txt").write_text("".join(f"{e}：歳入決算額の推移の CSV が見つからない\n" for e in skipped), encoding="utf-8")
    return {"行": len(rows), "版": len(editions) - len(skipped), "見つからない版": len(skipped), "前回のまま残した行": len(kept)}


# ---------- 国策（骨太の方針・デジタル重点計画） ----------

DATE_IN_TITLE = re.compile(r"[（(]((?:平成|令和)(?:元|\d+))年(\d+)月(\d+)日閣議決定[)）]")


def _date(era_year: str, month: str, day: str) -> str:
    y = wareki_year(era_year)
    return f"{y:04d}-{int(month):02d}-{int(day):02d}"


def fetch_policies(fetcher: Fetcher) -> dict:
    rows = []
    html = fetcher.text(HONEBUTO_INDEX)
    for href, label in links(html, HONEBUTO_INDEX):
        t = nfkc(label)
        m = DATE_IN_TITLE.search(t)
        if "基本方針" not in t or not m or not href.endswith(".html"):
            continue
        decided = _date(m.group(1), m.group(2), m.group(3))
        title = t[:m.start()].strip()
        page = fetcher.text(href)
        pdfs = [(u, nfkc(l)) for u, l in links(page, href) if u.endswith(".pdf") and "英語" not in nfkc(l) and "Overview" not in nfkc(l)]
        pdf = next((u for u, l in pdfs if "基本方針" in l), "") or next((u for u, l in pdfs if l.startswith("本文")), "")
        rows.append({"決定ID": f"国策-honebuto-{decided[:4]}", "題名": title, "決定日": decided, "決定の形式": "閣議決定",
                     "所管": "内閣府（経済財政諮問会議）", "本文URL": pdf, "掲載ページURL": href})
    seen = set()
    for page_url in DIGITAL_PAGES:
        html = fetcher.text(page_url)
        for href, label in links(html, page_url):
            m = re.search(r"/(20\d\d)(\d\d)(\d\d)_policies_priority_outline_\d+\.pdf$", href)
            if not m:
                continue
            decided = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            text = nfkc(label)
            main = "本文" in text or "統合版" in text or "重点計画" in text
            key = f"国策-デジタル重点計画-{decided}"
            if key in seen and not main:
                continue
            if key in seen:
                existing = next(r for r in rows if r["決定ID"] == key)
                if "本文" in text or not existing["本文URL"]:
                    existing["本文URL"] = href
                continue
            seen.add(key)
            rows.append({"決定ID": key, "題名": "デジタル社会の実現に向けた重点計画", "決定日": decided, "決定の形式": "閣議決定",
                         "所管": "デジタル庁", "本文URL": href if main else "", "掲載ページURL": page_url})
    _not_empty("policies", rows)
    rows.sort(key=lambda r: (r["所管"], r["決定日"]))
    write_csv(OUT / "policies.csv", POLICY_HEADER, rows)
    return {"国策": len(rows)}


def policy_texts(fetcher: Fetcher) -> dict:
    """国策の本文 PDF を文字にして .local/fiscal/text/<決定ID>.txt に置く（数値目標の読み手が読む）。"""
    done = 0
    failed = []
    for r in read_csv(OUT / "policies.csv"):
        if not r["本文URL"]:
            continue
        target = TEXT / f"{r['決定ID']}.txt"
        source = target.with_suffix(".url")
        if target.exists() and not source.exists():
            source.write_text(r["本文URL"], encoding="utf-8")  # 取得元を記録する前に作った本文
        blank = target.exists() and not has_japanese(target.read_text(encoding="utf-8"))  # CMap 無しで作った空の本文
        if target.exists() and not blank and source.read_text(encoding="utf-8").strip() == r["本文URL"]:
            continue
        old = source.read_text(encoding="utf-8").strip() if source.exists() and not blank else None
        fetcher.get(r["本文URL"])
        try:
            text = pdf_text(fetcher.path(r["本文URL"]))
        except RuntimeError as e:  # CMap の無い手元でも、ほかの決定の本文は取る
            print(e, file=sys.stderr)
            failed.append(r["決定ID"])
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        source.write_text(r["本文URL"], encoding="utf-8")
        done += 1
        # 本文が差し替わったときだけ、古い本文を読んだ結果と採った目標を外す（新しい本文で読み手2系統が照合し直すまで DB に入れない）。
        # 新しい手元で初めて本文を作るだけのとき（前の取得元が無い）は、採った目標の本文URL が同じなら残す
        targets_csv = OUT / "policy-targets.csv"
        rows = read_csv(targets_csv) if targets_csv.exists() else []
        stale = lambda t: t["決定ID"] == r["決定ID"] and (old is not None or t.get("本文URL", "") != r["本文URL"])
        if old is not None:
            for line in ("a", "b"):
                (TARGETS / line / f"{r['決定ID']}.json").unlink(missing_ok=True)
        if any(stale(t) for t in rows):
            write_csv(targets_csv, TARGET_HEADER, [t for t in rows if not stale(t)])
    return {"本文を文字にした": done, **({"日本語が取れない": failed} if failed else {})}


def texts_needed() -> bool:
    """policies.csv に、本文が未取得か、取得元（.url）と本文URL が違う決定があるか。"""
    for r in read_csv(OUT / "policies.csv") if (OUT / "policies.csv").exists() else []:
        target = TEXT / f"{r['決定ID']}.txt"
        source = target.with_suffix(".url")
        if r["本文URL"] and (not target.exists() or not has_japanese(target.read_text(encoding="utf-8"))
                             or (source.exists() and source.read_text(encoding="utf-8").strip() != r["本文URL"])):
            return True
    return False


def text_source(did: str) -> str:
    """読み手が読んだ本文の取得元（.url）。無ければ policies.csv の本文URL。"""
    source = TEXT / f"{did}.url"
    if source.exists():
        return source.read_text(encoding="utf-8").strip()
    return next((r["本文URL"] for r in read_csv(OUT / "policies.csv") if r["決定ID"] == did), "")


TARGET_HEADER = ["決定ID", "指標", "目標値", "単位", "目標年", "年の別", "原文", "行", "照合", "本文URL"]
WORK = ROOT / ".local" / "fiscal-more"
TARGETS = WORK / "targets"


def _unit(u) -> str:
    t = re.sub(r"(以上|以下|程度|超|未満)$", "", squash(u).replace("％", "%"))  # 「%以上」も「%」にそろえる
    return {"兆": "兆円", "億": "億円", "万": "万人"}.get(t, t)


def _locate(quote: str, text: str) -> tuple[int, int] | None:
    """読み手の原文を本文（squash 済み）で探し、見つかった範囲を返す。原文の全体が本文にそのまま有るときだけ
    （「…」で略した原文は、略した前後の片がどれもこの順で本文に有るとき）。作った文・付け足した文は採らない。"""
    pieces = [p.strip("。.、") for p in re.split(r"…+|\.\.\.", squash(quote))]
    pieces = [p for p in pieces if p]
    if not pieces or sum(len(p) for p in pieces) < 8:
        return None
    start, pos = None, 0
    for piece in pieces:
        i = text.find(piece, pos if start is not None else 0)
        if i < 0:
            return None
        start = i if start is None else start
        pos = i + len(piece)
    return start, pos


def _quote_ok(quote: str, text: str) -> bool:
    return _locate(quote, text) is not None


UNIT_WORDS = {"%": ["%", "パーセント"], "兆円": ["兆円", "兆"], "億円": ["億円", "億"], "万人": ["万人", "万"], "万円": ["万円", "万"]}  # 長い形を先に（「兆円超」の「超」まで読む）


def _qualifier(value: float, unit: str, found: str) -> str | None:
    """本文で目標値のすぐ後に付く語。「以上・以下・程度…」は単位に残す（「%以上」）。前に付く「約・少なくとも…」は「万人（約）」のように残す。「20%台」「1～2%」のような幅は None（1つの数で表せない）。"""
    q = squash(found).replace(",", "")
    v = str(int(value)) if float(value).is_integer() else str(value)
    after = _unit_pattern(unit)
    m = re.search(rf"(?<![\d.]){re.escape(v)}(?![\d.]){after}", q)  # 「1～2%」の上限も拾い、下で幅として外す
    if not m and unit == "%" and float(value) % 10 == 0:
        m = re.search(rf"(?<![\d.]){int(value) // 10}割", q)  # 「5割程度」も _value_in_quote と同じく割で読む
    if not m and unit == "%" and float(value) == 100:
        # 「全て」を 100% と読むとき（_value_in_quote と同じ語）も、前の「おおむね・ほぼ」を残す
        w = re.search(r"(約|少なくとも|概ね|おおむね|ほぼ)(?=全て|すべて|全部|全員|全数)", q)
        return f"（{w.group(1)}）" if w else ""
    if not m and unit not in UNIT_WORDS and after:
        # 数え方の語が少し後ろに来る単位（_value_in_quote と同じ間）。「100以上の地域」の「以上」は数のすぐ後ろで読む
        g = re.search(rf"(?<![\d.]){re.escape(v)}(?![\d.])(?=[^\d.万億兆千]{{0,15}}?{after})", q)
        w = g and re.match(r"(以上|以下|以内|程度|前後|超|未満|強|弱|を超え|を上回|を下回)", q[g.end():])
        if w:
            before = re.search(r"(約|少なくとも|最大|最低|概ね|おおむね)$", q[:g.start()])
            verb = {"を超え": "超", "を上回": "超", "を下回": "未満"}
            return verb.get(w.group(1), w.group(1)) + (f"（{before.group(1)}）" if before else "")
    if not m:
        return ""
    if re.match(r"台|[~～〜-]\d", q[m.end():]) or re.search(r"\d\D{0,2}[~～〜]$", q[:m.start()]):
        return None
    w = re.match(r"(以上|以下|以内|程度|前後|超|未満|強|弱|を超え|を上回|を下回)", q[m.end():])
    verb = {"を超え": "超", "を上回": "超", "を下回": "未満"}  # 「10倍を超える規模」は「倍超」
    before = re.search(r"(約|少なくとも|最大|最低|概ね|おおむね)$", q[:m.start()])  # 「約28万人」「少なくとも100か所」
    return (verb.get(w.group(1), w.group(1)) if w else "") + (f"（{before.group(1)}）" if before else "")


def _unit_pattern(unit: str) -> str:
    """単位の正規表現。長い形（「万円」）を先に。省略形（「万」）は、後ろに別の単位の字（「万人」の「人」など）が続くときは合わない。"""
    words = UNIT_WORDS.get(unit, [unit] if unit else [])
    if not words:
        return ""
    short = lambda w: w != unit and unit.startswith(w)
    return "(?:" + "|".join(re.escape(w) + ("(?![円人])" if short(w) else "") for w in words) + ")"


def _value_in_quote(value: float, unit: str, quote: str) -> bool:
    """目標値が単位つきで原文にあるか。数字の境目を見る（「2050年」の「50」を 50% と取らない）。「黒字化」の 0 は数字が無いので見ない。"""
    if unit == "黒字化":
        return float(value) == 0 and "黒字" in squash(quote)  # 「黒字化」と本文にあるときだけ（「赤字を10兆円まで削減」は採らない）
    q = squash(quote).replace(",", "")
    v = str(int(value)) if float(value).is_integer() else str(value)
    after = _unit_pattern(unit)
    if unit not in UNIT_WORDS and after:
        after = r"[^\d.万億兆千]{0,15}?" + after  # 間の字に倍率（万・億・兆・千）は入れない（「230万円」を 230円 と取らない）  # 「150 の地方公共団体」のように数え方の語が少し後ろに来る単位（団体・国・地域など）
    if re.search(rf"(?<![\d.]){re.escape(v)}(?![\d.]){after}", q):
        return True
    if unit == "%" and float(value) % 10 == 0 and re.search(rf"(?<![\d.]){int(value) // 10}割", q):
        return True  # 「３割削減」「５割程度」
    if unit == "%" and float(value) == 100 and re.search(r"全て|すべて|全部|全員|全数|100%", q):
        return True  # 「全ての都道府県で」。「全国」の「全」だけでは採らない
    return float(value) == 0 and "ゼロ" in q  # 「介護離職ゼロ」


def _year_names(year) -> str:
    """目標年の書き方（西暦と元号）。「平成32年」のように、先の年も決定の時の元号で書く。"""
    y = int(year)
    names = [str(y)] + ([f"平成{y - 1988}"] if y >= 1989 else []) + ([f"令和{y - 2018}"] if y >= 2020 else ["令和元"] if y == 2019 else [])
    return "(?:" + "|".join(names) + ")"


def _year_in(year, found: str) -> bool:
    """目標年が本文のその範囲に「2030年」「令和12年度」のように書かれているか。年の無い目標は見ない。"""
    return not year or bool(re.search(rf"(?<!\d){_year_names(year)}年", squash(found)))


def _year_kind(year, found: str) -> str:
    """目標年が本文で「2030年度」なら年度、「2030年」なら年。両方ある・どちらも無いときは不明。"""
    if not year:
        return ""
    q = squash(found)
    name = _year_names(year)
    fiscal = re.search(rf"(?<!\d){name}年度", q)
    calendar = re.search(rf"(?<!\d){name}年(?!度)", q)
    return "年度" if fiscal and not calendar else "年" if calendar and not fiscal else "不明"


def _same_passage(span_a: tuple[int, int] | None, span_b: tuple[int, int] | None) -> bool:
    """系統A・B の原文が本文の同じ箇所か（見つかった範囲が重なる）。値と年が同じ別の目標を一致と取らないため。"""
    return bool(span_a and span_b and span_a[0] < span_b[1] and span_b[0] < span_a[1])


def targets_pending() -> list[str]:
    """本文は有るのに読み手2系統の結果がそろっていない決定（新しく取った本文など）。文字の取れない本文（2018・2020年の骨太）は除く。"""
    return sorted(p.stem for p in TEXT.glob("*.txt")
                  if p.stat().st_size >= 2000 and not ((TARGETS / "a" / f"{p.stem}.json").exists() and (TARGETS / "b" / f"{p.stem}.json").exists()))


def compare_targets(line_a: Path = TARGETS / "a", line_b: Path = TARGETS / "b") -> dict:
    """国策の数値目標：系統A（通読）と系統B（語で探して前後を読む）が、目標値・単位・目標年で一致し、
    しかも原文が本文に実在するものだけを採る。片方だけ・原文が本文に無いものは .local の disagreements に残す。"""
    import json

    if not any(line_a.glob("*.json")) or not any(line_b.glob("*.json")):
        return {"採った目標": "読み手の結果が無いので前回の policy-targets.csv のまま", "読み手待ち": len(targets_pending())}
    adopted, disagreements, compared = [], [], set()
    for path in sorted(line_a.glob("*.json")):
        did = path.stem
        other = line_b / path.name
        text_path = TEXT / f"{did}.txt"
        if not other.exists() or not text_path.exists():
            continue  # 照合し直せない文書は、下で前回の行を残す
        compared.add(did)
        text = squash(text_path.read_text(encoding="utf-8"))
        a = json.loads(path.read_text(encoding="utf-8")).get("targets", [])
        b = json.loads(other.read_text(encoding="utf-8")).get("targets", [])

        def key(t):
            v = t.get("target_value")
            return (None if v is None else float(v), _unit(t.get("unit")), t.get("target_year"))

        spans_b = [_locate(tb.get("quote", ""), text) for tb in b]
        used_b = set()
        for ta in a:
            if ta.get("target_value") is None:
                continue
            span_a = _locate(ta.get("quote", ""), text)
            same_key = [i for i, tb in enumerate(b) if i not in used_b and key(tb) == key(ta)]
            match = next((i for i in same_key if _same_passage(span_a, spans_b[i])), None)
            quote = ta.get("quote", "")
            # 目標値は、本文の中で原文として見つかった範囲（読み手の書いた文ではなく本文そのもの）にあるかを見る
            found = text[min(span_a[0], spans_b[match][0]):max(span_a[1], spans_b[match][1])] if match is not None else ""
            # 目標年は原文のすぐ前（「2025 年度までに」の後ろから原文が始まるなど）にあることが多いので、前の30字までを見る
            before = text[max(0, min(span_a[0], spans_b[match][0]) - 30):min(span_a[0], spans_b[match][0])] if match is not None else ""
            reason = ("系統Bに同じ目標が無い" if not same_key else "原文が本文に見つからない" if span_a is None
                      else "系統A・Bの原文が本文の別の箇所" if match is None
                      else "目標値が原文に無い" if not _value_in_quote(key(ta)[0], key(ta)[1], found)
                      else "目標年が原文とその前に無い" if not (_year_in(key(ta)[2], found) or _year_in(key(ta)[2], before + found))
                      else "幅のある目標（「20%台」など、1つの数で表せない）" if _qualifier(key(ta)[0], key(ta)[1], found) is None else None)
            if reason:
                disagreements.append({"決定ID": did, "系統": "A", **{k: ta.get(k) for k in ("indicator", "target_value", "unit", "target_year", "quote")},
                                      "理由": reason})
                continue
            used_b.add(match)
            value, unit, year = key(ta)
            # 暦年か年度かは本文で決める。本文で決まらないときは、2系統の判断が同じならそれ、違えば不明
            year_kind = _year_kind(year, found if _year_in(year, found) else before + found)
            if year_kind == "不明":
                kinds = {ta.get("year_kind") or "不明", b[match].get("year_kind") or "不明"}
                year_kind = kinds.pop() if len(kinds) == 1 else "不明"
            unit += _qualifier(value, unit, found) or ""  # 「%以上」「兆円程度」のように、本文の語を単位に残す
            adopted.append({"決定ID": did, "指標": nfkc(ta.get("indicator")), "目標値": value, "単位": unit, "目標年": year or "",
                            "年の別": year_kind, "原文": nfkc(quote)[:120], "行": ta.get("line") or "",
                            "照合": "系統A・Bが一致、原文を本文で確認", "本文URL": text_source(did)})
        for i, tb in enumerate(b):
            if i not in used_b and tb.get("target_value") is not None:
                disagreements.append({"決定ID": did, "系統": "B", **{k: tb.get(k) for k in ("indicator", "target_value", "unit", "target_year", "quote")},
                                      "理由": "系統Aに同じ目標が無い"})
    if not compared:
        return {"採った目標": "照合できる本文が無いので前回の policy-targets.csv のまま"}
    kept = [r for r in read_csv(OUT / "policy-targets.csv")] if (OUT / "policy-targets.csv").exists() else []
    kept = [r for r in kept if r["決定ID"] not in compared]
    # 照合できた文書で採用が0件なのは正しい結果（読み手の直しで目標が消えたなど）なので、そのまま書き出して古い行を除く
    write_csv(OUT / "policy-targets.csv", TARGET_HEADER, kept + adopted)
    write_csv(WORK / "target-disagreements.csv", ["決定ID", "系統", "indicator", "target_value", "unit", "target_year", "quote", "理由"], disagreements)
    pending = targets_pending()
    return {"採った目標": len(adopted), "前回のまま": len(kept), "食い違い": len(disagreements), "読み手待ち": len(pending)}


# ---------- 照合 ----------

def sum_for_total(summed: float, local: float, total: float | None, tol: float) -> tuple[float, str]:
    """表の合計と比べる足し上げ。平成24〜27年度の表は「合計」が地方交付税交付金・地方特例交付金・地方譲与税譲与金を含まない
    （差がこの3つの額とちょうど同じ）ので、そのときだけ3つを除いた足し上げと比べ、備考に残す。"""
    if total is not None and abs(summed - total) > tol and abs(summed - local - total) <= tol:
        return round(summed - local, 3), TOTAL_WITHOUT_LOCAL
    return round(summed, 3), ""


def check_all() -> dict:
    checks = []

    def add(kind, target, a, b, note="", tol=1.0):
        diff = None if a is None or b is None else round(a - b, 3)
        verdict = "照合できない" if diff is None else ("一致" if abs(diff) <= tol else "不一致")
        checks.append({"照合": kind, "対象": target, "系統A": a, "系統B": b, "差": diff, "判定": verdict, "備考": note})

    budget = read_csv(OUT / "special-budget.csv")
    totals = read_csv(OUT / "special-budget-totals.csv")
    sums: dict[tuple, float] = {}
    local: dict[tuple, float] = {}
    for r in budget:
        if r["区分"] == "主要経費別":
            key = (r["会計"], r["表"], int(r["年度"]), r["段階"])
            sums[key] = sums.get(key, 0.0) + float(r["金額_億円"])
            if r["主要経費"] in LOCAL_TRANSFERS:
                local[key] = local.get(key, 0.0) + float(r["金額_億円"])
    table_total = {(t["表"], int(t["年度"]), t["段階"]): float(t["歳出_億円"]) for t in totals}
    for key, s in sorted(sums.items()):
        account, table, year, stage = key
        total = table_total.get((table, year, stage))
        tol = max(1.0, abs(total or 0) * 1e-6)
        summed, note = sum_for_total(s, local.get(key, 0.0), total, tol)
        add("予算：主要経費の足し上げ＝表の合計", f"{account} {year}年度 {stage}（第{table}表）", summed, total, note=note, tol=tol)

    jgb = read_csv(OUT / "jgb.csv")
    by_year: dict[int, dict[str, float]] = {}
    for r in jgb:
        by_year.setdefault(int(r["年度"]), {})[r["項目"]] = float(r["金額_億円"])
    parts = ["新規国債（小計）", "年金特例債", "復興債", "GX経済移行債", "子ども特例債", "半導体・AI債", "財投債", "借換債"]
    for year, v in sorted(by_year.items()):
        add("国債：発行額の計＝小計＋各債", f"{year}年度", round(sum(v.get(p, 0.0) for p in parts), 1), v.get("国債発行額の計"), tol=3.0)
        if "4条債（建設国債）" in v:
            add("国債：小計＝4条債＋特例債", f"{year}年度", round(v.get("4条債（建設国債）", 0.0) + v.get("特例債", 0.0), 1),
                v.get("新規国債（小計）"), tol=2.0)
        # 列の取り違え（年金特例債と復興債など）は計の足し算では見つからないので、発行の始まった年度より前が 0 かを確かめる
        for name, (since, until) in JGB_ISSUED.items():
            if (year < since or year > until) and v.get(name, 0.0) != 0.0:
                add("国債：発行の無い年度の欄が空", f"{year}年度 {name}", v.get(name), 0.0, note=f"{since}〜{until}年度だけ発行")
    status = {int(r["年度"]): r["実績の別"] for r in jgb}
    for r in read_csv(OUT / "jgb-balance.csv"):
        y = int(r["年度"])
        if status.get(y, "実績") != "実績" or r["実績の別"] != "実績":
            continue  # 見込み（補正後・当初）どうしは出した時期が違うので比べない
        add("国債：普通国債残高（発行額の推移）＝残高の推移の計", f"{y}年度", by_year.get(y, {}).get("普通国債残高"), float(r["金額_億円"]), tol=1.0)

    local = read_csv(OUT / "local-revenue.csv")
    groups: dict[tuple, list[dict]] = {}
    for r in local:
        groups.setdefault((int(r["年度"]), r["項目"]), []).append(r)
    for (year, item), rs in sorted(groups.items()):
        if len(rs) < 2:
            continue
        rs = sorted(rs, key=_edition_order)
        newest, oldest = float(rs[-1]["金額_億円"]), float(rs[0]["金額_億円"])
        add("地方財政：白書の版どうし", f"{year}年度 {item}（{rs[0]['白書の版']}版と{rs[-1]['白書の版']}版）", newest, oldest,
            note="版で数字が違うときは新しい版を採る", tol=0.05)
    # fetch_fiscal.py の取り込み（別の版の CSV・別の読み方）と同じ年度・項目を比べる（あちらは円）
    newest = {}
    for (year, item), rs in groups.items():
        newest[(year, item)] = float(sorted(rs, key=_edition_order)[-1]["金額_億円"])
    main_flows = read_csv(MAIN_FISCAL / "fiscal_flows.csv") if (MAIN_FISCAL / "fiscal_flows.csv").exists() else []
    for r in main_flows:
        if r["会計"] != "地方（純計）" or (int(r["年度"]), r["項目"]) not in newest:
            continue
        add("地方財政：fetch_fiscal.py の取り込みと", f"{r['年度']}年度 {r['項目']}", newest[(int(r["年度"]), r["項目"])],
            round(float(r["金額"]) / 1e8, 3), tol=0.05)
    main_policies = {f"国策-{r['id']}": r["閣議決定日"] for r in read_csv(MAIN_FISCAL / "policies.csv")} if (MAIN_FISCAL / "policies.csv").exists() else {}
    for r in read_csv(OUT / "policies.csv"):
        if r["決定ID"] in main_policies:
            same = main_policies[r["決定ID"]] == r["決定日"]
            checks.append({"照合": "国策：閣議決定日（一覧の題名と、fetch_fiscal.py の PDF の1頁目と）", "対象": r["決定ID"], "系統A": r["決定日"],
                           "系統B": main_policies[r["決定ID"]], "差": "", "判定": "一致" if same else "不一致", "備考": ""})
    # 数値目標の読み手（AI の2系統）は毎朝の更新からは回らない。新しい本文が読み手待ちなら、照合できないとして残して見えるようにする
    for did in targets_pending():
        checks.append({"照合": "国策：数値目標の読み手2系統", "対象": did, "系統A": "", "系統B": "", "差": "", "判定": "照合できない",
                       "備考": "本文は取ったが読み手の結果が無い（.local/fiscal-more/targets/{a,b}/ に置いて targets を回す）"})
    write_csv(OUT / "checks.csv", CHECK_HEADER, checks)
    # 人が見る一覧：DB は「主要経費の足し上げ＝表の合計」が一致の（会計・表・年度・段階）だけを入れ、不一致の会計・年度は年度ごと外す
    # （build_database.py の load_fiscal が checks.csv から決める）
    rejected = sorted({(c["対象"], c["判定"]) for c in checks if c["照合"].startswith("予算：主要経費") and c["判定"] != "一致"})
    write_csv(OUT / "special-budget-rejected.csv", ["対象", "判定"], [{"対象": t, "判定": v} for t, v in rejected])
    return {"照合": len(checks), **{v: sum(1 for c in checks if c["判定"] == v) for v in ("一致", "不一致", "照合できない")}}


def _edition_order(r: dict) -> int:
    e = r["白書の版"]
    return 2018 + int(e[1:]) if e.startswith("r") else 1988 + int(e)


# ---------- 入口 ----------

PHASES = ["special", "jgb", "local", "policies", "texts", "targets", "check"]
FETCH_PHASES = ["special", "jgb", "local", "policies", "texts"]  # 通信する段（月1回）。targets・check は手元で毎回


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="特別会計・国債・地方財政（2017年度以前）・国策の数値目標・デジタル庁の重点計画を *.go.jp の一次資料から取り込む")
    parser.add_argument("phase", choices=PHASES + ["all"], help="回す段（all は順にすべて）")
    parser.add_argument("--monthly", action="store_true", help="前回の取得から28日たっていなければ何もしない（自動更新用）")
    parser.add_argument("--offline", action="store_true", help="通信せず .local/fiscal/raw/ の原本だけで作り直す")
    parser.add_argument("--dry-run", action="store_true", help="通信もファイルの書き込みもせず、やることだけ出す")
    args = parser.parse_args(argv)
    phases = PHASES if args.phase == "all" else [args.phase]
    if args.monthly and not args.offline:
        # 段ごとに前回の取得を見る（1つの段が落ち続けても、ほかの段を毎朝取り直さない）
        # texts は期限前でも残し、回す直前に「一覧に未取得・本文URL の変わった本文が有るか」を見る（policies を取り直した日に本文も取る）
        phases = [p for p in phases if p not in FETCH_PHASES or p == "texts" or due(phase=p)]
        if not any(p in FETCH_PHASES and p != "texts" for p in phases):
            # 通信する段だけを飛ばし、手元の照合（targets・check）は毎回回す（読み手の結果を足した日に反映するため）
            print(f"どの取得の段も前回から{MONTHLY_DAYS}日たっていないので、手元の照合だけ回す")
    if "check" not in phases:
        phases.append("check")  # 取り直した段の照合と、DB に入れてよい予算の一覧をいつも作り直す
    if args.dry_run:
        print(f"回す段：{', '.join(phases)}（出力 {OUT.relative_to(ROOT)}、原本 {RAW.relative_to(ROOT)}）")
        return 0
    fetcher = Fetcher(offline=args.offline)
    steps = {"special": fetch_special, "jgb": fetch_jgb, "local": fetch_local, "policies": fetch_policies,
             "texts": policy_texts}
    failed, fetched = False, {}
    for phase in phases:
        if phase == "texts" and args.monthly and not args.offline and not due(phase="texts") and not texts_needed():
            continue
        try:
            result = check_all() if phase == "check" else compare_targets() if phase == "targets" else steps[phase](fetcher)
            print(f"{phase}：{result}")
            ok = True
        except Exception as error:  # 1つの取得元が落ちても残りは回す
            failed, ok = True, False
            print(f"{phase}：失敗 {type(error).__name__}: {error}")
        if phase in FETCH_PHASES:
            fetched[phase] = ok
    if not args.offline:
        fetcher.save_manifest()
        record_fetch(fetched)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
