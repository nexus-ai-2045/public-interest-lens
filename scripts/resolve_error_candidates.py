"""誤りの型の全件検査（error-type-check-v1）の候補を、一次資料の読み直しの記録から確定させる。AI は呼ばない。

  python3 scripts/resolve_error_candidates.py collect   .local/reread-v1/ の読み直しの生の記録を records/ にまとめる（1回だけ）
  python3 scripts/resolve_error_candidates.py           records/ と規則から corrections.csv・confirmed.csv・resolutions.csv を書く
  python3 scripts/resolve_error_candidates.py --check   出力が今の入力から作り直したものと同じか確かめる

決め方（この順。規則はここだけに書く）
  K2（税法の年度改正を定型改正に置いた）：読み直しの指示文 prompt-v1 の類型の定義
      「税法の年度ごとの改正は税率や対象を変えうるので、ここ（実質改正）に入る」をそのまま当てて、類型を実質改正に直す。AI は読まない。
  そのほかの型：項目は K1・K3 → 類型、C1・C2・C3 → 経済に効くか。
      1. Haiku 2系統（A：議案本文から、B：会議録から）が同じ値（判定不能でない）→ その値。
      2. 割れたら Sonnet（C、議案本文の条文・附則と会議録を読む）。C が A か B と同じ値 → その値（3つのうち2つ）。
      3. それでも決まらなければ Opus が一次資料で裁定（R）。裁定の値（判定不能でない）→ その値。
      4. 裁定も判定不能 → 決められない（候補のまま残す。サイトの値は直さない）。
      5. 経済に効くかを制度と決めても、制度と読んだ記録の判断が読めていない本法・条文・附則に懸かる（unread()）→ 決められない。
  決まった値の使い方
      類型：サイトの類型と同じ → confirmed.csv（誤りなし）。違う（空を含む）→ corrections.csv（直す）。
      経済に効くか：決まったら corrections.csv（C1 の「経済に効く」はサイトの区分と同じ語でも、到達点の扱いを直すので行を置く）。
  既にある行（#208 の6本）は書き換えない。
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived"
OUT = DERIVED / "primary-source-corrections-v1"
REC = OUT / "reread-v1"
RAW = ROOT / ".local" / "reread-v1"
CASCADE = REC / "cascade.csv"  # 1回目の反映の後に作り直した候補で、読み直した法律が新しく当たった C の型（写し）
FROZEN = REC / "candidates-at-reread.csv"  # 読み直しを始めた時点（2026-11-19、#208 の時点）の候補（R1 を除く）とサイトの値
PROMPT = "reverification-v1/prompt-v1.md（版 v1）"
RECORD = "data/derived/primary-source-corrections-v1/reread-v1/"
K2_RECORD = "data/derived/error-type-check-v1/README.md（K2）"
KIND_CODE = {"閣法": "09", "衆法": "05", "参法": "06"}
HONBUN = "https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/honbun/houan/g{s:03d}{c}{n:03d}.htm"
K2_QUOTE = "税法の年度ごとの改正は税率や対象を変えうるので、ここに入る。"
SITE_WORD = {"経済に効く": "経済に効く", "制度のみ": "制度"}
TYPE_ITEM = {"K1": "類型", "K3": "類型", "C1": "経済に効くか", "C2": "経済に効くか", "C3": "経済に効くか", "連鎖": "経済に効くか"}
CORR_HEADER = ["id", "項目", "直した値", "直す前の値", "理由", "引用", "出典URL", "判定者", "指示文", "記録"]
CONF_HEADER = ["id", "項目", "確かめた値", "理由", "判定者", "記録"]
RES_HEADER = ["id", "型", "項目", "サイトの値", "系統A", "系統B", "Sonnet", "Opus 裁定", "決めた値", "決め方", "決着"]
JUDGE = {
    "一致": "Haiku 2系統（系統A 議案本文から・系統B 会議録から）が一致",
    "多数": "Haiku 2系統が割れ、Sonnet（系統C 議案本文の条文・附則と会議録）が片方と一致（3つのうち2つ）",
    "裁定": "Haiku 2系統と Sonnet で決まらず、Opus が一次資料で裁定",
    "決められない": "Haiku 2系統・Sonnet・Opus のどれも一次資料から決められない（判定不能のまま残す）",
    "本法未読": "読み手は制度としたが、本法や条文・附則を読めていないと書き、その判断を読めた範囲に限っている。改正法だけでは補助や特例の有無が分からないので、制度とは確定しない（判定不能のまま残す。Codex の指摘）",
}
# 制度（経済に効かない）と決めた読みを確定しない条件（Codex の指摘）。期限の延長や大きな法律は、読めなかった本法・条文・附則で経済に効くかが変わりうる
UNREAD_BASE = ("未読", "取得できず")  # 経済の理由に、本法や附則を読めていないと書いた
HEDGE = re.compile(r"読めず|読めた範囲|読めた条文|読めた本文|読めた第|確認できな|未確認|未精読")  # 経済の理由を読めた範囲に限った
CUT_BODY = re.compile(r"附則|条文|第[一二三四五六七八九十百〇0-9]+条|後半|以降|先頭")  # 「読めなかった資料」に条文の欠けがある


def unread(rec: dict) -> bool:
    """この記録の経済の判断が、読めていない条文に懸かっている。
    「読めなかった資料」の欄だけでは決めない（会議録が見つからない・理由の節が無いなどはほぼ毎回あり、経済の判断に効かない）。"""
    why = rec.get("経済の理由") or rec.get("理由", "")
    if any(w in why for w in UNREAD_BASE):
        return True
    cut = any(CUT_BODY.search(u) and "会議録" not in u[:6] for u in rec.get("読めなかった資料") or [])
    return bool(HEDGE.search(why)) and cut
FIELD = {"類型": ("類型", "類型の理由"), "経済に効くか": ("経済に効くか", "経済の理由")}


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def honbun(i: str) -> str:
    k, s, n = i.split("-")
    return HONBUN.format(s=int(s), c=KIND_CODE[k], n=int(n))


def collect() -> int:
    """.local/reread-v1/{A,B,C}/{id}.json と R/{id}__{項目}.json を records/ の4つの JSON にまとめる。"""
    REC.mkdir(parents=True, exist_ok=True)
    for line in ("A", "B", "C"):
        rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((RAW / line).glob("*.json"))]
        old = REC / f"line{line}.json"
        n_old = len(json.loads(old.read_text(encoding="utf-8"))) if old.exists() else 0
        if len(rows) < n_old:  # 生の記録（.local、Git に入れない）が無い環境で、記録を空で上書きしない
            print(f"止める：{RAW / line} の記録 {len(rows)} 件が、置いてある記録 {n_old} 件より少ない", file=sys.stderr)
            return 1
        (REC / f"line{line}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"系統{line}：{len(rows)}件")
    rulings: dict[str, dict] = {}
    old_rulings = json.loads((REC / "rulings.json").read_text(encoding="utf-8")) if (REC / "rulings.json").exists() else {}
    if len(list((RAW / "R").glob("*.json"))) < sum(len(v) for v in old_rulings.values()):
        print(f"止める：{RAW / 'R'} の裁定が置いてある裁定より少ない", file=sys.stderr)
        return 1
    for p in sorted((RAW / "R").glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        i, item = p.stem.split("__")
        rulings.setdefault(i, {})[item] = {k: r.get(k, "") for k in ("値", "理由", "引用", "出典URL")}
    (REC / "rulings.json").write_text(json.dumps(rulings, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"裁定：{sum(len(v) for v in rulings.values())}件")
    return 0


def load_records() -> tuple[dict, dict, dict, dict]:
    def lines(name: str) -> dict:
        p = REC / name
        return {x["id"]: x for x in json.loads(p.read_text(encoding="utf-8"))} if p.exists() else {}
    p = REC / "rulings.json"
    return lines("lineA.json"), lines("lineB.json"), lines("lineC.json"), (json.loads(p.read_text(encoding="utf-8")) if p.exists() else {})


def ok(v: str | None) -> str | None:
    return v if v and v != "判定不能" else None


def vote(i: str, item: str, a: dict, b: dict, c: dict, rulings: dict) -> tuple[str | None, str, dict | None]:
    """読みの多数で決める（一致・多数・裁定）。"""
    key = FIELD[item][0]
    va, vb = ok(a.get(i, {}).get(key)), ok(b.get(i, {}).get(key))
    if va and va == vb:
        return va, "一致", a[i]
    vc = ok(c.get(i, {}).get(key))
    if vc and vc in (va, vb):
        return vc, "多数", c[i]
    r = rulings.get(i, {}).get(item)
    if r and ok(r.get("値")):
        return r["値"], "裁定", r
    return None, "決められない", None


def decide(i: str, item: str, a: dict, b: dict, c: dict, rulings: dict) -> tuple[str | None, str, dict | None]:
    """(値, 決め方, 根拠に使う記録)。値が None なら決められない。"""
    v, how, rec = vote(i, item, a, b, c, rulings)
    if item == "経済に効くか" and SITE_WORD.get(v or "", v) == "制度":
        # 制度と読んだ記録すべてを見る（2系統が一致しても、片方だけが未読を書くことがある）
        key = FIELD[item][0]
        recs = [rec] + [d[i] for d in (a, b, c) if i in d and ok(d[i].get(key)) == v]
        if any(unread(r) for r in recs):
            return None, "本法未読", rec
    return v, how, rec


def evidence(rec: dict, item: str, how: str) -> tuple[str, str, str]:
    if how == "裁定":
        return rec["理由"], rec["引用"], rec["出典URL"]
    quotes, urls = rec.get("引用") or [""], rec.get("出典URL") or [""]
    if item == "経済に効くか":  # 改正文の書き出し（「次のように改正する」）は経済の根拠にならないので、ほかの引用があればそちらを使う
        quotes = [q for q in quotes if "次のように改正" not in q] or quotes
    # 記録は引用と出典URLの対応を持たないので、出典は全部を ; でつないで残す（会議録の引用に議案本文の URL だけが付かないように）
    return rec[FIELD[item][1]], quotes[0], ";".join(dict.fromkeys(u for u in urls if u))


def build() -> tuple[list[dict], list[dict], list[dict]]:
    # 既にある行は #208 の行だけ（このスクリプトが書いた行は毎回作り直す）
    existing = [r for r in read_csv(OUT / "corrections.csv") if r["記録"] not in (RECORD, K2_RECORD)]
    have = {(r["id"], r["項目"]) for r in existing}
    # 読み直しを始めた時点の候補とサイトの値（直した後に作り直すと候補もサイトの値も変わるので、写しを使う）
    cands = read_csv(FROZEN)
    types: dict[str, set[str]] = {}
    site_at: dict[str, dict] = {}
    for r in cands:
        types.setdefault(r["id"], set()).add(r["型"])
        site_at[r["id"]] = r
    # 類型を直したことで新しく C の型に当たった法律と、新しく効果なし（定例）になった法律（型「連鎖」）。
    # 読み直しは両方の項目を読んでいるので、同じ記録で経済に効くかも決める（#208 の閣法-180-38・衆法-217-15 と同じ扱い：
    # 定型改正でも、続けなければ止まる補助や特例があれば経済に効くとして定例の規則 RT8 に当てない）
    for r in read_csv(CASCADE) if CASCADE.exists() else []:
        types.setdefault(r["id"], set()).add(r["型"])
        site_at.setdefault(r["id"], r)
    a, b, c, rulings = load_records()

    new_corr, conf, res = [], [], []
    for i in sorted(types):
        ts = types[i]
        title = site_at[i]["題名"]
        site_kind = site_at[i]["サイトの類型"]
        site_econ = site_at[i]["サイトの経済に効くか"]
        if "K2" in ts and (i, "類型") in have:
            res.append({"id": i, "型": "K2", "項目": "類型", "サイトの値": site_kind, "系統A": "", "系統B": "", "Sonnet": "",
                        "Opus 裁定": "", "決めた値": "", "決め方": "既に直してある（#208）", "決着": "直した"})
        elif "K2" in ts:
            new_corr.append({"id": i, "項目": "類型", "直した値": "実質改正", "直す前の値": site_kind,
                             "理由": f"税法（{title}）の一部改正。読み直しの指示文の類型の定義では、税法の年度ごとの改正は実質改正",
                             "引用": K2_QUOTE, "出典URL": honbun(i),
                             "判定者": "規則 K2（AI は読まない。指示文の類型の定義をそのまま当てた）",
                             "指示文": PROMPT, "記録": K2_RECORD})
            res.append({"id": i, "型": "K2", "項目": "類型", "サイトの値": site_kind, "系統A": "", "系統B": "", "Sonnet": "",
                        "Opus 裁定": "", "決めた値": "実質改正", "決め方": "規則 K2", "決着": "直した"})
        for item in sorted({TYPE_ITEM[t] for t in ts if t in TYPE_ITEM}):
            code = "・".join(sorted(t for t in ts if TYPE_ITEM.get(t) == item))
            site = site_kind if item == "類型" else site_econ
            key = FIELD[item][0]
            row = {"id": i, "型": code, "項目": item, "サイトの値": site or "（空）",
                   "系統A": a.get(i, {}).get(key, ""), "系統B": b.get(i, {}).get(key, ""),
                   "Sonnet": c.get(i, {}).get(key, ""), "Opus 裁定": rulings.get(i, {}).get(item, {}).get("値", "")}
            if item == "類型" and "K2" in ts:  # 類型は規則 K2 が決める（1つの項目に行を2つ置かない）。読みは記録として残す
                v, how, _ = decide(i, item, a, b, c, rulings)
                res.append({**row, "決めた値": "実質改正", "決め方": f"規則 K2（読み直しは{v or '決まらず'}、{how}）", "決着": "直した"})
                continue
            if (i, item) in have:
                res.append({**row, "決めた値": "", "決め方": "既に直してある（#208）", "決着": "直した"})
                continue
            v, how, rec = decide(i, item, a, b, c, rulings)
            if v is None:
                res.append({**row, "決めた値": "", "決め方": how, "決着": "決められない"})
                if item == "経済に効くか":  # 決められないことも後段へ渡す（定例の規則で効果なしに確定させない）
                    rec = rec or a.get(i) or b.get(i) or {}
                    reason, quote, url = evidence(rec, item, "裁定" if "理由" in rec else "一致") if rec else ("", "", "")
                    new_corr.append({"id": i, "項目": item, "直した値": "判定不能", "直す前の値": site,
                                     "理由": reason, "引用": quote, "出典URL": url, "判定者": JUDGE[how],
                                     "指示文": PROMPT, "記録": RECORD})
                continue
            v = SITE_WORD.get(v, v)
            reason, quote, url = evidence(rec, item, how)
            if item == "類型" and v == site_kind:
                conf.append({"id": i, "項目": item, "確かめた値": v, "理由": reason, "判定者": JUDGE[how], "記録": RECORD})
                res.append({**row, "決めた値": v, "決め方": how, "決着": "誤りなし"})
                continue
            new_corr.append({"id": i, "項目": item, "直した値": v, "直す前の値": site,
                             "理由": reason, "引用": quote, "出典URL": url, "判定者": JUDGE[how],
                             "指示文": PROMPT, "記録": RECORD})
            res.append({**row, "決めた値": v, "決め方": how, "決着": "直した"})
    return existing + new_corr, conf, res


def render(header: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, header, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", nargs="?", choices=["collect"], help="collect：生の記録を records/ にまとめる")
    parser.add_argument("--check", action="store_true", help="出力が今の入力から作り直したものと同じか確かめる")
    args = parser.parse_args(argv)
    if args.command == "collect":
        return collect()
    corr, conf, res = build()
    files = {OUT / "corrections.csv": render(CORR_HEADER, corr), OUT / "confirmed.csv": render(CONF_HEADER, conf),
             REC / "resolutions.csv": render(RES_HEADER, res)}
    if args.check:
        stale = [p.name for p, t in files.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
        print("一致" if not stale else f"出力が古い：{stale}")
        return 1 if stale else 0
    for p, t in files.items():
        p.write_text(t, encoding="utf-8")
    from collections import Counter
    print(Counter((r["決着"]) for r in res))
    print(Counter((r["項目"], r["決め方"]) for r in res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
