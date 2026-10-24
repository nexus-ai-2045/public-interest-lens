"""事前チェック：本番の作業（毎朝の自動更新・マージ）の前に、止まる原因を先に測る（設計決定0010）。

1本の入口で次を順に回し、「止まる（失敗）」と「注意」を分けて出す。失敗が1つでもあれば終了コード1。
- ドライラン：毎朝の作り直し（scripts/rebuild_public.py）が呼ぶスクリプトがそろい、構文が通るか（実際の計算はしない）。
- ヘルプ：主要な入口のスクリプトが --help で起動できるか。
- 通信先：一次資料のサイトと公開サイトに届くか（届かない取得元は注意。毎朝はその取得を飛ばす）。
- 権限：GitHub のリポジトリを読めるか（push 前提の作業の前に）。
- Vercel の枠：main の最新コミットの Vercel の状態が「上限」になっていないか（注意だけ。マージは止めない）。
- 個人名義：repo-preflight の個人名義検査（push 前の必須検査と同じもの）。
  環境変数 REPO_PREFLIGHT_ROOT があるときは、その直下の scripts/local_identity_guard.py だけを使う。
  未設定のときは、これまでどおりこのリポジトリの隣の repo-preflight を使う。
  明示した場所に検査が無いときは、別の場所へ替えずに失敗にする。指定した値は出さない。
- ロードマップ：scripts/roadmap_check.py。
- スモーク（--smoke のときだけ）：公開版をビルドし、localhost で主要6画面を開く（app の npm run preview:check）。
- E2E（--smoke のときだけ）：公開版の主要4ページの表示と操作をクラウド内蔵の Chromium で確かめる（app の npm run test:e2e:public、設計決定0011）。

使い方：python3 scripts/preflight.py [--smoke] [--offline] [--json 出力先]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import daily_update  # noqa: E402

REPO = "nexus-ai-2045/public-interest-lens"
PUBLIC_SITE = "kokuzoku.nexusai2045.com"
# --help で起動できることを確かめる入口（python -m で呼ぶ）。--help を解釈しない入口（rebuild_public・build_laws_catalog・
# build_all_laws_outcomes など）は本番の処理が走って生成物を書き換えるので入れない（ドライランの構文検査で見る）。
HELP_MODULES = ["scripts.daily_update", "scripts.build_price_index", "scripts.build_public_ranking", "scripts.eval_loop", "scripts.preflight", "scripts.person_ids",
                "scripts.fetch_enforcement_old_egov", "scripts.fetch_r3_series", "scripts.build_old_laws_triage",
                "scripts.build_old_laws_outcomes", "scripts.political_funds", "scripts.fetch_fiscal",
                "scripts.fetch_fiscal_more", "scripts.fetch_target_series"]
IDENTITY_GUARD = ROOT.parent / "repo-preflight" / "scripts" / "local_identity_guard.py"
OUT = ROOT / ".local" / "preflight"


@dataclass
class Item:
    check: str
    status: str  # 合格・注意・失敗
    detail: str = ""


def _run(args: list[str], cwd: Path = ROOT, timeout: int = 120) -> subprocess.CompletedProcess:
    """時間切れや起動失敗（node・git・npm が無いなど）は例外にせず、失敗として返す。事前チェック自体が止まらないように。"""
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", f"{timeout}秒で終わらなかった")
    except OSError as error:
        return subprocess.CompletedProcess(args, 127, "", f"起動できない：{error}")


REBUILD = ROOT / "scripts" / "rebuild_public.py"


def pipeline_scripts() -> list[Path]:
    """毎朝の作り直し（scripts/rebuild_public.py）が呼ぶスクリプト。本文の "scripts/…py|mjs" を拾う。

    判定ルール（RULES）は app/ の下、そのほかはリポジトリの直下にある。作り直しに段を足せば、ここにも自動で入る。
    """
    text = REBUILD.read_text(encoding="utf-8")
    # rebuild_public を import すると、構文エラーのとき事前チェック自体が落ちる。本文から RULES の中の名前だけ拾う。
    rules = re.search(r"^RULES = \[(.*?)^\]", text, re.S | re.M)
    app_scripts = set(re.findall(r"scripts/[\w./-]+\.(?:py|mjs)", rules.group(1))) if rules else set()
    found = [REBUILD]
    for name in re.findall(r"scripts/[\w./-]+\.(?:py|mjs)", text):
        path = (ROOT / "app" / name) if name in app_scripts else (ROOT / name)
        # app/ で動かす段（計算式の清書の検査など）は、直下に無ければ app/ の下を見る。
        if not path.exists() and (ROOT / "app" / name).exists():
            path = ROOT / "app" / name
        if path not in found:
            found.append(path)
    # python -m や import で呼ぶもの（出典チェックなど）。「from scripts import a, b」は全部拾う。
    modules = re.findall(r"-m\", \"scripts\.(\w+)", text)
    for names in re.findall(r"from scripts import ([\w, ]+)", text):
        modules += [n.strip() for n in names.split(",") if n.strip()]
    for module in modules:
        path = ROOT / "scripts" / f"{module}.py"
        if path not in found:
            found.append(path)
    return found


def dry_run(scripts: list[Path] | None = None) -> list[Item]:
    items = []
    for path in scripts if scripts is not None else pipeline_scripts():
        if not path.exists():
            items.append(Item("ドライラン", "失敗", f"{path.relative_to(ROOT)} が無い"))
            continue
        check = [sys.executable, "-m", "py_compile", str(path)] if path.suffix == ".py" else ["node", "--check", str(path)]
        result = _run(check)
        items.append(Item("ドライラン", "合格" if result.returncode == 0 else "失敗",
                          f"{path.relative_to(ROOT)}" + ("" if result.returncode == 0 else f"：{(result.stderr or result.stdout).strip()[:200]}")))
    return items


def help_screens() -> list[Item]:
    items = []
    for module in HELP_MODULES:
        source = ROOT / (module.replace(".", "/") + ".py")
        # 引数を解釈しない入口に --help を渡すと本番の処理が走るので、ArgumentParser の無いものは実行しない。
        if "ArgumentParser" not in source.read_text(encoding="utf-8"):
            items.append(Item("ヘルプ", "失敗", f"{module} は --help を解釈しない（HELP_MODULES から外す）"))
            continue
        result = _run([sys.executable, "-m", module, "--help"], timeout=60)
        ok = result.returncode == 0 and "usage" in result.stdout.lower()
        items.append(Item("ヘルプ", "合格" if ok else "失敗", module + ("" if ok else f"：{(result.stderr or result.stdout).strip()[-200:]}")))
    return items


def network(offline: bool) -> list[Item]:
    if offline:
        return [Item("通信先", "注意", "--offline のため確かめていない")]
    items = [Item("通信先", "合格" if daily_update.reachable(host) else "注意", f"{name}（{host}）")
             for name, host in daily_update.HOSTS.items()]
    items.append(Item("通信先", "合格" if daily_update.reachable(PUBLIC_SITE) else "注意", f"公開サイト（{PUBLIC_SITE}）"))
    return items


def permissions(offline: bool) -> list[Item]:
    if offline:
        return [Item("権限", "注意", "--offline のため確かめていない")]
    read = _run(["git", "ls-remote", "--heads", "origin", "main"], timeout=60)
    if read.returncode != 0 or "refs/heads/main" not in read.stdout:
        return [Item("権限", "失敗", f"GitHub のリポジトリを読めない：{read.stderr.strip()[:200]}")]
    # 書き込みは --dry-run で確かめる（受け側の認証まで通すが、何も送らない）。
    write = _run(["git", "push", "--dry-run", "origin", "HEAD:refs/heads/claude/preflight-probe"], timeout=60)
    return [Item("権限", "合格" if write.returncode == 0 else "失敗",
                 "GitHub のリポジトリを読めて、push できる" if write.returncode == 0 else f"push の権限が無い：{write.stderr.strip()[-200:]}")]


def vercel_quota(offline: bool) -> list[Item]:
    if offline:
        return [Item("Vercel の枠", "注意", "--offline のため確かめていない")]
    try:
        with urllib.request.urlopen(f"https://api.github.com/repos/{REPO}/commits/main/status", timeout=15) as response:
            statuses = json.load(response).get("statuses", [])
    except Exception as error:  # 測れないことは止まる理由にしない
        return [Item("Vercel の枠", "注意", f"状態を読めなかった：{type(error).__name__}")]
    vercel = next((s for s in statuses if s.get("context") == "Vercel"), None)
    if vercel is None:
        return [Item("Vercel の枠", "注意", "main の最新コミットに Vercel の状態が無い")]
    limited = "rate limit" in (vercel.get("description") or "").lower()
    return [Item("Vercel の枠", "注意" if limited else "合格",
                 "無料枠の上限で本番に反映されない（マージは止めない。手元の画面確認で代える）" if limited else f"Vercel：{vercel.get('state')}")]


NOREPLY = "273569186+nexus-ai-2045@users.noreply.github.com"


def commit_identity() -> list[Item]:
    """このリポジトリでコミットすると付く名義（作者と記録者）が運営名義（nexus_ai と noreply）か。値そのものは出さない。

    git var は GIT_AUTHOR_*・GIT_COMMITTER_* の環境変数も含めた、次のコミットに実際に付く名義を返す（Mac は環境変数で指定する）。
    """
    expected = f"nexus_ai <{NOREPLY}>"
    wrong = []
    for role, var in (("作者", "GIT_AUTHOR_IDENT"), ("記録者", "GIT_COMMITTER_IDENT")):
        ident = _run(["git", "var", var]).stdout.strip()
        if not ident.startswith(expected + " "):
            wrong.append(role)
    if not wrong:
        return [Item("コミット名義", "合格", "作者・記録者とも nexus_ai と noreply")]
    return [Item("コミット名義", "失敗",
                 f"{'・'.join(wrong)}の名義が運営名義でない。git config（または GIT_AUTHOR_*/GIT_COMMITTER_* の環境変数）を nexus_ai と {NOREPLY} にする")]


def identity_guard() -> Path | None:
    """個人名義検査のスクリプト。無いときは None。

    REPO_PREFLIGHT_ROOT は runtime/shared/run_preflight.py と同じ明示指定（前後の空白と引用符だけ外す）。
    指定があるときはその直下だけを見て、壊れていても隣や探索へ戻さない。未設定のときだけ隣を使う。
    """
    raw = os.environ.get("REPO_PREFLIGHT_ROOT", "").strip().strip('"')
    if not raw:
        return IDENTITY_GUARD if IDENTITY_GUARD.exists() else None
    try:
        guard = Path(raw).expanduser().resolve() / "scripts" / "local_identity_guard.py"
    except (OSError, RuntimeError):
        return None
    return guard if guard.is_file() else None


def identity() -> list[Item]:
    raw = os.environ.get("REPO_PREFLIGHT_ROOT", "").strip().strip('"')
    guard = identity_guard()
    if guard is None:
        if raw:
            return [Item("個人名義", "失敗", "REPO_PREFLIGHT_ROOT の指定が無効（個人名義検査を回せない）")]
        return [Item("個人名義", "失敗", "repo-preflight が隣に無い（push 前の個人名義検査を回せない）")]
    args = [sys.executable, str(guard), "--public-name", "nexus-ai-2045", "--public-name", "nexus_ai"]
    # 既定の check は --range HEAD（現在枝の全履歴）。失敗を注意へ下げない。
    # push 専用の --pre-push はこれから送る範囲だけを見る契約で、全履歴の失敗を通す根拠にはしない。
    result = _run(args + ["check"], timeout=300)
    detail = (result.stdout or result.stderr).strip().splitlines()[-1:][0] if (result.stdout or result.stderr).strip() else ""
    items = [Item("個人名義", "合格" if result.returncode == 0 else "失敗", detail)]
    # 浅い clone では古いコミットの名義を見られない（クラウドの環境は浅い clone で始まる）。
    if _run(["git", "rev-parse", "--is-shallow-repository"]).stdout.strip() == "true":
        items.append(Item("個人名義", "注意", "浅い clone のため全履歴は見ていない（git fetch --unshallow origin で全履歴を検査できる）"))
    return items


def roadmap() -> list[Item]:
    result = _run([sys.executable, "scripts/roadmap_check.py"])
    return [Item("ロードマップ", "合格" if result.returncode == 0 else "失敗", (result.stdout + result.stderr).strip()[:300])]


def smoke() -> list[Item]:
    result = _run(["npm", "run", "preview:check"], cwd=ROOT / "app", timeout=900)
    lines = [line for line in result.stdout.splitlines() if line.startswith(("OK", "NG"))]
    failed = [line for line in lines if line.startswith("NG")]
    detail = f"{len(lines) - len(failed)}/{len(lines)} 画面 OK" if lines else (result.stderr.strip()[-200:] or "画面を開けなかった")
    return [Item("スモーク", "合格" if result.returncode == 0 else "失敗", detail + ("：" + " / ".join(failed[:3]) if failed else ""))]


def e2e() -> list[Item]:
    """公開版の主要4ページの E2E。スモークがビルドした dist を使い、ビルドし直さない（E2E_NO_BUILD）。"""
    env = {**os.environ, "E2E_NO_BUILD": "1"}
    try:
        result = subprocess.run(["npm", "run", "test:e2e:public"], cwd=ROOT / "app", capture_output=True, text=True, timeout=1200, env=env)
    except subprocess.TimeoutExpired:
        return [Item("E2E", "失敗", "1200秒で終わらなかった")]
    except OSError as error:
        return [Item("E2E", "失敗", f"起動できない：{error}")]
    counts = re.findall(r"(\d+) (passed|failed|flaky|skipped)", result.stdout)
    detail = "、".join(f"{word} {n}" for n, word in counts) or (result.stderr or result.stdout).strip()[-200:] or "結果が読めない"
    return [Item("E2E", "合格" if result.returncode == 0 else "失敗", detail)]


def run_all(smoke_test: bool = False, offline: bool = False) -> list[Item]:
    items = (dry_run() + help_screens() + network(offline) + permissions(offline) + vercel_quota(offline)
             + commit_identity() + identity() + roadmap())
    if smoke_test:
        items += smoke()
        items += e2e()
    return items


def summary(items: list[Item]) -> str:
    counts = {s: sum(1 for i in items if i.status == s) for s in ("合格", "注意", "失敗")}
    return f"事前チェック：合格 {counts['合格']}、注意 {counts['注意']}、失敗 {counts['失敗']}"


def save(items: list[Item], out: Path | None = None) -> Path:
    """全項目（合格も含む）を JSON に残す（設計決定0010 の4）。"""
    out = out or OUT / f"{date.today()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([asdict(i) for i in items], ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--smoke", action="store_true", help="公開版をビルドして localhost で主要画面を開き、主要4ページの E2E を回す（時間がかかる）")
    parser.add_argument("--offline", action="store_true", help="通信先・権限・Vercel の枠を確かめない")
    parser.add_argument("--json", type=Path, default=None, help="結果の JSON の出力先（既定は .local/preflight/<日付>.json）")
    args = parser.parse_args()
    items = run_all(args.smoke, args.offline)
    for item in items:
        if item.status != "合格":
            print(f"{item.status}  {item.check}：{item.detail}")
    print(summary(items))
    save(items, args.json)
    return 1 if any(i.status == "失敗" for i in items) else 0


if __name__ == "__main__":
    sys.exit(main())
