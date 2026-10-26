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
- roster：総務省の「現職国会議員の資金管理団体一覧」「国会議員関係政治団体一覧」（議員と団体の対応表、文字の PDF）を
  表として読み、member-groups.csv にする。索引ページに関係議員名が無い団体は、この対応表で団体名から議員を引く。
- link：報告団体を議員の人物ID（data/derived/person-ids/persons.csv）に結ぶ。索引の「関係議員名」（無ければ対応表）を
  根拠にし、同姓同名で決まらないものは結ばない（person_ids の方針と同じ）。

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
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

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
MEMBER_GROUPS = ACQUIRED / "member-groups.csv"
# 総務省「政治団体名簿」（なるほど!政治資金）の議員と団体の対応表。名簿が更新されたらここに足す
ROSTERS = [
    ("https://www.soumu.go.jp/main_content/000718006.pdf", "資金管理団体", "令和7年3月31日時点の現職国会議員"),
    ("https://www.soumu.go.jp/main_content/000847595.pdf", "国会議員関係政治団体", "令和7年3月31日時点の現職国会議員"),
    ("https://www.soumu.go.jp/main_content/001041290.pdf", "資金管理団体", "令和7年参議院議員通常選挙後の現職国会議員"),
    ("https://www.soumu.go.jp/main_content/001041291.pdf", "国会議員関係政治団体", "令和7年参議院議員通常選挙後の現職国会議員"),
]
MONTHLY_DAYS = 28
MONTHLY_MINUTES = 40
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

SOURCES_HEADER = ["区分", "名前", "始点URL", "たどるパス", "形式", "備考"]
INDEX_HEADER = ["出典", "年分", "団体区分", "団体名", "関係議員名", "PDF_URL", "索引ページURL", "索引ページの資料ID", "リンク文字"]
MANIFEST_HEADER = ["PDF_URL", "sha256", "bytes", "material_id", "取得日時", "状態"]
TEXT_HEADER = ["sha256", "ページ数", "文字数", "状態"]
ROW_HEADER = ["系統", "sha256", "PDF_URL", "年分", "報告団体", "区分", "費目", "相手方", "照合キー", "相手方種別", "金額", "年月日", "頁"]
MEMBER_GROUP_HEADER = ["氏名", "届出上の氏名", "院", "選挙区", "届出先", "団体名", "区分", "種別", "名簿", "資料URL", "material_id"]
RELATION_HEADER = ["年分", "報告団体", "関係議員名", "人物ID", "帰属の照合", "区分", "費目", "相手方", "支払先キー", "団体名キー", "相手方種別", "団体の種類", "金額", "年月日", "PDF_URL", "頁", "照合"]

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

KEEP_CHOICES = ("all", "image", "none")
MIN_FREE_BYTES = 5 * 1024 ** 3  # 空きがこれを切ったら、原本を保管すべき取得は失敗にして止める


def _free_bytes(path: Path) -> int:
    import shutil

    path.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(path).free


