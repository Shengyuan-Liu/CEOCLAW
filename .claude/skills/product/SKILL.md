---
name: product
description: Use this skill when the user needs product strategy, feature planning, product iteration, or pricing/UX updates. Triggers when user says "产品规划", "功能设计", "产品迭代", "定价策略". This skill uses ProductAgent for product planning via LLM.
---

# Product (产品规划)

生成**产品策略**、**功能规划**、**产品迭代方案**、**定价和UX优化**等，使用 **ProductAgent**。

## When to Use

- 用户说「产品规划」「功能设计」「产品迭代」「定价策略」等
- 需要产品方向和功能规划时

## Agent

- **ProductAgent** (`script/agent.py`)
- 入参为 **model 对象**
- **异步**：`reply()` 为 `async`

## 返回格式

- `product_plan`: 产品规划详情
- `features`: 功能列表
- `roadmap`: 产品路线图

## 产品规划指南

【核心原则】
1. 产品规划要基于市场需求和用户痛点
2. 功能规划要有优先级排序（MVP优先）
3. 考虑技术可行性和资源约束
4. 提供清晰的产品路线图

【输出格式】(严格JSON)
{{
    "product_plan": {{
        "name": "产品名称",
        "vision": "产品愿景",
        "target_users": "目标用户",
        "core_value": "核心价值主张",
        "features": [
            {{
                "name": "功能名",
                "priority": "P0/P1/P2",
                "description": "功能描述",
                "effort": "开发工作量估算"
            }}
        ],
        "roadmap": [
            {{
                "phase": "MVP",
                "timeline": "2周",
                "deliverables": ["交付物1", "交付物2"]
            }}
        ],
        "tech_stack": "建议技术栈",
        "pricing": "定价策略"
    }}
}}
