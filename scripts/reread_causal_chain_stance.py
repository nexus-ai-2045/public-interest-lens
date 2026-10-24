#!/usr/bin/env python3
"""因果の鎖の賛否のうち、決まらなかった組を会議録の原文で読み直し、2系統の一致で決める。

1. prepare: 保留の組（stance-merged.csv の「保留」）と、系統B がまだ無い法案の組について、
   会議録 API から取った発言の原文（speeches/）から、法案に触れた部分を抜き出した読み直し用の文書
   reread/<法案ID>/NNN_氏名.txt と、読み手に渡す束 reread/batches/<束>.json を作る。
2. 読み手（系統C・系統D）が別々に束を読み、stance/reread.<束>.lineC.json・lineD.json に書く。
3. merge: 系統C と系統D が一致し、根拠の引用が原文にそのまま有るものだけ採用する。
   一致しないもの・引用が原文に無いものは「判定待ち」に回し、上位の読み手の判定
   （stance/reread.judge.json、理由つき）があれば、それを採用する。
   出力: stance-final.csv（全組の最終の立場と根拠）、involvements-causal-chain.csv（関与の表と同じ列）、
         stance-final-summary.json。
実名が入るので、出力は private-m2 側だけに置く。

使い方:
  python3 scripts/reread_causal_chain_stance.py prepare [--dir ...] [--batch-chars 70000]
  python3 scripts/reread_causal_chain_stance.py merge [--dir ...]
"""
import argparse, csv, json, re
from collections import Counter
from pathlib import Path

DEFAULT_DIR = "/mnt/project-files/private-m2/causal-chain"
BLOCK = re.compile(r"^■ ([^\n]+)\nspeechURL: (\S+)\n\n(.*?)(?=\n■ |\Z)", re.S | re.M)
# 法案名のほかに、その法律の審議だと分かる言葉（取得時の keywords に足す）
EXTRA = {"衆法-186-35": ["サイバーセキュリティ"], "衆法-189-20": ["特定複合観光施設", "カジノ", "ＩＲ"],
         "閣法-189-27": ["支援機構", "海外通信"], "閣法-193-59": ["通訳案内", "旅行業法", "ランドオペレーター"],
         "閣法-196-2": ["国際観光旅客税", "出国税", "観光旅客税"], "閣法-196-4": ["国際観光", "観光振興"]}
STANCE_WORDS = ("賛成", "反対", "本法案", "本案", "法律案", "修正", "撤回", "廃案", "成立", "提案")
STANCES = ("支持", "反対", "中立", "無関係")


def blocks(txt):
    return [(h, u, b.strip()) for h, u, b in BLOCK.findall(txt)]


def focus(body, keys, limit):
    """長い発言は、冒頭と、法案の言葉・賛否の言葉を含む文だけを残す。"""
    if len(body) <= limit:
        return body
    sents = re.split(r"(?<=。)", body)
    keep, n = [sents[0]], len(sents[0])
    for s in sents[1:]:
        if any(k in s for k in keys) or any(w in s for w in STANCE_WORDS):
            if n + len(s) > limit:
                break
            keep.append(s); n += len(s)
    return " …（中略）… ".join(x.strip() for x in keep)


def reread_text(txt, keys, total=4000):
    head = txt.split("\n\n", 1)[0]
    bl = blocks(txt)
    hit = [b for b in bl if any(k in b[2] for k in keys) or any(w in b[2] for w in ("賛成", "反対"))]
    use = hit or bl[:3]
    per = max(600, total // max(1, len(use)))
    parts, n = [], 0
    for h, u, b in use:
        s = focus(b, keys, per)
        parts.append(f"■ {h}\nspeechURL: {u}\n{s}\n")
        n += len(s)
        if n > total:
            parts.append(f"（法案に触れた発言はほかに {len(use) - len(parts)} 件。以下省略）"); break
    if not hit and len(bl) > 3:
        parts.append(f"（法案名・賛否の言葉を含む発言は無い。全 {len(bl)} 件のうち最初の3件だけ載せた）")
    return head + f"\n全発言数: {len(bl)}（法案名・賛否の言葉を含む発言 {len(hit)} 件）\n\n" + "\n".join(parts)


def metas(d):
    for p in sorted(d.glob("*.json")):
        if not p.name.startswith("stance"):
            yield json.load(open(p, encoding="utf-8"))


def targets(d):
    """読み直す組：保留の組と、系統B の無い法案の全員。"""
    merged = list(csv.DictReader(open(d / "stance-merged.csv", encoding="utf-8")))
    pend = {(r["法案ID"], r["氏名"]) for r in merged if r["判定"] == "保留"}
    with_b = {r["法案ID"] for r in merged}
    out = []
    for m in metas(d):
        for s in m["speakers"]:
            if (m["id"], s["氏名"]) in pend or m["id"] not in with_b:
                out.append((m, s))
    return out


def prepare(d, batch_chars):
    out_dir = d / "reread"; (out_dir / "batches").mkdir(parents=True, exist_ok=True)
    items = []
    for m, s in targets(d):
        files = list((d / "speeches" / m["id"]).glob(f"*_{s['氏名']}.txt"))
        if len(files) != 1:
            raise SystemExit(f"発言のファイルが1つに決まりません: {m['id']} {s['氏名']} {files}")
        keys = list(dict.fromkeys(m.get("keywords", []) + EXTRA.get(m["id"], [])))
        txt = reread_text(files[0].read_text(encoding="utf-8"), keys)
        p = out_dir / m["id"] / files[0].name
        p.parent.mkdir(exist_ok=True); p.write_text(txt, encoding="utf-8")
        items.append({"法案ID": m["id"], "題名": m["title"], "氏名": s["氏名"], "区分": s.get("区分", ""), "file": str(p), "chars": len(txt)})
    batches, cur, n = [], [], 0
    for it in items:
        if cur and (n + it["chars"] > batch_chars):
            batches.append(cur); cur, n = [], 0
        cur.append(it); n += it["chars"]
    if cur:
        batches.append(cur)
    # 前の束分けの定義を残すと load_line が古い割り当てを読むので、書く前に消す。
    for old in (out_dir / "batches").glob("b*.json"):
        old.unlink()
    for i, b in enumerate(batches, 1):
        (out_dir / "batches" / f"b{i:02d}.json").write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(items)} 組を {len(batches)} 束に分けた", Counter(it["法案ID"] for it in items))