def download(index: list[dict[str, str]], manifest: list[dict[str, str]], storage: Path = MATERIALS,
             wait: float = 1.0, limit: int | None = None, get_bytes=None, minutes: float | None = None,
             save=None, save_every: int = 20, keep: str = "all", text_dir: Path | None = None,
             workers: int = 1, free_bytes=None) -> list[dict[str, str]]:
    """未取得の PDF だけを落として保管庫に登録する。失敗は「状態」に残し、次回にまた試す。
    minutes を過ぎたら残りは次回に回す（自動更新を長引かせない。1回目の全件取得は時間を決めずに別に回す）。
    keep：all＝原本をすべて保管、image＝文字の無い（OCR の要る）原本だけ保管、none＝保管しない。
    all 以外は落としたその場で文字を抜いて text_dir に置く（全件で数十GBになり、作業場所の容量に収まらないため。
    文字だけの原本は公表期間中なら URL から取り直せる）。空きが MIN_FREE_BYTES を切ったら、保管すべき原本は「失敗」にして取得をやめる（次回に取り直す）。
    workers が2以上なら、ホストごとに並べて別々のホストを同時に取る（同じホストへは1本ずつ、wait 秒あける）。"""
    import threading
    from collections import defaultdict

    from scripts.register_external_material import register_once

    if keep not in KEEP_CHOICES:
        raise ValueError(f"keep は {KEEP_CHOICES} のどれか")
    started = time.monotonic()
    get_bytes = get_bytes or _get_bytes
    free_bytes = free_bytes or _free_bytes
    done = {m["PDF_URL"] for m in manifest if m.get("状態") == "取得済み"}
    out = [m for m in manifest if m.get("状態") == "取得済み"]
    tmp = WORK / "download"
    tmp.mkdir(parents=True, exist_ok=True)
    if text_dir is not None:
        text_dir.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    state = {"count": 0, "stop": False}
    # まだ試していない PDF を先に、前回失敗したものを後に回す（先頭の失敗だけで時間枠を使い切らないように）
    failed_before = {m["PDF_URL"] for m in manifest if m.get("状態", "").startswith("失敗")}
    ordered = sorted((r for r in index if r.get("PDF_URL") and r["PDF_URL"] not in done),
                     key=lambda r: r["PDF_URL"] in failed_before)
    seen_urls: set[str] = set()
    queues: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in ordered:
        if row["PDF_URL"] not in seen_urls:
            seen_urls.add(row["PDF_URL"])
            queues[urlsplit(row["PDF_URL"]).netloc if workers > 1 else ""].append(row)

    def take() -> bool:
        with lock:
            if state["stop"] or (limit is not None and state["count"] >= limit) or \
                    (minutes is not None and time.monotonic() - started > minutes * 60):
                state["stop"] = True
                return False
            state["count"] += 1
            if save and state["count"] % save_every == 0:
                save(list(out))  # 途中で打ち切られても、そこまでの取得の記録が残るように
            return True

    def fetch_one(row: dict[str, str]) -> dict[str, str]:
        url = row["PDF_URL"]
        observed = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        path = None
        try:
            body = get_bytes(url)
            digest = hashlib.sha256(body).hexdigest()
            # 同じ中身の PDF を別ホストから同時に取ることがあるので、作業用の控えは取得ごとに別の名前にする
            handle, name = tempfile.mkstemp(prefix=f"{digest}-", suffix=".pdf", dir=tmp)
            os.close(handle)
            path = Path(name)
            path.write_bytes(body)
            keep_this = keep == "all"
            if keep != "all":
                result = pdf_text(path)
                if result is None and keep == "none":
                    # 原本も文字も残らないまま「取得済み」にすると取り直さないので、失敗にして次回に回す
                    raise OSError("文字抽出の失敗（原本を残さない設定）")
                if result is not None:
                    (text_dir or WORK / "text").joinpath(f"{digest}.txt").write_text(result[0], encoding="utf-8")
                image = result is None or classify_text(*result) != "文字あり"
                if image and keep == "none":
                    # 文字の無い（画像の）PDF は OCR 用の原本が要る。残さない設定では取得済みにせず、失敗にして次回に回す
                    raise OSError("文字の無い PDF（原本を残さない設定）")
                keep_this = keep == "image" and image
            material = ""
            if keep_this and free_bytes(storage) <= MIN_FREE_BYTES:
                # 原本を残せないまま「取得済み」にすると次回も取り直さないので、失敗にして残りの取得もやめる
                with lock:
                    state["stop"] = True
                raise OSError(f"保管庫の空きが{MIN_FREE_BYTES // 1024 ** 3}GiB以下で原本を保管できない")
            if keep_this:
                material = register_once(input_path=path, source_url=url, task_id=TASK_ID,
                                         title=f"政治資金収支報告書 {row.get('年分', '')} {row.get('団体名', '')}".strip(),
                                         purpose="議員・党と団体の関係を一次資料で記録する", storage_root=storage, observed_at=observed)
            return {"PDF_URL": url, "sha256": digest, "bytes": str(len(body)), "material_id": material, "取得日時": observed, "状態": "取得済み"}
        except Exception as error:
            return {"PDF_URL": url, "sha256": "", "bytes": "", "material_id": "", "取得日時": observed, "状態": f"失敗：{str(error)[:120]}"}
        finally:
            if path is not None:
                path.unlink(missing_ok=True)  # 保管庫には写しを登録してあるので、作業用の控えは消す

    def run(rows: list[dict[str, str]]) -> None:
        for row in rows:
            if not take():
                return
            record = fetch_one(row)
            with lock:
                out.append(record)
            if wait:
                time.sleep(wait)

    if workers <= 1:
        for rows in queues.values():
            run(rows)
    else:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(run, sorted(queues.values(), key=len, reverse=True)))
    return out


def safe_url(url: str) -> str:
    """索引の href に混じる空白などをパーセント符号にする（urllib は制御文字・空白入りの URL を開けない）。"""
    return quote(url.strip(), safe=":/?&=%#~+,;@!$'()*[]")


def _get_bytes(url: str) -> bytes:
    url = safe_url(url)
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


# ---------- pages：画像 PDF の頁を様式で振り分ける ----------

# 収支報告書の様式の番号（各頁の左上の「（その○）」）。中身は手書き・印字の画像なので、OCR では本文は読めないが、
# 印刷された様式番号は読める。AI に読ませるのは、表紙（帰属の判定）と寄附・パーティー・支出の内訳の頁だけにする（pages_to_read）。
#   その1＝表紙、その2＝収支総括表、その3〜6＝収入の内訳、その7＝寄附の内訳、その8〜12＝あっせん・パーティー等、
#   その13＝支出の総括表、その14＝経常経費の内訳、その15＝政治活動費の内訳（寄附・交付金を含む）、その16＝同、その17〜＝資産等
FORM_MARK = re.compile(r"その\s*([0-9０-９]{1,2})")
PAGE_HEADER = ["sha256", "頁", "様式"]


