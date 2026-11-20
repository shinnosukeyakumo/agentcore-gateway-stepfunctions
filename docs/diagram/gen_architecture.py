"""構成図（architecture.drawio）を生成する。

    python3 gen_architecture.py architecture.drawio
    drawio -x -f png -e -b 16 -s 2 -o architecture.drawio.png architecture.drawio
"""
import base64
import os
import re
import sys
from xml.sax.saxutils import quoteattr

HERE = os.path.dirname(os.path.abspath(__file__))
cells = []
F = "fontFamily=Helvetica;"
INK = "#232F3E"
LABEL = f"verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;fontSize=12;fontColor={INK};{F}"

USER_X, TRUNK_X = 50, 115
C1, C2, C3, C4 = 345, 570, 810, 1045
R1, R2, R3 = 150, 335, 520
ICON = 48
LINE_ICON = 58


def v(id, value, style, cx, cy, w, h):
    cells.append(f'<mxCell id="{id}" value={quoteattr(value)} style={quoteattr(style)} vertex="1" parent="1"><mxGeometry x="{cx - w / 2}" y="{cy - h / 2}" width="{w}" height="{h}" as="geometry" /></mxCell>')


def box(id, value, style, x, y, w, h):
    cells.append(f'<mxCell id="{id}" value={quoteattr(value)} style={quoteattr(style)} vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>')


def label(name, sub=""):
    return name + (f"<br>({sub})" if sub else "")


def service(id, shape, color, name, sub, cx, cy):
    v(id, label(name, sub), f"sketch=0;outlineConnect=0;fillColor={color};strokeColor=#ffffff;dashed=0;aspect=fixed;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{shape};{LABEL}", cx, cy, ICON, ICON)


def line_icon(id, file, name, sub, cx, cy, side=110):
    """縦横比の違う線画を、共通の倍率のまま正方形の中央に置く。"""
    src = open(os.path.join(HERE, "icons", file)).read()
    vb = re.search(r'viewBox="([\d.\s]+)"', src).group(1).split()
    w, h = float(vb[2]), float(vb[3])
    inner = re.sub(r'^.*?<svg[^>]*>', "", src, count=1, flags=re.S).rsplit("</svg>", 1)[0]
    sq = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {side} {side}">'
          f'<g transform="translate({(side - w) / 2} {(side - h) / 2})">{inner}</g></svg>')
    b64 = base64.b64encode(sq.encode()).decode()
    v(id, label(name, sub), f"shape=image;aspect=fixed;imageAspect=0;image=data:image/svg+xml,{b64};spacingTop={-(LINE_ICON - ICON) // 2};{LABEL}", cx, cy, LINE_ICON, LINE_ICON)


def general(id, shape, name, cx, cy):
    v(id, name, f"sketch=0;outlineConnect=0;gradientColor=none;fillColor={INK};strokeColor=none;dashed=0;aspect=fixed;pointerEvents=1;shape=mxgraph.aws4.{shape};{LABEL}", cx, cy, ICON, ICON)


def anchor(id, cx, cy):
    v(id, "", "shape=point;size=0;strokeColor=none;fillColor=none;", cx, cy, 1, 1)


def group(id, name, x, y, w, h):
    box(id, name, f"rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#879196;dashed=1;strokeWidth=1;verticalAlign=top;align=left;spacingLeft=10;fontSize=13;fontColor={INK};spacingTop=4;{F}", x, y, w, h)


def edge(id, src, tgt, exit=None, entry=None, points=(), text="", side=False, pos=0):
    st = f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=open;endFill=0;endSize=8;strokeWidth=1.2;strokeColor={INK};fontColor={INK};fontSize=11;{F}"
    if exit:
        st += f"exitX={exit[0]};exitY={exit[1]};exitDx=0;exitDy=0;"
    if entry:
        st += f"entryX={entry[0]};entryY={entry[1]};entryDx=0;entryDy=0;"
    pts = "".join(f'<mxPoint x="{x}" y="{y}" />' for x, y in points)
    arr = f'<Array as="points">{pts}</Array>' if pts else ""
    cells.append(f'<mxCell id="{id}" style={quoteattr(st)} edge="1" parent="1" source="{src}" target="{tgt}"><mxGeometry relative="1" as="geometry">{arr}</mxGeometry></mxCell>')
    if text:
        off = (8, 0) if side else (0, -8)
        al = "left;verticalAlign=middle" if side else "center;verticalAlign=bottom"
        cells.append(f'<mxCell id="{id}-label" value={quoteattr(text)} style={quoteattr(f"edgeLabel;html=1;align={al};resizable=0;points=[];labelBackgroundColor=none;fontSize=11;fontColor={INK};{F}")} vertex="1" connectable="0" parent="{id}"><mxGeometry x="{pos}" relative="1" as="geometry"><mxPoint x="{off[0]}" y="{off[1]}" as="offset" /></mxGeometry></mxCell>')


