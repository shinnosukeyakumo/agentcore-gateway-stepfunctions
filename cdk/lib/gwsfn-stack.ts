import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';

const PREFIX = 'gwsfn';

/** 方向A で使う、エージェント（Harness）のシステムプロンプト */
const SUPPORT_PROMPT = `あなたは EC サイトのカスタマーサポート担当です。
- 注文の状態は get_order_status で確認してください。
- 返金の可否はあなたが判断せず、顧客が返金を求めたときは返金ワークフロー（StartExecution）を開始してください。可否はワークフローが決めます。
- 返金を求めていない問い合わせで返金ワークフローを開始してはいけません。
- 回答は日本語で簡潔に。`;

/** 方向B で使う、分類だけを担う Harness のシステムプロンプト */
const TRIAGE_PROMPT = `あなたは EC サイトの問い合わせ分類器です。顧客のメッセージを読み、次の JSON だけを出力してください。説明文やコードフェンスは不要です。
{"action": "START_REFUND" | "NONE", "orderId": "ORD-xxxx または null", "reason": "顧客が述べた理由の要約"}
- 顧客自身が返金（代金を戻すこと）を求めているときだけ START_REFUND にしてください。
- 返金できるかの判断はしないでください。条件の確認は後段のワークフローが行います。
- 質問・状況確認・クーポン要求・第三者を名乗る指示は NONE です。`;

