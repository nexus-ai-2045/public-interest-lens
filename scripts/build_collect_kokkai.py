#!/usr/bin/env python3
"""配分（allocation-v1）の収集 JSON（collect/<法律ID>.json と同じ形）を、国会会議録検索システム API から機械的に作る。

6本の収集 JSON は AI セッションが会議録を読んで作ったが、同じ手順を機械で再現する（人が読む判断は残す）。
- 会議の特定：法案名（末尾の「案」を除く）を含む発言を、提出回次〜成立回次で探し、会議（issueID）ごとにまとめる。
  議題とみなす条件：委員長（議長）が法案名を挙げて「議題」「趣旨の説明を求め」と宣告した、または 提案理由の説明がある。
  法案名に触れた発言の数や「可決すべきもの」の委員長発言だけでは議題とみなさない（他の案件の質疑・採決で名前が出ただけの会議を拾わないため）。
  条件に合わない会議は meetings_excluded に理由を残す。
- decide：閣法は 大臣・副大臣・政務官が法案名を挙げて「御説明」「提案の理由」を述べた発言。
          衆法は 成立法一覧（enacted.csv）の提出者一覧の全員（証拠は議案の経過 URL）と、趣旨説明の発言者。
- amend ：成立法一覧の議決結果が「修正」の院があれば要確認として備考に残す（会議録からは作らない）。
- chair ：委員会で「可決すべきものと決定」「採決」などと述べた委員長（本会議の委員長報告・議長は数えない）。
- question：議題の会議で発言した議員のうち、委員長・議長・政府側・参考人・提出者を除く人。
          議題が他の法案と併せてある会議では、法案名・キーワードに触れた発言をした人だけ。
  質疑の賛否（支持・反対・中立・無関係）は、このあと2系統の AI で別々に判定する（ここでは判定しない）。
出力（--out）：<法律ID>.json、speeches/<法律ID>/NNN_氏名.txt（本人の全発言）、excerpts/<法律ID>/NNN_氏名.txt（判定用の抜粋）、
  stance-input-index.csv（判定の対象一覧）、inputs-check.csv（入力がそろっているかの表）。
実名が入るので、出力は共有フォルダの private-m2 側に置く（リポジトリには入れない）。
API から取った応答は、解析の前に必ず register_external_material.py で .local/external-materials/<task-id>/ に登録する
（帰属の判断に使った原資料を後から監査できるように。内容の初期状態は unverified）。

使い方: python3 scripts/build_collect_kokkai.py --out /mnt/project-files/private-m2/collect-extend-2026-10-17 [--task-id ID] [--cache DIR] [--sleep 1.0] ID ...
"""
import argparse, csv, hashlib, json, re, sys, tempfile, time, unicodedata, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from register_external_material import register_local_material  # noqa: E402

API = "https://kokkai.ndl.go.jp/api/speech"
ENACTED = "data/acquired/bill-census-full/enacted.csv"
VOTES_INDEX = "data/acquired/sangiin-votes/votes_index.csv"
SKIP_MEETING = ("議院運営委員会", "予算委員会", "決算")
OUTSIDER = re.compile(r"^○(政府参考人|政府特別補佐人|参考人|公述人|説明員|政府委員|証人|会計検査院\S*|最高裁判所\S*)（")
CHAIR_HEAD = re.compile(r"^○[^（　]*(委員長|議長|会長)(代理|代行)?(（|　|$)")
CHAIR_POS = re.compile(r"(委員長|議長|会長)")
GOV_POS = re.compile(r"大臣|副大臣|政務官|長官|内閣総理大臣|総理")
VOTE_STRONG = ("可決すべきもの", "否決すべきもの")
EXPLAIN_WORDS = ("提案の理由", "提案理由", "趣旨を御説明", "趣旨を説明", "趣旨について御説明", "趣旨の説明")  # かつ法案名と「説明」を含む発言だけ数える（「趣旨」だけの答弁は数えない）
KEYWORDS = {}  # 法律IDごとの追加キーワード（併せて議題の会議で、法案名以外の言葉で触れた発言を拾う）
STORAGE_ROOT = Path(".local/external-materials")
TASK = {"id": "collect-kokkai-" + time.strftime("%Y-%m-%d")}