def load_line(d, line):
    """今の束（reread/batches/bNN.json）に入っている組の結果だけを、その束のファイルから読む。
    prepare をやり直して束の割り当てが変わっても、古い束の結果は混ざらない。"""
    assigned = {}
    for b in sorted((d / "reread" / "batches").glob("b*.json")):
        for it in json.load(open(b, encoding="utf-8")):
            assigned[(it["法案ID"], it["氏名"])] = b.stem
    out = {}
    for f in sorted((d / "stance").glob(f"reread.*.{line}.json")):
        bid = f.name.split(".")[1]
        for r in json.load(open(f, encoding="utf-8")):
            key = (r["法案ID"], r["氏名"])
            if assigned.get(key) == bid:
                out[key] = r
    return out


def quote_ok(d, bid, name, quote):
    """引用が発言の原文にそのまま有るか（空白の違いだけ吸収）。空の引用は、無関係のときだけ認める。"""
    if not quote:
        return False
    f = next((d / "speeches" / bid).glob(f"*_{name}.txt"), None)
    if f is None:
        return False
    norm = lambda t: re.sub(r"\s+", "", t)
    return norm(quote.replace("…", "")) in norm(f.read_text(encoding="utf-8"))


def quote_url(d, bid, name, quote, fallback=""):
    """引用を含む発言の speechURL（読み手の書いた URL より原文を優先する）。"""
    f = next((d / "speeches" / bid).glob(f"*_{name}.txt"), None)
    if f is None or not quote:
        return fallback
    norm = lambda t: re.sub(r"\s+", "", t)
    q = norm(quote.replace("…", ""))
    for _h, u, b in blocks(f.read_text(encoding="utf-8")):
        if q in norm(b):
            return u
    return fallback


