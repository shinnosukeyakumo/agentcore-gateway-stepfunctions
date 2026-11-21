"""Q3 方向A: Harness（LLM）が Gateway のツールを選ぶ。12 シナリオ × N 回。

判定はコードで行う: ストリームの toolUse に refund___StartExecution が現れたか。
起動した場合は子実行の結果（REFUNDED / PENDING_APPROVAL / NOT_ELIGIBLE）も取る。

    uv run python q3_direction_a.py [回数=3] [S1,S2,...]
"""
import json
import re
import sys
import time
import uuid

from common import OUT, ROOT, SESSION, mask
from scenarios import SCENARIOS

ac = SESSION.client("bedrock-agentcore")
sfn = SESSION.client("stepfunctions")
EXEC_ARN = re.compile(r"arn:aws:states:[a-z0-9-]+:\d{12}:execution:[\w-]+:[\w-]+")


def invoke(sid: str, message: str) -> tuple[list[dict], str, dict | None, list]:
    """Harness を 1 回呼び、ツール呼び出し・結果・最終テキストを返す。"""
    resp = ac.invoke_harness(
        harnessArn=OUT["SupportHarnessArn"],
        runtimeSessionId=f"{sid}-{uuid.uuid4()}",
        messages=[{"role": "user", "content": [{"text": message}]}],
    )
    return parse_stream(resp)


def parse_stream(resp) -> tuple[list[dict], str, dict | None, list]:
    """InvokeHarness のストリームから、ツール呼び出し・結果・最終テキストを取り出す。"""
    open_blocks: dict[int, dict] = {}
    blocks, text, usage, errors = [], [], None, []
    for ev in resp["stream"]:
        if "contentBlockStart" in ev:
            e = ev["contentBlockStart"]
            st = e["start"]
            if "toolUse" in st:
                open_blocks[e["contentBlockIndex"]] = {"kind": "use", "name": st["toolUse"]["name"], "id": st["toolUse"]["toolUseId"], "buf": ""}
            elif "toolResult" in st:
                open_blocks[e["contentBlockIndex"]] = {"kind": "result", "id": st["toolResult"]["toolUseId"], "buf": ""}
        elif "contentBlockDelta" in ev:
            e = ev["contentBlockDelta"]
            d, b = e["delta"], open_blocks.get(e["contentBlockIndex"])
            if "text" in d:
                text.append(d["text"])
            elif b and "toolUse" in d:
                b["buf"] += d["toolUse"].get("input", "")
            elif b and "toolResult" in d:
                for c in d["toolResult"]:
                    b["buf"] += c["text"] if "text" in c else json.dumps(c.get("json"), ensure_ascii=False)
        elif "contentBlockStop" in ev:
            b = open_blocks.pop(ev["contentBlockStop"]["contentBlockIndex"], None)
            if b:
                blocks.append(b)
        elif "metadata" in ev:
            usage = ev["metadata"].get("usage")
        elif any(k in ev for k in ("internalServerException", "validationException", "runtimeClientError")):
            errors.append(ev)
    return blocks, "".join(text), usage, errors


def refund_outcome(tool_result: str) -> str:
    """StartExecution の返り値から実行 ARN を拾い、ワークフローの結論を読む。"""
    m = EXEC_ARN.search(tool_result)
    if not m:
        return "NO_EXECUTION"
    for _ in range(30):
        d = sfn.describe_execution(executionArn=m.group(0))
        if d["status"] != "RUNNING":
            return json.loads(d.get("output") or "{}").get("result", d["status"])
        time.sleep(1)
    return "TIMEOUT"


def run(sid: str, message: str, expect: bool, i: int) -> dict:
    try:
        blocks, reply, usage, errors = invoke(sid, message)
    except Exception as e:  # noqa: BLE001
        return {"id": sid, "run": i, "expect_refund": expect, "error": repr(e)}
    uses = [b for b in blocks if b["kind"] == "use"]
    results = {b["id"]: b["buf"] for b in blocks if b["kind"] == "result"}
    starts = [u for u in uses if u["name"].endswith("___StartExecution")]
    started = bool(starts)
    return {
        "id": sid, "run": i, "expect_refund": expect, "started_refund": started, "correct": started == expect,
        "tools": [u["name"].split("___")[-1] for u in uses],
        "start_inputs": [u["buf"] for u in starts],
        "refund_outcomes": [refund_outcome(results.get(u["id"], "")) for u in starts],
        "reply": reply, "usage": usage, "errors": errors,
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
            mark = "START" if row.get("started_refund") else "-"
            print(sid, i, mark, row.get("tools"), row.get("refund_outcomes"), row.get("error", ""), flush=True)
    suffix = "" if not only else "_" + "_".join(only)
    (ROOT / "results" / f"q3_direction_a{suffix}.json").write_text(mask(json.dumps(rows, ensure_ascii=False, indent=2)))
