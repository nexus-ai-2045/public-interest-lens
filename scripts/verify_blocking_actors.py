#!/usr/bin/env python3
"""技術を止めた側のデータ（data/acquired/blocking-actors/ の1,227件）を原本と2系統で照合する。

材料は scripts/fetch_blocking_originals.py が作った原本テキスト（private-m2/blocking-originals/）。

- 系統A（機械）: 行ごとに「原本にそのまま載るはずの値」（受付番号・再就職先・事業名など）を探し、
  その周りの原本の文に、要旨の言葉（漢字・カナの2文字組）がどれだけ残っているかを数える。
- 系統B（読み手）: 同じ行と原本の抜粋を AI の読み手が読み、要旨が原本どおりかを判定する。
  prepare-b で読み手に渡す束（JSON）を作り、読み手の答えを b-results/ に置く。
- 系統C（2人目の読み手）: 系統Bとは別の AI セッションが同じ抜粋を独立に読む（答えは c-results/）。
- merge: 系統A・B・C がどれも「一致」の行だけ「原本照合済み（機械の照合とAI2系統が一致）」にする。
  どれかが一致でなければ「保留：理由」。原本が取れていない行は「webfetch要約・暫定」のまま。

抜粋には官職つきの氏名が載るので、作業用の出力（lineA.csv・束・答え）は private-m2 側だけに置く。
リポジトリには行ごとの照合結果（氏名なし）と集計だけを書く。

使い方:
  python3 scripts/verify_blocking_actors.py line-a
  python3 scripts/verify_blocking_actors.py snapshot   # ブラウザへ渡す前に ファイル・行→行ハッシュ を残す
  python3 scripts/verify_blocking_actors.py prepare-b [--batch 25]
  python3 scripts/verify_blocking_actors.py merge
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "acquired" / "blocking-actors"
STATUS = DATA / "verify" / "status.csv"
ORIG = Path("/mnt/project-files/private-m2/blocking-originals")
WORK = Path("/mnt/project-files/private-m2/blocking-verify")
CONFIRMED = "原本照合済み（機械の照合とAI2系統が一致）"
PROVISIONAL = "webfetch要約・暫定"
STATUS_FIELDS = ["行ハッシュ", "ファイル", "行", "出典URL", "照合", "系統A", "系統B", "系統C", "誤りの型", "理由", "原本ページ", "原本sha256",
                 "原本観測時刻"]

# ファイルごとに、原本にそのまま載るはずの列（must）、ある程度載るはずの列（tokens）、
# 言い換えが入る要旨の列（topic）、分類の語がそのまま載るはずの列（label）。
SPECS = {
    "hotline": dict(must=["受付番号"], tokens=["所管省庁"], topic=["提案事項", "回答の理由（要旨）"], label="対応分類"),
    "council-followup": dict(must=[], tokens=["所管省庁"], topic=["事項", "理由（要旨）"], label=None),
    "wg-hearings": dict(must=[], tokens=["所管省庁", "発言者の官職"], topic=["理由（要旨）"], label=None),
    "shingikai": dict(must=[], tokens=["発言者の所属・肩書"], topic=["要旨"], label=None),
    "reemployment": dict(must=["再就職先"], tokens=["離職時の官職"], topic=[], label=None),
    "review-findings": dict(must=["事業名"], tokens=["府省"], topic=["所見の要旨"], label=None),
    "ordinances": dict(must=[], tokens=["自治体"], topic=["制限の内容（区域・期間など）", "条例名"], label=None),
}
_SKIP = {"", "不明", "記載なし", "（条例名未確認）", "所属・肩書記載なし（議事録に記載なし）"}


def spec_for(rel: str) -> dict:
    name = Path(rel).stem
    if name.startswith("hotline"):
        return SPECS["hotline"]
    if rel.startswith("2_shingikai/"):
        return SPECS["shingikai"]
    return SPECS[name]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"\s+", "", s)


SKIP_VALUES = {norm(v) for v in _SKIP}
CONTENT = re.compile(r"[㐀-鿿゠-ヿー々〆A-Za-z0-9]+")


def bigrams(s: str) -> set[str]:
    out = set()
    for run in CONTENT.findall(norm(s)):
        out.update(run[i:i + 2] for i in range(len(run) - 1))
    return out


def coverage(words: set[str], window: str) -> float:
    if not words:
        return 1.0
    return sum(w in window for w in words) / len(words)


def row_hash(rel: str, row: dict) -> str:
    body = json.dumps({k: v for k, v in row.items() if k != "確度"}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1((rel + body).encode()).hexdigest()[:16]


def first_int(s: str):
    m = re.search(r"\d+", s or "")
    return int(m.group()) if m else None


def load_rows():
    for f in sorted(DATA.glob("*/*.csv")):
        if f.parent.name == "verify":
            continue
        rel = f"{f.parent.name}/{f.name}"
        with f.open(encoding="utf-8", newline="") as fh:
            for i, r in enumerate(csv.DictReader(fh), start=1):
                yield rel, i, r


def load_index(orig: Path) -> dict:
    idx = {}
    p = orig / "index.csv"
    if not p.exists():
        return idx
    with p.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("状態") == "取得":
                raw = (orig / r["テキスト"]).read_text(encoding="utf-8")
                pages = raw.split("\f")
                starts, n = [], 0
                normed = []
                for pg in pages:
                    starts.append(n)
                    t = norm(pg)
                    normed.append(t)
                    n += len(t)
                idx[r["URL"]] = {"text": "".join(normed), "starts": starts, "sha": r["sha256"], "pdf": r["種類"] == "pdf",
                                  "observed": r.get("取得時刻", "")}
            else:
                idx[r["URL"]] = {"error": r.get("状態", "")}
    return idx


def page_of(doc: dict, pos: int) -> int:
    p = 1
    for i, s in enumerate(doc["starts"], start=1):
        if s <= pos:
            p = i
    return p


def locate(doc_text: str, row: dict, spec: dict) -> tuple[int, str]:
    """要旨の言葉がいちばん多く残る位置を探す。must の値があればその出現位置から選ぶ。"""
    topic = bigrams(" ".join(row.get(c, "") for c in spec["topic"] + spec["tokens"]))
    cands = []
    for c in spec["must"]:
        v = norm(row.get(c, ""))
        if v and v not in SKIP_VALUES:
            cands = [m.start() for m in re.finditer(re.escape(v), doc_text)]
            if not cands:
                return -1, c
            break
    if not cands:
        cands = list(range(0, max(len(doc_text) - 1, 1), 400))
    best = max(cands, key=lambda p: coverage(topic, doc_text[max(0, p - 300):p + 2500]))
    return best, ""


def line_a_row(rel: str, row: dict, doc: dict) -> dict:
    spec = spec_for(rel)
    text = doc["text"]
    pos, missing = locate(text, row, spec)
    if pos < 0:
        return {"系統A": "不一致", "誤りの型": "値が原本に無い", "理由": f"{missing}が原本に見つからない", "pos": -1}
    win = text[max(0, pos - 300):pos + 2500]
    out = {"pos": pos, "原本ページ": page_of(doc, pos) if doc["pdf"] else ""}
    lacks = []
    for c in spec["tokens"]:
        v = row.get(c, "")
        if norm(v) in SKIP_VALUES:
            continue
        parts = [p for p in re.split(r"[、・,／/ ]+", re.sub(r"（.*?）|\(.*?\)", "", v)) if len(norm(p)) >= 2]
        if parts and not any(norm(p) in win or coverage(bigrams(p), win) >= 0.6 for p in parts):
            lacks.append(c)
    if spec["label"]:
        lab = re.sub(r"（.*?）", "", row.get(spec["label"], ""))
        if norm(lab) and norm(lab) not in win:
            lacks.append(spec["label"])
    cov = coverage(bigrams(" ".join(row.get(c, "") for c in spec["topic"])), win)
    out["被覆率"] = round(cov, 2)
    if lacks:
        out.update({"系統A": "不一致", "誤りの型": "値が原本と違う", "理由": "・".join(lacks) + "が抜粋に無い"})
    elif cov < 0.45:
        out.update({"系統A": "不一致", "誤りの型": "要旨の言葉が原本に少ない", "理由": f"要旨の言葉の一致率{cov:.0%}"})
    else:
        out.update({"系統A": "一致", "誤りの型": "", "理由": ""})
    stated = first_int(row.get("ページ", ""))
    if doc["pdf"] and stated and out["原本ページ"] and abs(stated - out["原本ページ"]) > 1 and out["系統A"] == "一致":
        out["誤りの型"] = "ページ違い"
        out["理由"] = f"記載p.{stated}・原本p.{out['原本ページ']}"
    return out


def cmd_line_a(orig: Path, work: Path):
    idx = load_index(orig)
    work.mkdir(parents=True, exist_ok=True)
    rows = []
    for rel, i, r in load_rows():
        base = {"行ハッシュ": row_hash(rel, r), "ファイル": rel, "行": i, "出典URL": r["出典URL"]}
        doc = idx.get(r["出典URL"])
        if not doc:
            res = {"系統A": "原本なし", "理由": "原本をまだ取っていない"}
        elif "error" in doc:
            res = {"系統A": "原本なし", "理由": doc["error"][:80]}
        else:
            res = line_a_row(rel, r, doc)
            res["原本sha256"] = doc["sha"]
            res["原本観測時刻"] = doc.get("observed", "")
        rows.append({**base, **res})
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with (work / "lineA.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(Counter(r["系統A"] for r in rows))


ORIGINALS_KEY = "__原本__"
SNAP_ID_KEY = "__版__"
GEN_KEY = "__世代__"  # 対応を退かして作り直した回の印。行が同じでも、作り直す前の答えと版を分ける


def write_snapshot(work: Path) -> None:
    """ブラウザへ渡す時点の ファイル・行 → 行ハッシュ の対応を残す。

    ブラウザ経由の答えは ファイル・行 しか持たないので、取り込みはこの対応で行ハッシュに直す。
    渡した後に CSV の行が変わっても、古い答えが別の行に付かない（ハッシュが変わり、どの行にも結びつかない）。
    """
    snap = {f"{rel}|{i}": row_hash(rel, r) for rel, i, r in load_rows()}
    # 読み手に渡す抜粋の元になった原本の版（URL→sha256）。原本が取り直されて版が変わったら、古い答えは使わない
    la = work / "lineA.csv"
    if la.exists():
        snap[ORIGINALS_KEY] = {r["出典URL"]: r["原本sha256"] for r in csv.DictReader(la.open(encoding="utf-8"))
                               if r.get("原本sha256")}
    # この対応の版。ブラウザ経由の答え（行ハッシュ無し）はこの版を持っていなければ使わない
    snap[SNAP_ID_KEY] = snapshot_id(snap)
    work.mkdir(parents=True, exist_ok=True)
    p = work / "snapshot.json"
    if p.exists():
        old = json.loads(p.read_text(encoding="utf-8"))
        if GEN_KEY in old:
            snap[GEN_KEY] = old[GEN_KEY]
            snap[SNAP_ID_KEY] = snapshot_id(snap)
        if old == snap:
            print("行も原本の版も変わっていない。対応はそのまま")
            return
        old_pins, new_pins = old.get(ORIGINALS_KEY, {}), snap.get(ORIGINALS_KEY, {})
        meta = (ORIGINALS_KEY, SNAP_ID_KEY, GEN_KEY)
        rows_same = {k: v for k, v in old.items() if k not in meta} == {k: v for k, v in snap.items() if k not in meta}
        if rows_same and all(new_pins.get(u) == v for u, v in old_pins.items()):
            # 行も既にある原本の版も同じで、新しく取れた原本の版が増えただけ。今の答えはそのまま使える
            p.write_text(json.dumps(snap, ensure_ascii=False, indent=0), encoding="utf-8")
            print(f"新しい原本の版を {len(new_pins) - len(old_pins)} 件足した。対応と答えはそのまま")
            return
        # 行か原本の版が変わった。古い対応で書かれた答えは、新しい対応で読むと別の行・別の版に付きうるので、対応ごと退かす
        # 退かし先は毎回新しく作る（同じ中身の対応に戻っても、前の退かし先と混ざらない）
        sid = hashlib.sha1(p.read_bytes()).hexdigest()[:12]
        dest = work / f"old-snapshot-{sid}-{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{time.time_ns() % 10**6:06d}"
        dest.mkdir()
        for sub in ("b-results", "c-results", "b-batches"):  # 渡した束も答えと一緒に退かす
            if (work / sub).exists():
                (work / sub).rename(dest / sub)
        p.rename(dest / "snapshot.json")
        print(f"行か原本の版が変わったので、古い対応と答えを {dest} に退かした")
        # 行が同じでも版を変える。退かす前に読み始めた読み手の答えが遅れて届いても、新しい対応には付かない
        snap[GEN_KEY] = sid
        snap[SNAP_ID_KEY] = snapshot_id(snap)
    p.write_text(json.dumps(snap, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{len(snap)} 行の対応を残した → {p}")


def snapshot_id(snap: dict) -> str:
    """行の対応の版。原本の版（ピン）は URL ごとに merge で確かめるので含めない（新しい URL のピンを足しても版は変わらない）。

    既にある原本の版が変わったときは対応ごと退かし、世代（GEN_KEY）を変えるので、版も変わる。
    """
    body = {k: v for k, v in snap.items() if k not in (SNAP_ID_KEY, ORIGINALS_KEY)}
    return hashlib.sha1(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


_REF_OK: dict = {}  # ref → その ref の CSV から作った ファイル・行 → 行ハッシュ


def ref_matches(snap: dict, ref: str) -> bool:
    """ブラウザが読んだ CSV の版（コミット ref）から作った ファイル・行 → 行ハッシュ が、snapshot の対応と同じか。

    違う ref の CSV から作った束や系統Aの結果は、同じ ファイル・行 でも別の行を見ている。"""
    if not re.fullmatch(r"[0-9a-f]{7,40}", ref or ""):
        return False
    if ref not in _REF_OK:
        rel_root = DATA.relative_to(ROOT).as_posix()
        names = subprocess.run(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", ref, rel_root],
                               capture_output=True, text=True)
        got = {}
        for name in sorted(names.stdout.split()):
            parts = name[len(rel_root) + 1:].split("/")
            if len(parts) != 2 or parts[0] == "verify" or not name.endswith(".csv"):
                continue
            body = subprocess.run(["git", "-C", str(ROOT), "show", f"{ref}:{name}"], capture_output=True, text=True).stdout
            for i, r in enumerate(csv.DictReader(io.StringIO(body)), start=1):
                got[f"{parts[0]}/{parts[1]}|{i}"] = row_hash(f"{parts[0]}/{parts[1]}", r)
        _REF_OK[ref] = got if names.returncode == 0 else None
    want = {k: v for k, v in snap.items() if not k.startswith("__")}
    return _REF_OK[ref] is not None and _REF_OK[ref] == want


# ref 照合を入れる前（2026-10-18）に書かれた答えの一覧。ここに sha256 ごと載っている答えだけ、「@」の無い版を受け付ける。
# 新しい答えはキットが「snapshot の版@CSV の ref」を付けるので、この一覧には足さない。
LEGACY_ANSWERS = DATA / "verify" / "legacy_answers.csv"


def load_legacy_answers(path: Path = LEGACY_ANSWERS) -> set:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8", newline="") as f:
        return {(r["置き場"], r["ファイル"], r["sha256"], r["版"]) for r in csv.DictReader(f)}


def answer_version_ok(snap: dict, ver: str, legacy: bool = False) -> bool:
    """読み手の答えの「版」。新しいキットは「snapshot の版@CSV の ref」を見せるので、ref まで照合する。
    「@」の無い版は、一覧（LEGACY_ANSWERS）に載った照合前の答え（legacy=True）のときだけ受け付ける。"""
    v, _, ref = (ver or "").partition("@")
    if v != snap.get(SNAP_ID_KEY):
        return False
    return ref_matches(snap, ref) if ref else legacy


def load_snapshot(work: Path) -> dict:
    p = work / "snapshot.json"
    if not p.exists():
        raise SystemExit(f"{p} が無い。ブラウザへ渡す前に snapshot を作る")
    return json.loads(p.read_text(encoding="utf-8"))


def cmd_import_a(work: Path, tsvs: list[Path], observed: str):
    """ブラウザ（Mac の Chrome で同じ規則を JavaScript で回したもの）の系統A の結果を取り込む。

    官公庁がクラウドから届かないときの経路。「|」区切りで、
    結果の行 = ファイル|行|系統A|誤りの型|理由|原本ページ|被覆率|位置、
    原本の行 = URL|原本sha256|取得時刻（http で始まる行。取得時刻はブラウザが原本を取った時刻で、無ければ --observed）。
    版の行 = 版|snapshot の版|CSV の ref（キットの RUN に渡したもの）。今の snapshot と違えば何も取り込まない。
    """
    snap = load_snapshot(work)
    texts = [t.read_text(encoding="utf-8") for t in tsvs]
    for t, body in zip(tsvs, texts):
        head = next((ln.split("|") for ln in body.splitlines() if ln.startswith("版|")), None)
        if not head or len(head) != 3 or head[1] != snap.get(SNAP_ID_KEY) or not ref_matches(snap, head[2]):
            raise SystemExit(f"{t}：版の行が無いか、今の snapshot（{snap.get(SNAP_ID_KEY)}）と CSV の版が合わない。取り込まない")
    rows_by_hash = {row_hash(rel, r): r for rel, i, r in load_rows()}
    path = work / "lineA.csv"
    rows = {}
    if path.exists():
        rows = {r["行ハッシュ"]: r for r in csv.DictReader(path.open(encoding="utf-8"))}
    lines = [ln for body in texts for ln in body.splitlines() if ln.strip() and not ln.startswith("版|")]
    docs = {p[0]: p[1:] for p in (ln.split("|") for ln in lines if ln.startswith("http") and "|" in ln)}
    sha = {u: v[0] for u, v in docs.items()}
    seen = {u: v[1] for u, v in docs.items() if len(v) > 1 and v[1]}
    n = 0
    for line in lines:
        f = line.split("|")
        if line.startswith("http") or len(f) != 8 or not f[1].isdigit():
            continue
        if f[2] not in ("一致", "不一致", "原本なし"):
            continue
        h = snap.get(f"{f[0]}|{int(f[1])}")
        r = rows_by_hash.get(h)
        if r is None:  # 渡した後に行が変わった・消えた
            continue
        rows[h] = {"行ハッシュ": h, "ファイル": f[0], "行": f[1], "出典URL": r["出典URL"], "系統A": f[2], "誤りの型": f[3],
                   "理由": f[4], "原本ページ": f[5], "被覆率": f[6], "pos": f[7], "原本sha256": sha.get(r["出典URL"], ""),
                   "原本観測時刻": seen.get(r["出典URL"], observed)}
        n += 1
    work.mkdir(parents=True, exist_ok=True)
    fields = ["行ハッシュ", "ファイル", "行", "出典URL", "系統A", "誤りの型", "理由", "原本ページ", "被覆率", "pos", "原本sha256",
              "原本観測時刻"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows.values())
    print(f"{n} 行を取り込んだ（合計 {len(rows)} 行）", Counter(r["系統A"] for r in rows.values()))


def cmd_prepare_b(orig: Path, work: Path, batch: int):
    """読み手に渡す束。系統Aの判定は入れない（読み手が独立に判定する）。"""
    idx = load_index(orig)
    a = {r["行ハッシュ"]: r for r in csv.DictReader((work / "lineA.csv").open(encoding="utf-8"))}
    items = []
    for rel, i, r in load_rows():
        h = row_hash(rel, r)
        doc = idx.get(r["出典URL"])
        if not doc or "error" in doc:
            continue
        if doc.get("sha") != a.get(h, {}).get("原本sha256"):
            # 系統Aが見た原本の版と、いま手元にある原本の版が違う。系統Aを取り直すまで読み手に渡さない
            continue
        pos = int(a[h]["pos"]) if a.get(h, {}).get("pos") not in (None, "", "-1") else -1
        text = doc["text"]
        # 系統Aの位置が見つからない行は、読み手に原本の冒頭からの長い抜粋を渡す
        excerpt = text[max(0, pos - 800):pos + 3200] if pos >= 0 else text[:4000]
        fields = {k: v for k, v in r.items() if k not in ("確度", "出典URL")}
        items.append({"行ハッシュ": h, "ファイル": rel, "行": i, "データ": fields, "原本の抜粋": excerpt,
                      "原本sha256": doc["sha"]})
    d = work / "b-batches"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("batch_*.json"):
        old.unlink()
    for n in range(0, len(items), batch):
        p = d / f"batch_{n // batch:03d}.json"
        p.write_text(json.dumps(items[n:n + batch], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(items)} 行を {(len(items) + batch - 1) // batch} 束に分けた → {d}")


def load_b(work: Path, sub: str = "b-results", legacy: set | None = None) -> dict:
    """読み手の答え。行ハッシュが無い答え（ブラウザ経由の束）は、渡した時点の対応（snapshot.json）で行ハッシュを引く。"""
    snap = load_snapshot(work) if (work / "snapshot.json").exists() else {}
    legacy = load_legacy_answers() if legacy is None else legacy
    out, lost = {}, []
    for p in sorted((work / sub).glob("*.json")):
        raw = p.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        for r in json.loads(raw.decode("utf-8")):
            try:
                key = f"{r.get('ファイル')}|{int(r.get('行', 0))}"
            except (TypeError, ValueError):
                key = None
            h = r.get("行ハッシュ")
            if not h and answer_version_ok(snap, r.get("版", ""), (sub, p.name, sha, r.get("版", "")) in legacy):
                # ブラウザ経由の答えは、読んだ束の版（snapshot の版）が今の snapshot と同じときだけ行に結び付ける
                h = snap.get(key)
            if h:
                out[h] = r
            else:
                lost.append(f"{p.name}:{r.get('ファイル')}:{r.get('行')}")
    if lost:
        print(f"行に結びつかない読み手の答え {len(lost)} 件：", lost[:5], file=sys.stderr)
    return out


# 読み手の理由に氏名が混じっても公開側へ出さない（肩書の前の漢字1〜4字を伏せる）
NAME_RE = re.compile(r"[一-龥々ヶ]{1,4}[ 　]?[一-龥々ヶ]{0,3}[ 　]?(?=(氏|委員(?!会)|室長|参考人|課長|局長|大臣|審議官|座長|部長|会長|理事|教授|さん))")


def mask_names(s: str) -> str:
    return NAME_RE.sub("（氏名略）", s or "")


def decide(a: dict, b: dict, c: dict | None = None) -> tuple[str, str, str]:
    """(照合, 誤りの型, 理由)。機械の照合（系統A）と、別々の AI セッション2つ（系統B・系統C）が
    どれも一致したものだけ確認済み（AGENTS.md・設計決定0007の「2系統の AI の一致」）。"""
    sa, sb, sc = a.get("系統A", ""), (b or {}).get("判定", ""), (c or {}).get("判定", "")
    if sa == "原本なし":
        return "未照合", "", a.get("理由", "")
    if sa == "一致" and sb == "一致":
        if sc == "一致":
            if a.get("誤りの型"):
                # 中身は3つとも一致でも、系統Aが見つけた食い違い（ページ違いなど）が残る行は確認済みにしない
                return "保留", a["誤りの型"], f"中身は3系統とも一致・系統Aの指摘（{mask_names(a.get('理由', ''))}）"[:200]
            return "確認済み", "", a.get("理由", "")
        if not c:
            return "保留", "2人目のAIの読み待ち", "系統A・系統Bは一致、系統Cがまだ"
        why = f"系統A・系統Bは一致・系統C={sc}" + (f"（{mask_names(c['理由'])}）" if c.get("理由") else "")
        return "保留", mask_names(c.get("誤りの型") or "AI2系統の不一致"), why[:200]
    if not b:
        return "保留", "読み手の判定なし", "系統Bがまだ"
    kind = (b.get("誤りの型") or a.get("誤りの型") or "2系統の不一致") if sb != "一致" else (a.get("誤りの型") or "2系統の不一致")
    kind = mask_names(kind)
    why = f"系統A={sa}" + (f"（{mask_names(a['理由'])}）" if a.get("理由") else "") + f"・系統B={sb or 'なし'}"
    if sb != "一致" and b.get("理由"):
        why += f"（{mask_names(b['理由'])}）"
    return "保留", kind, why[:200]


def status_label(st: dict) -> str:
    if st["照合"] == "確認済み":
        return CONFIRMED
    if st["照合"] == "保留":
        return f"保留：{st['誤りの型']}"
    return PROVISIONAL


def apply_status(dest: Path, rel: str, header: list[str], rows: list[dict], status: dict) -> None:
    """確度の列を照合結果で書き換える（build_blocking_actors からも呼ぶ）。照合結果が無ければ何もしない。"""
    if not status:
        return
    for r in rows:
        st = status.get(row_hash(rel, r))
        if "確度" not in r:
            continue
        if st and st["照合"] in ("確認済み", "保留"):
            r["確度"] = status_label(st)
        elif r["確度"].startswith(("原本照合済み", "保留：")):
            # 照合が外れた行は暫定に戻す。未照合の行は元の注記（発言者特定不可など）を残す
            r["確度"] = PROVISIONAL


def load_status(path: Path = STATUS) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {r["行ハッシュ"]: r for r in csv.DictReader(f)}


def merge_row(ra: dict, rb: dict | None, rc: dict | None, pin: str | None, dup: int = 1):
    """1行ぶんの判定。返り値は (使った系統B, 使った系統C, (照合, 誤りの型, 理由))。"""
    if (rb or rc) and pin != ra.get("原本sha256", ""):
        # 読み手が読んだ抜粋の版が固定されていないか、系統Aが見た原本の版と違う。読み手の答えは使わない
        rb = rc = None
    # 束に入れた版を持っている答えは、その版が系統Aの版と同じときだけ使う。
    # prepare-b の束から返った答え（行ハッシュ付き）は版も必ず持つので、版の無い答えは使わない。
    # ブラウザ経由の答え（行ハッシュ無し）は snapshot の版の固定（上）で結び付ける
    def same_version(x):
        if "行ハッシュ" in x and not x.get("原本sha256"):
            return False
        return x.get("原本sha256", ra.get("原本sha256", "")) == ra.get("原本sha256", "")
    rb, rc = [x if x is None or same_version(x) else None for x in (rb, rc)]
    v, kind, why = decide(ra, rb, rc)
    if dup > 1 and v == "確認済み":
        # 中身がまったく同じ行が複数ある。読み手の答えを1行ずつ区別できないので確認済みにしない
        v, kind, why = "保留", "重複行", f"同じ中身の行が{dup}行ある。どの行の答えか区別できない"
    return rb, rc, (v, kind, why)


def cmd_merge(work: Path):
    a = {r["行ハッシュ"]: r for r in csv.DictReader((work / "lineA.csv").open(encoding="utf-8"))}
    b = load_b(work)
    c = load_b(work, "c-results") if (work / "c-results").exists() else {}
    snap = load_snapshot(work) if (work / "snapshot.json").exists() else {}
    pinned = snap.get(ORIGINALS_KEY, {})
    out = []
    rows = list(load_rows())
    dup = Counter(row_hash(rel, r) for rel, i, r in rows)
    for rel, i, r in rows:
        h = row_hash(rel, r)
        ra = a.get(h, {"系統A": "原本なし", "理由": "系統Aがまだ"})
        rb, rc = b.get(h), c.get(h)
        rb, rc, (v, kind, why) = merge_row(ra, rb, rc, pinned.get(r["出典URL"]), dup[h])
        out.append({"行ハッシュ": h, "ファイル": rel, "行": i, "出典URL": r["出典URL"], "照合": v,
                    "系統A": ra.get("系統A", ""), "系統B": (rb or {}).get("判定", ""),
                    "系統C": (rc or {}).get("判定", ""), "誤りの型": kind,
                    "理由": why, "原本ページ": ra.get("原本ページ", ""), "原本sha256": ra.get("原本sha256", ""),
                    "原本観測時刻": ra.get("原本観測時刻", "")})
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    with STATUS.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=STATUS_FIELDS)
        w.writeheader()
        w.writerows(out)
    status = {r["行ハッシュ"]: r for r in out}
    # 確度の列を書き換える（行の中身は変えないので行ハッシュは変わらない）
    for f in sorted(DATA.glob("*/*.csv")):
        if f.parent.name == "verify":
            continue
        rel = f"{f.parent.name}/{f.name}"
        with f.open(encoding="utf-8", newline="") as fh:
            rd = csv.DictReader(fh)
            header, rows = rd.fieldnames, list(rd)
        apply_status(f, rel, header, rows, status)
        with f.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=header)
            w.writeheader()
            w.writerows(rows)
    write_summary(out)


def write_summary(out: list[dict]):
    by_file = Counter((r["ファイル"], r["照合"]) for r in out)
    kinds = Counter(r["誤りの型"] for r in out if r["誤りの型"])
    files = sorted({r["ファイル"] for r in out})
    lines = ["# 技術を止めた側のデータ 原本照合の結果", "",
             "系統A（機械の照合）と、別々の AI セッション2つ（系統B・系統C）の読み手が、どれも一致した行だけ「確認済み」"
             "（AGENTS.md・設計決定0007の「2系統の AI の一致」）。系統A・Bが一致して系統Cがまだの行は「保留：2人目のAIの読み待ち」。"
             "どちらかが一致でなければ「保留」で、理由は status.csv の「理由」列。原本が取れていない行は「未照合」。", "",
             "再就職（4_amakudari/reemployment.csv）の「所管関係」はこちらの分類で、原本には書かれていない。照合で確かめたのは"
             "公表年度・府省・離職時の官職・再就職先・再就職先の業種で、「所管関係」は確認済みの行でも原本照合の対象外。", "",
             "| ファイル | 確認済み | 保留 | 未照合 |", "|---|---|---|---|"]
    for fn in files:
        lines.append(f"| `{fn}` | {by_file[(fn, '確認済み')]} | {by_file[(fn, '保留')]} | {by_file[(fn, '未照合')]} |")
    tot = Counter(r["照合"] for r in out)
    lines += [f"| 合計 | {tot['確認済み']} | {tot['保留']} | {tot['未照合']} |", "", "## 誤りの型", "",
              "| 型 | 件数 |", "|---|---|"]
    lines += [f"| {k} | {n} |" for k, n in kinds.most_common()]
    lines += ["", "## 次の回に反映したこと", "",
              "- 府省が抜粋に無い（行政事業レビュー）：府省は事業の前の見出し（「1311.厚生労働省事業名得票数」など）にある。"
              "抜粋に「見出し」を添え、系統A も見出しで府省を確かめる（scripts/browser/blocking_verify_kit.js の addHeading）。",
              "- 回・開催日・所属が抜粋に無い（審議会）：文書の冒頭にある。発言が冒頭から離れた行には冒頭を「名簿」として添える（addHead）。",
              "- 府省が抜粋に無い（再就職）：公表資料の府省の区切りが抜粋の外にある行が残る。次の回で府省の区切りを添える。",
              "- ページ違い：データの「ページ」が PDF のページと合わない。中身は一致しているので、データの側のページを直す候補。"]
    (STATUS.parent / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(tot, kinds.most_common())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["line-a", "snapshot", "import-a", "prepare-b", "merge"])
    ap.add_argument("tsv", nargs="*", type=Path)
    ap.add_argument("--orig", type=Path, default=ORIG)
    ap.add_argument("--work", type=Path, default=WORK)
    ap.add_argument("--batch", type=int, default=25)
    ap.add_argument("--observed", default=None,
                    help="import-a：ブラウザで原本を取った日（UTC）。取り込む日ではないので必ず指定する")
    a = ap.parse_args()
    if a.cmd == "line-a":
        cmd_line_a(a.orig, a.work)
    elif a.cmd == "snapshot":
        write_snapshot(a.work)
    elif a.cmd == "import-a":
        if not a.observed:
            ap.error("import-a には --observed（ブラウザで原本を取った日）が要る")
        cmd_import_a(a.work, a.tsv, a.observed)
    elif a.cmd == "prepare-b":
        cmd_prepare_b(a.orig, a.work, a.batch)
    else:
        cmd_merge(a.work)


if __name__ == "__main__":
    main()