def page_forms(path: Path, run=subprocess.run) -> list[str]:
    """頁ごとの様式番号（読めない頁は空）。左上だけを 150dpi で描いて tesseract に読ませる（1頁0.3秒ほど）。"""
    def ok(done):
        # 描画・OCR が異常終了したら例外にして、classify_pages が済みにせず次回に試し直すようにする
        if done.returncode != 0:
            raise subprocess.SubprocessError(f"{done.args[0]} が終了コード {done.returncode} で止まった")
        return done.stdout

    info = ok(run(["pdfinfo", str(path)], capture_output=True, text=True, timeout=60))
    pages = int(next((l.split()[-1] for l in info.splitlines() if l.startswith("Pages:")), "0"))
    forms = []
    for page in range(1, pages + 1):
        image = ok(run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", "150", "-gray", "-x", "0", "-y", "0",
                     "-W", "700", "-H", "230", "-png", str(path)], capture_output=True, timeout=120))
        text = ok(run(["tesseract", "stdin", "stdout", "-l", "jpn", "--psm", "6"], input=image, capture_output=True,
                      timeout=120, env={**os.environ, "OMP_THREAD_LIMIT": "1"})).decode("utf-8", "replace")
        flat = re.sub(r"\s+", "", text)
        mark = FORM_MARK.search(flat)
        # 別紙（欄に入りきらなかった名前などの一覧。「*1」の本当の名前が載る）と監査報告書は様式番号が無いので、見出しの語で見分ける
        forms.append(nfkc(mark.group(1)) if mark else "別紙" if "別紙" in flat else "監査" if "監査" in flat else "")
    # 表紙は様式番号が別の位置にあって読めないことが多い。1頁目が空なら表紙とみなす。
    # 途中の読めない頁は、直前の頁の続き（同じ様式の2頁目以降）とみなす
    if forms and not forms[0]:
        forms[0] = "1"
    for i in range(1, len(forms)):
        forms[i] = forms[i] or forms[i - 1]
    return forms


def pages_to_read(forms: list[str]) -> list[int]:
    """AI に読ませる頁（1始まり）。表紙と、最初の寄附・支出等の内訳（その7〜16）から資産等（その17〜）の手前まで、それと末尾の別紙。
    様式番号の読み違い（14 を 13 と読むなど）で内訳の頁を落とさないよう、番号ごとではなく範囲で選ぶ。"""
    numbers = [int(f) if f.isdigit() else 0 for f in forms]
    start = next((i for i, n in enumerate(numbers) if 7 <= n <= 16), None)
    picked = [1] if forms else []
    if start is None:
        return picked
    # 終わりは「最後の内訳の頁の次」。途中の頁の番号を 17 以上と読み違えても（14 を 19 と読むなど）、後ろの内訳を落とさない
    end = max(i for i, n in enumerate(numbers) if 7 <= n <= 16) + 1
    # 別紙は報告書の末尾にある。明細の「*1」などの本当の名前を引くために読む
    notes = [i + 1 for i in range(end, len(forms)) if forms[i] == "別紙"]
    return picked + [i + 1 for i in range(start, end) if i > 0] + notes


def classify_pages(manifest: list[dict[str, str]], done: list[dict[str, str]], storage: Path = MATERIALS,
                   only: set[str] | None = None, workers: int = 4, run=subprocess.run) -> list[dict[str, str]]:
    """原本のある PDF の頁を様式で振り分ける。済んだ sha256 は飛ばす。only を渡すとその PDF_URL だけ。"""
    from concurrent.futures import ThreadPoolExecutor

    seen = {r["sha256"] for r in done}
    targets = []
    for m in manifest:
        sha = m.get("sha256", "")
        if m.get("状態") == "取得済み" and sha and sha not in seen and (only is None or m["PDF_URL"] in only):
            seen.add(sha)
            path = material_path(sha, manifest, storage)
            if path is not None:
                targets.append((sha, path))

    def one(item):
        sha, path = item
        try:
            return [{"sha256": sha, "頁": str(i), "様式": form} for i, form in enumerate(page_forms(path, run), 1)]
        except (subprocess.SubprocessError, OSError, ValueError):
            return []  # 次回に試し直す

    out = list(done)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for rows in pool.map(one, targets):
            out += rows
    return out


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
LEGAL_ENTITY_WORDS = ("株式会社", "有限会社", "合同会社", "合資会社", "合名会社", "(株)", "(有)", "法人")
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
    # 系統A（規則）と AI の読み手で同じ鍵になるよう、reader_name と同じ正規化（異体字の寄せ）をしてから作る
    return "個人#" + hashlib.sha256(re.sub(r"\s", "", reader_name(name)).encode("utf-8")).hexdigest()[:16]


