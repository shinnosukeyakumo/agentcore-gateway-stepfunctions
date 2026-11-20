"""cdk destroy で消えないものを掃除する。

- 実行中の Step Functions の execution（internal-batch の待機など）
- Harness が自動で作った Memory（名前が gwsfn_ で始まるもの）

    uv run python cleanup.py        # 先に実行
    cd ../cdk && npx cdk destroy    # その後スタックを消す
"""
from common import OUT, SESSION

sfn = SESSION.client("stepfunctions")
ctl = SESSION.client("bedrock-agentcore-control")

for key in ("RefundStateMachineArn", "InternalStateMachineArn", "TriageStateMachineArn"):
    for page in sfn.get_paginator("list_executions").paginate(stateMachineArn=OUT[key], statusFilter="RUNNING"):
        for e in page["executions"]:
            sfn.stop_execution(executionArn=e["executionArn"])
            print("stopped", e["name"])

for page in ctl.get_paginator("list_memories").paginate():
    for m in page["memories"]:
        if m["id"].startswith("gwsfn_"):
            ctl.delete_memory(memoryId=m["id"])
            print("deleted memory", m["id"])