def merge(d):
    merged = list(csv.DictReader(open(d / "stance-merged.csv", encoding="utf-8")))
    prev = {(r["法案ID"], r["氏名"]): r for r in merged}
    C, D = load_line(d, "lineC"), load_line(d, "lineD")
    jp = d / "stance" / "reread.judge.json"
    J = {(r["法案ID"], r["氏名"]): r for r in json.load(open(jp, encoding="utf-8"))} if jp.exists() else {}
    tset = {(m["id"], s["氏名"]) for m, s in targets(d)}
    rows, waiting, summary = [], [], Counter()
    for m in metas(d):
        for s in m["speakers"]:
            key = (m["id"], s["氏名"])
            base = {"法案ID": m["id"], "題名": m["title"], "氏名": s["氏名"], "院": s["院"], "会派": s["会派"], "区分": s.get("区分", ""), "発言数": s["発言数"]}
            if key not in tset:
                p = prev.get(key)
                if p is None:
                    rows.append({**base, "立場": "", "決め方": "判定待ち", "根拠の引用": "", "証拠URL": "", "系統C": "", "系統D": "", "判定の理由": "系統A・B の記録が無い"})
                    summary[("判定待ち", "")] += 1
                    continue
                rows.append({**base, "立場": p["立場"], "決め方": "系統A・Bの一致", "根拠の引用": p["根拠の引用_B"] or p["根拠の引用_A"],
                             "証拠URL": p["証拠URL_B"] or p["証拠URL_A"], "系統C": "", "系統D": "", "判定の理由": ""})
                summary[("系統A・Bの一致", p["立場"])] += 1
                continue
            c, dd = C.get(key, {}), D.get(key, {})
            sc, sd = c.get("立場", "なし"), dd.get("立場", "なし")
            qc, qd = c.get("根拠の引用", ""), dd.get("根拠の引用", "")
            okc = sc == "無関係" or quote_ok(d, *key, qc)
            okd = sd == "無関係" or quote_ok(d, *key, qd)
            if sc == sd and sc in STANCES and okc and okd:
                pick = c if (qc and sc != "無関係") else dd
                rows.append({**base, "立場": sc, "決め方": "系統C・Dの一致", "根拠の引用": pick.get("根拠の引用", ""),
                             "証拠URL": quote_url(d, *key, pick.get("根拠の引用", ""), pick.get("証拠URL", "")), "系統C": sc, "系統D": sd, "判定の理由": ""})
                summary[("系統C・Dの一致", sc)] += 1
                continue
            why = f"系統C={sc}・系統D={sd}" + ("" if okc and okd else "（引用が原文に無い）")
            j = J.get(key)
            agreed = [x for x, ok in ((sc, okc), (sd, okd)) if ok]
            if j and j.get("立場") in agreed and j["立場"] in STANCES and (j["立場"] == "無関係" or quote_ok(d, *key, j.get("根拠の引用", ""))):
                rows.append({**base, "立場": j["立場"], "決め方": "上位の読み手の判定", "根拠の引用": j.get("根拠の引用", ""),
                             "証拠URL": quote_url(d, *key, j.get("根拠の引用", ""), j.get("証拠URL", "")), "系統C": sc, "系統D": sd, "判定の理由": f"{why}。{j.get('理由', '')}"})
                summary[("上位の読み手の判定", j["立場"])] += 1
                continue
            if j and j.get("立場") in STANCES and j["立場"] not in agreed:
                why += f"。上位の読み手={j['立場']}（引用が原文に有る C・D のどちらとも違うので採らない。ADR 0007）"
            rows.append({**base, "立場": "", "決め方": "判定待ち", "根拠の引用": "", "証拠URL": "", "系統C": sc, "系統D": sd, "判定の理由": why})
            waiting.append({**base, "系統C": c, "系統D": dd, "理由": why, "file": str(next((d / "reread" / m["id"]).glob(f"*_{s['氏名']}.txt"), ""))})
            summary[("判定待ち", "")] += 1
    cols = list(rows[0].keys())
    with open(d / "stance-final.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)
    (d / "stance" / "reread.waiting.json").write_text(json.dumps(waiting, ensure_ascii=False, indent=1), encoding="utf-8")
    write_involvements(d, rows)
    out = {f"{k[0]}:{k[1]}" if k[1] else k[0]: v for k, v in sorted(summary.items())}
    (d / "stance-final-summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1), f"判定待ち {len(waiting)}")


INV_COLS = ["法律ID", "題名", "氏名", "氏名_原表記", "院", "行動", "当時の肩書", "立場区分", "立場の根拠", "日付", "証拠URL",
            "系統A", "系統B", "参院本会議の賛否", "算入", "除外理由"]
DATE = re.compile(r"/txt/\d{4}\d{5}X\d{3}(\d{8})/")


def write_involvements(d, rows):
    """関与の表（allocation-v1/involvements.csv）と同じ列で、審議での立場を「質疑」の行として書く。
    算入は、関与の表の約束どおり「支持」だけ。質疑は成立を左右しないので、額の配分には入らない（記録として表示だけ）。"""
    out = []
    for r in rows:
        if r["区分"] != "議員" or r["立場"] in ("", "無関係"):
            continue
        m = DATE.search(r["証拠URL"])
        date = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}" if m else ""
        counted = r["立場"] == "支持"
        out.append({"法律ID": r["法案ID"], "題名": r["題名"], "氏名": r["氏名"], "氏名_原表記": r["氏名"], "院": r["院"], "行動": "question",
                    "当時の肩書": "", "立場区分": "other", "立場の根拠": r["根拠の引用"], "日付": date, "証拠URL": r["証拠URL"],
                    "系統A": r["系統C"] or r["立場"], "系統B": r["系統D"] or r["立場"], "参院本会議の賛否": "",
                    "算入": "はい" if counted else "いいえ",
                    "除外理由": "" if counted else f"審議での立場が{r['立場']}（{r['決め方']}。支持ではない）"})
    with open(d / "involvements-causal-chain.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, INV_COLS); w.writeheader(); w.writerows(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prepare", "merge"])
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--batch-chars", type=int, default=70000)
    a = ap.parse_args()
    d = Path(a.dir)
    prepare(d, a.batch_chars) if a.cmd == "prepare" else merge(d)


if __name__ == "__main__":
    main()