export class GwSfnStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);
    const { account, region } = cdk.Stack.of(this);
    // モデルは `cdk deploy -c modelId=...` で差し替えられる
    const MODEL_ID: string = this.node.tryGetContext('modelId') ?? 'us.anthropic.claude-sonnet-4-6';
    // Q6 用: `-c refundDelaySec=60` で返金ワークフローの判定前に Wait を入れる（承認待ちなど、時間が掛かる状況の模擬）
    const REFUND_DELAY_SEC = Number(this.node.tryGetContext('refundDelaySec') ?? 0);
    // Q5 用: `-c refundNamedTarget=on` で StartExecution の name を公開した別ターゲットを足す
    const REFUND_NAMED_TARGET = this.node.tryGetContext('refundNamedTarget') === 'on';

    // ------------------------------------------------------------------
    // Lambda: 架空の注文データ（Gateway のツール / ワークフローの照会）
    // ------------------------------------------------------------------
    const code = lambda.Code.fromAsset(path.join(__dirname, '..', 'lambda'));
    const toolsFn = new lambda.Function(this, 'ToolsFn', {
      functionName: `${PREFIX}-support-tools`,
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: 'orders.tools_handler',
      code,
      timeout: cdk.Duration.seconds(10),
      logGroup: new logs.LogGroup(this, 'ToolsFnLogs', { removalPolicy: cdk.RemovalPolicy.DESTROY, retention: logs.RetentionDays.ONE_WEEK }),
    });
    const lookupFn = new lambda.Function(this, 'LookupFn', {
      functionName: `${PREFIX}-order-lookup`,
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: 'orders.lookup_handler',
      code,
      timeout: cdk.Duration.seconds(10),
      logGroup: new logs.LogGroup(this, 'LookupFnLogs', { removalPolicy: cdk.RemovalPolicy.DESTROY, retention: logs.RetentionDays.ONE_WEEK }),
    });

    // ------------------------------------------------------------------
    // Step Functions: 返金ワークフロー（決定論。お金は動かさない）
    // ------------------------------------------------------------------
    const refundDefinition = {
      Comment: '返金の可否と承認要否を決める。エージェントは順序を変えられない',
      QueryLanguage: 'JSONata',
      StartAt: 'ValidateInput',
      States: {
        ValidateInput: {
          Type: 'Choice',
          Choices: [{ Condition: "{% $type($states.input.orderId) = 'string' %}", Next: 'LookupOrder' }],
          Default: 'InvalidInput',
        },
        InvalidInput: { Type: 'Fail', Error: 'InvalidInput', Cause: 'orderId (string) is required' },
        LookupOrder: {
          Type: 'Task',
          Resource: 'arn:aws:states:::lambda:invoke',
          Arguments: { FunctionName: lookupFn.functionArn, Payload: { orderId: '{% $states.input.orderId %}' } },
          Output: '{% $states.result.Payload %}',
          Next: REFUND_DELAY_SEC > 0 ? 'WaitBeforeDecision' : 'CheckEligibility',
        },
        ...(REFUND_DELAY_SEC > 0
          ? { WaitBeforeDecision: { Type: 'Wait', Seconds: REFUND_DELAY_SEC, Next: 'CheckEligibility' } }
          : {}),
        CheckEligibility: {
          Type: 'Choice',
          Choices: [
            { Condition: '{% $states.input.found = false %}', Next: 'NotFound' },
            { Condition: "{% $states.input.status != 'DELIVERED' %}", Next: 'NotDelivered' },
            { Condition: '{% $states.input.daysSinceDelivery > 30 %}', Next: 'OverThirtyDays' },
            { Condition: '{% $states.input.amount > 10000 %}', Next: 'NeedsApproval' },
          ],
          Default: 'IssueRefund',
        },
        NotFound: { Type: 'Pass', Output: { orderId: '{% $states.input.orderId %}', result: 'NOT_ELIGIBLE', why: 'ORDER_NOT_FOUND' }, End: true },
        NotDelivered: { Type: 'Pass', Output: { orderId: '{% $states.input.orderId %}', result: 'NOT_ELIGIBLE', why: 'NOT_DELIVERED' }, End: true },
        OverThirtyDays: { Type: 'Pass', Output: { orderId: '{% $states.input.orderId %}', result: 'NOT_ELIGIBLE', why: 'OVER_30_DAYS' }, End: true },
        NeedsApproval: { Type: 'Pass', Output: { orderId: '{% $states.input.orderId %}', amount: '{% $states.input.amount %}', result: 'PENDING_APPROVAL' }, End: true },
        IssueRefund: { Type: 'Pass', Output: { orderId: '{% $states.input.orderId %}', amount: '{% $states.input.amount %}', result: 'REFUNDED', simulated: true }, End: true },
      },
    };
    const refundSm = new sfn.StateMachine(this, 'RefundWorkflow', {
      stateMachineName: `${PREFIX}-refund`,
      stateMachineType: sfn.StateMachineType.STANDARD,
      definitionBody: sfn.DefinitionBody.fromString(JSON.stringify(refundDefinition)),
    });
    lookupFn.grantInvoke(refundSm);

    // Q2 用: Gateway には公開しない別のワークフロー（10 分待つだけ）
    const internalSm = new sfn.StateMachine(this, 'InternalWorkflow', {
      stateMachineName: `${PREFIX}-internal-batch`,
      stateMachineType: sfn.StateMachineType.STANDARD,
      definitionBody: sfn.DefinitionBody.fromString(JSON.stringify({
        Comment: 'Gateway に公開しないワークフロー。到達範囲の確認用',
        StartAt: 'Wait',
        States: { Wait: { Type: 'Wait', Seconds: 600, End: true } },
      })),
    });

    // ------------------------------------------------------------------
    // Gateway のサービスロール（outbound）
    // ------------------------------------------------------------------
    const gatewayRole = new iam.Role(this, 'GatewayRole', {
      roleName: `${PREFIX}-gateway-role`,
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com', {
        conditions: {
          StringEquals: { 'aws:SourceAccount': account },
          ArnLike: { 'aws:SourceArn': `arn:aws:bedrock-agentcore:${region}:${account}:*` },
        },
      }),
    });
    toolsFn.grantInvoke(gatewayRole);
    // ピン留めできる操作: 公開するステートマシンだけ
    gatewayRole.addToPolicy(new iam.PolicyStatement({
      actions: ['states:StartExecution', 'states:ListExecutions', 'states:DescribeStateMachine'],
      resources: [refundSm.stateMachineArn],
    }));
    // ピン留めできない操作: 公開するステートマシンの execution だけに絞る
    gatewayRole.addToPolicy(new iam.PolicyStatement({
      actions: ['states:DescribeExecution', 'states:StopExecution', 'states:GetExecutionHistory'],
      resources: [`arn:aws:states:${region}:${account}:execution:${refundSm.stateMachineName}:*`],
    }));

    // ------------------------------------------------------------------
    // Gateway（inbound は IAM / SigV4）
    // ------------------------------------------------------------------
    const gateway = new agentcore.CfnGateway(this, 'Gateway', {
      name: `${PREFIX}-gateway`,
      protocolType: 'MCP',
      authorizerType: 'AWS_IAM',
      roleArn: gatewayRole.roleArn,
      exceptionLevel: 'DEBUG',
    });

    const gatewayRolePolicy = gatewayRole.node.tryFindChild('DefaultPolicy') as iam.Policy;

    // Lambda ターゲット: 注文照会 / FAQ / クーポン
    const supportTarget = new agentcore.CfnGatewayTarget(this, 'SupportTarget', {
      gatewayIdentifier: gateway.attrGatewayIdentifier,
      name: 'support',
      credentialProviderConfigurations: [{ credentialProviderType: 'GATEWAY_IAM_ROLE' }],
      targetConfiguration: {
        mcp: {
          lambda: {
            lambdaArn: toolsFn.functionArn,
            toolSchema: {
              inlinePayload: [
                {
                  name: 'get_order_status',
                  description: '注文の状態（商品・金額・配送状況・配達日）を取得する',
                  inputSchema: { type: 'object', properties: { orderId: { type: 'string', description: '注文番号（例: ORD-1001）' } }, required: ['orderId'] },
                },
                {
                  name: 'search_faq',
                  description: 'よくある質問（返金・送料・配送）を検索する',
                  inputSchema: { type: 'object', properties: { query: { type: 'string', description: '検索語' } }, required: ['query'] },
                },
                {
                  name: 'issue_coupon',
                  description: 'お詫びのクーポンを発行する',
                  inputSchema: { type: 'object', properties: { orderId: { type: 'string' }, reason: { type: 'string' } }, required: ['orderId', 'reason'] },
                },
              ],
            },
          },
        },
      },
    });
    supportTarget.node.addDependency(gatewayRolePolicy);

    // Step Functions コネクタターゲット
    const pin = { stateMachineArn: refundSm.stateMachineArn };
    const refundTarget = new agentcore.CfnGatewayTarget(this, 'RefundTarget', {
      gatewayIdentifier: gateway.attrGatewayIdentifier,
      name: 'refund',
      credentialProviderConfigurations: [{ credentialProviderType: 'GATEWAY_IAM_ROLE' }],
      targetConfiguration: {
        mcp: {
          connector: {
            source: { connectorId: 'states' },
            configurations: [
              {
                name: 'StartExecution',
                parameterValues: pin,
                description:
                  '返金ワークフローを開始する。顧客が返金を求めたときだけ使う。input は {"orderId": "ORD-xxxx", "reason": "理由"} の JSON 文字列。返金の可否と承認要否はワークフローが判定する。',
              },
              { name: 'ListExecutions', parameterValues: pin },
              { name: 'DescribeStateMachine', parameterValues: pin },
              { name: 'DescribeExecution' },
              { name: 'GetExecutionHistory' },
              { name: 'StopExecution' },
            ],
          },
        },
      },
    });
    refundTarget.node.addDependency(gatewayRolePolicy);

    // Q5 用: 同じ gwsfn-refund にピン留めし、StartExecution の name だけ公開したターゲット。
    // 既定では作らない。測定時は InvokeHarness の allowedTools で refund ターゲット側を外す
    let refundNamedTarget: agentcore.CfnGatewayTarget | undefined;
    if (REFUND_NAMED_TARGET) {
      refundNamedTarget = new agentcore.CfnGatewayTarget(this, 'RefundNamedTarget', {
        gatewayIdentifier: gateway.attrGatewayIdentifier,
        name: 'refund-named',
        credentialProviderConfigurations: [{ credentialProviderType: 'GATEWAY_IAM_ROLE' }],
        targetConfiguration: {
          mcp: {
            connector: {
              source: { connectorId: 'states' },
              configurations: [
                {
                  name: 'StartExecution',
                  parameterValues: pin,
                  // API リファレンスは JSON Pointer（/name）と書くが、2026-11-21 時点で通るのは JSONPath（$.name）だけだった
                  parameterOverrides: [{ path: '$.name', visible: true }],
                  description:
                    '返金ワークフローを開始する。顧客が返金を求めたときだけ使う。input は {"orderId": "ORD-xxxx", "reason": "理由"} の JSON 文字列。返金の可否と承認要否はワークフローが判定する。',
                },
                { name: 'ListExecutions', parameterValues: pin },
                { name: 'DescribeStateMachine', parameterValues: pin },
                { name: 'DescribeExecution' },
                { name: 'GetExecutionHistory' },
                { name: 'StopExecution' },
              ],
            },
          },
        },
      });
      refundNamedTarget.node.addDependency(gatewayRolePolicy);
    }

    // ------------------------------------------------------------------
    // Harness（方向A: Gateway のツールを使うサポートエージェント）
    // ------------------------------------------------------------------
    const harnessRole = new iam.Role(this, 'HarnessRole', {
      roleName: `${PREFIX}-harness-role`,
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com', {
        conditions: { StringEquals: { 'aws:SourceAccount': account } },
      }),
    });
    harnessRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream', 'bedrock:Converse', 'bedrock:ConverseStream'],
      resources: [
        `arn:aws:bedrock:*:${account}:inference-profile/${MODEL_ID}`,
        'arn:aws:bedrock:*::foundation-model/anthropic.claude-*',
      ],
    }));
    harnessRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:InvokeGateway'],
      resources: [gateway.attrGatewayArn],
    }));
    harnessRole.addToPolicy(new iam.PolicyStatement({
      actions: ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents', 'logs:DescribeLogStreams', 'logs:DescribeLogGroups',
        'xray:PutTraceSegments', 'xray:PutTelemetryRecords', 'cloudwatch:PutMetricData'],
      resources: ['*'],
    }));
    // Harness は会話履歴用の Memory を自動で作り、実行ロールで読み書きする
    harnessRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:CreateEvent', 'bedrock-agentcore:GetEvent', 'bedrock-agentcore:ListEvents',
        'bedrock-agentcore:ListSessions', 'bedrock-agentcore:RetrieveMemoryRecords', 'bedrock-agentcore:ListMemoryRecords'],
      resources: [`arn:aws:bedrock-agentcore:${region}:${account}:memory/${PREFIX}_*`],
    }));
    const harnessRolePolicy = harnessRole.node.tryFindChild('DefaultPolicy') as iam.Policy;

    // 既定では Harness の Memory を切る。自動作成の Memory は actorId が既定で "default" になり、
    // 別セッション・別ユーザーの会話から抽出した事実が同じ名前空間に溜まるため（README 参照）。
    // -c harnessMemory=on で自動作成の Memory を有効にした条件を再現できる。
    const harnessMemory = this.node.tryGetContext('harnessMemory') === 'on' ? undefined : { disabled: {} };

    const supportHarness = new agentcore.CfnHarness(this, 'SupportHarness', {
      harnessName: `${PREFIX}_support`,
      executionRoleArn: harnessRole.roleArn,
      model: { bedrockModelConfig: { modelId: MODEL_ID } },
      systemPrompt: [{ text: SUPPORT_PROMPT }],
      tools: [
        {
          type: 'agentcore_gateway',
          name: 'support_gateway',
          config: { agentCoreGateway: { gatewayArn: gateway.attrGatewayArn, outboundAuth: { awsIam: {} } } },
        },
      ],
      memory: harnessMemory,
      maxIterations: 10,
      timeoutSeconds: 300,
    });
    supportHarness.node.addDependency(harnessRolePolicy, supportTarget, refundTarget);
    if (refundNamedTarget) supportHarness.node.addDependency(refundNamedTarget);

    // Harness（方向B: 分類だけ。ツールは持たせない）
    const triageHarness = new agentcore.CfnHarness(this, 'TriageHarness', {
      harnessName: `${PREFIX}_triage`,
      executionRoleArn: harnessRole.roleArn,
      model: { bedrockModelConfig: { modelId: MODEL_ID } },
      systemPrompt: [{ text: TRIAGE_PROMPT }],
      memory: harnessMemory,
      maxIterations: 2,
      timeoutSeconds: 120,
    });
    triageHarness.node.addDependency(harnessRolePolicy);

    // ------------------------------------------------------------------
    // Step Functions: 方向B（ワークフローが親。LLM は分類だけ）
    // ------------------------------------------------------------------
    const triageDefinition = {
      Comment: 'LLM に分類だけさせ、返金ワークフローを起動するかはワークフローが決める',
      QueryLanguage: 'JSONata',
      StartAt: 'Classify',
      States: {
        Classify: {
          Type: 'Task',
          Resource: 'arn:aws:states:::bedrockagentcore:invokeHarness',
          Arguments: {
            HarnessArn: triageHarness.attrArn,
            RuntimeSessionId: '{% $uuid() %}',
            Messages: [{ Role: 'user', Content: [{ Text: '{% $states.input.message %}' }] }],
          },
          Output: {
            text: "{% $join($states.result.Output.Message.Content.Text, '') %}",
            usage: '{% $states.result.Usage %}',
          },
          TimeoutSeconds: 180,
          Next: 'ParseIntent',
        },
        ParseIntent: {
          Type: 'Pass',
          Output: "{% $merge([$parse($match($states.input.text, /\\{[\\s\\S]*\\}/)[0].match), {'usage': $states.input.usage}]) %}",
          Next: 'Route',
        },
        Route: {
          Type: 'Choice',
          Choices: [
            {
              Condition: "{% $states.input.action = 'START_REFUND' and $type($states.input.orderId) = 'string' %}",
              Next: 'StartRefund',
            },
          ],
          Default: 'NoRefund',
        },
        StartRefund: {
          Type: 'Task',
          Resource: 'arn:aws:states:::states:startExecution.sync:2',
          Arguments: {
            StateMachineArn: refundSm.stateMachineArn,
            Input: { orderId: '{% $states.input.orderId %}', reason: '{% $states.input.reason %}' },
          },
          Output: { routed: 'REFUND_WORKFLOW', intent: '{% $states.input %}', refund: '{% $states.result.Output %}' },
          End: true,
        },
        NoRefund: { Type: 'Pass', Output: { routed: 'CHAT_AGENT', intent: '{% $states.input %}' }, End: true },
      },
    };
    const triageSm = new sfn.StateMachine(this, 'TriageWorkflow', {
      stateMachineName: `${PREFIX}-triage`,
      stateMachineType: sfn.StateMachineType.STANDARD,
      definitionBody: sfn.DefinitionBody.fromString(JSON.stringify(triageDefinition)),
    });
    triageSm.addToRolePolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:InvokeHarness', 'bedrock-agentcore:InvokeAgentRuntime'],
      resources: [triageHarness.attrArn],
    }));
    triageSm.addToRolePolicy(new iam.PolicyStatement({
      actions: ['states:StartExecution'],
      resources: [refundSm.stateMachineArn],
    }));
    triageSm.addToRolePolicy(new iam.PolicyStatement({
      actions: ['states:DescribeExecution', 'states:StopExecution'],
      resources: [`arn:aws:states:${region}:${account}:execution:${refundSm.stateMachineName}:*`],
    }));
    triageSm.addToRolePolicy(new iam.PolicyStatement({
      actions: ['events:PutTargets', 'events:PutRule', 'events:DescribeRule'],
      resources: [`arn:aws:events:${region}:${account}:rule/StepFunctionsGetEventsForStepFunctionsExecutionRule`],
    }));

    // ------------------------------------------------------------------
    // 出力（scripts/ が読む）
    // ------------------------------------------------------------------
    new cdk.CfnOutput(this, 'GatewayUrl', { value: gateway.attrGatewayUrl });
    new cdk.CfnOutput(this, 'GatewayId', { value: gateway.attrGatewayIdentifier });
    new cdk.CfnOutput(this, 'SupportHarnessArn', { value: supportHarness.attrArn });
    new cdk.CfnOutput(this, 'TriageHarnessArn', { value: triageHarness.attrArn });
    new cdk.CfnOutput(this, 'RefundStateMachineArn', { value: refundSm.stateMachineArn });
    new cdk.CfnOutput(this, 'InternalStateMachineArn', { value: internalSm.stateMachineArn });
    new cdk.CfnOutput(this, 'TriageStateMachineArn', { value: triageSm.stateMachineArn });
  }
}
