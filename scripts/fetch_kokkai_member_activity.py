#!/usr/bin/env python3
"""議員ページの「国会での活動」用に、会議録 API から大臣・委員長としての発言数、出席した会議数、直近10件を取る。

fetch_kokkai_member_counts.py の件数（2系統一致）と合わせ、
data/derived/member-activity-v1/diet.json と同じ形（speeches・shugiin・sangiin・asMinister・asChair・meetings・first・recent[10]）で
private-m2 側に書く。公開用の変換は「議員の実名ランキングを公開する」スレッドの scripts/build_member_activity.py が担当する。
asMinister は発言者の肩書に「大臣」を含む発言（副大臣を含む）、asChair は「委員長」を含む発言。

使い方: python3 scripts/fetch_kokkai_member_activity.py [--counts .../members-speech-counts.csv] [--out .../diet-direct.json]
"""
import argparse, csv, json, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from person_ids import canonical  # noqa: E402

BASE = "https://kokkai.ndl.go.jp/api/"
DIR = "/mnt/project-files/private-m2/kokkai-direct"


def get(endpoint, params, sleep):
    url = BASE + endpoint + "?" + urllib.parse.urlencode(dict(params, recordPacking="json"))
    err = None
    for i in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                d = json.loads(r.read().decode("utf-8"))
            time.sleep(sleep)
            return url, d
        except Exception as e:
            err = e
            time.sleep(sleep * (2 ** (i + 1)))
    raise RuntimeError(f"{url}: {err}")


def activity(name, sleep):
    _, d = get("speech", {"speaker": name, "maximumRecords": 10}, sleep)
    recent = [{"date": r["date"], "house": r["nameOfHouse"], "meeting": r["nameOfMeeting"], "issue": r["issue"],
               "position": r.get("speakerPosition") or "", "group": r.get("speakerGroup") or "", "url": r["speechURL"]}
              for r in d.get("speechRecord") or []]
    _, dm = get("speech", {"speaker": name, "speakerPosition": "大臣", "maximumRecords": 1}, sleep)
    _, dc = get("speech", {"speaker": name, "speakerPosition": "委員長", "maximumRecords": 1}, sleep)
    _, dl = get("meeting_list", {"speaker": name, "maximumRecords": 1}, sleep)
    return {"asMinister": int(dm.get("numberOfRecords", 0)), "asChair": int(dc.get("numberOfRecords", 0)),
            "meetings": int(dl.get("numberOfRecords", 0)), "recent": recent}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--counts", default=f"{DIR}/members-speech-counts.csv")
    ap.add_argument("--members", default="app/public/distribution/members.json")
    ap.add_argument("--persons", default="data/derived/person-ids/persons.csv", help="人物台帳（同姓同名の判定に使う）")
    ap.add_argument("--out", default=f"{DIR}/diet-direct.json")
    ap.add_argument("--sleep", type=float, default=1.0)
    a = ap.parse_args()
    people = [(m["id"], m["name"]) for m in json.load(open(a.members, encoding="utf-8"))["members"]]
    # 会議録 API は氏名で探すので、同姓同名の人物（人物IDが分かれた人）の発言は分けられない。取らずに理由を残す。
    # 片方しか議員ページに載っていなくても、人物台帳で分かれていれば同姓同名として扱う。
    ledger = [r["氏名"] for r in csv.DictReader(open(a.persons, encoding="utf-8"))] if Path(a.persons).exists() else []
    listed, split = Counter(canonical(n) for _, n in people), Counter(canonical(n) for n in ledger)
    homonyms = {c for c in listed if max(listed[c], split[c]) > 1}
    out = Path(a.out)
    res = json.load(open(out, encoding="utf-8")) if out.exists() else {"members": {}}
    for i, (pid, n) in enumerate(people, 1):
        if canonical(n) in homonyms:
            res["members"].pop(n, None)  # 同姓同名になる前に氏名で取った分は、どちらの人の発言か分からないので捨てる
            res["members"].pop(canonical(n), None)
            if pid == canonical(n):
                continue  # 氏名と同じ人物ID（前からいる人）は、氏名のキーと区別できないので行を作らない
            res["members"][pid] = {"status": "保留", "reason": "同姓同名の人物がいて、会議録 API の氏名検索では発言を分けられない"}
            continue
        if pid in res["members"] or n in res["members"]:
            continue
        res["members"][pid] = activity(n, a.sleep)
        res["fetchedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(i, len(people), file=sys.stderr)
    # 件数（2系統一致）を合わせる。保留の人は件数を入れず、理由を残す。
    counts = {r["氏名"]: r for r in csv.DictReader(open(a.counts, encoding="utf-8"))} if Path(a.counts).exists() else {}
    names = dict(people)
    for key, m in res["members"].items():
        if m.get("reason", "").startswith("同姓同名"):
            continue
        c = counts.get(names.get(key, key)) or counts.get(key)
        if not c:
            m["status"] = "件数未取得"; continue
        m["status"] = c["判定"]
        if c["判定"] == "採用":
            m.update(speeches=int(c["系統A_総件数"]), shugiin=int(c["衆議院_件数"]), sangiin=int(c["参議院_件数"]),
                     first=c["初回発言日"])
        else:
            m["reason"] = c["理由"]
    res["source"] = "https://kokkai.ndl.go.jp/api/"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", len(res["members"]))


if __name__ == "__main__":
    main()
