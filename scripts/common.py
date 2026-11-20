"""共通: スタック出力の読み込みと、SigV4 で Gateway に MCP JSON-RPC を投げる関数。"""
import json
import pathlib

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGION = "us-west-2"
OUT = json.loads((ROOT / "outputs.json").read_text())["GwSfnStack"]
SESSION = boto3.Session(profile_name="default", region_name=REGION)


def mcp(method: str, params: dict | None = None, rid: int = 1) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
    req = AWSRequest(method="POST", url=OUT["GatewayUrl"], data=body,
                     headers={"Content-Type": "application/json"})
    SigV4Auth(SESSION.get_credentials(), "bedrock-agentcore", REGION).add_auth(req)
    r = httpx.post(OUT["GatewayUrl"], content=body, headers=dict(req.headers), timeout=60)
    return r.json()


def call_tool(name: str, args: dict) -> dict:
    return mcp("tools/call", {"name": name, "arguments": args}).get("result", {})


def mask(s: str) -> str:
    """公開用にアカウント ID を伏せる。"""
    import re
    return re.sub(r"(?<=:)\d{12}(?=:)", "<account>", s)
