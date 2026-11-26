# ovo-acceptance — Prove Anything 的现有实现基础（P0）

**Prove Anything 是 OVO 的族级协议与开放标准候选：Agent 说“完成了”，只是一项待验证的声明。** 本目录是它当前已经存在的最小实现基础，不是另一个商业产品，也不是一个万能裁判。

三个产品共用一套「任务怎么说清、过程怎么留痕、证据怎么登记、结论怎么验收」的最小契约。
它不替代 Askovo / Growovo / Verovo 各自的专业语义，只保证同一件事在族内可以被同一个审阅者复核。

## 为什么先建这一层

REA 和 Craft Anything 的经验值得借，但它们解决的是「怎么逆向一个产品」，不是「凭什么说这件事做完了」。
如果先把某个工具设成底层依赖，三个产品会各自长出一套无法互认的完成标准。所以顺序是：

1. **P0（本目录）**：统一任务合同、执行轨迹、证据账本、结果验收和人工升级。
2. **P1**：把 REA、Craft Anything 或其他工具接成**可替换的能力适配器**——适配器产出 `execution-trace` 和 `evidence-ledger` 条目，换掉工具不换契约。
3. **P2（暂不投入）**：通用软件克隆平台；不让任何逆向工具成为 OVO 的底层依赖。

## 五个契约

| 文件 | 回答的问题 | 关键约束 |
| --- | --- | --- |
| `contracts/task-contract.schema.json` | 这次任务承诺交付什么、给谁、按什么标准验收、什么不在范围内 | 每个 deliverable 至少一条可引用的验收标准；`out_of_scope` 显式写出 |
| `contracts/execution-trace.schema.json` | 实际跑了什么、按什么顺序、重试和缓存指向哪一步 | `retry_of` / `cache_hit_of` 只能指向更早的同动作步骤；供应商记录必须留 `external_id` |
| `contracts/evidence-ledger.schema.json` | 结论能指向的唯一证据池 | 每条证据有来源、`sha256`、观察时间、采集人、`trust`（observed / reported / derived） |
| `contracts/acceptance-record.schema.json` | 谁、在什么时候、按哪条标准、给了什么判定 | `PASS` 必须引用账本里的证据；`FAIL` 必须说明失败点；`UNPROVEN` 是一种判定，不是通过 |
| `contracts/escalation-record.schema.json` | 失败或无法证明时，谁做了什么决定 | `decision` 四选一：`accept_with_gap` / `rework` / `stop` / `external_review`；`accept_with_gap` 仍要有下一步动作 |

独立 Agent 真实任务另用 `contracts/agent-e2e-run.schema.json`：九类预登记任务见 `e2e/cases.json`，每案要求产品与通用 Agent 基线各跑一次全新会话。合成输入、缺人工验收、缺 Growovo 外部回执或带开放缺陷的记录不能标成 `REAL_SUCCESS`；当前矩阵仍为 `NOT_RUN`。

产品行为观察不是单独一套 schema，而是 `evidence-ledger` 里 `kind: "observation"` 的条目，额外要求：

- `trust` 必须是 `observed`（自己看到的，不是别人转述的）；
- `context` 必须写全 `product_version` / `account_permission` / `platform` / `region`；
- `generalization` 只能是 `single_case` / `repeated` / `multi_context`，**没有 universal**；
- `single_case` 的 `repeat_count` 必须为 1，`multi_context` 至少要两个不同的上下文四元组。

一次操作观察因此无法直接上升为普遍产品能力——想升级，只能补次数或补上下文。

## C-01 跨产品三凭证（共享层）

`contracts/` 另有 `result-receipt.schema.json`、`delegated-task.schema.json`、`service-capability.schema.json`，`validate` 会按 `schema` 字段自动识别：

```bash
python3 -m ovo_acceptance validate examples/valid-result-receipt.json
python3 -m ovo_acceptance validate examples/valid-delegated-task.json
python3 -m ovo_acceptance validate examples/valid-service-capability.json
```

三份契约固定了 C-01 审计中缺失的对象：结果凭证、委托任务、能力自描述。校验器只检查形状和几条硬边界——`verified_business_outcome` 必须有具名人工接受、空授权不能进入 `running`、`production_proven` 必须带 `evidence_refs`——它不证明跨产品流程已经跑通。

