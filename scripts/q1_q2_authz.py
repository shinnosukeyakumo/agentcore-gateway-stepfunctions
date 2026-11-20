"""Q1: ピン留めは効くか / Q2: ピン外の操作はどこまで届くか。

LLM を介さず、Gateway に MCP を直接投げて確かめる（呼び出し側が悪意を持った場合の上限を見る）。
"""
import json
import time

from common import OUT, ROOT, SESSION, call_tool, mask, mcp

sfn = SESSION.client("stepfunctions")
report = {}

# ---- tools/list ----
tools = mcp("tools/list")["result"]["tools"]
report["tools"] = []
for t in tools:
    props = t.get("inputSchema", {}).get("properties", {})
    report["tools"].append({"name": t["name"], "params": sorted(props), "description": t.get("description", "")[:160]})
names = {t["name"] for t in tools}
refund_tools = sorted(n for n in names if n.startswith("refund___"))

# ---- Q1: ピン留め ----
q1 = {}
start = next(t for t in tools if t["name"] == "refund___StartExecution")
q1["start_schema_has_stateMachineArn"] = "stateMachineArn" in start["inputSchema"].get("properties", {})
q1["start_schema"] = start["inputSchema"]

ok = call_tool("refund___StartExecution", {"input": json.dumps({"orderId": "ORD-1001", "reason": "q1"})})
q1["normal_call"] = {"isError": ok.get("isError"), "text": mask(json.dumps(ok.get("content"), ensure_ascii=False))[:400]}

hijack = call_tool("refund___StartExecution", {
    "stateMachineArn": OUT["InternalStateMachineArn"],
    "input": "{}",
})
q1["override_pinned_arn"] = {"isError": hijack.get("isError"), "text": mask(json.dumps(hijack.get("content"), ensure_ascii=False))[:400]}

listed = call_tool("refund___ListExecutions", {"stateMachineArn": OUT["InternalStateMachineArn"]})
q1["override_list_executions"] = {"isError": listed.get("isError"), "text": mask(json.dumps(listed.get("content"), ensure_ascii=False))[:400]}
report["Q1"] = q1

# ---- Q2: ピン外の操作の到達範囲 ----
q2 = {}
internal = sfn.start_execution(stateMachineArn=OUT["InternalStateMachineArn"], name=f"q2-{int(time.time())}")
internal_exec = internal["executionArn"]
time.sleep(2)

for op in ["DescribeExecution", "GetExecutionHistory", "StopExecution"]:
    res = call_tool(f"refund___{op}", {"executionArn": internal_exec})
    q2[f"{op}_other_sm"] = {"isError": res.get("isError"), "text": mask(json.dumps(res.get("content"), ensure_ascii=False))[:300]}

status = sfn.describe_execution(executionArn=internal_exec)["status"]
q2["other_sm_execution_status_after"] = status
if status == "RUNNING":
    sfn.stop_execution(executionArn=internal_exec)

# 公開している SM の execution には届くこと（対照）
refund_exec = sfn.list_executions(stateMachineArn=OUT["RefundStateMachineArn"], maxResults=1)["executions"][0]["executionArn"]
res = call_tool("refund___DescribeExecution", {"executionArn": refund_exec})
q2["DescribeExecution_own_sm"] = {"isError": res.get("isError"), "text": mask(json.dumps(res.get("content"), ensure_ascii=False))[:400]}
report["Q2"] = q2

out = ROOT / "results" / "q1_q2_authz.json"
out.write_text(mask(json.dumps(report, ensure_ascii=False, indent=2)))
print(mask(json.dumps(report, ensure_ascii=False, indent=2)))
