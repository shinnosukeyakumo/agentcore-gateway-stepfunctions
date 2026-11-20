"""Q4 方向B: Step Functions が親。LLM（Harness）は分類だけを返し、返金ワークフローを起動するかは Choice が決める。

判定はコードで行う: TriageWorkflow の出力の routed が REFUND_WORKFLOW か。

    uv run python q4_direction_b.py [回数=3] [S1,S2,...]
"""
import json
import sys
import time

from common import OUT, ROOT, SESSION, mask
from scenarios import SCENARIOS

sfn = SESSION.client("stepfunctions")


def run(sid: str, message: str, expect: bool, i: int) -> dict:
    arn = sfn.start_execution(
        stateMachineArn=OUT["TriageStateMachineArn"],
        name=f"{sid}-{i}-{int(time.time() * 1000)}",
        input=json.dumps({"message": message}, ensure_ascii=False),
    )["executionArn"]
    while True:
        d = sfn.describe_execution(executionArn=arn)
        if d["status"] != "RUNNING":
            break
        time.sleep(2)
    base = {"id": sid, "run": i, "expect_refund": expect, "status": d["status"]}
    if d["status"] != "SUCCEEDED":
        return {**base, "started_refund": False, "correct": not expect, "error": d.get("error"), "cause": (d.get("cause") or "")[:400]}
    out = json.loads(d["output"])
    started = out["routed"] == "REFUND_WORKFLOW"
    intent = {k: v for k, v in out["intent"].items() if k != "usage"}
    return {
        **base, "started_refund": started, "correct": started == expect, "intent": intent,
        "refund_outcome": (out.get("refund") or {}).get("result"),
        "duration_s": round((d["stopDate"] - d["startDate"]).total_seconds(), 1),
    }


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    only = sys.argv[2].split(",") if len(sys.argv) > 2 else None
    rows = []
    for sid, message, expect in SCENARIOS:
        if only and sid not in only:
            continue
        for i in range(runs):
            row = run(sid, message, expect, i)
            rows.append(row)
            print(sid, i, row["status"], "START" if row["started_refund"] else "-", row.get("intent"), row.get("refund_outcome"), row.get("error", ""), flush=True)
    suffix = "" if not only else "_" + "_".join(only)
    (ROOT / "results" / f"q4_direction_b{suffix}.json").write_text(mask(json.dumps(rows, ensure_ascii=False, indent=2)))
