"""Q6 ワークフローが長く掛かるときの待ち方。

`cdk deploy -c refundDelaySec=60` で gwsfn-refund の判定前に Wait を入れた状態で、S1（ORD-1001 返金）を流す。

- 方向A: StartExecution の後に照会系ツール（DescribeExecution など）を何回呼んだか、照会で見えた status、
  Harness が返った時点の子実行の status、最終回答が「受付済み」か「完了」か、所要時間
- 方向B: gwsfn-triage の所要時間と、ステートごとの所要時間（Classify = invokeHarness、StartRefund = 子実行の待ち）

判定はコードで行う。返答の分類はキーワードで、本文も JSON に残す。

    uv run python q6_wait.py <ラベル: delay60 / delay0 など> [回数=3]
"""
import json
import re
import sys
import time
import uuid

from common import OUT, ROOT, mask
from q3_direction_a import EXEC_ARN, ac, parse_stream, sfn
from scenarios import SCENARIOS

MESSAGE = dict((sid, msg) for sid, msg, _ in SCENARIOS)["S1"]
POLL_TOOLS = ("DescribeExecution", "ListExecutions", "GetExecutionHistory")
DONE_WORDS = re.compile(r"返金(が|は)?(完了|済み|いたしました|しました|されました)|REFUNDED|返金処理が完了")
ACCEPTED_WORDS = re.compile(r"開始|受け付け|受付|処理中|手続き中|進行中|RUNNING|お待ち")


def classify_reply(reply: str) -> str:
    done, accepted = bool(DONE_WORDS.search(reply)), bool(ACCEPTED_WORDS.search(reply))
    if done and not accepted:
        return "COMPLETED"
    if accepted and not done:
        return "ACCEPTED"
    return "MIXED" if done else "OTHER"


def run_a(i: int) -> dict:
    t0 = time.time()
    try:
        resp = ac.invoke_harness(
            harnessArn=OUT["SupportHarnessArn"], runtimeSessionId=f"q6-a-{i}-{uuid.uuid4()}",
            messages=[{"role": "user", "content": [{"text": MESSAGE}]}],
        )
        blocks, reply, usage, errors = parse_stream(resp)
    except Exception as e:  # noqa: BLE001
        return {"direction": "A", "run": i, "error": repr(e), "seconds": round(time.time() - t0, 1)}
    seconds = round(time.time() - t0, 1)
    uses = [b for b in blocks if b["kind"] == "use"]
    results = {b["id"]: b["buf"] for b in blocks if b["kind"] == "result"}
    names = [u["name"].split("___")[-1] for u in uses]
    start_idx = names.index("StartExecution") if "StartExecution" in names else None
    after = uses[start_idx + 1:] if start_idx is not None else []
    polls = [u for u in after if u["name"].split("___")[-1] in POLL_TOOLS]
    seen = [m.group(1) for u in polls for m in re.finditer(r'"status"\s*:\s*"([A-Z_]+)"', results.get(u["id"], ""))]
    exec_status_at_return, final_result = None, None
    if start_idx is not None:
        m = EXEC_ARN.search(results.get(uses[start_idx]["id"], ""))
        if m:
            exec_status_at_return = sfn.describe_execution(executionArn=m.group(0))["status"]
            while (d := sfn.describe_execution(executionArn=m.group(0)))["status"] == "RUNNING":
                time.sleep(3)
            final_result = json.loads(d.get("output") or "{}").get("result", d["status"])
    return {
        "direction": "A", "run": i, "seconds": seconds, "tools": names,
        "start_count": names.count("StartExecution"), "poll_count": len(polls),
        "poll_tools": [u["name"].split("___")[-1] for u in polls], "statuses_seen_by_agent": seen,
        "exec_status_when_agent_returned": exec_status_at_return, "refund_final_result": final_result,
        "reply_kind": classify_reply(reply), "reply": reply, "usage": usage, "errors": errors,
    }


def state_durations(arn: str) -> dict:
    events = []
    for page in sfn.get_paginator("get_execution_history").paginate(executionArn=arn):
        events += page["events"]
    out, entered = {}, {}
    for e in events:
        if e["type"].endswith("StateEntered"):
            entered[e["stateEnteredEventDetails"]["name"]] = e["timestamp"]
        elif e["type"].endswith("StateExited"):
            n = e["stateExitedEventDetails"]["name"]
            out[n] = round((e["timestamp"] - entered[n]).total_seconds(), 1)
    out["_timeouts"] = [e["type"] for e in events if "TimedOut" in e["type"]]
    return out


def run_b(i: int) -> dict:
    arn = sfn.start_execution(
        stateMachineArn=OUT["TriageStateMachineArn"], name=f"q6-b-{i}-{int(time.time() * 1000)}",
        input=json.dumps({"message": MESSAGE}, ensure_ascii=False),
    )["executionArn"]
    while (d := sfn.describe_execution(executionArn=arn))["status"] == "RUNNING":
        time.sleep(2)
    out = json.loads(d.get("output") or "{}")
    return {
        "direction": "B", "run": i, "status": d["status"],
        "seconds": round((d["stopDate"] - d["startDate"]).total_seconds(), 1),
        "states": state_durations(arn), "routed": out.get("routed"),
        "refund_final_result": (out.get("refund") or {}).get("result"),
        "error": d.get("error"), "cause": (d.get("cause") or "")[:400],
    }


if __name__ == "__main__":
    label = sys.argv[1]
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    rows = []
    for i in range(runs):
        row = run_a(i)
        rows.append({"label": label, **row})
        print(label, "A", i, row.get("seconds"), row.get("tools"), row.get("reply_kind"), row.get("exec_status_when_agent_returned"), flush=True)
    for i in range(runs):
        row = run_b(i)
        rows.append({"label": label, **row})
        print(label, "B", i, row["status"], row["seconds"], row["states"], flush=True)
    path = ROOT / "results" / "q6_wait.json"
    prev = [r for r in (json.loads(path.read_text()) if path.exists() else []) if r.get("label") != label]
    path.write_text(mask(json.dumps(prev + rows, ensure_ascii=False, indent=2)))
