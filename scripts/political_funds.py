#!/usr/bin/env python3
"""政治資金収支報告書（総務省の中央分と都道府県選管の公表分）を取り込み、議員・党と団体の関係を一次資料つきで残す。

段（それぞれ単独で回せる。毎朝の自動更新は --monthly で月1回だけ crawl→download→extract を回す）
- crawl：公表ページをたどって報告書 PDF の一覧を作る（data/acquired/political-funds/index.csv）。
  始点は sources.csv（総務省・47都道府県・WARP の公表ページ）。同じホストの同じパスの下だけをたどる。
- download：一覧のうち未取得の PDF を落とし、外部資料の保管庫（.local/external-materials/political-funds/）に
  register_once で登録する（原本はリポジトリに入れない）。取得の記録は manifest.csv。
- extract：pdftotext -layout で文字を出す。1ページあたりの文字が少ないものは画像 PDF として ocr-queue.csv に回す。
  OCR の結果（Mac の Vision か読み手の AI）は --ocr-dir に <sha256>.txt で置けば、以後の段はそれを読む。
- parse：系統A（規則）で、寄附（法人その他の団体・政治団体から）、政治資金パーティーの対価の支払者、
  寄附・交付金の支出先を行にする。系統B（別の読み手）の結果は --line-b の JSON を読み、compare で突き合わせる。
- compare：系統A と系統B が金額・相手方・区分で一致した行だけを relations.csv に採る。食い違いは .local の disagreements.csv（Git に入れない）。
- link：報告団体を議員の人物ID（data/derived/person-ids/persons.csv）に結ぶ。一覧の「関係議員名」だけを根拠にし、
  同姓同名で決まらないものは結ばない（person_ids の方針と同じ）。

個人の寄附者・個人のパーティー券購入者は氏名・住所・職業を出力に残さない（「（個人）」と金額だけ）。
支払先（支出・寄附の支出先）は個人でも報告書の公表どおりに名前を出す（住所は出さない、原本 PDF へのリンクつき）。
公表期間（3年）が終わった年の個人の支払先は、扱いが決まるまで伏せる。
点数への反映はしない（責任の配り方の決定待ち）。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import time
import unicodedata
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ACQUIRED = ROOT / "data" / "acquired" / "political-funds"
DERIVED = ROOT / "data" / "derived" / "political-funds"
WORK = ROOT / ".local" / "political-funds"
MATERIALS = ROOT / ".local" / "external-materials"
TASK_ID = "political-funds"
PERSONS = ROOT / "data" / "derived" / "person-ids" / "persons.csv"
SOURCES = ACQUIRED / "sources.csv"
INDEX = ACQUIRED / "index.csv"
MANIFEST = ACQUIRED / "manifest.csv"
LAST_FETCH = ACQUIRED / "last-fetch.txt"
MONTHLY_DAYS = 28
MONTHLY_MINUTES = 40
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

SOURCES_HEADER = ["区分", "名前", "始点URL", "たどるパス", "形式", "備考"]
INDEX_HEADER = ["出典", "年分", "団体区分", "団体名", "関係議員名", "PDF_URL", "索引ページURL", "索引ページの資料ID", "リンク文字"]
MANIFEST_HEADER = ["PDF_URL", "sha256", "bytes", "material_id", "取得日時", "状態"]
TEXT_HEADER = ["sha256", "ページ数", "文字数", "状態"]
ROW_HEADER = ["系統", "sha256", "PDF_URL", "年分", "報告団体", "区分", "費目", "相手方", "照合キー", "相手方種別", "金額", "年月日", "頁"]
RELATION_HEADER = ["年分", "報告団体", "関係議員名", "人物ID", "帰属の照合", "区分", "費目", "相手方", "支払先キー", "相手方種別", "団体の種類", "金額", "年月日", "PDF_URL", "頁", "照合"]

KINDS = ("受けた寄附", "パーティー対価", "出した寄附", "支出")
# 支出の費目（報告書の様式の区分）。経常経費4つと政治活動費の内訳。
EXPENSE_ITEMS = ["人件費", "光熱水費", "備品・消耗品費", "事務所費", "組織活動費", "選挙関係費", "機関紙誌の発行その他の事業費",
                 "調査研究費", "その他の経費"]
INDIVIDUAL = "（個人）"
# 個人の名前を伏せる区分。寄附者・パーティー券の購入者は伏せる。支払先（支出・寄附の支出先）は報告書の公表どおりに名前を出す
# （ねくさん 2026-10-23）。住所はどの区分でも出さない。公表期間（総務省は3年）が終わった年の個人の支払先は public_name で伏せる。
PRIVATE_KINDS = {"受けた寄附", "パーティー対価"}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


# ---------- 月1回の判定 ----------

def due(today: date | None = None, stamp: Path = LAST_FETCH, days: int = MONTHLY_DAYS) -> bool:
    """前回の取得から days 日以上たったか（記録が無ければ取る）。報告書は年1回の公表なので月1回で足りる。"""
    today = today or date.today()
    if not stamp.exists():
        return True
    try:
        last = date.fromisoformat(stamp.read_text(encoding="utf-8").strip())
    except ValueError:
        return True
    return (today - last).days >= days


# ---------- crawl ----------

# リンク文字の末尾の「(PDF形式 699キロバイト)」「[PDFファイル/2.1MB]」「（PDF：1,384KB）」は団体名に入れない
FILE_NOTE = re.compile(r"\s*[\(\[（【]\s*(PDF|pdf)[^\)\]）】]*[\)\]）】]?\s*$")


HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "caption": 5, "th": 6}


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str, str]] = []  # (href, リンク文字, 直前の見出し)
        self._href: str | None = None
        self._text: list[str] = []
        self._heading = ""
        # 見出しの階層ごとの文脈（h2 の年分の下に h3 の団体区分、のような並びで上位の年分を失わない）
        self._levels: dict[int, str] = {}
        self._level = 0
        self._in_heading = False
        self._heading_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []
        elif tag in HEADING_LEVELS:
            self._in_heading, self._heading_text, self._level = True, [], HEADING_LEVELS[tag]

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join("".join(self._text).split()), self._heading))
            self._href = None
        elif tag in HEADING_LEVELS and self._in_heading:
            self._in_heading = False
            text = " ".join("".join(self._heading_text).split())
            if text:
                self._levels = {k: v for k, v in self._levels.items() if k < self._level}
                self._levels[self._level] = text
                self._heading = " ".join(self._levels[k] for k in sorted(self._levels))

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)
        if self._in_heading:
            self._heading_text.append(data)


def parse_links(html: str, base: str) -> list[tuple[str, str, str]]:
    parser = _Links()
    parser.feed(html)
    return [(urljoin(base, href.strip()), text, heading) for href, text, heading in parser.links if href and not href.startswith(("mailto:", "javascript:", "#"))]


YEAR_BUN = re.compile(r"(令和|平成)\s*(\d+|元)\s*年分")
# 「令和7年11月28日公表」のような日付の年は年分ではないので、後ろに「○月」が続くものは除く
YEAR = re.compile(r"(令和|平成)\s*(\d+|元)\s*年(?!\s*\d+\s*月)")


def _seireki(m: re.Match) -> str:
    n = 1 if m.group(2) == "元" else int(m.group(2))
    return str((2018 if m.group(1) == "令和" else 1988) + n)


def year_of(*texts: str) -> str:
    """「令和5年分」などから西暦の年分を出す。「年分」と明示したものを優先し、公表日の年は使わない。決まらなければ空。"""
    for pattern in (YEAR_BUN, YEAR):
        for text in texts:
            m = pattern.search(nfkc(text))
            if m:
                return _seireki(m)
    return ""


GROUP_KINDS = ["政党本部", "政党の支部", "政治資金団体", "国会議員関係政治団体", "資金管理団体", "その他の政治団体"]


def group_kind(*texts: str) -> str:
    joined = " ".join(nfkc(t) for t in texts)
    for kind in GROUP_KINDS:
        if kind in joined:
            return kind
    if "政党" in joined:
        return "政党本部"
    return ""


MEMBER = re.compile(r"[（(]\s*(?:代表者|関係国会議員|国会議員)[:：]?\s*([^）)]+)[）)]")


def fetch_text(url: str, timeout: float = 30.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or ("shift_jis" if b"Shift_JIS" in raw[:2000] else "utf-8")
    return raw.decode(charset, errors="replace")


def keep_index_page(url: str, html: str, storage: Path = MATERIALS) -> str:
    """索引ページの HTML を外部資料として保管し、その material_id を返す。年分・団体名・関係議員名（人物IDに結ぶ根拠）は
    このページから読むので、公表ページが更新・削除されても当時の帰属の根拠を確かめられるように残す。"""
    from scripts.register_external_material import register_once

    observed = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    body = html.encode("utf-8")
    tmp = WORK / "index-pages"
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / f"{hashlib.sha256(body).hexdigest()}.html"
    path.write_bytes(body)
    return register_once(input_path=path, source_url=url, task_id=TASK_ID, title="政治資金収支報告書の索引ページ（UTF-8 に直したもの）",
                         purpose="報告書 PDF の年分・団体名・関係議員名の根拠を残す", storage_root=storage, observed_at=observed)


def crawl_source(source: dict[str, str], get=fetch_text, limit: int = 5000, wait: float = 1.0, keep=None) -> list[dict[str, str]]:
    """始点から、同じホストで「たどるパス」の下にある HTML だけをたどり、PDF のリンクを集める。
    keep を渡すと、取れた索引ページごとに keep(URL, HTML) を呼び、返り値（資料ID）を一覧の行に残す。"""
    start = source["始点URL"]
    host = urlsplit(start).netloc
    prefix = source.get("たどるパス") or urlsplit(start).path.rsplit("/", 1)[0] + "/"
    # 親の索引ページの年分・団体区分を子ページへ引き継ぐ（子ページに明示があればそちらを使う）
    # 「深さ」があれば始点からそのリンク数までしかたどらない（県のサイトでページ番号が平らに並び、パスで絞れないとき）
    depth_limit = int(source["深さ"]) if (source.get("深さ") or "").strip().isdigit() else None
    seen, queue, rows = set(), [(start, "", "", 0)], []
    while queue and len(seen) < limit:
        page, parent_year, parent_kind, depth = queue.pop(0)
        if page in seen:
            continue
        seen.add(page)
        try:
            html = get(page)
        except Exception as error:  # 1ページ取れなくても続ける
            rows.append({"出典": source["名前"], "PDF_URL": "", "索引ページURL": page, "リンク文字": f"取得失敗：{error}"})
            continue
        try:
            page_material = keep(page, html) if keep else ""
        except Exception as error:  # 保管に失敗しても一覧作りは続ける（資料IDが空の行になる）
            print(f"索引ページを保管できなかった：{page}：{error}", file=sys.stderr)
            page_material = ""
        for url, text, heading in parse_links(html, page):
            parts = urlsplit(url)
            if parts.netloc != host and not (source.get("区分") == "WARP" and "warp.da.ndl.go.jp" in parts.netloc):
                continue
            clean = url.split("#", 1)[0]
            if clean.lower().endswith(".pdf"):
                member = MEMBER.search(nfkc(text))
                rows.append({
                    "出典": source["名前"], "年分": year_of(text, heading) or parent_year,
                    "団体区分": group_kind(heading, text) or parent_kind, "団体名": FILE_NOTE.sub("", MEMBER.sub("", nfkc(text))).strip(),
                    "関係議員名": member.group(1).strip() if member else "",
                    "PDF_URL": clean, "索引ページURL": page, "索引ページの資料ID": page_material, "リンク文字": text,
                })
            elif (parts.path.startswith(prefix) and clean not in seen and re.search(r"(/|\.html?)$", parts.path)
                  and (depth_limit is None or depth < depth_limit)):
                queue.append((clean, year_of(text, heading) or parent_year, group_kind(heading, text) or parent_kind, depth + 1))
        if wait:
            time.sleep(wait)
    return rows


def crawl(sources: list[dict[str, str]], **kwargs) -> list[dict[str, str]]:
    rows, keys = [], set()
    for source in sources:
        if not source.get("始点URL"):
            continue  # 公表ページが未特定の行は始点が空（手がかりは備考）
        for row in crawl_source(source, **kwargs):
            key = row["PDF_URL"] or row["索引ページURL"]
            if key not in keys:
                keys.add(key)
                rows.append(row)
    return rows


def merge_index(old: list[dict[str, str]], new: list[dict[str, str]]) -> list[dict[str, str]]:
    """今回の一覧を優先し、今回見えなかった PDF の既存行は残す（ページの一時的な取得失敗や、公表期間が終わって
    リンクが消えた PDF の年分・団体名・関係議員名を失わないため）。取得失敗の記録行は今回の分だけ。"""
    seen = {r["PDF_URL"] for r in new if r.get("PDF_URL")}
    return new + [r for r in old if r.get("PDF_URL") and r["PDF_URL"] not in seen]


# ---------- download ----------

def download(index: list[dict[str, str]], manifest: list[dict[str, str]], storage: Path = MATERIALS,
             wait: float = 1.0, limit: int | None = None, get_bytes=None, minutes: float | None = None,
             save=None, save_every: int = 20) -> list[dict[str, str]]:
    """未取得の PDF だけを落として保管庫に登録する。失敗は「状態」に残し、次回にまた試す。
    minutes を過ぎたら残りは次回に回す（自動更新を長引かせない。1回目の全件取得は時間を決めずに別に回す）。"""
    started = time.monotonic()
    from scripts.register_external_material import register_once

    done = {m["PDF_URL"] for m in manifest if m.get("状態") == "取得済み"}
    get_bytes = get_bytes or _get_bytes
    out = [m for m in manifest if m.get("状態") == "取得済み"]
    tmp = WORK / "download"
    tmp.mkdir(parents=True, exist_ok=True)
    count = 0
    # まだ試していない PDF を先に、前回失敗したものを後に回す（先頭の失敗だけで時間枠を使い切らないように）
    failed_before = {m["PDF_URL"] for m in manifest if m.get("状態", "").startswith("失敗")}
    ordered = sorted(index, key=lambda r: r.get("PDF_URL", "") in failed_before)
    for row in ordered:
        url = row.get("PDF_URL", "")
        if not url or url in done:
            continue
        if (limit is not None and count >= limit) or (minutes is not None and time.monotonic() - started > minutes * 60):
            break
        count += 1
        if save and count % save_every == 0:
            save(out)  # 途中で打ち切られても、そこまでの取得の記録が残るように
        observed = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        try:
            body = get_bytes(url)
            digest = hashlib.sha256(body).hexdigest()
            path = tmp / f"{digest}.pdf"
            path.write_bytes(body)
            material = register_once(input_path=path, source_url=url, task_id=TASK_ID,
                                     title=f"政治資金収支報告書 {row.get('年分', '')} {row.get('団体名', '')}".strip(),
                                     purpose="議員・党と団体の関係を一次資料で記録する", storage_root=storage, observed_at=observed)
            out.append({"PDF_URL": url, "sha256": digest, "bytes": str(len(body)), "material_id": material, "取得日時": observed, "状態": "取得済み"})
            done.add(url)
        except Exception as error:
            out.append({"PDF_URL": url, "sha256": "", "bytes": "", "material_id": "", "取得日時": observed, "状態": f"失敗：{str(error)[:120]}"})
        if wait:
            time.sleep(wait)
    return out


def _get_bytes(url: str) -> bytes:
    last = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except Exception as error:
            last = error
            time.sleep(2 ** (attempt + 1))
    raise last  # type: ignore[misc]


def material_path(sha: str, manifest: list[dict[str, str]], storage: Path = MATERIALS) -> Path | None:
    for m in manifest:
        if m.get("sha256") == sha and m.get("material_id"):
            path = storage / TASK_ID / m["material_id"] / "original.pdf"
            if path.exists():
                return path
    return None


# ---------- extract ----------

MIN_CHARS_PER_PAGE = 80


def pdf_text(path: Path) -> tuple[str, int] | None:
    """pdftotext -layout の結果と、ページ数（改ページ \\f の数）。変換に失敗したら None（結果を保存しない）。"""
    try:
        done = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    text = done.stdout.decode("utf-8", errors="replace")
    return text, max(1, text.count("\f"))


def classify_text(text: str, pages: int) -> str:
    chars = len(re.sub(r"\s", "", text))
    return "文字あり" if chars >= MIN_CHARS_PER_PAGE * pages else "画像（OCR待ち）"


def extract(manifest: list[dict[str, str]], text_dir: Path, ocr_dir: Path | None = None, storage: Path = MATERIALS) -> list[dict[str, str]]:
    text_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for m in manifest:
        sha = m.get("sha256")
        if not sha or m.get("状態") != "取得済み":
            continue
        target = text_dir / f"{sha}.txt"
        ocr = ocr_dir / f"{sha}.txt" if ocr_dir else None
        if ocr and ocr.exists():
            text = ocr.read_text(encoding="utf-8")
            target.write_text(text, encoding="utf-8")
            rows.append({"sha256": sha, "ページ数": str(max(1, text.count("\f"))), "文字数": str(len(text)), "状態": "OCR"})
            continue
        if target.exists():
            text = target.read_text(encoding="utf-8")
            pages = max(1, text.count("\f"))
        else:
            path = material_path(sha, manifest, storage)
            if path is None:
                rows.append({"sha256": sha, "ページ数": "", "文字数": "", "状態": "原本が無い"})
                continue
            result = pdf_text(path)
            if result is None:
                # 失敗は保存しない。次回の extract で試し直す
                rows.append({"sha256": sha, "ページ数": "", "文字数": "", "状態": "文字抽出の失敗"})
                continue
            text, pages = result
            target.write_text(text, encoding="utf-8")
        rows.append({"sha256": sha, "ページ数": str(pages), "文字数": str(len(text)), "状態": classify_text(text, pages)})
    return rows


# ---------- parse（系統A：規則） ----------

AMOUNT = re.compile(r"(?<![\d,])(\d{1,3}(?:,\d{3})+|\d{4,})(?![\d,])")
AMOUNT_BEFORE_DATE = re.compile(r"(?<![\d,])(\d{1,3}(?:,\d{3})+|\d+)\s*円?\s*$")
DATE = re.compile(r"(?:(令和|平成|R|H)\s*(\d+|元)\s*[年./]\s*(\d{1,2})\s*[月./]\s*(\d{1,2})\s*日?)")
SECTIONS = [
    # (見出しの正規表現, 区分, 相手方の種別)
    (re.compile(r"個人からの寄附"), "受けた寄附", "個人"),
    (re.compile(r"法人その他の団体からの寄附"), "受けた寄附", "法人その他の団体"),
    (re.compile(r"政治団体からの寄附"), "受けた寄附", "政治団体"),
    (re.compile(r"政治資金パーティー.*(?:対価|支払者)"), "パーティー対価", ""),
    (re.compile(r"寄附・?交付金"), "出した寄附", ""),
    *[(re.compile(r"^\s*(?:\(?\d+\)?\s*)?" + re.escape(item).replace("・", "・?")), "支出", item) for item in EXPENSE_ITEMS],
]
SECTION_END = re.compile(r"^\s*(?:\(?\d+\)?|[０-９]+|[一二三四五六七八九十]+)\s*[.．、 ]\s*\S|^\s*(?:本年|前年|翌年|合\s*計|小\s*計|その他の収入|事業による収入|借入金|資産等)")
CORP_WORDS = ("株式会社", "有限会社", "合同会社", "(株)", "(有)", "協会", "連合会", "組合", "法人", "会社", "銀行", "工業会", "協議会", "連盟", "政治連盟", "支部", "党",
              "後援会", "の会", "研究会", "懇話会", "協同組合", "事務所", "商店", "商会", "センター")
# 「会」だけでは判定しない（会田・会沢のような姓を団体と取り違え、個人の公表期限の扱いが外れるため）


def wareki(m: re.Match) -> str:
    era, year, month, day = m.groups()
    y = 1 if year == "元" else int(year)
    base = 2018 if era in {"令和", "R"} else 1988
    return f"{base + y:04d}-{int(month):02d}-{int(day):02d}"


def counterpart_kind(name: str, section_kind: str) -> str:
    if section_kind:
        return section_kind
    return "法人その他の団体" if any(w in name for w in CORP_WORDS) else "個人"


def parse_lines(text: str, meta: dict[str, str]) -> list[dict[str, str]]:
    """報告書の文字から、相手方・金額・年月日のそろった行を拾う。個人は名前を残さない。"""
    rows = []
    kind = person_kind = None
    item = ""
    page = 1
    for raw in text.split("\n"):
        page += raw.count("\f")
        line = nfkc(raw.replace("\f", ""))
        if not line.strip():
            continue
        hit = next(((k, p) for rx, k, p in SECTIONS if rx.search(line)), None)
        if hit:
            kind, person_kind = hit
            item = person_kind if kind == "支出" else ("寄附・交付金" if kind == "出した寄附" else "")
            if kind == "支出":
                person_kind = ""
            continue
        if kind is None:
            continue
        when = DATE.search(line)
        # 金額は年月日の直前の数（1,000円未満の明細も拾う）。無ければ行のどこかのカンマ付き・4桁以上の数。
        amount = AMOUNT_BEFORE_DATE.search(line[: when.start()]) if when else None
        if when and not amount:
            amount = AMOUNT.search(line)
        if not amount or not when:
            if SECTION_END.search(line) and not AMOUNT.search(line):
                kind = None
            continue
        head = line[: min(amount.start(), when.start())]
        head = re.sub(r"^\s*\d+\s+", "", head)  # 行番号
        # 寄附の行は「氏名・名称  住所  職業・代表者  金額  年月日」の順が多い。最初の列（2つ以上の空白まで）だけを名前にする。
        cols = [c for c in re.split(r"\s{2,}", head.strip()) if c]
        name = " ".join(cols[0].split()) if cols else ""
        if kind in {"出した寄附", "支出"}:
            # 支出の行は「目的 金額 年月日 支出先 住所」の順が多い。年月日のあとの最初の語を支出先にする。
            # 列は2つ以上の空白で区切られる（pdftotext -layout）。名前の中の1つの空白では切らない。
            after = [c for c in re.split(r"\s{2,}", line[when.end():].strip()) if c]
            name = after[0].strip() if after else name
        if not name:
            continue
        ck = counterpart_kind(name, person_kind or "")
        hidden = ck == "個人" and kind in PRIVATE_KINDS
        rows.append({**meta, "系統": "A", "区分": kind, "費目": item, "相手方": INDIVIDUAL if hidden else name,
                     "照合キー": private_key(name) if hidden else "",
                     "相手方種別": ck, "金額": amount.group(1).replace(",", ""), "年月日": wareki(when), "頁": str(page)})
    return rows


# ---------- compare ----------

def private_key(name: str) -> str:
    """伏せた個人を照合するための鍵（名前そのものは残さない）。照合用の行は .local にだけ置く。"""
    return "個人#" + hashlib.sha256(re.sub(r"\s", "", nfkc(name)).encode("utf-8")).hexdigest()[:16]


def _key(row: dict[str, str]) -> tuple:
    # 伏せた個人は表示名「（個人）」ではなく照合キーで突き合わせる（別人を一致にしないため）
    name = row.get("照合キー") or re.sub(r"\s", "", nfkc(row.get("相手方", "")))
    # 相手方種別も合わせる（個人か団体かで、名前の伏せ方と公表期限の扱いが変わるため）。頁も合わせ、別の明細の対応付けを防ぐ。
    return (row.get("sha256"), row.get("区分"), row.get("費目", ""), row.get("相手方種別", ""), name, row.get("金額"), row.get("年月日"), row.get("頁", ""))


def compare(line_a: list[dict[str, str]], line_b: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """系統A と系統B で、区分・相手方・金額・年月日がそろった行だけを採る。片方だけの行は食い違いに出す。"""
    from collections import Counter

    a, b = Counter(_key(r) for r in line_a), Counter(_key(r) for r in line_b)
    agreed, disagreed = [], []
    used = Counter()
    for row in line_a:
        k = _key(row)
        if used[k] < min(a[k], b[k]):
            used[k] += 1
            agreed.append({**row, "照合": "A・B一致"})
        else:
            disagreed.append({**row, "照合": "Aだけ"})
    left = b - a
    for row in line_b:
        k = _key(row)
        if left[k] > 0:
            left[k] -= 1
            disagreed.append({**row, "照合": "Bだけ"})
    return agreed, disagreed


def _line_b_items(data) -> list[dict]:
    return data.get("行", []) if isinstance(data, dict) else data


def line_b_attribution(directory: Path) -> dict[str, str]:
    """系統Bが独立に判定した、報告書の関係議員名（<sha256>.json の {"関係議員名": ..., "根拠": ..., "行": [...]}）。
    配列だけの JSON（帰属を判定していないもの）は含めない。"""
    out = {}
    if not directory or not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "関係議員名" in data:
            out[path.stem] = str(data.get("関係議員名") or "")
    return out


def load_line_b(directory: Path, meta_by_sha: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    """系統B（別の読み手）の結果。<sha256>.json に {"関係議員名", "根拠", "行": [{区分,費目,相手方,相手方種別,金額,年月日,頁}]}
    （古い形の、行の配列だけでもよい。そのときは議員への帰属が未確認になる）。
    区分は KINDS のどれか。費目は区分が「支出」なら EXPENSE_ITEMS のどれか（必須）、「出した寄附」なら「寄附・交付金」（省略可）、
    寄附・パーティー対価なら空。支出で費目が無い・違う行は「入力不備」として一致させない。"""
    rows = []
    if not directory or not directory.is_dir():
        return rows
    for path in sorted(directory.glob("*.json")):
        sha = path.stem
        for item in _line_b_items(json.loads(path.read_text(encoding="utf-8"))):
            kind = item.get("相手方種別", "")
            hidden = kind == "個人" and item.get("区分") in PRIVATE_KINDS
            expense = item.get("費目", "")
            if item.get("区分") == "出した寄附" and not expense:
                expense = "寄附・交付金"
            elif item.get("区分") == "支出" and expense not in EXPENSE_ITEMS:
                expense = f"入力不備：費目「{expense}」"  # 一致させずに食い違いへ回す
            name = INDIVIDUAL if hidden else item.get("相手方", "")
            rows.append({**meta_by_sha.get(sha, {"sha256": sha}), "系統": "B", "区分": item.get("区分", ""), "費目": expense, "相手方": name,
                         "照合キー": private_key(item.get("相手方", "")) if hidden else "",
                         "相手方種別": kind, "金額": str(item.get("金額", "")).replace(",", ""), "年月日": item.get("年月日", ""), "頁": str(item.get("頁", ""))})
    return rows


# ---------- 公表期間 ----------

def public_until(year: str) -> date | None:
    """総務省の公表期間の終わり（年分 Y はおおむね Y+1 年11月末に公表し、3年間）。"""
    try:
        return date(int(year) + 4, 11, 30)
    except ValueError:
        return None


def payee_key(row: dict[str, str]) -> str:
    """同じ支払先を年をまたいでつなぐ鍵。伏せた個人も、名前そのものではなくハッシュの頭でつなぐ（偏りの計算に使う）。"""
    name = re.sub(r"\s", "", nfkc(row.get("相手方", "")))
    if not name or name == INDIVIDUAL:
        return ""
    return name if row.get("相手方種別") != "個人" else "個人#" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:10]


def public_name(row: dict[str, str], today: date | None = None) -> str:
    """公表期間が終わった年の個人の支払先は名前を伏せる（扱いはねくさんの判断待ち。それまでは伏せる側に倒す）。"""
    name = row.get("相手方", "")
    if row.get("相手方種別") != "個人" or name == INDIVIDUAL:
        return name
    until = public_until(row.get("年分", ""))
    return name if until and (today or date.today()) <= until else INDIVIDUAL


# ---------- link ----------

ORG_TYPES = [
    # 労働組合を先に見る（業界団体の「組合」「連合会」に先に当たって誤分類しないように）
    ("労働組合", ("労働組合", "労組", "ユニオン")),
    ("宗教団体", ("教団", "宗教", "神社", "寺", "教会", "学会", "霊", "神道", "仏教")),
    ("業界団体", ("連盟", "協会", "連合会", "工業会", "組合", "協議会", "団体連合", "医師会", "政治連盟", "政経研究会")),
    ("企業", ("株式会社", "有限会社", "合同会社", "(株)", "(有)", "銀行", "証券", "保険")),
    ("後援会", ("後援会", "励ます会", "を支える会", "友の会")),
    ("政党", ("党", "支部")),
]


def org_type(name: str, kind: str) -> str:
    if kind == "個人":
        return "個人"
    name = nfkc(name)
    for label, words in ORG_TYPES:
        if any(w in name for w in words):
            return label
    return "その他の団体"


def person_index(persons: list[dict[str, str]]) -> dict[str, list[str]]:
    from scripts.person_ids import canonical

    by_name: dict[str, list[str]] = {}
    for p in persons:
        if p.get("人物ID"):
            by_name.setdefault(canonical(p["氏名"]), []).append(p["人物ID"])
    return by_name


def attribution_check(member: str, line_b_member: str | None) -> str:
    """議員への帰属（系統A＝索引の関係議員名、系統B＝別の読み手の判定）の照合。「A・B一致」のときだけ人物IDを付ける。"""
    from scripts.person_ids import canonical

    if not member:
        return "関係議員名なし"
    if line_b_member is None:
        return "系統Bの判定なし"
    if canonical(member) != canonical(line_b_member):
        return f"食い違い：B「{line_b_member}」"
    return "A・B一致"


def link(rows: list[dict[str, str]], index_by_url: dict[str, dict[str, str]], persons: list[dict[str, str]],
         attribution: dict[str, str] | None = None) -> list[dict[str, str]]:
    """報告団体の関係議員名を人物IDに結ぶ。帰属が系統A・Bで一致し、候補が1人のときだけ結ぶ。
    一致しない・判定が無い・候補が0人か2人以上のものは空のまま（算入外、「帰属の照合」に理由）。"""
    from scripts.person_ids import canonical

    by_name = person_index(persons)
    attribution = attribution or {}
    out = []
    for row in rows:
        meta = index_by_url.get(row.get("PDF_URL", ""), {})
        member = meta.get("関係議員名", "")
        check = attribution_check(member, attribution.get(row.get("sha256", "")))
        ids = by_name.get(canonical(member), []) if check == "A・B一致" else []
        out.append({**row, "相手方": public_name(row), "支払先キー": payee_key(row), "報告団体": row.get("報告団体") or meta.get("団体名", ""), "関係議員名": member,
                    "人物ID": ids[0] if len(ids) == 1 else "", "帰属の照合": check,
                    "団体の種類": org_type(row.get("相手方", ""), row.get("相手方種別", ""))})
    return out


# ---------- 議員ごとのお金の使い方 ----------

def spending_by_member(relations: list[dict[str, str]], top: int = 20) -> dict:
    """人物IDに結んだ関係団体（資金管理団体・政党支部など）の支出を、議員・年分・費目ごとに合計し、支払先の上位を並べる。
    個人の支払先は公表期間の間だけ名前を出す（link の public_name）。住所は出さない。点数には使わない記録。"""
    from collections import defaultdict

    out: dict = {}
    payees: dict = defaultdict(lambda: defaultdict(lambda: [0, 0, set(), ""]))  # (支払先キー, 費目)ごと：金額・件数・出典・表示名
    spread: dict = defaultdict(lambda: defaultdict(lambda: [0, set(), set(), ""]))  # 支払先キーごと（費目をまたぐ）：金額・年分・団体・表示名
    for row in relations:
        pid = row.get("人物ID")
        if not pid or row.get("区分") not in {"支出", "出した寄附"}:
            continue
        try:
            amount = int(row.get("金額") or 0)
        except ValueError:
            continue
        person = out.setdefault(pid, {"人物ID": pid, "関係議員名": row.get("関係議員名", ""), "団体": [], "年分": {}})
        if row.get("報告団体") and row["報告団体"] not in person["団体"]:
            person["団体"].append(row["報告団体"])
        year = person["年分"].setdefault(row.get("年分", ""), {"合計": 0, "費目": {}})
        item = row.get("費目") or ("寄附・交付金" if row["区分"] == "出した寄附" else "不明")
        cell = year["費目"].setdefault(item, {"金額": 0, "件数": 0})
        cell["金額"] += amount
        cell["件数"] += 1
        year["合計"] += amount
        # 支払先は支払先キーでまとめる（伏せた個人もハッシュで同じ人をつなぎ、別人を「（個人）」1件に合算しない）。
        key = row.get("支払先キー") or ("" if row.get("相手方", INDIVIDUAL) == INDIVIDUAL else row["相手方"])
        label = row["相手方"] if row.get("相手方") and row["相手方"] != INDIVIDUAL else (f"（個人）{key.removeprefix('個人')}" if key else INDIVIDUAL)
        payee = payees[pid][(key or label, item)]
        payee[0] += amount
        payee[1] += 1
        if row.get("PDF_URL"):
            payee[2].add(row["PDF_URL"])
        if not payee[3] or not label.startswith(INDIVIDUAL):  # 実名の年があれば実名を表示名にする
            payee[3] = label
        # 偏りも支払先キーでまとめる。キーの無い行（寄附者側で伏せたもの）は入れない。
        if key:
            # 同じ人の公表期間内（実名）と期間後（伏せた名前）の年分を1つに数える。表示名は実名があれば実名。
            cell = spread[pid][key]
            cell[0] += amount
            cell[1].add(row.get("年分", ""))
            cell[2].add(row.get("報告団体", ""))
            if row.get("相手方") and row["相手方"] != INDIVIDUAL:
                cell[3] = row["相手方"]
            elif not cell[3]:
                cell[3] = f"（個人）{key.removeprefix('個人')}"
    for pid, person in out.items():
        ranked = sorted(payees[pid].items(), key=lambda kv: -kv[1][0])[:top]
        person["主な支払先"] = [{"支払先": v[3] or name, "費目": item, "金額": v[0], "件数": v[1], "出典": sorted(v[2])[:5]} for (name, item), v in ranked]
        person["偏り"] = concentration(spread[pid])
    return dict(sorted(out.items()))


# 偏りの印の基準。印は「支払いが偏っている」という事実だけで、不正を意味しない。
FLAG_MIN_TOTAL = 1_000_000   # 名前の分かる支払先への支出の合計がこれ未満なら印を付けない（少額で割合が跳ねるため）
FLAG_TOP1_SHARE = 0.30       # 1つの支払先が合計の30%以上
FLAG_TOP3_SHARE = 0.60       # 上位3つの支払先で合計の60%以上
FLAG_MULTI_YEARS = 3         # 同じ支払先に3年分以上、かつ合計の10%以上
FLAG_MULTI_SHARE = 0.10


def concentration(spread: dict) -> dict:
    """支払先の集中度：上位1・上位3の割合、HHI、複数年・複数の関連団体にまたがる支払先。基準を超えたら印の理由を並べる。"""
    total = sum(v[0] for v in spread.values())
    # 鍵ではなく表示名で並べる（4つ目の要素が表示名。無ければ鍵そのもの）
    ranked = sorted(((v[3] if len(v) > 3 and v[3] else k, v) for k, v in spread.items()), key=lambda kv: -kv[1][0])
    if total <= 0:
        return {"名前の分かる支払先の合計": 0, "印": [], "理由": []}
    shares = [v[0] / total for _, v in ranked]
    top1, top3 = shares[0], sum(shares[:3])
    hhi = round(sum(x * x for x in shares) * 10000)
    across = [{"支払先": name, "金額": v[0], "割合": round(v[0] / total, 3), "年分": sorted(v[1]), "団体": sorted(v[2])}
              for name, v in ranked if len(v[1]) >= 2 or len(v[2]) >= 2][:10]
    reasons = []
    if total >= FLAG_MIN_TOTAL:
        if top1 >= FLAG_TOP1_SHARE:
            reasons.append(f"1つの支払先（{ranked[0][0]}）が支出の{top1:.0%}")
        if len(ranked) >= 3 and top3 >= FLAG_TOP3_SHARE:
            reasons.append(f"上位3つの支払先で支出の{top3:.0%}")
        for name, v in ranked:
            if len(v[1]) >= FLAG_MULTI_YEARS and v[0] / total >= FLAG_MULTI_SHARE:
                reasons.append(f"{name} に{len(v[1])}年分にわたり支出の{v[0] / total:.0%}")
    return {"名前の分かる支払先の合計": total, "上位1の割合": round(top1, 3), "上位3の割合": round(top3, 3), "HHI": hhi,
            "複数年・複数団体にまたがる支払先": across, "印": ["偏りがある"] if reasons else [], "理由": reasons,
            "注": "偏りは事実の記録で、不正を意味しない。親族企業・秘書が関わる会社かどうかは一次資料で確かめたものだけを別に記す。"}


# ---------- 入口 ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("phase", choices=["crawl", "download", "extract", "parse", "compare", "link", "all", "status"])
    parser.add_argument("--monthly", action="store_true", help="前回の取得から28日たっていなければ何もしない（自動更新用）")
    parser.add_argument("--limit", type=int, default=None, help="download で落とす件数の上限（試し用）")
    parser.add_argument("--minutes", type=float, default=None, help="download を打ち切る分数（--monthly のときは既定で40分）")
    parser.add_argument("--wait", type=float, default=1.0, help="1件ごとの待ち秒数")
    parser.add_argument("--ocr-dir", type=Path, default=WORK / "ocr", help="画像 PDF の OCR 結果 <sha256>.txt の置き場")
    parser.add_argument("--line-b", type=Path, default=WORK / "line-b", help="系統B の結果 <sha256>.json の置き場")
    parser.add_argument("--source", action="append", default=None, help="crawl する始点を名前で絞る（部分一致、複数可。試し・追加した始点だけ回すとき）")
    parser.add_argument("--dry-run", action="store_true", help="通信もファイルの書き込みもせず、やることだけ出す")
    args = parser.parse_args(argv)

    # 通信する段だけを月次にする。公表期間の切れた個人の支払先を伏せ直すため、手元のデータの段は毎回回す
    offline_only = args.monthly and not due()
    if offline_only:
        print(f"前回の取得（{LAST_FETCH.read_text(encoding='utf-8').strip()}）から{MONTHLY_DAYS}日たっていないので、取得は飛ばして手元のデータだけ作り直す")
    sources = read_csv(SOURCES)
    if args.source:
        sources = [s for s in sources if any(k in s.get("名前", "") for k in args.source)]
    if args.phase == "status" or args.dry_run:
        index, manifest = read_csv(INDEX), read_csv(MANIFEST)
        ok = sum(1 for m in manifest if m.get("状態") == "取得済み")
        print(f"始点 {len(sources)}件・一覧 {len(index)}件・取得済み {ok}件・次の月次取得 {'今回' if due() else 'まだ'}")
        return 0
    phases = ["crawl", "download", "extract", "parse", "compare", "link"] if args.phase == "all" else [args.phase]
    if offline_only:
        phases = [p for p in phases if p not in {"crawl", "download"}]
    text_dir = WORK / "text"
    for phase in phases:
        if phase == "crawl":
            rows = merge_index(read_csv(INDEX), crawl(sources, wait=args.wait, keep=keep_index_page))
            write_csv(INDEX, INDEX_HEADER, rows)
            print(f"一覧 {len(rows)}件")
        elif phase == "download":
            # 自動更新の1段の上限（daily_update の Run.command は3600秒）に、一覧作り・抽出の分を残して収める
            manifest = download(read_csv(INDEX), read_csv(MANIFEST), wait=args.wait, limit=args.limit,
                                minutes=args.minutes if args.minutes is not None else (MONTHLY_MINUTES if args.monthly else None),
                                save=lambda rows: write_csv(MANIFEST, MANIFEST_HEADER, rows))
            write_csv(MANIFEST, MANIFEST_HEADER, manifest)
            fetched = {m["PDF_URL"] for m in manifest if m["状態"] == "取得済み"}
            tried = {m["PDF_URL"] for m in manifest}
            remaining = sum(1 for r in read_csv(INDEX) if r.get("PDF_URL") and r["PDF_URL"] not in tried)
            # まだ試していない PDF がある間は月次の記録を進めない（翌日の自動更新で続きを取る）。失敗分は翌月に試し直す。
            if not remaining:
                LAST_FETCH.write_text(str(date.today()) + "\n", encoding="utf-8")
            print(f"取得済み {len(fetched)}件・失敗 {sum(1 for m in manifest if m['状態'] != '取得済み')}件・残り {remaining}件")
        elif phase == "extract":
            texts = extract(read_csv(MANIFEST), text_dir, args.ocr_dir)
            write_csv(ACQUIRED / "texts.csv", TEXT_HEADER, texts)
            write_csv(WORK / "ocr-queue.csv", TEXT_HEADER, [t for t in texts if t["状態"].startswith("画像")])
            print(f"文字あり {sum(t['状態'] == '文字あり' for t in texts)}件・OCR {sum(t['状態'] == 'OCR' for t in texts)}件・OCR待ち {sum(t['状態'].startswith('画像') for t in texts)}件")
        elif phase == "parse":
            index_by_url = {r["PDF_URL"]: r for r in read_csv(INDEX)}
            rows = []
            for m in read_csv(MANIFEST):
                path = text_dir / f"{m.get('sha256', '')}.txt"
                if m.get("sha256") and path.exists():
                    meta = {"sha256": m["sha256"], "PDF_URL": m["PDF_URL"], "年分": index_by_url.get(m["PDF_URL"], {}).get("年分", ""),
                            "報告団体": index_by_url.get(m["PDF_URL"], {}).get("団体名", "")}
                    rows += parse_lines(path.read_text(encoding="utf-8"), meta)
            write_csv(WORK / "line-a.csv", ROW_HEADER, rows)
            print(f"系統A {len(rows)}行")
        elif phase == "compare":
            line_a = read_csv(WORK / "line-a.csv")
            meta = {r["sha256"]: {k: r[k] for k in ("sha256", "PDF_URL", "年分", "報告団体")} for r in line_a}
            agreed, disagreed = compare(line_a, load_line_b(args.line_b, meta))
            write_csv(WORK / "agreed.csv", ROW_HEADER + ["照合"], agreed)
            # 食い違いは照合前の生の行（伏せていない個人名を含みうる）なので、Git に入れない .local に置く
            write_csv(WORK / "disagreements.csv", ROW_HEADER + ["照合"], disagreed)
            print(f"一致 {len(agreed)}行・食い違い {len(disagreed)}行")
        elif phase == "link":
            index_by_url = {r["PDF_URL"]: r for r in read_csv(INDEX)}
            rows = link(read_csv(WORK / "agreed.csv"), index_by_url, read_csv(PERSONS), line_b_attribution(args.line_b))
            write_csv(DERIVED / "relations.csv", RELATION_HEADER, rows)
            spending = spending_by_member(rows)
            (DERIVED / "spending-by-member.json").write_text(json.dumps({"説明": "議員ごとの関係政治団体の支出（政治資金収支報告書、系統A・B一致分）。点数には使わない。個人の支払先は公表期間（3年）の間だけ報告書どおりの名前を出し、住所は出さない。寄附者・パーティー券購入者の個人は名前を出さない。", "議員": spending}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(f"関係 {len(rows)}行（人物IDに結んだもの {sum(1 for r in rows if r['人物ID'])}行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
