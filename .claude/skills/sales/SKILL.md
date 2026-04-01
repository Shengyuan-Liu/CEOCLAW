---
name: sales
description: Use this skill when the user needs customer discovery, prospect research, outreach generation, or lead qualification. Triggers when user says "找客户", "潜在客户", "销售线索", "客户拓展". This skill uses SalesAgent for sales execution support via LLM.
---

# Sales (销售执行)

执行**客户发现**、**潜在客户研究**、**外展方案生成**、**线索评估**等，使用 **SalesAgent**。

## When to Use

- 用户说「找客户」「潜在客户」「销售线索」「客户拓展」等

## Agent

- **SalesAgent** (`script/agent.py`)
- 入参为 **model 对象**
- **异步**：`reply()` 为 `async`

## 返回格式

- `status`: `"success"` 或 `"error"`
- `prospects`: 潜在客户列表
- `outreach_plan`: 外展方案

## 销售执行指南

【任务说明】
1. 基于产品特点和目标市场识别潜在客户画像
2. 提供具体的客户获取策略和渠道
3. 生成外展话术和邮件模板
4. 评估线索质量和优先级

【输出格式】(严格JSON)
{{
    "prospects": {{
        "target_profile": "目标客户画像",
        "channels": ["获客渠道1", "获客渠道2"],
        "potential_customers": [
            {{
                "type": "客户类型",
                "description": "客户描述",
                "approach": "接触方式"
            }}
        ]
    }},
    "outreach_plan": {{
        "email_template": "邮件模板",
        "pitch": "电梯演讲稿",
        "follow_up": "跟进策略"
    }}
}}