共享层还提供只读适配器：已有 Proof Bundle 可以投影成结果凭证，也可以导出产品能力描述：

```bash
python3 -m ovo_acceptance adapter --proof path/to/proof-bundle --out receipt.json --by roy
python3 -m ovo_acceptance adapter --product growovo --out capability.json
```

凭证固定为 `verification_state=observed`、`causality=not_claimed`：它只说明“这个 bundle 被验证过”，不说明业务成功。能力描述是产品边界的静态表，不是实时能力探测。

**边界**：三个产品目前尚未接入这三份 schema 的适配器；共享层先保证“同一对象可以被同一审阅者解析”，产品内的本地 receipt/run/能力说明仍是各自事实源。下一步要么三仓各加适配层并写契约测试，要么正式把这三份降级为文档模板。

## 统一业务结果投影

`contracts/task-result.schema.json` 将各产品已有任务状态投影为 `ovo.task-result/1`，不另建运行时。六种状态为 `running`、`waiting_external`、`needs_decision`、`partial_result`、`completed`、`unable_to_complete`；输出同时携带已完成工作、观察、证据引用、局部缺项、下一步和 `resume_ref`。

```bash
python3 -m ovo_acceptance validate examples/valid-task-result.json
```

校验器要求 `needs_decision` 与 `user_decision_required` 一致，`completed` 不得保留阻断缺项，`partial_result` 必须有实际成果或证据，`unable_to_complete` 必须给出恢复动作。投影本身不证明后台执行、外部交付或业务验收；Askovo `decide status`、Growovo `grow status --explain` 和 Verovo `economics` 分别复用各自事实源生成该块。

## 统一 Experiment Contract

`contracts/experiment-contract.schema.json` 为 Askovo 需求验证、Growovo 增长实验和 Verovo 工具价值实验提供同一份可携带合同。它固定假设与证伪条件、处理/对照组、主指标、可比性、时间窗、停止条件、授权、观察、结果和业务决定：

```bash
python3 -m ovo_acceptance validate examples/valid-experiment-contract.json
python3 -c "from ovo_acceptance import model; import json; d=json.load(open('examples/valid-experiment-contract.json')); print(model.experiment_design_hash(d))"
```

`design_sha256` 绑定假设、设计、时间窗和停止条件；注册后改动这些字段会使合同失效。每个 arm 还可携带结构化 `price {amount,currency,definition}`，金额非负、币种为三位大写字母，价格变更同样会使设计指纹失效。价格字段只描述实验条件，不把注册意向升级为支付或收入。观察必须引用已登记分组和主指标，排除样本要说明原因，外部招募、分发、渠道或付费动作需要授权引用。

结果把 `supports_hypothesis / refutes_hypothesis / inconclusive / not_evaluated` 与 `descriptive_association / causal_supported / causal_refuted / not_claimed` 分开。固定分组和前后对比最多先形成描述性关联；因果声明还要求随机分组、控制/处理组、同任务集、同验收标准、同预算以及每组合格观察。校验器只检查这些结构前提，不计算统计显著性，也不证明实验已在真实世界执行。业务决定由具名负责人另行记录。

三个产品分别提供只读导出器：Askovo 从 `capture plan` 投影，Growovo 从持久增长实验与事件投影，Verovo 从可比 tool-value 任务投影。它们共用本合同但不互相依赖；导出只整理本地事实，不代表实验已自动执行、样本足够或业务结论通过。

多份已校验合同可整理为本地可复用数据集：

```bash
python3 -m ovo_acceptance experiment-dataset \
  --dataset-id ovo-local-experiments --out ./experiment-dataset \
  examples/valid-experiment-contract.json
```

`experiment-dataset` 固定为 `classification=local_only` 和 `public_release=not_authorized`，输出完整合同、稳定数据集哈希、产品/状态/结果/证据资格计数和指标清单。它不复制原始证据文件，不跨实验合并异质指标、成本或人群，也不提升因果等级。公开分享必须另行授权和脱敏；本地数据集构建不等于外部贡献、采用或 R5 生态结果已经成立。