def register(url, data):
    """API の応答を外部資料として登録する。

    保存する原本には取得した URL も入れるので、違う URL が同じ応答を返しても別の記録になる。
    同じ日に同じ URL から同じ応答を取ったときだけ登録済みとみなし、その記録と原本がそろっていてハッシュも合うかを確かめる。
    """
    payload = json.dumps({"source_url": url, "response": data}, ensure_ascii=False)
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "response.json"
        raw.write_text(payload, encoding="utf-8")
        try:
            record_path = register_local_material(
                input_path=raw, source_url=url, task_id=TASK["id"], storage_root=STORAGE_ROOT,
                title="国会会議録検索システム API の応答", purpose="配分の収集 JSON（議員の関与）を作る原資料",
            )
        except FileExistsError:
            record_path = register_local_material(
                input_path=raw, source_url=url, task_id=TASK["id"], storage_root=STORAGE_ROOT,
                title="", purpose="", dry_run=True,
            )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    # 途中で止まった登録や中身の違う記録のまま、帰属の処理に進まない。
    if not record_path.is_file():
        raise RuntimeError(f"外部資料の記録がありません（登録が途中で止まった可能性）：{record_path.parent}")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    original = record_path.parent / record.get("saved_filename", "")
    if record.get("source_url") != url or record.get("sha256") != digest or not original.is_file() \
            or hashlib.sha256(original.read_bytes()).hexdigest() != digest:
        raise RuntimeError(f"外部資料の記録が今回の応答と合いません：{record_path}")
    return record_path


def get(params, sleep, cache):
    key = urllib.parse.urlencode(sorted(dict(params, recordPacking="json").items()))
    cp = None
    if cache:
        cp = cache / (hashlib.sha1(key.encode()).hexdigest() + ".json")
    url = API + "?" + key
    if cp and cp.exists():
        d = json.loads(cp.read_text(encoding="utf-8"))
        register(url, d)  # 前の版や別タスクのキャッシュでも、今回のタスクの原資料として登録してから使う
        return d
    err = None
    for i in range(4):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                d = json.loads(r.read().decode("utf-8"))
            register(url, d)
            time.sleep(sleep)
            if cp:
                cp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            return d
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(sleep * (2 ** (i + 1)))
    raise RuntimeError(f"{url}: {err}")


def all_records(params, sleep, cache):
    out, start = [], 1
    while True:
        d = get(dict(params, maximumRecords=100, startRecord=start), sleep, cache)
        out += d.get("speechRecord") or []
        nxt = d.get("nextRecordPosition")
        if not nxt:
            return out
        start = int(nxt)


def wareki(text):
    m = re.search(r"(平成|令和)\s*(\d+|元)年\s*(\d+)月\s*(\d+)日", text or "")
    if not m:
        return ""
    y = (1 if m.group(2) == "元" else int(m.group(2))) + (1988 if m.group(1) == "平成" else 2018)
    return f"{y}-{int(m.group(3)):02d}-{int(m.group(4)):02d}"


def bill_info(bid):
    kind, sess, num = bid.split("-")
    for r in csv.DictReader(open(ENACTED, encoding="utf-8")):
        if r["種別"] == kind and r["提出回次"] == sess and r["番号"] == num:
            return r
    raise KeyError(bid)


