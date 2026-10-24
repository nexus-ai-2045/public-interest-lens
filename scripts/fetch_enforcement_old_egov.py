#!/usr/bin/env python3
"""第77〜141回の成立法の施行日を、e-Gov 法令 API v2 から法令番号で取る（暫定値）。

入力:  data/acquired/bill-census-old/enacted_old.csv
       （回次,法律番号,法令番号,公布日,題名,出典URL,一覧URL）
出力:  data/acquired/enforcement-dates-old/enforcement_old.csv
       data/acquired/enforcement-dates-old/manifest.csv（url, path, sha256, http, fetched_at）
原本:  .local/enforcement-dates-old/raw/*.json（git 管理外）

方針（scripts/fetch_enforcement_dates.py と apply_enforcement_egov_browser.py の規則に合わせる）:
(a) /laws?law_num=<法令番号> でその法律自体が e-Gov にあれば、/law_revisions/{law_id} のうち
    amendment_law_num が空または当該法令番号の版の amendment_enforcement_date（初めの版）を取る。
    初めの版を e-Gov が保持しない（最も古い版が別の改正法の版）ときは取らない。
(b) 無ければ、題名の「〇〇法の一部を改正する法律」の〇〇から現行法令を /laws?law_title= で引き、
    その /law_revisions のうち amendment_law_num が当該法令番号に一致する版の
    amendment_enforcement_date を取る。版ごとの日が2日以上あれば（段階施行の可能性）確定せず、最も早い日を候補として理由に書く。
(c) どれも取れなければ施行日を空にし、備考に理由を書く。e-Gov に無いことで取れないものは
    「R16 待ち（*.go.jp の許可後に衆議院の附則で取る）」と書く。
推測では埋めない。公布日より前の日は採らない。

使い方（通信するのは別セッション）:
  python3 scripts/fetch_enforcement_old_egov.py --dry-run --limit 20   # 通信せず、何を引くかだけ表示
  python3 scripts/fetch_enforcement_old_egov.py --limit 20             # 試し
  python3 scripts/fetch_enforcement_old_egov.py                        # 全件（既に raw がある URL は取り直さない）
  python3 scripts/fetch_enforcement_old_egov.py --prior-manifest 前の manifest.csv  # manifest を作り直すとき、最初の取得時刻を引き継ぐ
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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:  # 直接実行（python3 scripts/...）とモジュール実行の両方に対応
    from scripts.fetch_enforcement_dates import ERAS, amended_titles, parse_law_num, title_candidates
    from scripts.register_external_material import register_once
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.fetch_enforcement_dates import ERAS, amended_titles, parse_law_num, title_candidates
    from scripts.register_external_material import register_once

ROOT = Path(__file__).resolve().parents[1]
API = "https://laws.e-gov.go.jp/api/2/"
USER_AGENT = "public-interest-lens/1.0 (enforcement-dates-old; research use)"
DEFAULT_SLEEP = 0.5

INPUT = ROOT / "data/acquired/bill-census-old/enacted_old.csv"
OUT_DIR = ROOT / "data/acquired/enforcement-dates-old"
RAW_DIR = ROOT / ".local/enforcement-dates-old/raw"  # 取り直さないための控え。原本は外部資料として登録する
MATERIALS = ROOT / ".local/external-materials"  # AGENTS.md：タスク単位の保管庫（record.json、初期状態 unverified）
TASK_ID = "r1-enforcement-dates-old"

OUT_COLS = ["回次", "法律番号", "法令番号", "公布日", "題名", "施行日", "施行日の種別", "取得経路", "照合URL", "備考"]
MANIFEST_COLS = ["url", "path", "sha256", "http", "fetched_at", "material_id"]

KIND_ORIGINAL = "新規法令の初めの版（e-Gov 改正履歴、暫定値）"
KIND_AMEND = "改正履歴の amendment_law_num 一致（e-Gov、暫定値）"
ROUTE_A = "e-Gov 法令API v2（laws?law_num → law_revisions）"
ROUTE_B = "e-Gov 法令API v2（laws?law_title → law_revisions）"
R16 = "R16 待ち（*.go.jp の許可後に衆議院の附則で取る）"
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# 「〇〇法等の一部を改正する法律」の「等」（改正対象を省いている）。「都市公園等整備緊急措置法」のような名前の中の「等」は含めない
ABBREVIATED = re.compile(r"(法|法律|令)等の")
# 通信失敗で取れなかった行（e-Gov に無いのではないので R16 の対象にしない）
FETCH_FAILED = "e-Gov への通信に失敗（再実行で取り直す）"
# 公布日から2年より後の日は確定しない（apply_enforcement_egov_browser.original_ok と同じ線）。
# e-Gov が初めの版を持たず後年の版の日を返す、または未施行の改正に仮の日（2117-12-31 など）が入っていることがある
LATE_DAYS = 730


# ---------- 純粋関数（通信しない） ----------

def parse_laws_response(data: dict | None) -> list[dict]:
    """/laws の応答 → [{law_id, law_num, title}]。応答の形: laws[].law_info{law_id,law_num}, revision_info{law_title}。"""
    out = []
    for row in (data or {}).get("laws") or []:
        info = row.get("law_info") or {}
        if info.get("law_id"):
            out.append({"law_id": info["law_id"], "law_num": info.get("law_num") or "",
                        "title": (row.get("revision_info") or {}).get("law_title") or ""})
    return out


def pick_by_law_num(laws: list[dict], law_num: str) -> str | None:
    """法令番号が完全一致する法令の law_id（検索は部分一致なので絞る）。"""
    for law in laws:
        if law["law_num"] == law_num:
            return law["law_id"]
    return None


def pick_by_title(laws: list[dict], title: str) -> list[str]:
    """現行題名が完全一致する法令の law_id（既存実装と同じ）。"""
    return [law["law_id"] for law in laws if law["title"] == title]


def existed_before(laws: list[dict], own: tuple[str, int, int]) -> list[dict]:
    """改正法より前からあった法令だけ残す（後から公布された同名の法令は改正の対象になり得ない）。
    法令番号の年が改正法より後、または同じ年で番号が後のものを外す。法令番号を読めないものは残す。"""
    mine = (ERAS[own[0]][1] + own[1], own[2])
    out = []
    for law in laws:
        n = parse_law_num(law.get("law_num"))
        if n is None or (ERAS[n[0]][1] + n[1], n[2]) < mine:
            out.append(law)
    return out


def _valid_date(value) -> bool:
    """形だけでなく暦の上でもある日か（1976-99-99 は不正）。"""
    if not (isinstance(value, str) and DATE_RE.fullmatch(value)):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def original_enforcement(revs: dict | None, own: tuple[str, int, int]) -> tuple[list[str], str]:
    """(a) 初めの版の施行日。(日付のリスト, 備考)。
    初めの版 = amendment_law_num が空、または当該法令番号の版。無ければ e-Gov は初めの版を保持しない。"""
    rows = (revs or {}).get("revisions") or []
    dates, undated = [], 0
    for r in rows:
        num = r.get("amendment_law_num")
        if not num or parse_law_num(num) == own:
            if _valid_date(r.get("amendment_enforcement_date")):
                dates.append(r["amendment_enforcement_date"])
            else:
                undated += 1
    if dates and undated:
        # 初めの版の候補に施行日の無い版がある。その版が別の日に施行されたかもしれないので確定しない
        return [], f"初めの版の候補に施行日の無い版がある（取れた最も早い日 {min(dates)} は候補）"
    if dates:
        return dates, ""
    if rows:
        return [], "e-Gov の改正履歴に初めの版が無い（最も古い版が別の改正法の版）"
    return [], "e-Gov の改正履歴が空"


def amendment_enforcement(revs: dict | None, own: tuple[str, int, int]) -> list[str]:
    """(b) amendment_law_num が当該法令番号に一致する版の施行日（版ごと、重複あり）。"""
    out = []
    for r in (revs or {}).get("revisions") or []:
        num = r.get("amendment_law_num")
        if num and parse_law_num(num) == own and _valid_date(r.get("amendment_enforcement_date")):
            out.append(r["amendment_enforcement_date"])
    return out


def undated_matches(revs: dict | None, own: tuple[str, int, int]) -> int:
    """(b) 当該法令番号に一致するのに施行日が空・不正な版の数。その版が別の日に施行されたかもしれない。"""
    return sum(1 for r in (revs or {}).get("revisions") or []
               if r.get("amendment_law_num") and parse_law_num(r["amendment_law_num"]) == own
               and not _valid_date(r.get("amendment_enforcement_date")))


def pick_earliest(dates: list[str], promulgation: str = "") -> tuple[str, list[str]]:
    """公布日より前の日を除き、最も早い日を返す。(施行日, 備考のリスト)。"""
    notes = []
    ok = sorted(set(d for d in dates if not promulgation or d >= promulgation))
    dropped = sorted(set(dates) - set(ok))
    if dropped:
        notes.append(f"公布日 {promulgation} より前の日（{'、'.join(dropped)}）は採らない")
    if not ok:
        return "", notes
    if len(ok) > 1:
        notes.append(f"複数の版が一致（{len(dates)}版、{len(ok)}日: {'、'.join(ok)}）")
    return ok[0], notes


def several_reason(dates: list[str], promulgation: str) -> str:
    """公布日以後の施行日が2日以上あれば理由（段階施行の可能性があり、主な施行日を決められない）。1日以下なら空。
    fetch_enforcement_dates.pick_main は版の数が最も多い日を採るが、ここは e-Gov が古い版を一部しか持たないので版の数で決めない。"""
    ok = sorted(set(d for d in dates if not promulgation or d >= promulgation))
    if len(ok) < 2:
        return ""
    return f"版ごとの施行日が{len(ok)}日ある（段階施行の可能性。主な施行日を決められない。最も早い日 {ok[0]} は候補）"


def too_late(day: str, promulgation: str) -> bool:
    """公布日から LATE_DAYS 日より後なら True（原本で確かめるまで候補に留める）。"""
    if not (day and promulgation):
        return False
    return date.fromisoformat(day) > date.fromisoformat(promulgation) + timedelta(days=LATE_DAYS)


def late_reason(day: str) -> str:
    return (f"e-Gov の日 {day} が公布日から2年より後（e-Gov が古い版を持たず後年の版の日、"
            f"または未施行の仮の日の可能性。{day} は候補）")


def target_candidates(title: str) -> list[list[str]]:
    """題名 → 改正される側の法令名の候補の組。[] なら「〜の一部を改正する法律」の形ではない。
    先頭の組は題名の〇〇全体の候補、2組目以降は「及び」「並びに」「、」で割った各部分の候補
    （既存 resolve_one と同じ規則: 全体 → 「ための」の後ろ → 末尾の「等」を外した形）。"""
    stem = amended_titles(title)
    if not stem:
        return []
    groups = [title_candidates(stem[0])]
    base = stem[0].rsplit("ための", 1)[-1]
    parts = [p for p in re.split(r"及び|並びに|、", base) if p]
    if len(parts) > 1:
        groups += [title_candidates(p) for p in parts]
    return groups


def laws_url(params: dict) -> str:
    return API + "laws?" + urllib.parse.urlencode(params)


def law_num_url(num: str) -> str:
    return laws_url({"law_num": num, "law_type": "Act", "limit": 5})


def law_title_url(title: str) -> str:
    return laws_url({"law_title": title, "law_type": "Act", "limit": 100})


def revisions_url(law_id: str) -> str:
    return API + f"law_revisions/{law_id}"


# ---------- 通信 ----------

class FetchError(RuntimeError):
    pass


def prior_fetches(path: Path | None) -> dict[tuple[str, str, str], tuple[str, str]]:
    """前の manifest の (url, path, sha256) → (http, fetched_at)。取得時刻の分かる行だけ（控えから作り直しても最初の取得時刻を消さない）。"""
    if not path or not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as fh:
        return {(r["url"], r["path"], r["sha256"]): (r["http"], r["fetched_at"])
                for r in csv.DictReader(fh) if r.get("fetched_at")}


class Client:
    """GET して raw を保存、manifest に記録する。既に raw がある URL は取り直さない。
    生成時にはディレクトリを作らない（--dry-run がファイルを書かないため）。"""

    def __init__(self, raw_dir: Path, manifest_path: Path, sleep: float = DEFAULT_SLEEP, materials: Path | None = None,
                 prior: Path | None = None):
        self.raw_dir, self.manifest_path, self.sleep = raw_dir, manifest_path, sleep
        self.materials = materials or MATERIALS
        self.prior = prior_fetches(prior)
        self.known: set[str] | None = None
        self.last = 0.0

    def _path(self, url: str, status: int = 200) -> Path:
        stem = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
        return self.raw_dir / (f"{stem}.json" if status == 200 else f"{stem}.http{status}.json")

    def cached(self, url: str, repair: bool = True) -> tuple[int, Path] | None:
        """控えがあれば (status, path)。repair=False（--dry-run）なら読めない控えを動かさず、無いものとして返す。"""
        for status in (200, 404):
            p = self._path(url, status)
            if p.exists():
                if status == 200 and _json_object(p.read_bytes()) is None:  # 前の版が残した読めない控えは退避して取り直す
                    if repair:
                        p.replace(p.with_name(p.name + ".invalid"))
                    return None
                return status, p
        return None

    def _known(self) -> set[tuple[str, str]]:
        """manifest にある (URL, 本文の sha256)（初めの1回だけ読む）。同じ URL でも本文が違う控えは別に登録する。"""
        if self.known is None:
            self.known = set()
            if self.manifest_path.exists():
                with self.manifest_path.open(encoding="utf-8", newline="") as fh:
                    self.known = {(r["url"], r["sha256"]) for r in csv.DictReader(fh)}
        return self.known

    def _record(self, url: str, path: Path, body: bytes, http, fetched_at: str) -> None:
        """原本を外部資料として登録し（同じ日・同じ中身は登録し直さない）、manifest に1行足す。"""
        material_id = register_once(input_path=path, source_url=url, task_id=TASK_ID,
                                    title="e-Gov 法令API v2 の応答", purpose="第77〜141回の成立法の施行日（R1）",
                                    storage_root=self.materials, observed_at=fetched_at or None)
        new = not self.manifest_path.exists()
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("a", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            if new:
                w.writerow(MANIFEST_COLS)
            w.writerow([url, _rel(path), hashlib.sha256(body).hexdigest(), http, fetched_at, material_id])
        self._known().add((url, hashlib.sha256(body).hexdigest()))

    def get(self, url: str) -> tuple[int, dict | None]:
        hit = self.cached(url)
        if hit:  # 控えから使うときも登録し、manifest に無い URL は「cache」として残す（取得時刻は分からないので空欄）
            status, p = hit
            body = p.read_bytes()
            digest = hashlib.sha256(body).hexdigest()
            if (url, digest) not in self._known():
                # 前の manifest に同じ URL・置き場所・中身の行があれば、その HTTP と取得時刻を引き継ぐ
                http, fetched_at = self.prior.get((url, _rel(p), digest), ("cache", ""))
                self._record(url, p, body, http, fetched_at)
            return status, (json.loads(body.decode("utf-8")) if status == 200 else None)
        body, status = b"", 0
        for attempt in range(3):
            wait = self.last + self.sleep - time.monotonic()
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
                if status == 404:
                    break
            except (urllib.error.URLError, TimeoutError, OSError):
                body, status = b"", 0
            time.sleep(2 * (attempt + 1))
        if status not in (200, 404):  # 403（プロキシ）・5xx・通信断は答えとして残さない
            raise FetchError(f"{url} -> HTTP {status or '通信失敗'}")
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        path = self._path(url, status)
        if status == 200 and _json_object(body) is None:
            # HTTP 200 の HTML や壊れた JSON は控えに残さず .invalid に退避し、通信失敗として次の実行で取り直す
            path.with_name(path.name + ".invalid").write_bytes(body)
            raise FetchError(f"{url} -> HTTP 200 だが JSON として読めない")
        path.write_bytes(body)
        self._record(url, path, body, status, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        return status, (json.loads(body.decode("utf-8")) if status == 200 else None)


def _json_object(body: bytes) -> dict | None:
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError:  # UnicodeDecodeError と JSONDecodeError
        return None
    return data if isinstance(data, dict) else None


def _rel(path: Path) -> str:
    """manifest に書く置き場所。リポジトリの外（ホーム配下など）ならファイル名だけにする（個人名義を含むパスを残さない）。"""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return path.name


# ---------- 1本分の処理（client は get(url) -> (status, data) を持てばよい） ----------

def resolve(client, row: dict) -> dict:
    """返り値: date, kind, route, urls, notes, reason。取れなければ date は空で reason に理由。"""
    res = {"date": "", "kind": "", "route": "", "urls": [], "notes": [], "reason": ""}
    num, prom, title = row["法令番号"], row["公布日"], row["題名"]
    own = parse_law_num(num)
    if own is None:
        res["reason"] = f"法令番号「{num}」を読めない"
        return res

    def fetch(url):
        res["urls"].append(url)
        return client.get(url)

    # (a) 当該法律自体が e-Gov にあるか
    status, data = fetch(law_num_url(num))
    law_id = pick_by_law_num(parse_laws_response(data), num) if status == 200 else None
    if law_id:
        status, revs = fetch(revisions_url(law_id))
        if status == 200:
            dates, a_note = original_enforcement(revs, own)
            d, notes = pick_earliest(dates, prom)
            if d and several_reason(dates, prom):
                res["notes"] += notes
                res["reason"] = several_reason(dates, prom)
                return res
            if d and too_late(d, prom):
                res["notes"] += notes
                res["reason"] = late_reason(d)
                return res
            if d:
                res.update(date=d, kind=KIND_ORIGINAL, route=ROUTE_A)
                res["notes"] += notes
                return res
            a_note = a_note or "初めの版の施行日が公布日より前"
        else:
            a_note = f"法令 {law_id} の改正履歴を取得できない（HTTP {status}）"
        res["notes"].append(f"e-Gov に当該法律あり（{law_id}）だが施行日を取れない: {a_note}")

    # (b) 改正される側の法令の改正履歴
    groups = target_candidates(title)
    if not groups:
        res["reason"] = "題名から改正される側の法令を特定できない" + ("" if law_id else "（かつ e-Gov に当該法律が無い）")
        return res
    targets: list[tuple[str, list[str]]] = []  # (法令名, 同名の law_id すべて)

    def lookup(cands):
        for cand in cands:
            st, d = fetch(law_title_url(cand))
            hits = pick_by_title(existed_before(parse_laws_response(d), own), cand) if st == 200 else []
            if hits:
                return cand, hits
        return None

    missing = 0  # 照合できなかった改正対象の数。1つでもあれば施行日を確定しない（欠けた側の方が早いかもしれない）
    whole = lookup(groups[0])
    if whole:
        targets.append(whole)
    else:
        for part in groups[1:]:
            got = lookup(part)
            if got:
                targets.append(got)
            else:
                missing += 1
                res["notes"].append(f"改正対象「{part[0]}」の現行法令が e-Gov に無い")
    if not targets:
        res["reason"] = f"改正される側の法令（題名「{title}」から取り出した名）が e-Gov に無い（改称・廃止の可能性）"
        return res
    dates: list[str] = []
    for name, lids in targets:
        # 同名の現行法令が複数あるときは全部の改正履歴を見る。どれか1つで一致すればその対象は照合できたとする
        if len(lids) > 1:
            res["notes"].append(f"同名の現行法令が{len(lids)}件（{name}）。すべて照合")
        found, failed = False, False
        for lid in lids:
            status, revs = fetch(revisions_url(lid))
            if status != 200:
                failed = True
                res["notes"].append(f"{name}（{lid}）: 改正履歴を取得できない（HTTP {status}）")
                continue
            d = amendment_enforcement(revs, own)
            if undated_matches(revs, own):
                # 一致した版に施行日が無い。別の同名法令から日が取れても、この版の日が分からないので確定しない
                failed = True
                res["notes"].append(f"{name}（{lid}）: 当該法令番号の版に施行日が無い")
            if d:
                found = True
                dates += d
                res["notes"].append(f"{name}（{lid}）: {len(d)}版が一致")
            else:
                res["notes"].append(f"{name}（{lid}）: 改正履歴に当該法令番号の版が無い")
        if not found or failed:
            # 取得できなかった同名法令に、より早い版があるかもしれない
            missing += 1
    day, notes = pick_earliest(dates, prom)
    res["notes"] += notes
    if day and several_reason(dates, prom):
        res["reason"] = several_reason(dates, prom)
        return res
    if day and too_late(day, prom):
        res["reason"] = late_reason(day)
        return res
    if day and ABBREVIATED.search(title):
        # 「地方税法等の一部を改正する法律」は「等」で省いた別の法律も改正する。それを照合できないので確定しない
        res["reason"] = f"題名の「等」で省かれた改正対象を照合できない（取れた側の最も早い日 {day} は候補）"
        return res
    if day and missing:
        # scripts/fetch_enforcement_dates.py の partial と同じく、一部の対象からしか取れない日は候補に留める
        res["reason"] = f"改正対象の一部しか照合できない（取れた側の最も早い日 {day} は候補）"
        return res
    if day:
        res.update(date=day, kind=KIND_AMEND, route=ROUTE_B)
        return res
    res["reason"] = ("改正履歴に当該法令番号の版が無い（e-Gov の保持範囲外、または同日施行の別改正に版が統合）"
                     if not dates else "一致した版の施行日がいずれも公布日より前")
    return res


def result_to_row(src: dict, res: dict) -> dict:
    notes = list(res["notes"])
    if not res["date"]:
        notes.append(f"確定できず: {res['reason']}")
        if res["reason"] != FETCH_FAILED:
            notes.append(R16)
    return {
        "回次": src["回次"], "法律番号": src["法律番号"], "法令番号": src["法令番号"], "公布日": src["公布日"],
        "題名": src["題名"], "施行日": res["date"], "施行日の種別": res["kind"], "取得経路": res["route"],
        "照合URL": ";".join(dict.fromkeys(res["urls"])), "備考": "；".join(n for n in notes if n),
    }


def plan(row: dict) -> list[str]:
    """--dry-run 用: 引く URL。通信しない。"""
    lines = [f"  (a) {law_num_url(row['法令番号'])}"]
    groups = target_candidates(row["題名"])
    if groups:
        lines.append(f"  (b) 改正対象の候補: {' / '.join(groups[0])}")
        lines.append(f"      {law_title_url(groups[0][0])}")
        if len(groups) > 1:
            lines.append(f"      （見つからなければ部分ごと: {' | '.join(g[0] for g in groups[1:])}）")
    else:
        lines.append("  (b) 題名から改正対象を取り出せない（(a) で無ければ (c)）")
    return lines


# ---------- 入出力 ----------

def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def key_of(row: dict) -> str:
    # 会期が年をまたぐと法律番号は年ごとに振り直されるので、（回次, 法律番号）は重なる（26組）。法令番号で区別する
    return row["法令番号"]


def write_out(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_COLS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def run(args) -> int:
    src = read_csv(Path(args.input))
    end = None if args.limit is None else args.offset + args.limit
    todo = src[args.offset:end]
    out_dir, raw_dir = Path(args.out_dir), Path(args.raw_dir)
    out_path = out_dir / "enforcement_old.csv"
    client = Client(raw_dir, out_dir / "manifest.csv", args.sleep,
                    prior=Path(args.prior_manifest) if args.prior_manifest else None)
    if args.dry_run:
        for row in todo:
            cached = client.cached(law_num_url(row["法令番号"]), repair=False)
            print(f"[{row['回次']}-{row['法律番号']}] {row['法令番号']} {row['題名']}"
                  f"{'  （(a) は raw 済み）' if cached else ''}")
            print("\n".join(plan(row)))
        print(f"dry-run: {len(todo)} 本。通信もファイル書き込みもしていません", file=sys.stderr)
        return 0
    done = {key_of(r): r for r in read_csv(out_path)} if out_path.exists() else {}

    def flush():
        write_out(out_path, [done[key_of(r)] for r in src if key_of(r) in done])

    fails = 0
    failed_total = 0  # 散発的な失敗も数える。1本でも未取得なら非ゼロで終える
    for i, row in enumerate(todo, 1):
        try:
            res = resolve(client, row)
            fails = 0
        except FetchError as err:
            res = {"date": "", "kind": "", "route": "", "urls": [], "notes": [str(err)], "reason": FETCH_FAILED}
            fails += 1
            failed_total += 1
        if res["reason"] != FETCH_FAILED or key_of(row) not in done:  # 通信失敗で前回の結果を消さない
            done[key_of(row)] = result_to_row(row, res)
        if i % 25 == 0:
            flush()
            print(f"{i}/{len(todo)} 本", file=sys.stderr)
        if fails >= 5:
            flush()
            print("通信失敗が5本続いたので中断します（接続を確認して再実行。取れた分の raw は再利用されます）", file=sys.stderr)
            return 1
    flush()
    rows = [done[key_of(r)] for r in src if key_of(r) in done]
    print(f"施行日あり {sum(1 for r in rows if r['施行日'])} / {len(rows)} 本 -> {_rel(out_path)}")
    if failed_total:
        print(f"通信失敗で取れなかった法律が {failed_total} 本あります（再実行すると raw を再利用して続きを取ります）", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="第77〜141回の成立法の施行日を e-Gov 法令 API v2 から取る")
    ap.add_argument("--input", default=str(INPUT), help="入力 CSV（既定: enacted_old.csv）")
    ap.add_argument("--out-dir", default=str(OUT_DIR), help="出力先（enforcement_old.csv と manifest.csv）")
    ap.add_argument("--raw-dir", default=str(RAW_DIR), help="生の応答の保存先（Git 管理外）")
    ap.add_argument("--sleep", type=float, default=DEFAULT_SLEEP, help="通信の間隔（秒、既定 0.5）")
    ap.add_argument("--limit", type=int, default=None, help="先頭から N 本だけ処理")
    ap.add_argument("--offset", type=int, default=0, help="先頭から N 本を飛ばす")
    ap.add_argument("--prior-manifest", default=None,
                    help="前の manifest（作り直す前の写し）。同じ URL・置き場所・中身の控えは、その HTTP と取得時刻を引き継ぐ")
    ap.add_argument("--dry-run", action="store_true", help="通信せず、何を引くかだけ表示（ファイルも書かない）")
    return ap


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
