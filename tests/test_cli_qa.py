#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CEOClaw CLI 端到端集成测试
"""
import asyncio
import sys
import os
import json

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from agentscope.model import OpenAIChatModel
from config_agentscope import init_agentscope
from config import LLM_CONFIG
from context.memory_manager import MemoryManager
from agents.intention_agent import IntentionAgent
from agents.orchestration_agent import OrchestrationAgent
from agents.lazy_agent_registry import LazyAgentRegistry
from agentscope.message import Msg


async def test_intention_recognition():
    """测试意图识别"""
    print("=" * 60)
    print("测试1: 意图识别")
    print("=" * 60)

    init_agentscope()
    model = OpenAIChatModel(
        model_name=LLM_CONFIG["model_name"],
        api_key=LLM_CONFIG["api_key"],
        client_kwargs={"base_url": LLM_CONFIG["base_url"], "timeout": 60},
        temperature=LLM_CONFIG.get("temperature", 0.7),
        max_tokens=LLM_CONFIG.get("max_tokens", 2000),
    )

    agent = IntentionAgent(name="IntentionAgent", model=model)

    test_queries = [
        "帮我调研一下AI教育市场",
        "制定一个B2B SaaS的营销策略",
        "做一个产品规划方案",
    ]

    for query in test_queries:
        print(f"\n输入: {query}")
        msg = Msg(name="user", content=query, role="user")
        result = await agent.reply(msg)
        data = json.loads(result.content)
        intents = data.get("intents", [])
        schedule = data.get("agent_schedule", [])
        print(f"意图: {[i['type'] for i in intents]}")
        print(f"调度: {[s['agent_name'] for s in schedule]}")
        print(f"✓ 通过")

    print("\n意图识别测试完成！")


async def test_full_pipeline():
    """测试完整流水线"""
    print("\n" + "=" * 60)
    print("测试2: 完整流水线")
    print("=" * 60)

    init_agentscope()
    model = OpenAIChatModel(
        model_name=LLM_CONFIG["model_name"],
        api_key=LLM_CONFIG["api_key"],
        client_kwargs={"base_url": LLM_CONFIG["base_url"], "timeout": 60},
        temperature=LLM_CONFIG.get("temperature", 0.7),
        max_tokens=LLM_CONFIG.get("max_tokens", 2000),
    )

    memory_manager = MemoryManager(
        user_id="test_user",
        session_id="test_session",
        llm_model=model
    )

    intention_agent = IntentionAgent(name="IntentionAgent", model=model)

    agent_cache = {}
    lazy_registry = LazyAgentRegistry(
        model=model,
        cache=agent_cache,
        memory_manager=memory_manager
    )

    orchestrator = OrchestrationAgent(
        name="OrchestrationAgent",
        agent_registry=lazy_registry,
        memory_manager=memory_manager
    )

    # 测试查询
    query = "帮我调研一下AI教育市场"
    print(f"\n输入: {query}")

    msg = Msg(name="user", content=query, role="user")
    intention_result = await intention_agent.reply(msg)
    print(f"意图识别完成: {intention_result.content[:100]}...")

    orchestration_result = await orchestrator.reply(intention_result)
    result_data = json.loads(orchestration_result.content)
    print(f"执行状态: {result_data.get('status')}")
    print(f"执行智能体数: {result_data.get('agents_executed')}")

    for r in result_data.get("results", []):
        print(f"  - {r['agent_name']}: {r['status']}")

    print("\n完整流水线测试完成！")


if __name__ == "__main__":
    asyncio.run(test_intention_recognition())
    asyncio.run(test_full_pipeline())
    print("\n" + "=" * 60)
    print("所有测试完成！")
    print("=" * 60)