## 研发工单范围与实现覆盖

`ovo_acceptance/roadmap_coverage.py` 校验编号工单目录，并分别汇总实现、验收、优先级和范围决定：

```bash
python3 -m ovo_acceptance roadmap-coverage ../ai输出/研发交付/roadmap-work-items-20261125.json --json
```

每项 `A1-01` 类工单必须绑定所属模块、产品、标题、优先级、实现/验收状态、证据、测试、案例、范围决定和未决条件。`unknown` 与 `pending` 不会被实现文档自动消除；`accepted_external` 必须有案例且无未决条件。无子编号模块单独计数。目录用于安排研发与补验，不把范围决定或局部测试冒充外部产品完成。

## 47 个业务场景的入口与验收覆盖

`ovo_acceptance/scenario_coverage.py` 校验机器可读场景目录，并把实现状态与验收状态分开：

```bash
python3 -m ovo_acceptance scenario-coverage ../ai输出/研发交付/business-scenario-catalog-20261125.json --json
```

每个 `A-Sxx / G-Sxx / V-Sxx` 场景必须声明产品、入口、实现状态、验收状态、已有线索、测试、案例和未决条件。`accepted_real` / `accepted_external` 必须引用案例且不能保留未决条件；本地实现、合成通过或真实业务的部分证据都不能自动升级成整场景接受。当前目录覆盖 15／16／16 个场景，输出只报告分层计数，不给出虚假的整体完成百分比。

## Model Upgrade Test

`ovo_acceptance/model_upgrade.py` 对同一任务的四个独立运行做描述性比较：弱模型无 OVO、弱模型+OVO、强模型无 OVO、强模型+OVO。指标可声明 `higher_better` 或 `lower_better`，输出两种模型下的 OVO 增益、增益变化和容差内的 `amplified / stable / diminishing`：

```bash
python3 -m ovo_acceptance model-upgrade examples/valid-model-upgrade.json --json
```

四臂必须有唯一运行引用、原始证据、自然语言任务、新鲜会话和无答案提示，并满足同任务、输入、授权、验收规则与预算。缺资格时不计算增益。单任务结果只是描述性证据，不自动证明一般产品架构结论、因果或在更复杂/更长任务上的表现；真实采用仍需相应外部记录。

## 低人工干预有效交付率与体验失败分类

`ovo_acceptance/experience.py` 汇总真实授权的 `agent-e2e-run`、独立人工耗时记录、各 case 的预登记人工上限和失败分类：

```bash
python3 -m ovo_acceptance experience examples/experience-summary.json --json
```

分母是所有已开始的真实授权运行，包括失败和高人工成功；分子只包含总人工不超过 case 上限的 `REAL_SUCCESS`。缺少耗时或上限保持未决，合成运行单列，不能变成零人工成功。人工记录区分总耗时、授权、必要业务输入和产品问题耗时。失败分类覆盖 discovery、installation、invocation、context、data、execution、recovery、intelligence、delivery、intervention 和 value。输出同时给总体与逐 case 比率、结果分布、人工耗时和失败分类，指标是描述性验收，不证明因果。

## Problem Resolution Contract

`ovo_acceptance/resolution.py` 把三产品遇到问题后的默认行为统一为七类：`auto_fix`、`switch_path`、`partial_delivery`、`data_needed`、`permission_needed`、`business_decision` 和 `stop`：

```bash
python3 -m ovo_acceptance resolution examples/problem-resolution.json --json
```

自动修复必须无副作用、保持原授权并限制尝试次数；替代路径必须已验证、合规、范围一致且有授权引用。外部结果未知时，修复或换路前先对账，已完成结果不得重复执行。缺数据先尝试无副作用的合规自动获取，仍缺失才询问用户；权限请求只包含缺少的增量范围。部分交付必须列出限制，业务判断必须给证据和至少两个带影响的选项。校验器只输出下一步建议，`execution_applied` 永远为 `false`；三产品的实际接入和外部执行结果分别验收。

## Host Compatibility Matrix

`ovo_acceptance/host_matrix.py` 汇总宿主×模型×产品的八类能力：Skill 发现、CLI 安装执行、MCP 调用、高阶任务、文件/数据访问、多轮恢复、后台执行和自然语言交付：

