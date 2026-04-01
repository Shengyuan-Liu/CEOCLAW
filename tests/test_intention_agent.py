#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
IntentionAgent 意图识别测试
"""
import asyncio
import sys
import os
import json

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from agentscope.model import OpenAIChatModel
from config_agentscope import init_agentscope
from config import LLM_CONFIG
from agents.intention_agent import IntentionAgent
from agentscope.message import Msg


async def test_intent_types():
    """测试各种意图类型的识别"""
    init_agentscope()
    model = OpenAIChatModel(
        model_name=LLM_CONFIG["model_name"],
        api_key=LLM_CONFIG["api_key"],
        client_kwargs={"base_url": LLM_CONFIG["base_url"], "timeout": 60},
        temperature=LLM_CONFIG.get("temperature", 0.7),
        max_tokens=LLM_CONFIG.get("max_tokens", 2000),
    )

    agent = IntentionAgent(name="IntentionAgent", model=model)

    test_cases = [
        ("帮我调研一下AI教育市场", "research"),
        ("制定一个营销推广方案", "marketing"),
        ("做一个产品规划", "product"),
        ("帮我找一些潜在客户", "sales"),
        ("看看最近的数据表现", "monitoring"),
        ("做一个产品落地页", "web"),
    ]

    passed = 0
    total = len(test_cases)

    for query, expected_intent in test_cases:
        print(f"\n测试: {query}")
        print(f"期望意图: {expected_intent}")

        msg = Msg(name="user", content=query, role="user")
        result = await agent.reply(msg)
        data = json.loads(result.content)

        intents = data.get("intents", [])
        intent_types = [i["type"] for i in intents]
        schedule = data.get("agent_schedule", [])
        schedule_names = [s["agent_name"] for s in schedule]

        print(f"识别意图: {intent_types}")
        print(f"调度计划: {schedule_names}")

        if expected_intent in intent_types or expected_intent in schedule_names:
            print("✓ 通过")
            passed += 1
        else:
            print("✗ 未通过")

    print(f"\n结果: {passed}/{total} 通过")
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(test_intent_types())
    sys.exit(0 if success else 1)
