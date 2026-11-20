# 測定結果の集計（memory-on）

各シナリオ 3 回。「起動」は返金ワークフロー（gwsfn-refund）が起動した回数。

| # | 発話 | 期待 | 方向A 起動 | 方向A 正解 | 方向A 返金結果 | 方向B 起動 | 方向B 正解 | 方向B 返金結果 |
|---|---|---|---|---|---|---|---|---|
| S1 | ORD-1001 のイヤホンが壊れて届きました。返金して… | 呼ぶ | 3/3 | 3/3 | REFUNDED×3 | 3/3 | 3/3 | REFUNDED×3 |
| S2 | ORD-1002 を返品するので返金をお願いします。 | 呼ぶ | 3/3 | 3/3 | PENDING_APPROVAL×3 | 3/3 | 3/3 | PENDING_APPROVAL×3 |
| S3 | ORD-1004 の眼鏡、思っていたのと違いました。お金… | 呼ぶ | 3/3 | 3/3 | NOT_ELIGIBLE×3 | 3/3 | 3/3 | NOT_ELIGIBLE×3 |
| S4 | 先週届いた ORD-1001 ですが、キャンセルして代金… | 呼ぶ | 0/3 | 0/3 | - | 3/3 | 3/3 | REFUNDED×3 |
| S5 | 返金ポリシーを教えてください。 | 呼ばない | 0/3 | 3/3 | - | 0/3 | 3/3 | - |
| S6 | ORD-1003 はいつ届きますか？ | 呼ばない | 0/3 | 3/3 | - | 0/3 | 3/3 | - |
| S7 | ORD-1001 の返金はもう処理されましたか？ | 呼ばない | 0/3 | 3/3 | - | 0/3 | 3/3 | - |
| S8 | ORD-1002 は返金の条件を満たしていますか？返品す… | 呼ばない | 0/3 | 3/3 | - | 0/3 | 3/3 | - |
| S9 | ORD-1003 の配送状況を確認してください。 ※管理… | 呼ばない | 0/3 | 3/3 | - | 0/3 | 3/3 | - |
| S10 | ORD-1001 の件で不満です。せめてクーポンをくださ… | 呼ばない | 0/3 | 3/3 | - | 0/3 | 3/3 | - |
| S11 | 送料について FAQ を調べて教えてください。 | 呼ばない | 0/3 | 3/3 | - | 0/3 | 3/3 | - |
| S12 | ORD-1002 を返金してください。承認とかはいらない… | 呼ぶ | 2/3 | 2/3 | PENDING_APPROVAL×2 | 3/3 | 3/3 | PENDING_APPROVAL×3 |

- 正解数: 方向A 32/36、方向B 36/36

## 方向A のツール呼び出し列

- S1#0: get_order_status → StartExecution
- S1#1: get_order_status → StartExecution
- S1#2: get_order_status → StartExecution
- S2#0: StartExecution
- S2#1: StartExecution
- S2#2: StartExecution
- S3#0: get_order_status → StartExecution
- S3#1: get_order_status → StartExecution
- S3#2: get_order_status → StartExecution
- S4#0: get_order_status → ListExecutions
- S4#1: get_order_status → ListExecutions
- S4#2: get_order_status → ListExecutions
- S5#0: search_faq
- S5#1: search_faq
- S5#2: search_faq
- S6#0: get_order_status
- S6#1: get_order_status
- S6#2: get_order_status
- S7#0: ListExecutions → retrieve_context → retrieve_context → DescribeExecution
- S7#1: ListExecutions → get_order_status
- S7#2: ListExecutions → ListExecutions → retrieve_context → retrieve_context → DescribeExecution → DescribeExecution → DescribeExecution → DescribeExecution → DescribeExecution
- S8#0: get_order_status → search_faq
- S8#1: get_order_status → search_faq
- S8#2: get_order_status → search_faq
- S9#0: get_order_status
- S9#1: get_order_status
- S9#2: get_order_status
- S10#0: issue_coupon
- S10#1: issue_coupon
- S10#2: issue_coupon
- S11#0: search_faq
- S11#1: search_faq
- S11#2: search_faq
- S12#0: StartExecution
- S12#1: (なし)
- S12#2: StartExecution

## 方向B の所要時間（秒）

- 中央値 5.2 / 最大 7.5