AWS_GROUP = "points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],[1,1],[0.75,1],[0.5,1],[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]];outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=12;fontStyle=0;container=0;pointerEvents=0;collapsible=0;recursiveResize=0;shape=mxgraph.aws4.group;verticalAlign=top;align=left;spacingLeft=30;fillColor=none;" + F

# 枠
box("aws-cloud", "AWS Cloud", AWS_GROUP + f"grIcon=mxgraph.aws4.group_aws_cloud_alt;strokeColor={INK};fontColor={INK};dashed=0;", 160, 0, 1000, 660)
box("region", "US West (Oregon) us-west-2", AWS_GROUP + "grIcon=mxgraph.aws4.group_region;strokeColor=#00A4A6;fontColor=#00A4A6;dashed=1;", 180, 35, 960, 605)
group("g-a", "方向A: エージェントが親", 200, 78, 710, 170)
group("g-refund", "返金ワークフロー", 690, 268, 430, 150)
group("g-b", "方向B: ワークフローが親", 200, 455, 455, 165)

# ノード
general("user", "user", "検証スクリプト<br>(scripts/)", USER_X, (R1 + R3) / 2)
line_icon("support", "agentcore.svg", "AgentCore Harness", "gwsfn_support", C1, R1)
line_icon("gateway", "agentcore-gateway.svg", "AgentCore Gateway", "AWS_IAM", C2, R1)
service("tools", "lambda", "#ED7100", "AWS Lambda", "support-tools", C3, R1)
service("refund", "step_functions", "#E7157B", "AWS Step Functions", "gwsfn-refund", C3, R2)
service("lookup", "lambda", "#ED7100", "AWS Lambda", "order-lookup", C4, R2)
service("triage", "step_functions", "#E7157B", "AWS Step Functions", "gwsfn-triage", C1, R3)
line_icon("triage-h", "agentcore.svg", "AgentCore Harness", "gwsfn_triage", C2, R3)

anchor("a-gateway", C2, R1 + 70)
anchor("a-triage", C1, R3 + 70)
anchor("a-refund", C3, R2 + 70)

# ユーザーから幹を 1 本立てて上下に分ける
mid = (R1 + R3) / 2
edge("e-invoke", "user", "support", (1, 0.5), (0, 0.5), [(TRUNK_X, mid), (TRUNK_X, R1)], text="InvokeHarness", pos=0.78)
edge("e-start", "user", "triage", (1, 0.5), (0, 0.5), [(TRUNK_X, mid), (TRUNK_X, R3)], text="StartExecution", pos=0.78)

# 方向A
edge("e-mcp", "support", "gateway", text="MCP (SigV4)")
edge("e-lambda", "gateway", "tools", text="tools/call")
edge("e-pin", "a-gateway", "refund", None, (0, 0.5), [(C2, R2)], text="StartExecution<br>(ARN 固定)", pos=0.06)

# 返金ワークフロー
edge("e-lookup", "refund", "lookup", text="invoke")

# 方向B
edge("e-classify", "triage", "triage-h", text="invokeHarness")
edge("e-child", "a-triage", "a-refund", None, None, [(C1, 600), (C3, 600)], text="startExecution.sync", pos=0.22)

xml = ('<mxfile host="Electron" version="29.6.1"><diagram name="構成" id="arch">'
       '<mxGraphModel dx="1000" dy="700" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="0" pageScale="1" pageWidth="1200" pageHeight="700" math="0" shadow="0" background="#FFFFFF">'
       '<root><mxCell id="0" /><mxCell id="1" parent="0" />' + "".join(cells) + '</root></mxGraphModel></diagram></mxfile>\n')
open(sys.argv[1], "w").write(xml)
print("written", len(cells), "cells")