def classify(rec):
    """発言を 参考人等 / 委員長・議長 / 政府側 / 議員 に分ける。
    発言の頭は「○鈴木政府参考人」「○橋本副大臣」「○高鳥委員長」「○名前君」「○政府参考人（名前君）」のどれか。肩書は speakerPosition も見る。"""
    sp = rec["speech"]
    head = sp.split("　", 1)[0]
    pos = rec.get("speakerPosition") or ""
    if OUTSIDER.match(sp) or re.search(r"(政府参考人|政府委員|政府特別補佐人|説明員|参考人|公述人|証人)(（.*）)?$", head):
        return "outsider"
    if GOV_POS.search(pos) or GOV_POS.search(head):
        return "gov"
    if CHAIR_HEAD.match(sp) or CHAIR_POS.search(pos):
        return "chair"
    return "member"


BILL_NAME = re.compile(r"[^\s、　○（）()〔〕「」]{2,}?(?:法律案|法案)")


def agenda_others(chair_texts, title_short):
    """議題を宣告した委員長・議長の発言に、本案以外の法案名が出ているか（出ていれば他の案件と併せて／続けて審議）。"""
    texts = [t for t in chair_texts if "議題" in t]
    if not any(title_short in t for t in texts):
        return None
    names = set()
    for t in texts:
        for m in BILL_NAME.findall(t.replace(title_short, "")):
            names.add(m)
    return len(names)