```bash
python3 -m ovo_acceptance host-matrix examples/host-compatibility.json --json
```

`PASS/FAIL` 必须引用运行和证据，`CAPABILITY_ONLY` 必须有探测证据但绝不等同后台运营通过，`UNSUPPORTED` 必须解释原因，`NOT_RUN` 与不支持的语义保持分离。高阶任务和自然语言交付都通过时，矩阵才给出结构性 `core_l3_status=PASS`；关联的 `agent-e2e-run` 仍须独立满足新鲜会话、真实输入和人工验收，才能声称真实 L3/L4。矩阵只汇总已有观察，不执行新测试，也不生成“完全兼容”总标签。

## 家族词汇映射

`contracts/family-vocabulary.json` 是一张声明式映射表：产品别名（含 `AgentMeasure`/`buyer-ledger`）、三产品生命周期状态到家族状态的映射、六套判决词表到家族判决的映射、证据轴、结果分层和 `P0`/`G-xx` 命名空间。`ovo_acceptance/vocabulary.py` 负责加载、校验和翻译：

```bash
python3 -m ovo_acceptance vocabulary --json
python3 -c "from ovo_acceptance import vocabulary as v; print(v.translate_state('askovo','scoped'))"
python3 -c "from ovo_acceptance import vocabulary as v; print(v.translate_verdict('proof','UNCHECKED'))"
```

它不替换任何产品的状态机；产品内部状态保持原样，只在跨产品阅读时使用同一张表。映射表中带 `notes` 的格子是产品语义判断（例如 Askovo `blocked` → `failed`），需要产品负责人确认后才能升级为运行时约束。

## Prove Anything Proof Bundle 协议（当前实现）

目标 Proof Bundle 把一次任务整理为可携带目录：

```text
proof-bundle/
├── contract.json       任务目标、范围、禁止事项、验收条件
├── trace.jsonl         实际工具调用、状态变化、审批与失败
├── artifacts/          交付物，或其哈希与安全引用
├── checks.json         验证器、预期结果、实际结果、覆盖范围
├── proof.json          通过项、失败项、未知项、有效环境与时效
└── replay/             可复跑脚本、环境与输入说明
```

当前十四份 schema 中，五份核心记录覆盖合同、轨迹、证据、验收与升级基础；另有 `agent-e2e-run`、`proof`、`proof-checks`、`replay-manifest` 四份，C-01 的 `result-receipt`、`delegated-task`、`service-capability` 三份，以及跨产品 `experiment-contract` 和 `task-result`。`proof` 命令进一步校验 `checks.json`、`proof.json`、P0–P4 分级、五态、产物哈希、投影一致性和 `replay/manifest.json`。三个产品的只读导出器分别位于各自仓库；真实外部采用、语义复核和买方处置仍须独立回执，导出成功不会替代它们。

协议中的 `PASS / FAIL / UNCHECKED / INDETERMINATE / EXPIRED` 必须分开：未检查不是成功，无法判断不是失败，过期结论不能冒充当前结论。`bundle` 保留原有验收总体结论，`proof` 使用五态并输出各等级计数，不给整个任务计算最高证明等级。Proof 输出同时包含 `contract_validation.status` 与 `business_verdict.status`：前者为 `PASS` 只表示结构和格式有效，后者为 `FAIL / BLOCKED / INDETERMINATE / EXPIRED` 时必须使对应业务验收失败或保持未决，不能仅凭 `errors=[]` 认定任务成功。时间戳沿用合同的可选时区形式；无时区时间按 UTC 参与顺序比较并记录 `time_semantics.timezone_assumed=UTC` 和字段路径，混合时区不会导致校验器崩溃，但潜在业务 `PASS` 会降级为 `INDETERMINATE`。

> 下表的 `P0–P4` 一律指 **proof 等级**，不是族级阶段 `P0/P1/P2`，也不是工单优先级或页面批次。

