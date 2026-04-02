#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ResearchAgent 调研智能体测试

测试内容：
1. Tavily 搜索 + LLM 总结的完整流程
2. 不同类型的调研 query（市场调研、竞品分析、创意验证）
3. 输入格式兼容性（纯文本 vs JSON 格式）
4. 空输入的容错处理
5. 结果结构校验
"""
import asyncio
import sys
import os
import json

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from agentscope.model import OpenAIChatModel
from agentscope.message import Msg
from config_agentscope import init_agentscope
from config import LLM_CONFIG


def create_model():
    """创建 LLM model 实例"""
    return OpenAIChatModel(
        model_name=LLM_CONFIG["model_name"],
        api_key=LLM_CONFIG["api_key"],
        client_kwargs={"base_url": LLM_CONFIG["base_url"], "timeout": 60},
        temperature=LLM_CONFIG.get("temperature", 0.7),
        max_tokens=LLM_CONFIG.get("max_tokens", 2000),
    )


def create_agent(model):
    """创建 ResearchAgent 实例"""
    from importlib.util import spec_from_file_location, module_from_spec
    agent_path = os.path.join(project_root, ".claude/skills/research/script/agent.py")
    spec = spec_from_file_location("research_agent", agent_path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ResearchAgent(name="ResearchAgent", model=model)


def validate_result_structure(data: dict) -> list:
    """校验结果的数据结构，返回错误列表"""
    errors = []
    if "status" not in data:
        errors.append("缺少 status 字段")
    if "findings" not in data:
        errors.append("缺少 findings 字段")
    if "results" not in data:
        errors.append("缺少 results 字段")

    if data.get("status") == "success":
        results = data.get("results", {})
        if "summary" not in results:
            errors.append("成功状态下缺少 results.summary")
        if "sources" not in results:
            errors.append("成功状态下缺少 results.sources")
        else:
            sources = results["sources"]
            if not isinstance(sources, list) or len(sources) == 0:
                errors.append("sources 应为非空列表")
            else:
                first = sources[0]
                for field in ["title", "url", "snippet", "score"]:
                    if field not in first:
                        errors.append(f"source 缺少 {field} 字段")
    return errors


async def test_basic_search(agent):
    """测试1: 基本搜索功能（纯文本输入）"""
    print("\n=== 测试1: 基本搜索（纯文本输入） ===")
    msg = Msg(name="user", content="2024年全球AI市场规模和增长趋势", role="user")
    result = await agent.reply(msg)
    data = json.loads(result.content)

    errors = validate_result_structure(data)
    status = data.get("status")
    print(f"  状态: {status}")

    if status == "success":
        sources = data["results"].get("sources", [])
        print(f"  搜索结果数: {len(sources)}")
        print(f"  摘要长度: {len(data.get('findings', ''))} 字符")
        for s in sources[:2]:
            print(f"  - [{s.get('score', 'N/A'):.2f}] {s.get('title', '')[:50]}")

    if errors:
        print(f"  ✗ 结构校验失败: {errors}")
        return False

    print("  ✓ 通过")
    return True


async def test_json_input(agent):
    """测试2: JSON 格式输入（模拟 OrchestrationAgent 的调用方式）"""
    print("\n=== 测试2: JSON 格式输入（模拟编排器调用） ===")
    input_data = {
        "context": {
            "rewritten_query": "待办事项应用市场竞品分析 Todoist TickTick",
            "intents": [{"type": "research", "confidence": 0.9}],
            "key_entities": {"industry": "生产力工具", "product_type": "To-Do App"}
        },
        "reason": "需要了解竞品格局",
        "expected_output": "竞品分析报告",
        "previous_results": []
    }
    msg = Msg(name="Orchestrator", content=json.dumps(input_data, ensure_ascii=False), role="user")
    result = await agent.reply(msg)
    data = json.loads(result.content)

    errors = validate_result_structure(data)
    status = data.get("status")
    print(f"  状态: {status}")

    if status == "success":
        findings = data.get("findings", "")
        print(f"  摘要长度: {len(findings)} 字符")
        print(f"  摘要预览: {findings[:100]}...")

    if errors:
        print(f"  ✗ 结构校验失败: {errors}")
        return False

    print("  ✓ 通过")
    return True


async def test_null_input(agent):
    """测试3: 空输入容错"""
    print("\n=== 测试3: 空输入容错 ===")
    result = await agent.reply(None)
    data = json.loads(result.content)

    if data.get("query_success") is False:
        print("  ✓ 通过 (正确返回 query_success=False)")
        return True
    else:
        print(f"  ✗ 未通过，返回: {data}")
        return False


async def test_competitor_analysis(agent):
    """测试4: 竞品分析场景"""
    print("\n=== 测试4: 竞品分析场景 ===")
    msg = Msg(name="user", content="分析Notion和Obsidian的功能差异和市场定位", role="user")
    result = await agent.reply(msg)
    data = json.loads(result.content)

    errors = validate_result_structure(data)
    status = data.get("status")
    print(f"  状态: {status}")

    if status == "success":
        sources = data["results"].get("sources", [])
        print(f"  搜索结果数: {len(sources)}")
        # 检查搜索结果相关性分数
        scores = [s.get("score", 0) for s in sources]
        avg_score = sum(scores) / len(scores) if scores else 0
        print(f"  平均相关性分数: {avg_score:.2f}")
        if avg_score < 0.3:
            print("  ⚠ 相关性分数偏低")

    if errors:
        print(f"  ✗ 结构校验失败: {errors}")
        return False

    print("  ✓ 通过")
    return True


async def test_idea_validation(agent):
    """测试5: 创意验证场景"""
    print("\n=== 测试5: 创意验证场景 ===")
    msg = Msg(name="user", content="面向远程团队的异步视频沟通工具是否有市场需求", role="user")
    result = await agent.reply(msg)
    data = json.loads(result.content)

    errors = validate_result_structure(data)
    status = data.get("status")
    print(f"  状态: {status}")

    if status == "success":
        findings = data.get("findings", "")
        has_substance = len(findings) > 100
        print(f"  摘要长度: {len(findings)} 字符")
        if not has_substance:
            print("  ⚠ 摘要内容过短")

    if errors:
        print(f"  ✗ 结构校验失败: {errors}")
        return False

    print("  ✓ 通过")
    return True


async def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("ResearchAgent 测试套件")
    print("=" * 60)

    init_agentscope()
    model = create_model()
    agent = create_agent(model)

    # 检查 Tavily 是否可用
    if agent.tavily_client is None:
        print("\n⚠ Tavily 未配置，部分测试可能返回 error 状态")

    tests = [
        ("基本搜索", test_basic_search),
        ("JSON格式输入", test_json_input),
        ("空输入容错", test_null_input),
        ("竞品分析", test_competitor_analysis),
        ("创意验证", test_idea_validation),
    ]

    passed = 0
    total = len(tests)

    for name, test_fn in tests:
        try:
            success = await test_fn(agent)
            if success:
                passed += 1
        except Exception as e:
            print(f"  ✗ 异常: {e}")

    print("\n" + "=" * 60)
    print(f"结果: {passed}/{total} 通过")
    print("=" * 60)

    return passed == total


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
