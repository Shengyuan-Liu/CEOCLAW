---
name: research
description: Use this skill when the user needs market research, competitor analysis, idea validation, or any research-heavy task. Triggers when user says "调研市场", "分析竞品", "验证想法", "研究一下XX". This skill uses ResearchAgent for automated research via Tavily search API.
---

# Research (市场调研)

执行**市场调研**、**竞品分析**、**创意验证**等研究密集型任务，使用 **ResearchAgent** 通过 Tavily Search API 获取实时数据。

## When to Use

- 用户说「调研一下XX市场」「分析竞品」「验证这个想法」等
- 其他智能体需要市场数据支撑决策时

## Agent

- **ResearchAgent** (`script/agent.py`)
- 入参为 **model 对象**（非 model_config_name）
- **异步**：`reply()` 为 `async`，需 `await`

## 返回格式

- `status`: `"success"` 或 `"error"`
- `findings`: 调研发现摘要
- `results.summary`: LLM 总结的调研报告
- `results.sources`: 数据来源列表（含 title, snippet, url, score）

## 调研生成指南

【回答要求】
1. 基于搜索结果进行专业的市场分析
2. 提供结构化的调研报告（市场规模、竞品、趋势、机会）
3. 如果信息不足，明确说明并给出建议的调研方向
4. 回答要客观、有数据支撑