| 证明层级 | 只证明什么 | 不能据此声称 |
| --- | --- | --- |
| P0 执行回执 | 工具或流程运行过 | 业务任务完成 |
| P1 产物有效 | 文件、代码或报告存在且可读取 | 内容符合真实需求 |
| P2 状态正确 | 目标系统中的最终状态符合合同 | 所有业务语义都正确 |
| P3 领域规则通过 | 独立专业验证器接受指定检查 | 专业人员已批准 |
| P4 外部结果成立 | 客户签收、真实采用、账务或业务结果被观察 | 结果一定由 Agent 导致 |

等级附着于具体检查，不给整个任务取最高等级盖章。验证优先使用确定性检查与目标系统独立最终状态；LLM Judge 只能辅助，专业责任仍由有权限的人签署。

### VCF 边界

Verified Capability Factory（VCF）是后续开源研究候选，生产带对象、动作、状态、约束、恢复、验证器和证明策略的 Verified Capability Package（VCP）。它不是本目录的当前依赖。只有在单点对照、三域共用核心、跨 Agent 可携带等阶段门通过后，才考虑扩成平台；否则收缩为任务包模板。

## 用法

```bash
cd ovo-acceptance

# 校验单份文档（按 schema 字段自动识别类型）
python3 -m ovo_acceptance validate examples/valid-bundle.json

# 校验整个验收包，输出 PASS / PASS_WITH_GAP / BLOCKED / FAIL / INVALID
python3 -m ovo_acceptance bundle examples/valid-bundle.json
python3 -m ovo_acceptance bundle path/to/bundle-dir/     # 目录下的 bundle.json

# 输入契约：bundle 接受单个 bundle 文件，或含 bundle.json/acceptance-bundle.json 的目录。
# proof 只接受目录，且必须含 bundle.json、contract.json、checks.json、proof.json
# 与 trace.jsonl（replay/manifest.json 可选）；传文件或不存在路径按用法错误退出 2。
# 两套状态作用域不同：bundle 结论是 PASS/PASS_WITH_GAP/BLOCKED/FAIL/INVALID，
# proof 判定态是 PASS/FAIL/UNCHECKED/INDETERMINATE/EXPIRED，不能互相替代。

# proof.json 与 replay manifest 须对重放可用性和缺失输入给出一致说明。
# 校验完整 Proof Bundle：五态、P0–P4、证据引用、产物哈希、投影和重放清单
python3 -m ovo_acceptance proof path/to/proof-bundle/ --json

# 公开一个不含原始输入的验收投影、任务模板和静态查看页
python3 -m ovo_acceptance publish examples/valid-bundle.json \
  --out /tmp/ovo-public-proof --classification synthetic --by roy

# 跑契约测试
python3 -m unittest discover -s tests

# 真实任务案例：查询、校验、重放与发布门
python3 -m ovo_acceptance case list
python3 -m ovo_acceptance case intents
python3 -m ovo_acceptance case show A-HMC-RESEARCH-01
python3 -m ovo_acceptance case incidents --out ../ai输出/ovo-真实任务资产库/INCIDENTS.md
python3 -m ovo_acceptance case validate
python3 -m ovo_acceptance case verify --root .. --run-root ../临时工作区/ovo-case-verify
```

## 真实任务案例门

`case` 复用同一份案例运行时和注册表，不再由三个产品分别实现案例逻辑。Askovo、Growovo、Verovo 也分别提供 `case` 薄入口；`OVO_ACCEPTANCE_HOME` 可覆盖运行时位置，`OVO_CASE_REGISTRY` 可为隔离测试指定另一份注册表，`OVO_CASE_ROOT` 可显式覆盖证据根目录。默认家族注册表确定家族工作区根路径；自定义注册表默认使用当前工作目录，因此从任一产品仓库调用都能正确解析案例证据。

`case intents` 列出真实用户意图测试合同；`case validate` 校验案例、执行问题、用户意图、路径、重复 ID 与常见凭据材料。`case replay` 在隔离目录重跑一个任务；`case verify` 重跑全部可重放案例并区分 `task_rerun` 与 `evidence_only`。外部写案例只复核账本与证据，不重新发送、付款或签核。详细案例与问题全景见 `../ai输出/ovo-真实任务资产库/README.md` 和 `../ai输出/ovo-真实任务资产库/INCIDENTS.md`。

