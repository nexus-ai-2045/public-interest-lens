#!/usr/bin/env python3
"""金融政策と海外の比較系列を、日本銀行・BIS・IMF・FRED の公表データから取り込む（年の系列にそろえる）。

段（それぞれ単独で回せる。毎朝の自動更新は --monthly で段ごとに月1回）
- boj：日本銀行 時系列統計データ検索サイトの API（コールレート・基準貸付利率・マネタリーベース・日本銀行勘定の国債・ETF・J-REIT・総資産）。
- mpm：日本銀行 金融政策決定会合の公表文（1998年〜）。会合ごとの決定・賛否の数・注に名前のある賛成と反対の委員。
- bis：BIS の政策金利（WS_CBPOL）と実質実効為替レート（WS_EER。広い 64 か国の籠と、1964年からの狭い籠）。
- imf：IMF World Economic Outlook（datamapper API）の一般政府の債務残高・財政収支（対GDP比）と消費者物価上昇率。
- fred：FRED（セントルイス連銀）の長期金利（OECD 主要経済指標の10年国債利回り、IRLTLT01）。
- all：上の段を順に。取ったあとは毎回、照合（IMF の日本の物価上昇率 ＝ e-Stat の消費者物価指数の前年比）を checks.csv に書く。

月の値から年の値を作る決まり（備考にも書く）
- 金利・為替のような水準：12か月そろった年だけ、月の値の平均（年平均）。
- 残高（国債・ETF・総資産・マネタリーベース）と政策金利：12月の値（年末）。12月の無い年は出さない。
- IMF の値は年の値のまま。今年以降は見通し（予測）なので入れない。直近の年は推計を含む。

出力は data/acquired/monetary-stats/ の CSV（Git に入れる。列：系列,国,区分,年,値,単位,領域,出典URL,備考）。
原本は .local/monetary/raw/ に置き、manifest.csv に URL・sha256・取得日を残し、.local/external-materials/monetary/ にも外部資料として登録する（AGENTS.md）。
DB への取り込みは scripts/build_database.py の load_series（数値の系列）と load_monetary_decisions（決定会合を decisions へ）。

使い方：python3 scripts/fetch_monetary.py all [--monthly] [--offline] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import re
import time
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_fiscal_more import due, read_csv, record_fetch, write_csv  # noqa: E402

OUT = ROOT / "data" / "acquired" / "monetary-stats"
RAW = ROOT / ".local" / "monetary" / "raw"
LAST_FETCH = OUT / "last-fetch.txt"
USER_AGENT = "public-interest-lens monetary (research; GitHub nexus-ai-2045/public-interest-lens)"
HEADER = ["系列", "国", "区分", "年", "値", "単位", "領域", "出典URL", "備考"]
MANIFEST_HEADER = ["URL", "sha256", "bytes", "取得日", "保存先"]

# 比較する国（OECD の比較国13と、世界の GDP の図の国）。ISO 3166-1 alpha-3 → alpha-2（BIS・FRED の符号）
COUNTRIES = {"JPN": "JP", "USA": "US", "GBR": "GB", "FRA": "FR", "DEU": "DE", "ITA": "IT", "CAN": "CA", "KOR": "KR", "NLD": "NL", "NOR": "NO",
             "SWE": "SE", "ESP": "ES", "AUS": "AU", "CHN": "CN", "IND": "IN", "BRA": "BR", "RUS": "RU", "IDN": "ID", "VNM": "VN", "TWN": "TW"}
EURO_AREA = ("XM", "EA")  # ユーロ圏（ECB の政策金利）。ユーロ導入後の独仏伊蘭西の政策金利はこちら

BOJ_API = "https://www.stat-search.boj.or.jp/api/v1/getDataCode?format=csv&lang=jp&db={db}&startDate={start}&code={code}"
# (DB, 系列コード, 系列, 単位, 年の値の作り方, 備考)
BOJ_SERIES = [
    ("fm02", "STRACLUCON", "無担保コールレート（翌日物）", "年%", "mean", "日本銀行 FM02。月平均の12か月平均。1985年7月から"),
    ("fm02", "STRACLCOON", "有担保コールレート（翌日物）", "年%", "mean", "日本銀行 FM02。月平均の12か月平均"),
    ("ir01", "MADR1M", "基準割引率および基準貸付利率（旧・公定歩合）", "年%", "december", "日本銀行 IR01。12月の値"),
    ("md01", "MABS1AN11", "マネタリーベース（平均残高）", "億円", "december", "日本銀行 MD01。12月の平均残高"),
    ("bs01", "MABJMA5", "日本銀行の国債保有（日本銀行勘定）", "億円", "december", "日本銀行 BS01。12月末。1998年4月から"),
    ("bs01", "MABJMA003", "日本銀行のETF保有（金銭の信託・指数連動型上場投資信託）", "億円", "december", "日本銀行 BS01。12月末。2010年12月から"),
    ("bs01", "MABJMA004", "日本銀行のJ-REIT保有（金銭の信託・不動産投資信託）", "億円", "december", "日本銀行 BS01。12月末。2010年12月から"),
    ("bs01", "MABJMTA", "日本銀行の総資産（日本銀行勘定）", "億円", "december", "日本銀行 BS01。12月末。1998年4月から"),
]

BIS_API = "https://stats.bis.org/api/v1/data/{flow}/{key}?format=csv"
IMF_API = "https://www.imf.org/external/datamapper/api/v1/{indicator}"
IMF_SERIES = [  # (指標, 系列, 単位, 領域)
    ("GGXWDG_NGDP", "一般政府の債務残高（対GDP比、IMF WEO）", "%", "財政"),
    ("GGXCNL_NGDP", "一般政府の財政収支（純貸出・純借入、対GDP比、IMF WEO）", "%", "財政"),
    ("PCPIPCH", "消費者物価上昇率（年平均、IMF WEO）", "%", "物価"),
]
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
FRED_LONG_RATE = "IRLTLT01{cc}M156N"  # OECD 主要経済指標の長期金利（多くの国で10年国債）を FRED が再配布したもの


class Fetcher:
    """原本を .local/monetary/raw/ に保存し、manifest.csv と外部資料の台帳に残す。--offline は保存済みの原本だけを読む。"""

    def __init__(self, offline: bool = False, wait: float = 1.0):
        self.offline = offline
        self.wait = wait
        self.manifest = {r["URL"]: r for r in read_csv(OUT / "manifest.csv")}

    def path(self, url: str) -> Path:
        # API の URL は問い合わせ文字列で中身が変わるので、URL 全体の要約を名前にする
        host = url.split("/")[2]
        return RAW / host / (hashlib.sha256(url.encode()).hexdigest()[:20] + ".dat")

    def get(self, url: str) -> bytes:
        target = self.path(url)
        if self.offline:
            return target.read_bytes()
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
        time.sleep(self.wait)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        self.manifest[url] = {"URL": url, "sha256": hashlib.sha256(body).hexdigest(), "bytes": str(len(body)),
                              "取得日": date.today().isoformat(), "保存先": str(target.relative_to(ROOT))}
        register(target, url)
        return body

    def save_manifest(self) -> None:
        write_csv(OUT / "manifest.csv", MANIFEST_HEADER, [self.manifest[k] for k in sorted(self.manifest)])


def register(path: Path, url: str) -> None:
    """データの原本を .local/external-materials/monetary/ に登録する（AGENTS.md）。"""
    from scripts.register_external_material import register_once

    register_once(input_path=path, source_url=url, task_id="monetary", title=f"金融政策・海外比較の原本（{url.split('/')[2]}）",
                  purpose="データベースの系列（金融・財政・物価の比較）に入れる", storage_root=ROOT / ".local" / "external-materials",
                  observed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))


def annual(monthly: dict[str, float], how: str) -> dict[int, float]:
    """月の値（"YYYY-MM" か "YYYYMM"）→ 年の値。mean は12か月そろった年だけの平均、december は12月の値。"""
    by_year: dict[int, dict[int, float]] = defaultdict(dict)
    for key, value in monthly.items():
        digits = key.replace("-", "")
        by_year[int(digits[:4])][int(digits[4:6])] = value
    out = {}
    for year, months in sorted(by_year.items()):
        if how == "mean" and len(months) == 12:
            out[year] = round(sum(months.values()) / 12, 4)
        elif how == "december" and 12 in months:
            out[year] = months[12]
    return out


def _number(text: str) -> float | None:
    text = (text or "").strip()
    if text in ("", ".", "NaN", "NA"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _not_empty(phase: str, rows: list) -> None:
    if not rows:
        raise RuntimeError(f"{phase}：行が取れない（前回の取得結果を残す）")


# ---------- 日本銀行 ----------

def parse_boj(body: bytes) -> tuple[dict[str, dict[str, float]], str]:
    """時系列統計 API の CSV（Shift_JIS）→ {系列コード: {YYYYMM: 値}} と次の取得位置（NEXTPOSITION）。"""
    text = body.decode("cp932", "replace")
    series: dict[str, dict[str, float]] = defaultdict(dict)
    nxt, header = "", None
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        if row[0] == "STATUS" and row[1] != "200":
            raise RuntimeError(f"日本銀行の API が {row[1]} を返した")
        if row[0] == "NEXTPOSITION":
            nxt = row[1] if len(row) > 1 else ""
        elif row[0] == "SERIES_CODE":
            header = row
        elif header:
            r = dict(zip(header, row))
            v = _number(r.get("VALUES", ""))
            if v is not None:
                series[r["SERIES_CODE"]][r["SURVEY_DATES"]] = v
    return series, nxt


def fetch_boj(fetcher: Fetcher) -> dict:
    rows = []
    for db in dict.fromkeys(s[0] for s in BOJ_SERIES):
        codes = [s for s in BOJ_SERIES if s[0] == db]
        url = BOJ_API.format(db=db, start="195001", code=",".join(s[1] for s in codes))
        data: dict[str, dict[str, float]] = defaultdict(dict)
        page, position = url, ""
        for _ in range(50):
            got, position = parse_boj(fetcher.get(page))
            for code, values in got.items():
                data[code].update(values)
            if not position:
                break
            page = f"{url}&startPosition={position}"
        for _, code, label, unit, how, note in codes:
            for year, value in annual(data.get(code, {}), how).items():
                rows.append({"系列": label, "国": "JPN", "区分": "年平均" if how == "mean" else "年末", "年": year, "値": value,
                             "単位": unit, "領域": "金融", "出典URL": url, "備考": f"{note}。系列 {code}"})
    _not_empty("boj", rows)
    write_csv(OUT / "boj.csv", HEADER, rows)
    return {"行": len(rows), "系列": len({r["系列"] for r in rows})}


# ---------- BIS ----------

def parse_bis(body: bytes) -> dict[str, dict[str, float]]:
    """BIS の SDMX CSV → {REF_AREA: {YYYY-MM: 値}}。"""
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for r in csv.DictReader(io.StringIO(body.decode("utf-8-sig"))):
        v = _number(r.get("OBS_VALUE", ""))
        if v is not None:
            out[r["REF_AREA"]][r["TIME_PERIOD"]] = v
    return out


def _iso3(cc: str) -> str:
    return next((k for k, v in COUNTRIES.items() if v == cc), "EUR" if cc in EURO_AREA else cc)


def fetch_bis(fetcher: Fetcher) -> dict:
    areas = list(COUNTRIES.values()) + ["XM"]
    rows = []
    jobs = [  # (データの流れ, 鍵, 系列, 年の値の作り方, 区分, 単位, 備考)
        ("WS_CBPOL", "M." + "+".join(areas), "政策金利（中央銀行、BIS）", "december", "年末", "年%", "BIS WS_CBPOL。12月の値"),
        ("WS_EER", "M.R.B." + "+".join(areas), "実質実効為替レート（広い籠・64か国、BIS）", "mean", "年平均", "指数（2020年=100）",
         "BIS WS_EER（実質・広い籠）。月の12か月平均。1994年から"),
        ("WS_EER", "M.R.N." + "+".join(areas), "実質実効為替レート（狭い籠・27か国、BIS）", "mean", "年平均", "指数（2020年=100）",
         "BIS WS_EER（実質・狭い籠）。月の12か月平均。1964年から"),
    ]
    for flow, key, label, how, kind, unit, note in jobs:
        url = BIS_API.format(flow=flow, key=key)
        for cc, monthly in parse_bis(fetcher.get(url)).items():
            for year, value in annual(monthly, how).items():
                rows.append({"系列": label, "国": _iso3(cc), "区分": kind, "年": year, "値": value, "単位": unit,
                             "領域": "金融", "出典URL": url, "備考": note + ("。ユーロ圏（ECB）" if cc in EURO_AREA else "")})
    _not_empty("bis", rows)
    write_csv(OUT / "bis.csv", HEADER, rows)
    return {"行": len(rows), "国": len({r["国"] for r in rows})}


# ---------- IMF ----------

def parse_imf(body: bytes, indicator: str, last_year: int) -> dict[str, dict[int, float]]:
    """datamapper の JSON → {国: {年: 値}}。比較する国だけ、last_year までの年だけ（見通しは入れない）。"""
    values = json.loads(body).get("values", {}).get(indicator, {})
    out: dict[str, dict[int, float]] = {}
    for iso3 in COUNTRIES:
        points = {int(y): float(v) for y, v in (values.get(iso3) or {}).items() if v is not None and int(y) <= last_year}
        if points:
            out[iso3] = points
    return out


def fetch_imf(fetcher: Fetcher, today: date | None = None) -> dict:
    last_year = (today or date.today()).year - 1
    rows = []
    for indicator, label, unit, domain in IMF_SERIES:
        url = IMF_API.format(indicator=indicator)
        for iso3, points in parse_imf(fetcher.get(url), indicator, last_year).items():
            for year, value in sorted(points.items()):
                rows.append({"系列": label, "国": iso3, "区分": "", "年": year, "値": value, "単位": unit, "領域": domain, "出典URL": url,
                             "備考": f"IMF World Economic Outlook（datamapper {indicator}）。{last_year + 1}年以降の見通しは入れない。直近の年は推計を含む"})
    _not_empty("imf", rows)
    write_csv(OUT / "imf.csv", HEADER, rows)
    return {"行": len(rows), "国": len({r["国"] for r in rows})}


# ---------- FRED ----------

def parse_fred(body: bytes) -> dict[str, float]:
    """fredgraph.csv（observation_date,系列）→ {YYYY-MM: 値}。欠けた月（"."）は飛ばす。"""
    out = {}
    for row in list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))[1:]:
        if len(row) >= 2 and (v := _number(row[1])) is not None:
            out[row[0][:7]] = v
    return out


def fetch_fred(fetcher: Fetcher) -> dict:
    rows, missing = [], []
    for iso3, cc in COUNTRIES.items():
        series = FRED_LONG_RATE.format(cc=cc)
        url = FRED_CSV.format(series=series)
        try:
            monthly = parse_fred(fetcher.get(url))
        except urllib.error.HTTPError as e:
            if e.code != 404:  # 一時的な失敗で国を落として fred.csv を上書きしない（段ごと失敗にして前回の結果を残す）
                raise
            missing.append(iso3)  # 系列の無い国（OECD の主要経済指標に無い国）は飛ばす
            continue
        except FileNotFoundError:  # --offline で原本の無い国（取得のときに 404 だった国）
            missing.append(iso3)
            continue
        for year, value in annual(monthly, "mean").items():
            rows.append({"系列": "長期金利（10年国債利回り、OECD 主要経済指標・FRED）", "国": iso3, "区分": "年平均", "年": year, "値": value,
                         "単位": "年%", "領域": "金融", "出典URL": url, "備考": f"FRED {series}（OECD Main Economic Indicators）。月の12か月平均"})
    _not_empty("fred", rows)
    write_csv(OUT / "fred.csv", HEADER, rows)
    return {"行": len(rows), "国": len({r["国"] for r in rows}), "系列の無い国": missing}


# ---------- 日本銀行 金融政策決定会合 ----------

BOJ_SITE = "https://www.boj.or.jp"
MPM_LIST = BOJ_SITE + "/mopo/mpmdeci/state_{year}/index.htm"
MPM_FIRST_YEAR = 1998  # 新日銀法の施行（1998年4月）から。公表文の一覧はこの年から
MPM_HEADER = ["決定ID", "会合日", "題名", "決定の要旨", "賛否", "賛成", "反対", "出典URL"]
VOTE_HEADER = ["決定ID", "会合日", "委員", "賛否", "出典URL"]


def parse_mpm_list(html: str) -> list[tuple[str, str, str]]:
    """公表文の一覧（年別）→ [(会合日 YYYY-MM-DD, URL, 題名)]。（参考）の資料は外す。"""
    out = []
    for row in re.findall(r"<tr.*?</tr>", html, re.S):
        m = re.search(r"(\d{4})年\s*(?:&nbsp;)?\s*(\d{1,2})月\s*(\d{1,2})日", row)
        a = re.search(r'<a href="([^"]+)"[^>]*>(.*?)</a>', row, re.S)
        if not (m and a):
            continue
        title = re.sub(r"&nbsp;|\[PDF.*?\]|<[^>]+>", " ", a.group(2))
        title = re.sub(r"\s+", " ", title).strip()
        if title.startswith("（参考）"):
            continue
        out.append((f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", BOJ_SITE + a.group(1) if a.group(1).startswith("/") else a.group(1), title))
    return out


def statement_text(body: bytes, url: str) -> str:
    if url.endswith(".pdf"):
        from scripts.fetch_fiscal_more import pdf_text
        path = RAW / "tmp-statement.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return pdf_text(path)
    html = body.decode("utf-8", "replace")
    i = html.find('id="contents')
    return re.sub(r"<[^>]+>", "", html[i if i >= 0 else 0:])


MPM_NAME = r"[一-龥々ぁ-んァ-ヶー]{1,6}委員"
MPM_NAMES = rf"(?:{MPM_NAME}[、,]?)+"
MPM_STANCES = ("賛成", "反対", "棄権", "欠席")


def _names(s: str) -> list[str]:
    return [n[:-2] for n in re.findall(MPM_NAME, s)]


def _name_blocks(flat: str) -> list[dict[str, list[str]]]:
    """注の名簿「賛成：A委員、B委員。反対：C委員。棄権：D委員」→ 欄ごとの名前。欄は名前の並びが切れたところで閉じる（後ろの説明や次の注を取り込まない）。"""
    blocks = []
    for m in re.finditer(rf"賛成[:：]({MPM_NAMES})", flat):
        block = {"賛成": _names(m.group(1)), "反対": [], "棄権": [], "欠席": []}
        pos = m.end()
        while f := re.match(rf"。?(反対|棄権|欠席)[:：](なし|{MPM_NAMES})", flat[pos:]):
            block[f.group(1)] = [] if f.group(2) == "なし" else _names(f.group(2))
            pos += f.end()
        blocks.append(block)
    return blocks


def parse_statement(text: str) -> dict:
    """公表文 → 決定の要旨・最初の採決の賛否（「賛成7反対2」「賛成7反対1棄権1」「全員一致」「賛成多数」）と、その採決の委員の名簿。

    1つの公表文に採決が複数あるので、名簿は人数がその採決と合うものだけを結ぶ（別の議案の反対者を付けない）。合う名簿が無ければ名前は空。
    """
    t = unicodedata.normalize("NFKC", text)
    flat = re.sub(r"[（(]注\d*[）)]", "", re.sub(r"\s+", "", t))  # 「(賛成7反対(注)1)」「(全員一致(注))」の注の印を外す
    vote = re.search(r"[（(](賛成\d+(?:反対\d+)?(?:棄権\d+)?|全員一致|賛成多数)[）)]", flat)
    decided = re.search(r"(日本銀行は、?本日[^。]*?(?:決定した|決定しました|こととした)[^。]*。)", flat) \
        or re.search(r"([^。]*?(?:決定した|決定しました|こととした)[^。]*。)", flat)
    label = vote.group(1) if vote else ""
    counts = {k: int(n) for k, n in re.findall(r"(賛成|反対|棄権)(\d+)", label)}
    block = None
    for b in _name_blocks(flat):
        if counts and all(len(b[k]) == counts.get(k, 0) for k in ("賛成", "反対", "棄権")):
            block = b
        elif label == "全員一致" and b["賛成"] and not (b["反対"] or b["棄権"]):
            block = b
        if block:
            break
    block = block or {k: [] for k in MPM_STANCES}
    summary = decided.group(1) if decided else ""
    if "以下のとおり" in summary:  # 決めた中身（金利の誘導水準など）は次の文や箇条書きにある。「以上」か次の注・項目の手前まで足す
        rest = re.split(r"以上|[（(]注|\d\.(?=[^\d])|[（(]\d[）)]", flat[decided.end():], maxsplit=1)[0]
        summary += rest
    return {"賛否": label, "決定の要旨": summary[:300], **block}


def statement_of_meeting(fetcher: Fetcher, docs: list[tuple[str, str]]) -> tuple[tuple[str, str], dict]:
    """同じ日の資料から決定の公表文を選ぶ。公表文らしいもの（k+日付[a].htm/pdf、題名が金融政策運営・調節方針・金融緩和）から順に読み、
    採決（賛否）の書かれた最初のものを本文とする（「目で見る…」や運用の資料を決定にしない）。どれにも採決が無ければ最初の候補。"""
    def rank(doc: tuple[str, str]) -> int:
        url, title = doc
        return (0 if re.search(r"/k\d{6}a?\.(?:htm|pdf)$", url) else 2) + (0 if re.search(r"金融政策運営について|金融市場調節方針|金融緩和", title) else 1)
    first = None
    for doc in sorted(docs, key=rank):
        info = parse_statement(statement_text(fetcher.get(doc[0]), doc[0]))
        first = first or (doc, info)
        if info["賛否"]:
            return doc, info
    return first


def fetch_mpm(fetcher: Fetcher, today: date | None = None) -> dict:
    rows, votes = [], []
    for year in range(MPM_FIRST_YEAR, (today or date.today()).year + 1):
        items = parse_mpm_list(fetcher.get(MPM_LIST.format(year=year)).decode("utf-8", "replace"))
        by_date: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for day, url, title in items:
            by_date[day].append((url, title))
        for day, docs in sorted(by_date.items()):
            main, info = statement_of_meeting(fetcher, docs)
            did = f"日銀会合-{day}"
            titles = "／".join(dict.fromkeys(re.sub(r"[（(]\d+時\d+分公表[）)]", "", t).strip() for _, t in docs))
            rows.append({"決定ID": did, "会合日": day, "題名": titles, "決定の要旨": info["決定の要旨"], "賛否": info["賛否"],
                         "賛成": "、".join(info["賛成"]), "反対": "、".join(info["反対"]), "出典URL": main[0]})
            for stance in MPM_STANCES:
                for name in info[stance]:
                    votes.append({"決定ID": did, "会合日": day, "委員": name, "賛否": stance, "出典URL": main[0]})
    _not_empty("mpm", rows)
    write_csv(OUT / "mpm-decisions.csv", MPM_HEADER, rows)
    write_csv(OUT / "mpm-votes.csv", VOTE_HEADER, votes)
    return {"会合": len(rows), "賛否の数が取れた": sum(bool(r["賛否"]) for r in rows), "委員ごとの賛否": len(votes)}


# ---------- 照合 ----------

CPI_DOMESTIC = ROOT / "data" / "acquired" / "domestic-stats" / "cpi_items_annual_2020base.csv"
CHECK_HEADER = ["照合", "国", "年", "値", "相手の値", "結果", "備考"]


def check_all() -> dict:
    """IMF の日本の消費者物価上昇率を、e-Stat の消費者物価指数（2020年基準・総合）の前年比と突き合わせる（指数の丸めがあるので 0.3 ポイントまで一致）。"""
    index = {int(r["年"]): float(r["値"]) for r in read_csv(CPI_DOMESTIC) if r["品目"] == "総合"}
    rows = []
    for r in read_csv(OUT / "imf.csv"):
        if r["国"] != "JPN" or not r["系列"].startswith("消費者物価"):
            continue
        y = int(r["年"])
        if y in index and y - 1 in index:
            mine = round((index[y] / index[y - 1] - 1) * 100, 2)
            ok = abs(mine - float(r["値"])) <= 0.3
            rows.append({"照合": "IMF の消費者物価上昇率 ＝ e-Stat の消費者物価指数（2020年基準・総合）の前年比", "国": "JPN", "年": y,
                         "値": r["値"], "相手の値": mine, "結果": "一致" if ok else "不一致", "備考": "指数の丸めがあるので 0.3 ポイントまで一致とする"})
    write_csv(OUT / "checks.csv", CHECK_HEADER, rows)
    return {"照合": len(rows), "一致": sum(r["結果"] == "一致" for r in rows), "不一致": sum(r["結果"] == "不一致" for r in rows)}


PHASES = ["boj", "mpm", "bis", "imf", "fred"]
STEPS = {"boj": fetch_boj, "mpm": fetch_mpm, "bis": fetch_bis, "imf": fetch_imf, "fred": fetch_fred}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="日本銀行・BIS・IMF・FRED の金融政策と海外比較の系列を取り込む")
    parser.add_argument("phase", choices=PHASES + ["all"], help="回す段（all は順にすべて）")
    parser.add_argument("--monthly", action="store_true", help="段ごとに前回の取得から28日たっていなければ飛ばす（自動更新用）")
    parser.add_argument("--offline", action="store_true", help="通信せず .local/monetary/raw/ の原本だけで作り直す")
    parser.add_argument("--dry-run", action="store_true", help="通信もファイルの書き込みもせず、やることだけ出す")
    args = parser.parse_args(argv)
    phases = PHASES if args.phase == "all" else [args.phase]
    if args.monthly and not args.offline:
        phases = [p for p in phases if due(stamp=LAST_FETCH, phase=p)]
    if args.dry_run or not phases:
        print(f"回す段：{', '.join(phases) or 'なし（どの段も前回から28日たっていない）'}（出力 {OUT.relative_to(ROOT)}）")
        return 0
    fetcher = Fetcher(offline=args.offline)
    failed, fetched = False, {}
    for phase in phases:
        try:
            print(f"{phase}：{STEPS[phase](fetcher)}")
            fetched[phase] = True
        except Exception as error:  # 1つの取得元が落ちても残りは回す
            failed, fetched[phase] = True, False
            print(f"{phase}：失敗 {type(error).__name__}: {error}")
    if not args.offline:
        fetcher.save_manifest()
        record_fetch(fetched, stamp=LAST_FETCH)
    print(f"check：{check_all()}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