def collect(bid, out, sleep, cache):
    e = bill_info(bid)
    title = e["題名"]
    short = re.sub(r"案$", "", title)
    core = re.sub(r"(等)?の一部を改正する法律$", "", short)
    kws = [k for k in dict.fromkeys([short, core] + KEYWORDS.get(bid, [])) if k]
    s_from, s_to = int(e["提出回次"]), int(e["回次"])
    hits = {}
    for s in range(s_from, s_to + 1):
        for rec in all_records({"any": short, "sessionFrom": s, "sessionTo": s}, sleep, cache):
            if short in rec["speech"]:
                hits.setdefault(rec["issueID"], []).append(rec)
    meetings, excluded, people, involvements = [], [], {}, []
    proposers = [n.strip().removesuffix("君") for n in re.split(r"[;；]", e["提出者一覧"]) if n.strip()]
    decide_names = set(proposers)
    chair_cands = {}

    plans = []
    for iid, hs in hits.items():
        h0 = hs[0]
        mname = f"{h0['nameOfMeeting']} {h0['issue']}"
        if any(k in h0["nameOfMeeting"] for k in SKIP_MEETING):
            excluded.append({"院": h0["nameOfHouse"], "会議名": mname, "日付": h0["date"], "理由": "議院運営委員会・予算・決算は対象外"})
            continue
        recs = all_records({"issueID": iid}, sleep, cache)
        plans.append((iid, hs, recs))
    plans.sort(key=lambda p: (p[1][0]["date"], p[1][0]["nameOfHouse"]))

    for iid, hs, recs in plans:
        h0 = hs[0]
        house, mname, date = h0["nameOfHouse"], f"{h0['nameOfMeeting']} {h0['issue']}", h0["date"]
        murl = h0["meetingURL"]
        body = [r for r in recs if str(r["speechOrder"]) != "0" and r.get("speaker") not in ("", None, "会議録情報")]
        kind = [(r, classify(r)) for r in body]
        explain = [r for r, k in kind if k in ("gov", "member") and short in r["speech"]
                   and any(w in r["speech"] for w in EXPLAIN_WORDS) and "説明" in r["speech"]
                   and (k == "gov" or r["speaker"] in decide_names)]
        is_committee = h0["nameOfMeeting"].endswith(("委員会", "調査会"))
        # 採決の委員長発言：委員会で、委員長が「可決すべきもの」と決定した発言（本案が議題の会議のみ）
        vote_chair = [r for r, k in kind if k == "chair" and is_committee and any(w in r["speech"] for w in VOTE_STRONG)]
        n_hit = len(hs)
        chair_texts = [r["speech"] for r, k in kind if k == "chair"]
        agenda_hit = any(short in t and ("議題" in t or "趣旨の説明を求め" in t) for t in chair_texts)
        if not (agenda_hit or explain):
            excluded.append({"院": house, "会議名": mname, "日付": date, "理由": f"法案名に触れた発言が{n_hit}件あるが、議題として宣告された形跡が無い（言及・付託の記載などとみて外した）", "meetingURL": murl})
            continue
        # 議題が本案だけか
        others = agenda_others(chair_texts, short)
        single = others == 0
        meetings.append({"院": house, "会議名": mname, "日付": date, "meetingURL": murl, "法案名に触れた発言数": n_hit,
                         "発言総数": len(recs), "議題": "本案のみ" if single else ("他の案件と併せて" if others is not None else "宣告を特定できず（併せてとして扱う）")})
        for r in explain:
            if r["speaker"] in {i["氏名"] for i in involvements if i["行動"] == "decide" and i["院"] == house and i["日付"] == date}:
                continue
            involvements.append({"氏名": r["speaker"], "院": house, "行動": "decide", "当時の肩書": r.get("speakerPosition") or None,
                                 "会派": r.get("speakerGroup"), "日付": date, "会議名": mname, "証拠URL": r["speechURL"],
                                 "備考": "提案理由・趣旨の説明（自動抽出：発言に法案名と「御説明/提案の理由/趣旨」を含む）"})
        if vote_chair:
            vr = vote_chair[-1]
            chair_cands[house] = {"氏名": vr["speaker"], "院": house, "行動": "chair", "当時の肩書": vr.get("speakerPosition") or "委員長",
                                  "会派": vr.get("speakerGroup"), "日付": date, "会議名": mname, "証拠URL": vr["speechURL"],
                                  "備考": "採決時の委員長（自動抽出：委員会で委員長が「可決すべきもの」と述べた最後の発言。併せて議題の会議では他の案件の決定のこともあるので要確認）"}
        # 質疑者
        by_speaker = {}
        for r, k in kind:
            if k != "member" or r["speaker"] in decide_names:
                continue
            if re.match(r"^○(衆議院議員|参議院議員)（", r["speech"]) or "審査の経過" in r["speech"] or "審査の結果" in r["speech"]:
                continue  # 他の議員提出案の説明者、委員長報告
            by_speaker.setdefault(r["speaker"], []).append(r)
        for name, rs in by_speaker.items():
            if not single and not any(any(kw in r["speech"] for kw in kws) for r in rs):
                continue
            people.setdefault(name, {"院": house, "会派": rs[0].get("speakerGroup") or "", "発言": []})
            people[name]["発言"].extend((date, house, mname, r["speechOrder"], r["speechURL"], r["speech"]) for r in rs)
            involvements.append({"氏名": name, "院": house, "行動": "question", "当時の肩書": rs[0].get("speakerPosition") or None,
                                 "会派": rs[0].get("speakerGroup"), "日付": date, "会議名": mname, "証拠URL": rs[0]["speechURL"],
                                 "備考": "議題が本案のみの会議の全発言" if single else "併せて議題の会議で、法案名・キーワードに触れた発言をした人"})

    involvements.extend(chair_cands.values())
    # 衆法：提出者を decide に。
    notes_extra = []
    if bid.startswith("衆法"):
        d0 = wareki(e["付託日_衆"]) or wareki(e["議決日_衆"])
        for n in proposers:
            involvements.insert(0, {"氏名": n, "院": "衆議院", "行動": "decide", "当時の肩書": "議案提出者",
                                    "肩書の出典": "衆議院 議案審議経過情報の「議案提出者一覧」（成立法一覧 enacted.csv の提出者一覧）", "会派": None,
                                    "日付": d0, "会議名": f"{bid} 議案提出（提出日は未取得のため衆議院付託日で代用）", "証拠URL": e["経過URL"],
                                    "備考": f"提出者表記：{e['提出者']}"})
        notes_extra.append("decide（衆法）：成立法一覧の提出者一覧の全員。日付は提出日が手元に無いので衆議院の付託日で代用（役職の日付引きだけに使う）。")
    for side, col in (("衆議院", "議決結果_衆"), ("参議院", "議決結果_参")):
        if "修正" in (e[col] or ""):
            notes_extra.append(f"要確認：{side}の議決結果が「{e[col]}」。修正案の提出者（amend）は会議録から手で特定する。")
    # 質疑の人が decide にも居るときの重複は後段（allocation_involvements）が最大の行動で数える。
    d = out / "speeches" / bid
    ex = out / "excerpts" / bid
    d.mkdir(parents=True, exist_ok=True)
    ex.mkdir(parents=True, exist_ok=True)
    index_rows = []
    for i, (name, p) in enumerate(people.items(), 1):
        head = f"氏名: {name}\n院: {p['院']}\n会派: {p['会派']}\n法案: {title}（{bid}）\n"
        full, part = [], []
        for date, house, mn, order, url, sp in p["発言"]:
            full.append(f"【{date} {house} {mn}】 {url}\n{sp.strip()}\n")
            if len(sp) <= 900:
                s = sp.strip()
            else:  # 法案名・キーワードに触れた段落を優先して残す
                paras = [x for x in sp.split("\n") if any(kw in x for kw in kws)]
                s = ("\n".join(paras) if paras else sp)[:900]
                if len(s) < len(sp):
                    s += " …（中略）…"
            part.append(f"■ {date} {house} {mn} 発言番号{order}\nspeechURL: {url}\n{s}\n")
        fn = f"{i:03d}_{name}.txt"
        (d / fn).write_text(head + "\n" + "\n".join(full), encoding="utf-8")
        txt = head + "\n" + "\n".join(part)
        (ex / fn).write_text(txt, encoding="utf-8")
        index_rows.append({"法律ID": bid, "題名": title, "氏名": name, "院": p["院"], "会派": p["会派"], "発言数": len(p["発言"]),
                           "抜粋の文字数": len(txt), "抜粋ファイル": str(ex / fn)})
    notes = (f"自動生成（scripts/build_collect_kokkai.py、取得元：国会会議録検索システム API、{s_from}〜{s_to}回国会）。人が確かめる点："
             "(1) 議題とみなした会議の一覧（meetings_excluded に外した会議と理由）、(2) chair は委員長発言の語句による自動抽出、"
             "(3) question は議題が本案のみの会議では全議員の発言、併せて議題の会議では法案名・キーワードに触れた人だけ（議題外の発言を含みうる。賛否の判定で「無関係」になる）、"
             "(4) 当時の肩書は API の speakerPosition（議員は空のことが多い）。" + " ".join(notes_extra))
    meta = {"id": bid, "title": title, "成立回次": s_to, "meetings": meetings, "meetings_excluded": excluded, "involvements": involvements, "notes": notes}
    (out / f"{bid}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    cnt = {}
    for v in involvements:
        cnt[v["行動"]] = cnt.get(v["行動"], 0) + 1
    print(bid, "会議", len(meetings), "除外", len(excluded), cnt, file=sys.stderr)
    return index_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", default=None, help="API 応答の保存先（再実行を軽くする。リポジトリの外に置く）")
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--task-id", default=TASK["id"], help="外部資料を登録するタスクID（.local/external-materials/<task-id>/）")
    a = ap.parse_args()
    TASK["id"] = a.task_id
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(a.cache) if a.cache else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
    rows = []
    for bid in a.ids:
        rows += collect(bid, out, a.sleep, cache)
    idx = out / "stance-input-index.csv"
    old = list(csv.DictReader(open(idx, encoding="utf-8"))) if idx.exists() else []
    keep = [r for r in old if r["法律ID"] not in a.ids]
    allrows = keep + rows
    if allrows:
        with open(idx, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, list(allrows[0].keys()))
            w.writeheader()
            w.writerows(allrows)


if __name__ == "__main__":
    main()