def _key(row: dict[str, str]) -> tuple:
    # 伏せた個人は表示名「（個人）」ではなく照合キーで突き合わせる（別人を一致にしないため）
    name = row.get("照合キー") or re.sub(r"\s", "", reader_name(row.get("相手方", "")))
    # 相手方種別も合わせる（個人か団体かで、名前の伏せ方と公表期限の扱いが変わるため）。頁も合わせ、別の明細の対応付けを防ぐ。
    return (row.get("sha256"), row.get("区分"), row.get("費目", ""), row.get("相手方種別", ""), name, row.get("金額"), row.get("年月日"), row.get("頁", ""))


DONOR_KINDS = {"個人", "法人その他の団体", "政治団体"}


def adoptable(row: dict[str, str]) -> bool:
    """採ってよい行か。費目が入力不備、金額が無い、日付欄のある明細で年月日が無い、受けた寄附で寄附者の区分が無い行は、
    両系統が同じように欠けていても採らない（空どうしの一致で不完全な行や、伏せるべき個人名が入るのを防ぐ）。"""
    if row.get("費目", "").startswith("入力不備"):
        return False
    if not str(row.get("金額", "")).isdigit() or int(row["金額"]) <= 0:
        return False
    if not str(row.get("頁", "")).isdigit():
        return False  # 根拠の頁が無い行は、別の頁の明細と取り違えるおそれがあり、出典も残らない
    if row.get("区分") != "パーティー対価" and not row.get("年月日"):
        return False
    return row.get("区分") != "受けた寄附" or row.get("相手方種別") in DONOR_KINDS


