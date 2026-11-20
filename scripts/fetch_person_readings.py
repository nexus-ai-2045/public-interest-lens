#!/usr/bin/env python3
"""人物台帳（data/derived/person-ids/persons.csv）で読みが空の人の読みを、国会会議録 API の発言者の読み（speakerYomi）から取る。

使い道：議員ページの曝露ランキングで、同じ階層の中を読みの五十音順に並べるため（表示の並びだけ。額・人物IDの決め方には使わない）。
persons.csv の読みは「現職の名簿に載った人」の印も兼ねる（scripts/person_ids.py）ので、そこには書き足さず、別の表に置く。

確かめ方（一次資料）：会議録 API で 1986-07 以降の発言を発言者名（氏名、無ければ台帳の別表記）の完全一致で引き（API は部分一致なので、返った行を完全一致で絞り、完全一致が100件そろうまで最大10ページ読む。読み切れないときは最も古い発言も1件足す）、
一致した発言の読みが1通りのとき（濁点の有無だけの違いは同じとみなし、多い方を採る）だけ読みを入れる。
読みが2通り以上（同姓同名の疑い）や一致なしは、読みを空にして理由を書く（推測しない）。
院と選挙区を付けて分けた人物ID（「鬼木誠（衆・福岡2）」など）は、同姓同名がいると分かっている人なので引かずに理由を書く。

出力：data/acquired/diet-roster/readings-kokkai.csv（人物ID,氏名,読み,一致した発言数,理由,出典URL,取得日時,外部資料ID）
原本：API の応答は1回ごとに scripts/register_external_material.py の register_once で
.local/external-materials/person-readings-kokkai/ に登録し（AGENTS.md）、その material_id を「外部資料ID」列に空白区切りで書く。
再開できる：取得済みの人物IDは引き直さない（--refresh で全部引き直す）。API が応答しなかった人は理由を書いて残し、次の実行で引き直す。

使い方：python3 scripts/fetch_person_readings.py [--workers 4] [--sleep 0.2] [--limit N] [--dry-run] [--refresh]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_roster_kokkai import API, nospace, spellings

PERSONS = ROOT / "data/derived/person-ids/persons.csv"
OUT = ROOT / "data/acquired/diet-roster/readings-kokkai.csv"
FIELDS = ["人物ID", "氏名", "読み", "一致した発言数", "理由", "出典URL", "取得日時", "外部資料ID"]
TASK_ID = "person-readings-kokkai"
MATERIALS = ROOT / ".local" / "external-materials"
WORK = ROOT / ".local" / "work" / TASK_ID
SPLIT_ID = re.compile(r"（[^）]*）$")


def read(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(open(path, encoding="utf-8", newline=""))) if path.exists() else []


def targets() -> list[tuple[str, str, list[str]]]:
    """読みが空の人（人物ID, 氏名, 別表記）。空の行は数えない。"""
    return [(r["人物ID"], r["氏名"], [n for n in re.split(r"[;／]", r["別表記"]) if n.strip()])
            for r in read(PERSONS) if r["人物ID"] and not r["読み"].strip()]


def no_dakuten(y: str) -> str:
    return unicodedata.normalize("NFC", unicodedata.normalize("NFD", y).replace("゙", "").replace("゚", ""))


RETRY_REASON = "API が応答しなかった"
PAGES = 10  # 部分一致の結果を何ページ（100件ずつ）まで読むか


def source_url(spelled: str) -> str:
    return API + "?" + urllib.parse.urlencode({"speaker": spelled, "from": "1986-07-01", "maximumRecords": "100", "recordPacking": "json"})


def fetch_raw(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "public-interest-lens-research/1.0"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read()
        except Exception:  # noqa: BLE001
            time.sleep(2 * (i + 1))
    raise RuntimeError("API が応答しない")


def keep_material(url: str, raw: bytes, observed: str, storage: Path) -> str:
    """API の応答の原本を外部資料として登録し、その material_id を返す（同じ日・同じ URL・同じ中身は登録し直さない）。"""
    from scripts.register_external_material import register_once

    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / f"{hashlib.sha256(raw).hexdigest()}.json"
    path.write_bytes(raw)
    return register_once(input_path=path, source_url=url, task_id=TASK_ID, title="国会会議録 API の発言検索の応答",
                         purpose="人物台帳で読みが空の人の読み（speakerYomi）の根拠を残す", storage_root=storage, observed_at=observed)


def call_kept(params: dict[str, str], materials: list[str], get=fetch_raw, storage: Path = MATERIALS) -> dict:
    """会議録 API を引き、応答の原本を登録して material_id を materials に足し、応答を返す。"""
    url = API + "?" + urllib.parse.urlencode({**params, "recordPacking": "json"})
    observed = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    raw = get(url)
    materials.append(keep_material(url, raw, observed, storage))
    return json.loads(raw)


def exact_records(spelled: str, sleep: float, materials: list[str] | None = None, call=None) -> list[dict]:
    """発言者名の完全一致の発言。API の speaker は部分一致なので、長い名前の発言で先頭100件が埋まっても、
    最大 PAGES ページまで読み進める（新しい順）。同姓同名の別人を見落とさないよう、いちばん古い発言も1件足す。
    応答の原本は1回ごとに登録し、material_id を materials に足す。"""
    materials = [] if materials is None else materials
    call = call or (lambda params: call_kept(params, materials))
    base = {"speaker": spelled, "from": "1986-07-01", "maximumRecords": "100"}
    out: list[dict] = []
    start, total, read_end = 1, None, 0
    for _ in range(PAGES):
        d = call({**base, "startRecord": str(start)})
        time.sleep(sleep)
        total = int(d.get("numberOfRecords", 0))
        read_end = start - 1 + len(d.get("speechRecord", []))  # 読んだ最後の位置
        out += [r for r in d.get("speechRecord", []) if nospace(r.get("speaker", "")) == spelled]
        nxt = d.get("nextRecordPosition")
        if len(out) >= 100 or not nxt:
            break
        start = int(nxt)
    if out and total and total > read_end:
        # 読み切っていない：いちばん古い発言（部分一致の最後）が同じ名前なら足す
        last = call({**base, "startRecord": str(total), "maximumRecords": "1"}).get("speechRecord", [])
        time.sleep(sleep)
        out += [r for r in last if nospace(r.get("speaker", "")) == spelled]
    return out


def look_up(pid: str, name: str, aliases: list[str], sleep: float) -> dict[str, str]:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    row = {"人物ID": pid, "氏名": name, "読み": "", "一致した発言数": "0", "理由": "", "出典URL": "", "取得日時": now, "外部資料ID": ""}
    if SPLIT_ID.search(pid):
        return {**row, "理由": "同姓同名を院と選挙区で分けた人物（発言者名だけでは決まらない）"}
    recs: list[dict] = []
    materials: list[str] = []
    tries = list(dict.fromkeys(s for n in [name, *aliases] for s in spellings(nospace(n))))
    try:
        for spelled in tries:
            recs = exact_records(spelled, sleep, materials)
            if recs:
                break
    except RuntimeError as e:  # API が応答しない人は空にして理由を書く（他の人の結果は残す。次の実行で引き直す）
        return {**row, "理由": f"{RETRY_REASON}（{e}）", "外部資料ID": " ".join(dict.fromkeys(materials))}
    row["外部資料ID"] = " ".join(dict.fromkeys(materials))
    # 出典：一致した表記の問い合わせ。一致なしなら、試した表記の問い合わせを全部。
    row["出典URL"] = " ".join(source_url(t) for t in ([spelled] if recs else tries))
    yomi = Counter(nospace(r.get("speakerYomi") or "") for r in recs if r.get("speakerYomi"))
    row["一致した発言数"] = str(sum(yomi.values()))
    if not yomi:
        return {**row, "理由": "会議録に発言者名の完全一致なし（1986-07以降）"}
    if len({no_dakuten(y) for y in yomi}) > 1:
        return {**row, "理由": "読みが2通り以上（同姓同名の疑い）：" + "・".join(sorted(yomi))}
    return {**row, "読み": yomi.most_common(1)[0][0]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sleep", type=float, default=0.2, help="1回の問い合わせごとの待ち（秒）")
    ap.add_argument("--limit", type=int, default=0, help="今回引く人数の上限（0 は全員）")
    ap.add_argument("--dry-run", action="store_true", help="引く人数だけ出して終わる（API に問い合わせない）")
    ap.add_argument("--refresh", action="store_true", help="取得済みの人も引き直す")
    a = ap.parse_args(argv)
    want = targets()
    done = {} if a.refresh else {r["人物ID"]: r for r in read(OUT) if not r["理由"].startswith(RETRY_REASON)}
    todo = [t for t in want if t[0] not in done]
    if a.limit:
        todo = todo[: a.limit]
    print(f"読みが空の人 {len(want)} 人 / 取得済み {len(done)} / 今回 {len(todo)}", file=sys.stderr)
    if a.dry_run:
        return 0
    got = dict(done)
    with ThreadPoolExecutor(a.workers) as ex:
        for row in ex.map(lambda t: look_up(t[0], t[1], t[2], a.sleep), todo):
            got[row["人物ID"]] = row
    keep = {t[0] for t in want}
    rows = sorted((r for pid, r in got.items() if pid in keep), key=lambda r: r["人物ID"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS, lineterminator="\n", restval="")
        w.writeheader()
        w.writerows(rows)
    filled = sum(bool(r["読み"]) for r in rows)
    print(f"書いた {len(rows)} 人（読みあり {filled}、空 {len(rows) - filled}）→ {OUT.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
