"""議員ごとの国会での活動 `app/public/distribution/member-activity.json` を作る。

入力（data/derived/member-activity-v1/）
- diet.json：国会会議録検索システム API から取った件数と直近の発言（名前ごと）
- roles.json：公的機関・政党の公式ページで確かめられた役職など（名前ごと）

点数には使わない参考表示。議員ページ（members.json）にいる名前だけを出す。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "derived" / "member-activity-v1"
MEMBERS = ROOT / "app" / "public" / "distribution" / "members.json"
OUTPUT = ROOT / "app" / "public" / "distribution" / "member-activity.json"

KOKKAI = re.compile(r"https://kokkai\.ndl\.go\.jp/")
OFFICIAL = re.compile(r"https://([a-z0-9-]+\.)*(go\.jp|lg\.jp|jimin\.jp|komei\.or\.jp|cdp-japan\.jp|dpfp\.or\.jp|o-ishin\.jp|jcp\.or\.jp|sdp\.or\.jp)/")
DIET_KEYS = ("speeches", "shugiin", "sangiin", "asMinister", "asChair", "meetings", "first")
SPEECH_KEYS = ("date", "house", "meeting", "issue", "position", "group", "url")
ROLE_KEYS = ("category", "title", "period", "url", "source")


def build(fetched_at: str) -> dict:
    names = {m["name"] for m in json.loads(MEMBERS.read_text(encoding="utf-8"))["members"]}
    diet = json.loads((SOURCE / "diet.json").read_text(encoding="utf-8"))
    roles = json.loads((SOURCE / "roles.json").read_text(encoding="utf-8"))
    unknown = sorted((set(diet) | set(roles)) - names)
    if unknown:
        raise ValueError(f"議員ページにいない名前があります: {unknown}")
    members: dict[str, dict] = {}
    for name in sorted(names):
        entry: dict = {}
        if name in diet:
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