`golden_script` 用于已经人工审查过的真实任务重放器。注册表给出 `script`、`inputs` 和 argv；`--cli`、`--inputs`、`--ocr-source` 的相对路径跟随案例工作区根目录，`{run_dir}` 指向隔离运行目录。脚本必须输出结果 JSON，且不能声明外部写；它不是执行原始会话文本或下载脚本的通道。

### 独立安装与案例工作区

```bash
python3 -m pip wheel --no-deps --no-build-isolation .
python3 -m venv /tmp/ovo-case-venv
/tmp/ovo-case-venv/bin/pip install --no-deps dist/ovo_acceptance-0.3.1rc1-py3-none-any.whl
cd /path/to/case-workspace
OVO_CASE_REGISTRY=/path/to/case-workspace/cases.jsonl \
  /tmp/ovo-case-venv/bin/ovo-acceptance case validate
OVO_CASE_REGISTRY=/path/to/case-workspace/cases.jsonl \
  /tmp/ovo-case-venv/bin/ovo-acceptance case replay CASE-ID --run-root runs
```

wheel 包含校验器和合同，不复制整个家族证据库。自定义注册表默认以当前目录为证据根；家族工作区也可用 `OVO_CASE_ROOT` 显式指定。完整重放写入临时 `--run-root`，跑完只把 `summary.json` 归档到 `ai输出/ovo-真实任务资产库/runs/verification-<时间戳>/` 并删除副本，不直接指向资产库 `runs/`。默认家族注册表仍是本机增强能力，不冒充所有证据都能随 wheel 携带。

退出码：`0` 通过，`1` 校验失败，`2` 文件读不到或用法错误。

`publish` 不是上传：它只在本地新目录生成 `bundle.json`、`template.json`、`index.html` 和 `share.json`。公开投影默认遮蔽目标、交付说明、验收标准、备注、人员身份、工具／供应商名、输入输出路径及嵌套上下文；只保留结构 ID、枚举状态、时间、计数和证据哈希，用可重复的匿名占位符维持跨记录引用，不复制源文件。只有 `synthetic` 或已经具名授权的 `public-redacted` 包可以生成，CLI 指定的具名发布人只保留在 `share.json` 和查看页。默认私有材料不能直接发布；这不是启发式 PII 检测或全面脱敏认证。公开重放检查的是合同结构、证据引用与验收记录，不证明市场需求、普遍能力或业务结果。

## 判定语义

| 总体结论 | 含义 |
| --- | --- |
| `PASS` | 所有 deliverable 都 ACCEPTED，且无契约错误 |
| `PASS_WITH_GAP` | 有差距，但每处差距都有署名的 `accept_with_gap` 和下一步动作 |
| `BLOCKED` | 有 `UNPROVEN` 未升级、或有 deliverable 没有验收记录 |
| `FAIL` | 有 `FAIL` 且结论落到 `stop`，或关键验收失败未处理 |
| `INVALID` | 文档本身不合契约，先修文档再谈验收 |

`ok` 只在无错误且结论为 `PASS` / `PASS_WITH_GAP` 时为真。`PASS_WITH_GAP` 不能被当成完整通过。

## 与三个产品的接口

- **Askovo**：`askovo proof export STUDY --out NEW_DIR --by NAME` 只读投影 Decision Brief；源 study 保持不变，P3 语义复核与 P4 外部采用默认 `UNCHECKED`。
- **Growovo**：`mkt --workspace DATA proof export RUN --out NEW_DIR --by NAME` 只读操作账本与产品事件；committed 只进 P0，完整独立回读进 P2，外部事件进 P4，私密目标与正文不复制。
- **Verovo**：`verovo proof export --bundle PERIOD --out NEW_DIR --by NAME` 导出 canonical 账期证明；`verovo proof replay NEW_DIR --bundle PERIOD` 重核输入并重算输出，变化输入返回 `EXPIRED`。

三产品导出器都只读 canonical 事实源，不搬运彼此业务词表；共同校验器检查证明形状，不把结构合格升级为市场需求、普遍能力、业务结果或因果。

本目录只约定形状，不搬运任何一个产品的业务词表；各自的语义正本仍在原仓库。