def compare(line_a: list[dict[str, str]], line_b: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """系統A と系統B で、区分・相手方・金額・年月日がそろった行だけを採る。片方だけの行は食い違いに出す。"""
    from collections import Counter

    usable = adoptable
    a, b = Counter(_key(r) for r in line_a if usable(r)), Counter(_key(r) for r in line_b if usable(r))
    agreed, disagreed = [], []
    used = Counter()
    for row in line_a:
        k = _key(row)
        if usable(row) and used[k] < min(a[k], b[k]):
            used[k] += 1
            agreed.append({**row, "照合": "A・B一致"})
        else:
            disagreed.append({**row, "照合": "Aだけ"})
    left = b - a
    for row in line_b:
        k = _key(row)
        if not usable(row) or left[k] > 0:
            left[k] -= 1
            disagreed.append({**row, "照合": "Bだけ"})
    return agreed, disagreed


def tie_break(agreed: list[dict[str, str]], disagreed: list[dict[str, str]],
              line_c: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """A・Bが食い違った行を、その頁だけを読んだ3つ目の読み手（C）で決める。C が A か B の片方と
    区分・相手方・金額・年月日まで一致した行だけを採る（独立した2つの読みの一致という基準は変えない）。
    C は食い違いのあった頁だけを読むので、その頁の C の行だけを使う。"""
    from collections import Counter

    pages = {(r.get("sha256"), r.get("頁")) for r in disagreed}
    left = Counter(_key(r) for r in line_c if (r.get("sha256"), r.get("頁")) in pages and adoptable(r))
    # C は食い違った頁全体を読むので、A・Bですでに採った同じ明細の分は C の件数から差し引く
    left = left - Counter(_key(r) for r in agreed)
    out_agreed, out_disagreed = list(agreed), []
    taken: Counter = Counter()
    for row in disagreed:
        k = _key(row)
        # 同じ行が複数あっても、C の行数までしか採らない
        if adoptable(row) and taken[k] < left[k]:
            taken[k] += 1
            side = "A" if row.get("照合") == "Aだけ" else "B"
            out_agreed.append({**row, "照合": f"{side}・C一致"})
        else:
            out_disagreed.append(row)
    return out_agreed, out_disagreed


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


NAME_FOLDS = str.maketrans({"壯": "壮", "濱": "浜", "髙": "高", "﨑": "崎", "德": "徳", "濵": "浜", "邊": "辺", "邉": "辺", "齋": "斎", "齊": "斉"})


def reader_name(name: str) -> str:
    """AI の読み手が写した名前の表記をそろえる（NFKC で ㈱→(株)、異体字を通用字に、空白を1つに）。"""
    return re.sub(r"\s+", " ", nfkc(name).translate(NAME_FOLDS)).strip()


def fold_name(name: str) -> str:
    """人名の異体字を通用字に寄せる（人物IDとの照合用）。"""
    return nfkc(name or "").translate(NAME_FOLDS)


def manifest_meta(manifest: list[dict[str, str]], index: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """sha256 ごとの出典（PDF_URL・年分・報告団体）。読み手が行を出したかどうかに関係なく、原簿から決める。"""
    index_by_url = {r["PDF_URL"]: r for r in index}
    out = {}
    for m in manifest:
        if m.get("sha256") and m["sha256"] not in out:
            i = index_by_url.get(m["PDF_URL"], {})
            out[m["sha256"]] = {"sha256": m["sha256"], "PDF_URL": m["PDF_URL"], "年分": i.get("年分", ""), "報告団体": i.get("団体名", "")}
    return out


def load_line_b(directory: Path, meta_by_sha: dict[str, dict[str, str]], line: str = "B") -> list[dict[str, str]]:
    """系統B（別の読み手）の結果。<sha256>.json に {"関係議員名", "根拠", "行": [{区分,費目,相手方,相手方種別,金額,年月日,頁}]}
    （古い形の、行の配列だけでもよい。そのときは議員への帰属が未確認になる）。
    区分は KINDS のどれか。費目は区分が「支出」なら EXPENSE_ITEMS のどれか（必須）、「出した寄附」なら「寄附・交付金」（省略可）、
    寄附・パーティー対価なら空。支出で費目が無い・違う行は「入力不備」として一致させない。
    画像 PDF の系統A（Bとは別の AI の読み手）も同じ形なので、line="A" で読む。"""
    rows = []
    if not directory or not directory.is_dir():
        return rows
    for path in sorted(directory.glob("*.json")):
        sha = path.stem
        for item in _line_b_items(json.loads(path.read_text(encoding="utf-8"))):
            # 読み手ごとの表記のゆれ（㈱と(株)、髙と高など）をそろえてから突き合わせる
            item = {**item, "相手方": reader_name(item.get("相手方", ""))}
            kind = item.get("相手方種別", "")
            if item.get("区分") != "受けた寄附":
                # 寄附者の区分の欄がある「受けた寄附」以外は、系統Aの規則と同じく名前から決める（読み手ごとの判断のゆれを消す）。
                # ただし読み手が「個人」と書いたものは、法人格が名前に出ていない限り個人のまま（「○○商店」のような個人事業主の名前を伏せ損ねないため）
                guessed = counterpart_kind(item.get("相手方", ""), "")
                legal = any(w in item.get("相手方", "") for w in LEGAL_ENTITY_WORDS)
                kind = "個人" if kind == "個人" and not legal else guessed
            day = str(item.get("年月日", ""))
            era = DATE.search(nfkc(day))
            if era:
                day = wareki(era)  # 「R6/7/1」「令和6年7月1日」のままでも系統Aと同じ形に直す
            hidden = kind == "個人" and item.get("区分") in PRIVATE_KINDS
            expense = item.get("費目", "")
            if item.get("区分") == "出した寄附" and not expense:
                expense = "寄附・交付金"
            elif item.get("区分") == "支出" and expense not in EXPENSE_ITEMS:
                expense = f"入力不備：費目「{expense}」"  # 一致させずに食い違いへ回す
            name = INDIVIDUAL if hidden else item.get("相手方", "")
            rows.append({**meta_by_sha.get(sha, {"sha256": sha}), "系統": line, "区分": item.get("区分", ""), "費目": expense, "相手方": name,
                         "照合キー": private_key(item.get("相手方", "")) if hidden else "",
                         "相手方種別": kind, "金額": str(item.get("金額", "")).replace(",", ""), "年月日": day, "頁": str(item.get("頁", ""))})
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
            for name in {p["氏名"], *filter(None, re.split(r"[|;、,／/]", p.get("別表記", "")))}:
                ids = by_name.setdefault(canonical(fold_name(name)), [])
                if p["人物ID"] not in ids:
                    ids.append(p["人物ID"])
    return by_name


# ---------- 議員と団体の対応表（総務省の政治団体名簿） ----------

def _cell(value) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\n", "")).strip()


PARTS = ("", "１", "２", "１・２")


def parse_roster(path: Path, kind: str, roster: str, url: str = "", material_id: str = "") -> list[dict[str, str]]:
    """名簿 PDF の表（氏名・衆参・選挙区・総務大臣届出の団体名と区分・都道府県選管届出の届出先と団体名と区分）を行にする。
    1人の議員の2行目以降は氏名欄が空なので、直前の議員を引き継ぐ（ページをまたいでも同じ）。"""
    import pdfplumber

    out, current = [], None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    cells = [_cell(c) for c in row] + [""] * 8
                    name = (row[0] or "").strip()
                    if name.startswith(("氏名", "【")) or cells[3] == "団体名" or cells[6] == "団体名":
                        continue
                    if name:
                        lines = [l.strip() for l in name.split("\n") if l.strip()]
                        alias = re.sub(r"^[（(]|[）)]$", "", lines[1]) if len(lines) > 1 else ""
                        current = {"氏名": lines[0], "届出上の氏名": alias, "院": cells[1], "選挙区": cells[2]}
                    if not current:
                        continue
                    common = {**current, "種別": kind, "名簿": roster, "資料URL": url, "material_id": material_id}
                    # 資金管理団体の名簿は区分欄が無い（氏名・衆参・選挙区・団体名・届出先選管・団体名）
                    if kind == "資金管理団体" and len(row) < 8:
                        pairs = [("総務大臣", cells[3], ""), (cells[4], cells[5], "")]
                    else:
                        pairs = [("総務大臣", cells[3], cells[4]), (cells[5], cells[6], cells[7])]
                    for office, group, part in pairs:
                        # 長い団体名がはみ出して区分欄に入ることがある（「…（慶歯」「会）２」）。区分の数字だけを残して名前に戻す
                        spill = re.fullmatch(r"(.*?)(１・２|１|２)(.*)", part) if part not in PARTS else None
                        if spill:
                            group, part = group + spill.group(1) + spill.group(3), spill.group(2)
                        if group:
                            out.append({**common, "届出先": office, "団体名": group, "区分": part})
    return out


def roster_rows(get_bytes=None, storage: Path = MATERIALS) -> list[dict[str, str]]:
    """ROSTERS の名簿 PDF を落として保管庫に登録し、表を読む。"""
    from scripts.register_external_material import register_once

    get_bytes = get_bytes or _get_bytes
    tmp = WORK / "rosters"
    tmp.mkdir(parents=True, exist_ok=True)
    out = []
    for url, kind, roster in ROSTERS:
        body = get_bytes(url)
        path = tmp / f"{hashlib.sha256(body).hexdigest()}.pdf"
        path.write_bytes(body)
        observed = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        material = register_once(input_path=path, source_url=url, task_id=TASK_ID, title=f"現職国会議員の{kind}一覧（{roster}）",
                                 purpose="報告団体と議員の対応（関係議員名）の根拠を残す", storage_root=storage, observed_at=observed)
        out += parse_roster(path, kind, roster, url, material)
    return out


def group_key(name: str) -> str:
    """団体名の照合キー。かっこ書き（代表者名・略称）と空白・異体字セレクタを落とす（索引と名簿で代表者名の字が違うことがある）。"""
    text = re.sub(r"[\ufe00-\ufe0f\U000e0100-\U000e01ef]", "", nfkc(name))
    text = re.sub(r"\([^()]*\)", "", text)
    return re.sub(r"\s+", "", text)


def roster_lookup(members: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    """(届出先, 団体名の照合キー) → 議員の氏名の集合。総務省の索引は届出先「総務大臣」、県の索引は県名で引く。"""
    from scripts.person_ids import canonical

    # 名簿によって氏名の書き方（空白・ひらがな・異体字）が違うので、氏名と届出上の氏名でつながる人は1人にまとめる
    parent: dict[str, str] = {}

    def root(name: str) -> str:
        while parent.setdefault(name, name) != name:
            name = parent[name]
        return name

    for m in members:
        if m.get("届出上の氏名"):
            parent[root(canonical(m["届出上の氏名"]))] = root(canonical(m["氏名"]))
    out: dict[tuple[str, str], dict[str, str]] = {}
    for m in members:
        out.setdefault((m["届出先"], group_key(m["団体名"])), {}).setdefault(root(canonical(m["氏名"])), m["氏名"])
    return out


def member_of(meta: dict[str, str], lookup: dict[tuple[str, str], dict[str, str]]) -> str:
    """索引の関係議員名。無ければ対応表で団体名から引き、議員が1人に決まるときだけ返す。"""
    if meta.get("関係議員名"):
        return meta["関係議員名"]
    source = meta.get("出典", "")
    office = "総務大臣" if source.startswith("総務省") or "WARP" in source else source
    names = lookup.get((office, group_key(meta.get("団体名", ""))), {})
    return next(iter(names.values())) if len(names) == 1 else ""


def attribution_check(member: str, line_b_member: str | None, line_a_member: str | None = None) -> str:
    """議員への帰属の照合。索引（名簿）の関係議員名と、表紙を読んだ2つの読み手（系統B・AI の系統A）の判定を突き合わせ、2者が合えば採る。
    「A・B一致」＝索引と系統B、「読み手A・B一致」＝索引に関係議員名が無く、2つの読み手の表紙の判定が一致。
    2つの AI の読み手が食い違うときは、索引と片方が合っても人物IDを付けない（個人への帰属は2系統の AI の一致が要る、AGENTS.md）。"""
    if not member:
        if line_a_member and line_b_member and same_name(line_a_member, line_b_member):
            return "読み手A・B一致"
        return "関係議員名なし"
    if line_b_member is None:
        return "系統Bの判定なし"
    if same_name(member, line_b_member):
        return "A・B一致"
    return f"食い違い：B「{line_b_member}」"


LINKED_CHECKS = {"A・B一致", "読み手A・B一致"}


def same_name(a: str, b: str) -> bool:
    """同じ氏名か（人物IDの正規化に、報告書でよく出る異体字の寄せを足して比べる）。"""
    from scripts.person_ids import canonical

    return bool(a) and canonical(fold_name(a)) == canonical(fold_name(b))


def link(rows: list[dict[str, str]], index_by_url: dict[str, dict[str, str]], persons: list[dict[str, str]],
         attribution: dict[str, str] | None = None, members: list[dict[str, str]] | None = None,
         cover_a: dict[str, str] | None = None) -> list[dict[str, str]]:
    """報告団体の関係議員名を人物IDに結ぶ。帰属が2者で一致し（attribution_check）、候補が1人のときだけ結ぶ。
    一致しない・判定が無い・候補が0人か2人以上のものは空のまま（算入外、「帰属の照合」に理由）。"""
    from scripts.org_names import org_key
    from scripts.person_ids import canonical

    by_name = person_index(persons)
    attribution = attribution or {}
    lookup = roster_lookup(members or [])
    out = []
    for row in rows:
        meta = index_by_url.get(row.get("PDF_URL", ""), {})
        member = member_of(meta, lookup)
        sha = row.get("sha256", "")
        check = attribution_check(member, attribution.get(sha), (cover_a or {}).get(sha))
        if check == "読み手A・B一致":
            member = attribution[sha]
        ids = by_name.get(canonical(fold_name(member)), []) if check in LINKED_CHECKS else []
        out.append({**row, "相手方": public_name(row), "支払先キー": payee_key(row),
                    "団体名キー": "" if row.get("相手方種別") == "個人" else org_key(row.get("相手方", "")), "報告団体": row.get("報告団体") or meta.get("団体名", ""), "関係議員名": member,
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
        # 出した寄附（自分の後援会・党支部への資金移動が大半）は支払いの偏りではないので入れない。
        if key and row["区分"] == "支出":
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
FLAG_MULTI_YEARS = 3         # 同じ支払先に3年分以上、かつ合計の20%以上（ホテル・税理士など毎年使う先の1割程度は普通なので）
FLAG_MULTI_SHARE = 0.20


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
    parser.add_argument("phase", choices=["crawl", "roster", "download", "extract", "pages", "parse", "compare", "link", "all", "status"])
    parser.add_argument("--monthly", action="store_true", help="前回の取得から28日たっていなければ何もしない（自動更新用）")
    parser.add_argument("--limit", type=int, default=None, help="download で落とす件数の上限（試し用）")
    parser.add_argument("--minutes", type=float, default=None, help="download を打ち切る分数（--monthly のときは既定で40分）")
    parser.add_argument("--wait", type=float, default=1.0, help="1件ごとの待ち秒数")
    parser.add_argument("--ocr-dir", type=Path, default=WORK / "ocr", help="画像 PDF の OCR 結果 <sha256>.txt の置き場")
    parser.add_argument("--line-a-ai", type=Path, default=WORK / "line-a-ai", help="画像 PDF の系統A（Bとは別の AI の読み手）の結果 <sha256>.json の置き場（形は系統Bと同じ）")
    parser.add_argument("--line-c", type=Path, default=WORK / "line-c", help="A・Bが食い違った頁だけを読んだ3つ目の読み手の結果 <sha256>.json（形は系統Bと同じ）")
    parser.add_argument("--line-b", type=Path, default=WORK / "line-b", help="系統B の結果 <sha256>.json の置き場")
    parser.add_argument("--storage", type=Path, default=MATERIALS, help="原本の保管庫（既定は .local/external-materials。全件で数十GBになるので、容量の大きい場所を指せる）")
    parser.add_argument("--keep", choices=KEEP_CHOICES, default="all", help="原本の保管：all／image（文字の無い PDF だけ）／none。all 以外は取得時に文字を抜く")
    parser.add_argument("--workers", type=int, default=1, help="download で同時に取るホストの数（同じホストへは1本ずつ）")
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
    phases = ["crawl", "roster", "download", "extract", "parse", "compare", "link"] if args.phase == "all" else [args.phase]
    if offline_only:
        phases = [p for p in phases if p not in {"crawl", "roster", "download"}]
    text_dir = WORK / "text"
    for phase in phases:
        if phase == "crawl":
            rows = merge_index(read_csv(INDEX), crawl(sources, wait=args.wait, keep=keep_index_page))
            write_csv(INDEX, INDEX_HEADER, rows)
            print(f"一覧 {len(rows)}件")
        elif phase == "roster":
            try:
                members = roster_rows(storage=args.storage)
            except Exception as error:  # 通信・PDF の読み取りの失敗のどれでも
                # 名簿が取れなくても、手元の対応表のまま後の段（取得・再計算）は続ける
                print(f"名簿の取得に失敗したので、前回の対応表を使う：{error}")
            else:
                write_csv(MEMBER_GROUPS, MEMBER_GROUP_HEADER, members)
                print(f"議員と団体の対応 {len(members)}行（議員 {len({m['氏名'] for m in members})}人）")
        elif phase == "download":
            # 自動更新の1段の上限（daily_update の Run.command は3600秒）に、一覧作り・抽出の分を残して収める
            manifest = download(read_csv(INDEX), read_csv(MANIFEST), wait=args.wait, limit=args.limit,
                                minutes=args.minutes if args.minutes is not None else (MONTHLY_MINUTES if args.monthly else None),
                                save=lambda rows: write_csv(MANIFEST, MANIFEST_HEADER, rows),
                                keep=args.keep, text_dir=text_dir, workers=args.workers, storage=args.storage)
            write_csv(MANIFEST, MANIFEST_HEADER, manifest)
            fetched = {m["PDF_URL"] for m in manifest if m["状態"] == "取得済み"}
            tried = {m["PDF_URL"] for m in manifest}
            remaining = sum(1 for r in read_csv(INDEX) if r.get("PDF_URL") and r["PDF_URL"] not in tried)
            # まだ試していない PDF がある間は月次の記録を進めない（翌日の自動更新で続きを取る）。失敗分は翌月に試し直す。
            if not remaining:
                LAST_FETCH.write_text(str(date.today()) + "\n", encoding="utf-8")
            print(f"取得済み {len(fetched)}件・失敗 {sum(1 for m in manifest if m['状態'] != '取得済み')}件・残り {remaining}件")
        elif phase == "extract":
            texts = extract(read_csv(MANIFEST), text_dir, args.ocr_dir, storage=args.storage)
            write_csv(ACQUIRED / "texts.csv", TEXT_HEADER, texts)
            write_csv(WORK / "ocr-queue.csv", TEXT_HEADER, [t for t in texts if t["状態"].startswith("画像")])
            print(f"文字あり {sum(t['状態'] == '文字あり' for t in texts)}件・OCR {sum(t['状態'] == 'OCR' for t in texts)}件・OCR待ち {sum(t['状態'].startswith('画像') for t in texts)}件")
        elif phase == "pages":
            pages = classify_pages(read_csv(MANIFEST), read_csv(WORK / "pages.csv"), storage=args.storage, workers=args.workers)
            write_csv(WORK / "pages.csv", PAGE_HEADER, pages)
            by_sha: dict[str, list[str]] = {}
            for r in pages:
                by_sha.setdefault(r["sha256"], []).append(r["様式"])
            print(f"頁 {len(pages)}件（AI が読む頁 {sum(len(pages_to_read(f)) for f in by_sha.values())}件）")
        elif phase == "parse":
            meta_by_sha = manifest_meta(read_csv(MANIFEST), read_csv(INDEX))
            # AI の読み手の結果がある PDF（画像 PDF）は、規則で読めた一部の行ではなく AI の結果を系統Aにする
            ai_read = {path.stem for path in args.line_a_ai.glob("*.json")} if args.line_a_ai.is_dir() else set()
            rows = []
            for sha, meta in meta_by_sha.items():
                path = text_dir / f"{sha}.txt"
                if sha not in ai_read and path.exists():
                    rows += parse_lines(path.read_text(encoding="utf-8"), meta)
            # 画像 PDF は文字が無いので、系統A は規則ではなく別の AI の読み手の結果を使う（文字のある PDF は規則のまま）
            meta_ai = {sha: meta for sha, meta in meta_by_sha.items() if sha in ai_read}
            rows += [r for r in load_line_b(args.line_a_ai, meta_ai, line="A") if r["sha256"] in meta_ai]
            write_csv(WORK / "line-a.csv", ROW_HEADER, rows)
            print(f"系統A {len(rows)}行")
        elif phase == "compare":
            line_a = read_csv(WORK / "line-a.csv")
            # 系統Aが1行も読めなかった PDF でも、B・C一致で採る行に出典が付くよう、原簿（manifest・索引）から補う
            meta = manifest_meta(read_csv(MANIFEST), read_csv(INDEX))
            agreed, disagreed = compare(line_a, load_line_b(args.line_b, meta))
            line_c = [r for r in load_line_b(args.line_c, meta, line="C")]
            if line_c:
                agreed, disagreed = tie_break(agreed, disagreed, line_c)
            write_csv(WORK / "agreed.csv", ROW_HEADER + ["照合"], agreed)
            # 食い違いは照合前の生の行（伏せていない個人名を含みうる）なので、Git に入れない .local に置く
            write_csv(WORK / "disagreements.csv", ROW_HEADER + ["照合"], disagreed)
            print(f"一致 {len(agreed)}行・食い違い {len(disagreed)}行")
        elif phase == "link":
            index_by_url = {r["PDF_URL"]: r for r in read_csv(INDEX)}
            rows = link(read_csv(WORK / "agreed.csv"), index_by_url, read_csv(PERSONS), line_b_attribution(args.line_b), read_csv(MEMBER_GROUPS), line_b_attribution(args.line_a_ai))
            write_csv(DERIVED / "relations.csv", RELATION_HEADER, rows)
            spending = spending_by_member(rows)
            (DERIVED / "spending-by-member.json").write_text(json.dumps({"説明": "議員ごとの関係政治団体の支出（政治資金収支報告書、系統A・B一致分）。点数には使わない。個人の支払先は公表期間（3年）の間だけ報告書どおりの名前を出し、住所は出さない。寄附者・パーティー券購入者の個人は名前を出さない。", "議員": spending}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(f"関係 {len(rows)}行（人物IDに結んだもの {sum(1 for r in rows if r['人物ID'])}行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
