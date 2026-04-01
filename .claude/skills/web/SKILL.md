---
name: web
description: Use this skill when the user needs landing page generation, web product creation, or deployment artifacts. Triggers when user says "做落地页", "生成网页", "Web产品", "部署页面". This skill uses WebAgent to generate a Lovable URL that auto-creates the landing page.
---

# Web (Web部署)

生成**落地页**、**简单Web产品**、**部署方案**等，使用 **WebAgent** 通过 Lovable Build-with-URL 自动生成。

## When to Use

- 用户说「做一个落地页」「生成网页」「Web产品」等
- 需要Web相关的产出物时

## Agent

- **WebAgent** (`script/agent.py`)
- 入参为 **model 对象**
- **异步**：`reply()` 为 `async`

## 工作流程

1. 收集上游 agent 的产品/营销信息
2. 让 LLM 生成一段详细的 Lovable prompt（纯文本，非HTML）
3. 将 prompt 编码进 Lovable URL：`https://lovable.dev/?autosubmit=true#prompt=...`
4. 用户点击链接后，Lovable 自动生成并部署落地页

## 返回格式

- `status`: `"success"` 或 `"error"`
- `lovable_url`: Lovable 自动生成链接（用户点击即可）
- `lovable_prompt`: 生成落地页的详细 prompt
- `deployment`: 部署方案说明

## Lovable Prompt 生成指南

【任务说明】
1. 基于产品信息生成给 Lovable 的详细 prompt
2. prompt 应描述：页面结构、设计风格、配色、各section内容、CTA按钮
3. 融入已有的产品名、功能、定价、目标用户等信息
4. 输出纯文本 prompt，不是 HTML 或 JSON
5. 控制在 2000 字以内
