#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
OrchestrationAgent 协调器测试
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
from context.memory_manager import MemoryManager
from agents.intention_agent import IntentionAgent
from agents.orchestration_agent import OrchestrationAgent
from agents.lazy_agent_registry import LazyAgentRegistry
from agentscope.message import Msg


async def test_orchestration():
    """测试协调器调度"""
    print("=" * 60)
    print("协调器调度测试")
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

    test_queries = [
        "帮我调研一下在线教育市场",
        "帮我做一个SaaS产品的营销方案",
    ]

    for query in test_queries:
        print(f"\n输入: {query}")

        msg = Msg(name="user", content=query, role="user")
        intention_result = await intention_agent.reply(msg)

        intention_data = json.loads(intention_result.content)
        schedule = intention_data.get("agent_schedule", [])
        print(f"调度计划: {[s['agent_name'] for s in schedule]}")

        result = await orchestrator.reply(intention_result)
        result_data = json.loads(result.content)

        print(f"执行状态: {result_data.get('status')}")
        for r in result_data.get("results", []):
            print(f"  - {r['agent_name']}: {r['status']}")

    print("\n协调器测试完成！")


if __name__ == "__main__":
    asyncio.run(test_orchestration())
