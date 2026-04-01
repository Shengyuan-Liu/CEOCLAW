---
name: marketing
description: Use this skill when the user needs marketing strategy generation, campaign planning, SEO experiments, or virtual testing. Triggers when user says "制定营销策略", "营销方案", "推广计划", "SEO优化". This skill uses MarketingAgent for strategy generation via LLM.
---

# Marketing (营销策略)

生成**营销策略**、**推广方案**、**SEO实验设计**、**虚拟测试**等，使用 **MarketingAgent**。

## When to Use

- 用户说「制定营销策略」「推广方案」「SEO优化」等
- 需要市场推广相关的方案设计时

## Agent

- **MarketingAgent** (`script/agent.py`)
- 入参为 **model 对象**
- **异步**：`reply()` 为 `async`

## 返回格式

- `status`: `"success"` 或 `"error"`
- `strategy`: 营销策略详情
- `channels`: 推荐渠道列表
- `budget_estimate`: 预算估算

## 营销策略生成指南

【任务说明】
1. 根据产品特点和目标市场生成针对性的营销策略
2. 包含具体的渠道选择、内容策略、预算分配
3. 如果有调研数据支撑，结合数据给出建议
4. 策略要具有可执行性，包含时间线和优先级

【输出格式】(严格JSON)
{{
    "strategy": {{
        "title": "营销策略标题",
        "target_audience": "目标受众",
        "channels": ["渠道1", "渠道2"],
        "content_strategy": "内容策略描述",
        "timeline": "执行时间线",
        "budget_estimate": "预算估算",
        "kpis": ["KPI1", "KPI2"]
    }},
    "action_items": [
        {{
            "action": "具体行动",
            "priority": "高/中/低",
            "timeline": "执行时间"
        }}
    ]
}}
