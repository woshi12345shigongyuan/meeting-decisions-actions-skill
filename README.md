# meeting-decisions-actions

一个 Agent Skill：把会议纪要、语音转写或群聊记录，整理成「定了什么、谁做什么、什么时候交、还有什么没定」。

```text
meeting-decisions-actions/
├── SKILL.md                  # 技能定义：触发条件、提取规则、输出格式
├── scripts/
│   └── extract_check.py      # 结构与证据校验脚本（仅标准库）
└── examples/
    ├── sample_notes.md       # 示例会议纪要
    └── sample_output.json    # 对应的结构化输出
```

## 做什么

输出两部分：

1. **结构化 JSON** — `meeting`（主题/日期/参会人）、`summary`（≤3 句）、`decisions`、`action_items`（负责人、截止日期、优先级）、`risks`、`open_questions`，每条都带 `evidence` 原文依据。
2. **Markdown 清单** — 会议概要、决策表、待办表、风险与待解决表，以及一节「说明」列出未指定项、日期换算假设与未核实信息。

## 为什么不一样

- **可追溯**：每条结论都要求逐字引用原文，方便复核「会上到底说没说」。
- **不编造**：负责人与截止日期只在原文明确时填写，否则一律「未指定」。不根据部门职责猜人，不把「下周」擅自换算成具体日期。
- **可机器校验**：`scripts/extract_check.py` 检查 JSON 结构、编号与日期格式，并在提供原文时逐条核对 `evidence` 是否为原文的连续片段。

## 本地校验

需要 Python 3.8+，无第三方依赖：

```bash
cd meeting-decisions-actions
python scripts/extract_check.py examples/sample_output.json --notes examples/sample_notes.md --strict
```

预期输出：

```text
[OK] JSON 结构可解析，共 8 条：决策 3 / 待办 3 / 风险 1 / 待解决问题 1
[OK] 证据核对：8/8 条 evidence 可在原文定位
[INFO] 未指定负责人 0 条；未指定截止日期 1 条（允许，需在说明中列出）
结果：通过（0 错误，0 个警告）
```

退出码：`0` 通过，`1` 校验失败，`2` 文件或 JSON 解析错误。

## 说明

示例纪要与输出均为虚构，人名、日期、项目内容不指向真实组织。Skill 本身不联网、不调用外部 API，校验脚本仅使用 Python 标准库。
