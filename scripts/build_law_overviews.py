#!/usr/bin/env python3
"""法律ごとの概要（何をする・狙い・反対側の心配）の AI 要約をまとめ、検査して台帳にする。

材料は data/acquired/bill-speeches/speeches.csv（国会会議録の提案理由の説明と反対討論の抜粋）だけ。
要約は AI の読み手が抜粋ごとに1行で書いたもの（JSON Lines）を、ここで受け取って検査する。
- 材料の抜粋が空の項目に文が入っていたら捨てる（材料の無い推測を載せない）。
- 長すぎる文（60字超）は捨てる。
- 入力に無い id は捨てる。
- 1つの発言を2本以上の法案が材料にしているとき（まとめて説明された法案など）は、抜粋からの要約を使わない。
  抜粋は発言の冒頭なので、題名が出ていても別の法案の説明の途中で触れているだけのことがある
  （例：閣法-164-22 地方交付税法の改正の抜粋は、同じ発言の冒頭にある地方税法の改正の説明だった）。
  発言の全文からその法案の部分を切り出せたもの（segments.csv、scripts/split_shared_speeches.py）だけ、
  切り出した部分の要約（2つ目のフォルダ）で埋める。
出力：data/derived/law-overviews-v1/overviews.csv

- 別の読み手が、各要約をその抜粋だけと照らして確かめた結果（3つ目のフォルダ、{"id", 欄: "ok"|"ng"}）で、
  "ng"とされた欄は捨てる。照合していない欄も捨てる。"ng" になるのは、要約に抜粋に無い中身が入っているとき、
  "other" は、抜粋がそもそもこの法律についての発言ではないとき（予算や動議、別の法案への討論を拾った場合など）。
  そのときは「別の議題の発言」の欄に区分（説明・反対）を書き、画面ではその発言をこの法律の発言として示さない。
- 要約が空の欄の発言（画面では「見つかった発言」として示す）は、照合結果に {"説明の発言": "ok"}・{"反対の発言": "ok"}
  が無ければ「確かめていない発言」の欄に区分を書き、画面では示さない。"other" なら「別の議題の発言」に書く。
- "ok" は、照合した要約の文（"照合した要約": {欄: 文}）と、照らした抜粋の指紋（"照合した抜粋"）が
  いまの要約・抜粋と一致するときだけ使う。発言そのものの "ok"・"other"（欄の "other" も）は、"照合した発言": {区分: {"字数", "指紋"}} がいまの抜粋か切り出しと合うときだけ使う（抜粋は {"字数", "指紋"}：読み手に見せた頭の字数と、その部分の sha256 の先頭16字）。要約や抜粋を作り直した後に、古い照合結果で「確かめた」としないため。

使い方: python3 scripts/build_law_overviews.py <要約のフォルダ> <切り出した部分の要約のフォルダ> <照合結果のフォルダ>
照合結果のフォルダは省けない（別の読み手が確かめていない要約を、確かめた印つきで出さないため）。
フォルダが無い・読めない行がある・中身が無い・照合の欠けた欄が1%を超えるときは、台帳を書かずに終了コード 2 で止める。
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEECHES = ROOT / "data" / "acquired" / "bill-speeches" / "speeches.csv"
SEGMENTS = SPEECHES.parent / "segments.csv"
OUT = ROOT / "data" / "derived" / "law-overviews-v1" / "overviews.csv"
FIELDS = ["id", "題名", "何をする", "狙い", "反対側の心配", "材料", "別の議題の発言", "確かめていない発言", "要約の方法"]
LIMIT = 60
# 照合結果が欠けた欄（要約の欄・見つかった発言）の割合がこれを超えたら、照合が途中で止まったとみて台帳を書かない
MISSING_LIMIT = 0.01
COLUMNS = (("何をする", "説明の抜粋"), ("狙い", "説明の抜粋"), ("反対側の心配", "反対の抜粋"))
METHOD = "国会会議録の抜粋を AI（Claude）が1行に要約し、別の読み手が抜粋と照らして合わないものを捨てた。抜粋に無いことは書かない決まりで、材料の無い項目は空にした"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def matches(seen: dict, texts: list[str]) -> bool:
    """読み手が見た抜粋の頭（{"字数", "指紋"}）が、texts のどれかの頭と同じか。

    字数が正の整数でないもの（0字は、どの抜粋の頭とも同じになる）や、抜粋より長いものは合わないとする。
    """
    length = seen.get("字数")
    if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
        return False
    return any(len(text) >= length and digest(text[:length]) == seen.get("指紋") for text in texts)


def short(title: str) -> str:
    return re.sub(r"案$", "", title)


def read_jsonl(folder: str, dropped: dict) -> list[dict]:
    items = []
    for path in sorted(Path(folder).glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                dropped["読めない行"] += 1
    return items


def main(folder: str, segment_folder: str, verify_folder: str) -> int:
    # フォルダの打ち間違いや空の照合結果で、全部の要約を捨てた台帳を上書きしないよう、書く前に止める
    for path in (folder, segment_folder, verify_folder):
        if not Path(path).is_dir():
            print(f"フォルダがありません: {path}", file=sys.stderr)
            return 2
    # 3つのフォルダとも、読めない行が1行でもあれば（途中で切れた出力など）止める。
    # 要約と照合結果は id のある行が1件も無ければ止める。切り出しの要約は、切り出し（segments.csv）があるのに1件も無ければ止める
    loaded = {}
    has_segments = SEGMENTS.exists() and any(True for _ in csv.DictReader(SEGMENTS.open(encoding="utf-8")))
    for name, path, required in (("要約", folder, True), ("切り出しの要約", segment_folder, has_segments), ("照合結果", verify_folder, True)):
        broken = {"読めない行": 0}
        items = [item for item in read_jsonl(path, broken) if isinstance(item, dict) and item.get("id")]
        if broken["読めない行"] or (required and not items):
            print(f"{name}が読めないか、ありません: {path}", file=sys.stderr)
            return 2
        loaded[path] = items
    verdict_items = loaded[verify_folder]
    # 並べて取った分（speeches-*.csv）もまとめて読む
    speeches = {row["id"]: row for path in sorted(SPEECHES.parent.glob("speeches*.csv")) for row in csv.DictReader(path.open(encoding="utf-8"))}
    # 要約が途中で止まった出力（行は正しいが件数が足りない）で、載っていた概要を消さないよう、書く前に止める。
    # 対象は、説明か反対討論の発言が見つかった法案（要約の材料がある法案）
    expected = {law_id for law_id, row in speeches.items() if row["説明のURL"] or row["反対のURL"]}
    lacking = expected - {str(item.get("id", "")) for item in loaded[folder]}
    if expected and len(lacking) / len(expected) > MISSING_LIMIT:
        print(f"要約が欠けています（{len(lacking)}/{len(expected)} 本）。要約を最後まで回してから作り直してください: {folder}", file=sys.stderr)
        return 2
    written: dict[str, dict] = {}
    # 欄ごとに、要約の材料にした抜粋（照合結果がこの抜粋に対するものか確かめるため）
    excerpts: dict[tuple[str, str], str] = {}
    dropped = {"見つかった発言を確かめていない": 0, "別の議題の発言": 0, "材料なし": 0, "長すぎ": 0, "不明な id": 0, "読めない行": 0, "どの法案の話か区別できない": 0, "照合で合わない": 0, "照合していない": 0, "照合した文と違う": 0}
    shared: dict[tuple[str, str], list[dict]] = {}
    for row in speeches.values():
        for basis in ("説明のURL", "反対のURL"):
            if row[basis]:
                shared.setdefault((basis, row[basis]), []).append(row)
    for item in loaded[folder]:
        source = speeches.get(item.get("id", ""))
        if not source:
            dropped["不明な id"] += 1
            continue
        row = {"id": source["id"], "題名": source["題名"], "材料": "", "要約の方法": METHOD}
        for column, basis in COLUMNS:
            text = str(item.get(column) or "").strip()
            if text and not source[basis]:
                dropped["材料なし"] += 1
                text = ""
            url_key = "説明のURL" if basis == "説明の抜粋" else "反対のURL"
            if text and len(shared[(url_key, source[url_key])]) > 1:
                dropped["どの法案の話か区別できない"] += 1
                text = ""
            if len(text) > LIMIT:
                dropped["長すぎ"] += 1
                text = ""
            row[column] = text
            if text:
                excerpts[(row["id"], column)] = source[basis]
        row["材料"] = "・".join(name for name, basis in (("提案理由の説明", "説明のURL"), ("反対討論", "反対のURL")) if source[basis])
        written[row["id"]] = row
    refilled = 0
    segments: dict[tuple[str, str], str] = {}
    if SEGMENTS.exists():
        # 切り出しは、いまの発言 URL から切り出したものだけ使う（発言を取り直して URL が変わったら、古い切り出しは使わない）
        for row in csv.DictReader(SEGMENTS.open(encoding="utf-8")):
            source = speeches.get(row["id"])
            if source and row["URL"] == source.get(f"{row['区分']}のURL"):
                segments[(row["id"], row["区分"])] = row["抜粋"]
    # 切り出しの要約が途中で止まった出力（行は正しいが件数が足りない）で、切り出しから埋めた要約を消さないよう、書く前に止める
    expected = {law_id for law_id, _ in segments if law_id in written}
    summarized = {str(item.get("id", "")) for item in loaded[segment_folder]}
    lacking = expected - summarized
    if expected and len(lacking) / len(expected) > MISSING_LIMIT:
        print(f"切り出しの要約が欠けています（{len(lacking)}/{len(expected)} 本）。要約を最後まで回してから作り直してください: {segment_folder}", file=sys.stderr)
        return 2
    for item in loaded[segment_folder]:
        row = written.get(item.get("id", ""))
        if not row:
            dropped["不明な id"] += 1
            continue
        for column, basis in COLUMNS:
            text = str(item.get(column) or "").strip()
            kind = "説明" if basis == "説明の抜粋" else "反対"
            if not text or row[column]:
                continue
            if not segments.get((row["id"], kind)):
                dropped["材料なし"] += 1
                continue
            if len(text) > LIMIT:
                dropped["長すぎ"] += 1
                continue
            row[column] = text
            excerpts[(row["id"], column)] = segments[(row["id"], kind)]
            refilled += 1
    verdicts = {item["id"]: item for item in verdict_items}
    for row in written.values():
        verdict = verdicts.get(row["id"], {})
        source = speeches[row["id"]]

        def seen_now(kind: str) -> bool:
            """読み手が見た抜粋（"照合した発言": {区分: {"字数", "指紋"}}）が、いまの抜粋か切り出しと合うか。"""
            seen = (verdict.get("照合した発言") or {}).get(kind) or {}
            current = [text for text in (source[f"{kind}の抜粋"], segments.get((row["id"], kind), "")) if text]
            return matches(seen, current)

        other = []
        for column, basis in COLUMNS:
            # "other"（別の議題）も、読み手が見た抜粋がいまの抜粋と合うときだけ使う。合わなければ照合していないものとして扱う
            if verdict.get(column) == "other" and seen_now("説明" if basis == "説明の抜粋" else "反対"):
                # 抜粋が予算・動議・別の法案などについての発言、またはこの法案に賛成する討論で、
                # この法律の説明・反対討論ではなかった（要約が空の欄も、見つかった発言として示さないために記録する）
                kind = "説明" if basis == "説明の抜粋" else "反対"
                if kind not in other:
                    other.append(kind)
            if not row[column]:
                continue
            if verdict.get(column) == "ok":
                checked = (verdict.get("照合した要約") or {}).get(column) == row[column]
                seen = (verdict.get("照合した抜粋") or {}).get(column) or {}
                # 読み手には抜粋の頭の部分だけを見せたことがあるので、見せた字数の分を比べる
                checked = checked and matches(seen, [excerpts.get((row["id"], column), "")])
                if checked:
                    continue
                dropped["照合した文と違う"] += 1
                row[column] = ""
                continue
            reason = verdict.get(column)
            if reason == "other" and ("説明" if basis == "説明の抜粋" else "反対") not in other:
                reason = ""
            dropped[{"ng": "照合で合わない", "other": "別の議題の発言"}.get(reason, "照合していない")] += 1
            row[column] = ""
        # 要約が空でも発言の URL があるもの（画面では「見つかった発言」として示す）は、別の読み手が
        # この法律の説明・反対討論だと確かめた（{"説明の発言": "ok"} など）ものだけを示す。確かめていないものは示さない
        unchecked = []
        for kind, column, url in (("説明", "何をする", "説明のURL"), ("反対", "反対側の心配", "反対のURL")):
            # 発言そのものの判定（"ok"・"other"）も、読み手が見た抜粋がいまの抜粋か切り出しと合うときだけ使う
            if verdict.get(f"{kind}の発言") == "other" and kind not in other and seen_now(kind):
                other.append(kind)
            relevant = verdict.get(f"{kind}の発言") == "ok" and seen_now(kind)
            if source[url] and not row[column] and kind not in other and not relevant:
                unchecked.append(kind)
                dropped["見つかった発言を確かめていない"] += 1
        row["別の議題の発言"] = "・".join(other)
        row["確かめていない発言"] = "・".join(unchecked)
    # 照合が途中で止まった出力（行は正しいが件数が足りない）で、要約の大半を捨てた台帳を上書きしないよう、書く前に止める
    candidates = sum(1 for row in written.values() for column, _ in COLUMNS if row[column]) + dropped["照合した文と違う"] + dropped["照合で合わない"] + dropped["別の議題の発言"] + dropped["照合していない"]
    candidates += sum(1 for row in written.values() for kind, url in (("説明", "説明のURL"), ("反対", "反対のURL")) if speeches[row["id"]][url])
    missing = dropped["照合していない"] + dropped["見つかった発言を確かめていない"]
    if candidates and missing / candidates > MISSING_LIMIT:
        print(f"照合結果が欠けています（{missing}/{candidates} 欄）。照合を最後まで回してから作り直してください: {verify_folder}", file=sys.stderr)
        return 2
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for law_id in speeches:
            if law_id in written:
                writer.writerow(written[law_id])
    filled = sum(1 for row in written.values() if row["何をする"])
    print(json.dumps({"要約した法律": len(written), "何をするが入った": filled, "切り出しから埋めた項目": refilled, "捨てた": dropped}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(*sys.argv[1:]))
