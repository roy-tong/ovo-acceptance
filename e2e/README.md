# 独立 Agent 真实任务验收

`cases.json` 预登记 Askovo、Growovo、Verovo 各三类核心任务。当前状态是 `NOT_RUN`；2026-11-20 的 18 场会话使用合成输入和 dry-run，保留为缺陷证据，不计入这九类真实任务通过数。

每个 `case_id` 至少运行两次全新会话：

- `arm: product`：Agent 自行发现、安装或连接对应 OVO 产品并交付。
- `arm: baseline`：另一个未安装 OVO 的通用 Agent 完成同一任务。

两边只给自然语言意图和用户合法持有、授权使用的相同材料，不给命令、预期调用链或答案。保存原始会话、工具轨迹、授权与外部回执、最终交付物、人工验收和缺陷编号。人工分钟与费用缺失时保持未知，不填 0。

运行记录使用 `contracts/agent-e2e-run.schema.json`；示例 `examples/agent-e2e-refusal.json` 只是合成输入下合理拒绝的格式示例，不是产品成绩。校验器会拒绝以下记录：

- 合成或 demo 输入标成 `REAL_SUCCESS`；
- 没有具名人工验收或最终交付物的成功；
- Growovo 没有独立外部结果与平台回执的成功；
- 仍带开放缺陷编号的成功；
- 没有缺陷编号的 `INCORRECT_DELIVERY`。

```bash
cd ovo-acceptance
python3 -m ovo_acceptance validate examples/agent-e2e-refusal.json
python3 -m unittest tests.test_agent_e2e -v
```

私密原始会话和买方材料不进入公开 Proof Bundle。公开分享仍走现有 `publish` 的 `synthetic` 或具名授权 `public-redacted` 分类。

完成弱/强模型四臂运行后，可用 `python3 -m ovo_acceptance model-upgrade examples/valid-model-upgrade.json --json` 计算 OVO 增益是否放大。比较器要求唯一运行和证据引用、同任务/输入/授权/验收/预算；单任务 `amplified / stable / diminishing` 是描述性结果，不替代这些真实 E2E 验收或因果分析。

用 `python3 -m ovo_acceptance experience examples/experience-summary.json --json` 汇总低人工干预有效交付率。分母保留全部真实已开始任务；人工上限、独立耗时和 11 类失败按 run/case 登记，缺数据不进入低人工分子。

用 `python3 -m ovo_acceptance host-matrix examples/host-compatibility.json --json` 汇总 Skill/CLI/MCP、高阶任务、文件访问、恢复、后台能力和自然语言交付。实测状态必须引用运行与证据；能力探测、未测和不支持分别记录。矩阵不执行新测试，示例的 `INCOMPLETE` 不是宿主实测失败，也不是真实 L3 通过。
