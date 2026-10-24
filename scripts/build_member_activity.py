"""議員ごとの国会での活動 `app/public/distribution/member-activity.json` を作る。

入力（data/derived/member-activity-v1/）
- diet.json：国会会議録検索システム API から取った件数と直近の発言（名前ごと）
- roles.json：公的機関・政党の公式ページで確かめられた役職など（名前ごと）

点数には使わない参考表示。議員ページ（members.json）にいる人だけを出す。
入力は氏名のキーで、議員ページの人物と canonical（空白・敬称を除き、髙→高 など同一人物の字体ゆれを寄せた氏名）で結ぶ。
出力のキーは人物ID。同じ氏名の人物が複数いて入力のキーが人物IDそのものでないときは、どちらか決められないので止める。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.person_ids import canonical  # noqa: E402

SOURCE = ROOT / "data" / "derived" / "member-activity-v1"
MEMBERS = ROOT / "app" / "public" / "distribution" / "members.json"
OUTPUT = ROOT / "app" / "public" / "distribution" / "member-activity.json"
PERSONS = ROOT / "data" / "derived" / "person-ids" / "persons.csv"

KOKKAI = re.compile(r"https://kokkai\.ndl\.go\.jp/")
OFFICIAL = re.compile(r"https://([a-z0-9-]+\.)*(go\.jp|lg\.jp|pref\.[a-z]+\.jp|jimin\.jp|komei\.or\.jp|cdp-japan\.jp|dpfp\.or\.jp|o-ishin\.jp|jcp\.or\.jp|sdp\.or\.jp)/")
DIET_KEYS = ("speeches", "shugiin", "sangiin", "asMinister", "asChair", "meetings", "first")
SPEECH_KEYS = ("date", "house", "meeting", "issue", "position", "group", "url")
ROLE_KEYS = ("category", "title", "period", "url", "source")


def build(fetched_at: str) -> dict:
    people = json.loads(MEMBERS.read_text(encoding="utf-8"))["members"]
    ids = {m["id"] for m in people}
    by_name: dict[str, list[str]] = {}
    for m in people:
        by_name.setdefault(canonical(m["name"]), []).append(m["id"])
    # 人物台帳で分かれた同姓同名（議員ページに片方しか載っていない場合も）。
    in_ledger: dict[str, int] = {}
    if PERSONS.exists():
        with PERSONS.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                in_ledger[canonical(r["氏名"])] = in_ledger.get(canonical(r["氏名"]), 0) + 1

    def person_of(key: str) -> str | None:
        found = by_name.get(canonical(key), [])
        split = len(found) > 1 or in_ledger.get(canonical(key), 0) > 1
        # 同姓同名の名前は、院・選挙区付きの人物IDで書いたキーだけ受ける。氏名と同じ文字列のキーは、前からいる人の人物IDと
        # 同じでも、同姓同名になる前に氏名で取った分かもしれないので受けない。
        if split and (key == canonical(key) or key not in ids):
            raise ValueError(f"同じ氏名の人物が複数いて決められません（院・選挙区付きの人物IDで書き直してください）: {key} → {found}")
        if key in ids:
            return key
        if len(found) > 1:
            raise ValueError(f"同じ氏名の人物が複数いて決められません（人物IDで書き直してください）: {key} → {found}")
        return found[0] if found else None

    diet_raw = json.loads((SOURCE / "diet.json").read_text(encoding="utf-8"))
    roles_raw = json.loads((SOURCE / "roles.json").read_text(encoding="utf-8"))
    unknown = sorted(k for k in set(diet_raw) | set(roles_raw) if person_of(k) is None)
    if unknown:
        raise ValueError(f"議員ページにいない名前があります: {unknown}")
    diet = {person_of(k): v for k, v in diet_raw.items()}
    roles = {person_of(k): v for k, v in roles_raw.items()}
    if len(diet) != len(diet_raw) or len(roles) != len(roles_raw):
        raise ValueError("入力の中に、同じ人物になる名前が2つあります（表記ゆれ）")
    members: dict[str, dict] = {}
    for name in sorted(ids):
        entry: dict = {}
        if name in diet and diet[name].get("status") != "保留":  # 保留（同姓同名で発言を分けられない等）は0件として出さない
            row = diet[name]
            recent = [{k: s.get(k, "") for k in SPEECH_KEYS} for s in row.get("recent", [])]
            if any(not KOKKAI.match(s["url"]) for s in recent):
                raise ValueError(f"会議録以外の URL があります: {name}")
            entry["diet"] = {**{k: row.get(k, 0 if k != "first" else "") for k in DIET_KEYS}, "recent": recent}
        picked = [{k: r.get(k, "") for k in ROLE_KEYS} for r in roles.get(name, [])]
        if any(not OFFICIAL.match(r["url"]) for r in picked):
            raise ValueError(f"公式ページ以外の URL があります: {name}")
        if picked:
            entry["roles"] = picked
        if entry:
            members[name] = entry
    return {
        "schema": "member-activity/v1",
        "fetchedAt": fetched_at,
        "method": {
            "diet": "国会会議録検索システム API（speech・meeting_list）の件数。発言者名の完全一致で数え、大臣・委員長は発言者の肩書の部分一致",
            "roles": "公開ページを機械で探し、公的機関・政党の公式ページで確かめられたものだけ（報道・百科事典は除く）",
        },
        "members": members,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetched-at", required=True, help="取得日（YYYY-MM-DD）")
    args = parser.parse_args()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.fetched_at):
        raise SystemExit("取得日は YYYY-MM-DD で渡してください")
    payload = build(args.fetched_at)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(len(payload["members"]), "人")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
