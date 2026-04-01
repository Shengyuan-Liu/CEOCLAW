---
name: monitoring
description: Use this skill when the user needs performance tracking, KPI analysis, traffic/signup/revenue monitoring, or ROI analysis. Triggers when user says "看数据", "分析表现", "监控指标", "ROI分析". This skill uses MonitoringAgent for business metrics analysis via LLM.
---

# Monitoring (绩效监控)

追踪和分析**业务指标**（流量、注册、收入、ROI、漏斗转化）等，使用 **MonitoringAgent**。

## When to Use

- 用户说「看看数据表现」「分析ROI」「监控指标」等

## Agent

- **MonitoringAgent** (`script/agent.py`)
- 入参为 **model 对象**、**memory_manager**（用于读取历史数据）
- **异步**：`reply()` 为 `async`

## 返回格式

- `status`: `"success"` 或 `"error"`
- `metrics`: 指标数据
- `analysis`: 分析结论
- `recommendations`: 建议

## 监控分析指南

【回答要求】
1. 基于已有数据提供客观的绩效分析
2. 识别趋势和异常
3. 给出可操作的改进建议
4. 如果没有足够数据，说明需要监控哪些指标
