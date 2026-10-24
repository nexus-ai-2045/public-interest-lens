#!/usr/bin/env python3
"""技術を止めた法律の審議で、誰が何を言ったかを国会会議録検索システム API から直接集める。

1. 法案名（「案」を除く）で、成立した回次と提出回次の発言を探し、審議した会議（院・会議名・日付）を特定する。
2. その会議の発言を全部取り、議員ごとに1ファイルにまとめる（政府参考人・参考人・公述人は除く）。
3. 法案ごとの会議一覧を JSON に書く。

賛否の向き（支持・反対・中立）は、このあと2系統の読み手で別々に判定し、一致したものだけ採用する。
実名が入るので、出力は共有フォルダの private-m2 側に置く（リポジトリには入れない）。

使い方: python3 scripts/fetch_causal_chain_kokkai.py [--out /mnt/project-files/private-m2/causal-chain] [--sleep 1.0] [ID ...]
"""
import argparse, csv, json, re, sys, time, urllib.parse, urllib.request
from collections import OrderedDict
from pathlib import Path

API = "https://kokkai.ndl.go.jp/api/speech"
ENACTED = "data/acquired/bill-census-full/enacted.csv"
# スレッド「新技術を止めた法律の特定」の「計算に乗せる候補」の表（2026-10-17）
TARGETS = ["衆法-185-2", "閣法-171-27", "閣法-193-61", "閣法-195-7", "閣法-189-75", "閣法-171-50",
           "閣法-147-96", "閣法-171-54", "閣法-196-28", "閣法-183-73", "閣法-185-21", "閣法-196-60"]
# 法案名のほかに、その法律の審議だと分かる言葉（発言がこれを含むときだけ数える）
KEYWORDS = {"衆法-185-2": ["タクシー"], "閣法-171-27": ["タクシー"], "閣法-193-61": ["住宅宿泊", "民泊"],
            "閣法-195-7": ["旅館業法", "民泊"], "閣法-189-75": ["航空法", "無人航空機", "ドローン"],
            "閣法-171-50": ["資金決済", "資金移動"], "閣法-147-96": ["電子署名", "認証業務"],
            "閣法-171-54": ["著作権"], "閣法-196-28": ["著作権"], "閣法-183-73": ["薬事法", "医薬品"],
            "閣法-185-21": ["薬事法", "薬剤師法", "インターネット販売", "ネット販売"], "閣法-196-60": ["医療法", "医師法"]}
SKIP_MEETING = ("議院運営委員会", "予算委員会", "決算")
# 発言の冒頭「○政府参考人（…君）」から区分を取る。参考人は業界団体などの意見陳述なので残す。
ROLE_RE = re.compile(r"^○(政府参考人|政府特別補佐人|参考人|公述人|説明員|政府委員|証人|会計検査院\S*|最高裁判所\S*)（")


def get(params, sleep):
    url = API + "?" + urllib.parse.urlencode(dict(params, recordPacking="json"))
    err = None
    for i in range(4):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                d = json.loads(r.read().decode("utf-8"))
            time.sleep(sleep)
            return url, d
        except Exception as e:
            err = e
            time.sleep(sleep * (2 ** (i + 1)))
    raise RuntimeError(f"{url}: {err}")


def all_records(params, sleep):
    out, start = [], 1
    while True:
        _, d = get(dict(params, maximumRecords=100, startRecord=start), sleep)
        out += d.get("speechRecord") or []
        nxt = d.get("nextRecordPosition")
        if not nxt:
            return out
        start = int(nxt)


def bill_info(bid):
    kind, sess, num = bid.split("-")
    for r in csv.DictReader(open(ENACTED, encoding="utf-8")):
        if r["種別"] == kind and r["提出回次"] == sess and r["番号"] == num:
            return r
    raise KeyError(bid)


def collect(bid, out, sleep):
    r = bill_info(bid)
    title = r["題名"]
    short = re.sub(r"案$", "", title)
    core = re.sub(r"(等)?の一部を改正する法律$", "", short)
    kws = [short, core] + KEYWORDS.get(bid, [])
    sessions = sorted({r["回次"], r["提出回次"]})
    meetings = OrderedDict()
    for s in sessions:
        for rec in all_records({"any": short, "sessionFrom": s, "sessionTo": s}, sleep):
            if short not in rec["speech"]:
                continue
            if any(k in rec["nameOfMeeting"] for k in SKIP_MEETING):
                continue
            key = (rec["nameOfHouse"], rec["nameOfMeeting"], rec["date"])
            meetings.setdefault(key, {"院": key[0], "会議名": f"{key[1]} {rec['issue']}", "日付": key[2],
                                      "meetingURL": rec["meetingURL"], "法案名に触れた発言数": 0})
            meetings[key]["法案名に触れた発言数"] += 1
    people = OrderedDict()
    for (house, mname, date), m in meetings.items():
        recs = all_records({"nameOfHouse": house, "nameOfMeeting": mname, "from": date, "until": date}, sleep)
        m["発言総数"] = len(recs)
        for rec in recs:
            pos = rec.get("speakerPosition") or ""
            if str(rec["speechOrder"]) == "0" or rec.get("speaker") in ("", None, "会議録情報"):
                continue
            mrole = ROLE_RE.match(rec["speech"])
            kubun = mrole.group(1) if mrole else "議員"
            if not any(k in rec["speech"] for k in kws):
                continue
            p = people.setdefault(rec["speaker"], {"院": house, "会派": rec.get("speakerGroup") or "", "区分": kubun, "発言": []})
            p["発言"].append((date, house, m["会議名"], rec["speechOrder"], pos, rec["speechURL"], rec["speech"]))
    d = out / "speeches" / bid
    d.mkdir(parents=True, exist_ok=True)
    involvements = []
    for i, (name, p) in enumerate(people.items(), 1):
        lines = [f"氏名: {name}", f"院: {p['院']}", f"会派: {p['会派']}", f"区分: {p['区分']}",
                 f"法案: {title}（{r['種別']} 第{r['提出回次']}回国会 第{r['番号']}号）", ""]
        for date, house, mn, order, pos, url, sp in p["発言"]:
            lines += [f"■ {date} {house} {mn} 発言番号{order}" + (f"（{pos}）" if pos else ""), f"speechURL: {url}", "", sp, ""]
        (d / f"{i:03d}_{name}.txt").write_text("\n".join(lines), encoding="utf-8")
        involvements.append({"氏名": name, "院": p["院"], "会派": p["会派"], "区分": p["区分"], "発言数": len(p["発言"]),
                             "最初の発言URL": p["発言"][0][5]})
    meta = {"id": bid, "title": title, "回次": sessions, "meetings": list(meetings.values()),
            "keywords": kws, "speakers": involvements, "source": API}
    (out / f"{bid}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(bid, "会議", len(meetings), "議員", len(people), file=sys.stderr)
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--out", default="/mnt/project-files/private-m2/causal-chain")
    ap.add_argument("--sleep", type=float, default=1.0)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    for bid in a.ids or TARGETS:
        if (out / f"{bid}.json").exists():
            continue
        collect(bid, out, a.sleep)


if __name__ == "__main__":
    main()
