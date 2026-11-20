"""results/*.json を集計して results/summary.md を書く。

  uv run python summarize.py              # Memory 無効（既定）の結果
  uv run python summarize.py memory-on    # Memory 有効で測った結果
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from scenarios import SCENARIOS

ROOT = Path(__file__).resolve().parent.parent / "results"
SUFFIX = f".{sys.argv[1]}" if len(sys.argv) > 1 else ""
a = json.loads((ROOT / f"q3_direction_a{SUFFIX}.json").read_text())
b = json.loads((ROOT / f"q4_direction_b{SUFFIX}.json").read_text())


def by_id(rows):
    d = defaultdict(list)
    for r in rows:
        d[r["id"]].append(r)
    return d


A, B = by_id(a), by_id(b)
lines = [
    f"# 測定結果の集計（{SUFFIX.lstrip('.') or 'Memory 無効'}）",
    "",
    "各シナリオ 3 回。「起動」は返金ワークフロー（gwsfn-refund）が起動した回数。",
    "",
    "| # | 発話 | 期待 | 方向A 起動 | 方向A 正解 | 方向A 返金結果 | 方向B 起動 | 方向B 正解 | 方向B 返金結果 |",
    "|---|---|---|---|---|---|---|---|---|",
]
totA = totB = 0
for sid, msg, expect in SCENARIOS:
    ra, rb = A[sid], B[sid]
    ca = sum(r["correct"] for r in ra)
    cb = sum(r["correct"] for r in rb)
    totA += ca
    totB += cb
    oa = Counter(o for r in ra for o in r["refund_outcomes"])
    ob = Counter(r["refund_outcome"] for r in rb if r["refund_outcome"])
    fmt = lambda c: ", ".join(f"{k}×{v}" for k, v in c.items()) or "-"
    msg = msg.replace("\n", " ")
    short = msg if len(msg) <= 28 else msg[:28] + "…"
    lines.append(
        f"| {sid} | {short} | {'呼ぶ' if expect else '呼ばない'} "
        f"| {sum(r['started_refund'] for r in ra)}/3 | {ca}/3 | {fmt(oa)} "
        f"| {sum(r['started_refund'] for r in rb)}/3 | {cb}/3 | {fmt(ob)} |"
    )
lines += ["", f"- 正解数: 方向A {totA}/36、方向B {totB}/36", ""]

lines += ["## 方向A のツール呼び出し列", ""]
for sid, _, _ in SCENARIOS:
    for r in A[sid]:
        errs = f" / errors: {r['errors']}" if r["errors"] else ""
        lines.append(f"- {sid}#{r['run']}: {' → '.join(r['tools']) or '(なし)'}{errs}")
lines.append("")

lat = [r["duration_s"] for r in b if r.get("duration_s")]
if lat:
    lat.sort()
    lines += ["## 方向B の所要時間（秒）", "", f"- 中央値 {lat[len(lat)//2]:.1f} / 最大 {lat[-1]:.1f}", ""]

(ROOT / f"summary{SUFFIX}.md").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
