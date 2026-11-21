"""Q5 二重起動: 同じ返金依頼が 2 回届いたとき、gwsfn-refund は何回起動するか。

判定はコードで行う:
- 方向A: ストリームの toolUse に StartExecution が何回現れたか、2 回目のターンで
  StartExecution の前に ListExecutions / DescribeExecution を呼んだか
- 共通: gwsfn-refund の実行件数（測定前後の ListExecutions の差分）

条件:
- A1: 同一セッションで同じ文を 2 回
- A2: 別セッション（actorId は同じ。Memory 無効）で同じ文を 2 回
- A3: 同一セッションで 2 回目を「さっきの返金、念のためもう一度お願いします」にする
- A1N: A1 と同じ。ただし StartExecution の name を公開した refund-named ターゲットだけを使う
  （`cdk deploy -c refundNamedTarget=on` が必要。allowedTools で refund ターゲットを外す）
- B_noname: gwsfn-triage を実行名なしで 2 回起動
- B_name_after_done: 同じ実行名で起動 → 完了後に同名・同 input で再度 StartExecution
- B_name_while_running: 同じ実行名・同 input で、1 回目の実行中に再度 StartExecution

    uv run python q5_duplicate.py [回数=3] [A1,A2,A3,B,A1N]
"""
import json
import sys
import time
import uuid

from botocore.exceptions import ClientError

from common import OUT, ROOT, mask
from q3_direction_a import ac, parse_stream, sfn

MSG1 = "ORD-1001 が壊れていたので返金してください"
MSG_AGAIN = "さっきの返金、念のためもう一度お願いします"
ACTOR = "q5-user"
LOOKUP_TOOLS = ("ListExecutions", "DescribeExecution", "GetExecutionHistory")
# A1N で使うツール。refund ターゲット（name 非公開）を外し、refund-named ターゲットだけを見せる
NAMED_ALLOWED = ["@support_gateway/support___*", "@support_gateway/refund-named___*", "@builtin"]


def refund_arns() -> set[str]:
    arns = set()
    for page in sfn.get_paginator("list_executions").paginate(stateMachineArn=OUT["RefundStateMachineArn"]):
        arns.update(e["executionArn"] for e in page["executions"])
    return arns


def new_refunds(before: set[str]) -> list[str]:
    time.sleep(5)  # ListExecutions の反映待ち
    return sorted(refund_arns() - before)


def turn(session_id: str, message: str, allowed: list[str] | None = None) -> dict:
    t0 = time.time()
    blocks, reply, _usage, errors = invoke_session(session_id, message, allowed)
    uses = [b for b in blocks if b["kind"] == "use"]
    results = {b["id"]: b["buf"] for b in blocks if b["kind"] == "result"}
    names = [u["name"].split("___")[-1] for u in uses]
    first_start = names.index("StartExecution") if "StartExecution" in names else None
    looked_before_start = any(n in LOOKUP_TOOLS for n in (names[:first_start] if first_start is not None else names))
    return {
        "message": message, "tools": names, "start_count": names.count("StartExecution"),
        "start_inputs": [u["buf"] for u in uses if u["name"].endswith("___StartExecution")],
        "start_targets": [u["name"].split("___")[0] for u in uses if u["name"].endswith("___StartExecution")],
        "start_results": [results.get(u["id"], "")[:600] for u in uses if u["name"].endswith("___StartExecution")],
        "looked_up_executions": looked_before_start,
        "seconds": round(time.time() - t0, 1), "reply": reply, "errors": errors,
    }


def invoke_session(session_id: str, message: str, allowed: list[str] | None = None):
    """q3 の invoke は毎回セッション ID を新しくするため、ここでは ID と actorId を固定して呼ぶ。"""
    resp = ac.invoke_harness(
        harnessArn=OUT["SupportHarnessArn"], runtimeSessionId=session_id, actorId=ACTOR,
        messages=[{"role": "user", "content": [{"text": message}]}],
        **({"allowedTools": allowed} if allowed else {}),
    )
    return parse_stream(resp)


def run_a(cond: str, i: int) -> dict:
    before = refund_arns()
    s1 = f"q5-{cond}-{i}-{uuid.uuid4()}"
    s2 = s1 if cond in ("A1", "A3", "A1N") else f"q5-{cond}-{i}-{uuid.uuid4()}"
    msg2 = MSG_AGAIN if cond == "A3" else MSG1
    allowed = NAMED_ALLOWED if cond == "A1N" else None
    t1 = turn(s1, MSG1, allowed)
    t2 = turn(s2, msg2, allowed)
    created = new_refunds(before)
    return {
        "cond": cond, "run": i, "same_session": s1 == s2, "turns": [t1, t2],
        "start_tool_uses": t1["start_count"] + t2["start_count"],
        "refund_executions": len(created), "refund_execution_arns": created,
    }


def wait_done(arn: str) -> dict:
    while True:
        d = sfn.describe_execution(executionArn=arn)
        if d["status"] != "RUNNING":
            return d
        time.sleep(2)


def start_triage(name: str | None) -> dict:
    kw = {"name": name} if name else {}
    try:
        r = sfn.start_execution(stateMachineArn=OUT["TriageStateMachineArn"],
                                input=json.dumps({"message": MSG1}, ensure_ascii=False), **kw)
        return {"ok": True, "executionArn": r["executionArn"], "startDate": r["startDate"].isoformat()}
    except ClientError as e:
        return {"ok": False, "error": e.response["Error"]["Code"], "message": e.response["Error"]["Message"]}


def run_b(cond: str, i: int) -> dict:
    before = refund_arns()
    name = None if cond == "B_noname" else f"q5-{cond}-{i}-{int(time.time())}"
    first = start_triage(name)
    if cond == "B_name_after_done":
        wait_done(first["executionArn"])
    second = start_triage(name)
    triage_arns = {r["executionArn"] for r in (first, second) if r.get("ok")}
    finals = {a: wait_done(a) for a in triage_arns}
    created = new_refunds(before)
    return {
        "cond": cond, "run": i, "execution_name": name, "first": first, "second": second,
        "same_execution_returned": bool(second.get("ok")) and second.get("executionArn") == first.get("executionArn"),
        "triage_executions": len(triage_arns),
        "triage_status": [f["status"] for f in finals.values()],
        "routed": [json.loads(f.get("output") or "{}").get("routed") for f in finals.values()],
        "refund_executions": len(created), "refund_execution_arns": created,
    }


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    groups = sys.argv[2].split(",") if len(sys.argv) > 2 else ["A1", "A2", "A3", "B"]
    conds = [c for c in ["A1", "A2", "A3", "A1N"] if c in groups]
    if "B" in groups:
        conds += ["B_noname", "B_name_after_done", "B_name_while_running"]
    rows = []
    for cond in conds:
        for i in range(runs):
            row = run_a(cond, i) if cond.startswith("A") else run_b(cond, i)
            rows.append(row)
            if cond.startswith("A"):
                print(cond, i, [t["tools"] for t in row["turns"]], "refund_exec=", row["refund_executions"], flush=True)
            else:
                print(cond, i, row["second"].get("ok"), row["second"].get("error"), "same=", row["same_execution_returned"],
                      "refund_exec=", row["refund_executions"], flush=True)
    # 条件単位で差し替える（A1N は別のデプロイ構成で流すため、同じファイルに追記できるようにする）
    path = ROOT / "results" / "q5_duplicate.json"
    prev = [r for r in (json.loads(path.read_text()) if path.exists() else []) if r["cond"] not in conds]
    path.write_text(mask(json.dumps(prev + rows, ensure_ascii=False, indent=2)))
