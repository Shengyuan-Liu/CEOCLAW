"""
JSON 解析辅助工具
提供更鲁棒的 JSON 解析功能，处理常见的格式问题
"""
import json
import re
import logging

logger = logging.getLogger(__name__)


def robust_json_parse(text: str, fallback=None) -> dict:
    """
    鲁棒的 JSON 解析函数

    Args:
        text: 要解析的文本（可能包含 JSON）
        fallback: 解析失败时的默认返回值

    Returns:
        解析后的字典，或 fallback 值

    Raises:
        ValueError: 如果所有解析尝试都失败且没有提供 fallback
    """
    if not text:
        if fallback is not None:
            return fallback
        raise ValueError("Empty text provided")

    # 如果已经是字典，直接返回
    if isinstance(text, dict):
        return text

    # 清理文本，移除 markdown 代码块标记
    text = text.strip()
    if text.startswith('```json'):
        text = text[7:]
    elif text.startswith('```'):
        text = text[3:]
    if text.endswith('```'):
        text = text[:-3]
    text = text.strip()

    # 提取 JSON 部分
    start_idx = text.find('{')
    end_idx = text.rfind('}')

    if start_idx == -1 or end_idx == -1 or start_idx >= end_idx:
        if fallback is not None:
            logger.warning("No JSON found in text, using fallback")
            return fallback
        raise ValueError("No JSON found in response")

    json_str = text[start_idx:end_idx+1]

    # 尝试1: 直接解析
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"Direct JSON parse failed: {e}")
        error_pos = getattr(e, 'pos', 0)
        start = max(0, error_pos - 50)
        end = min(len(json_str), error_pos + 50)
        logger.warning(f"Error context: ...{json_str[start:end]}...")

    # 尝试2: 移除控制字符后解析
    try:
        json_str_cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str)
        result = json.loads(json_str_cleaned)
        logger.info("JSON parsed successfully after removing control characters")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed after cleaning: {e}")

    # 尝试3: 修复引号问题
    try:
        json_str_fixed = re.sub(r"'([^']*)'(\s*:\s*)", r'"\1"\2', json_str)  # 键名
        json_str_fixed = re.sub(r':\s*\'([^\']*)\'', r': "\1"', json_str_fixed)  # 字符串值
        result = json.loads(json_str_fixed)
        logger.info("JSON parsed successfully after fixing quotes")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed after fixing quotes: {e}")

    # 尝试4: 修复常见的尾部逗号问题
    try:
        json_str_fixed = re.sub(r',(\s*[}\]])', r'\1', json_str)
        result = json.loads(json_str_fixed)
        logger.info("JSON parsed successfully after removing trailing commas")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed after removing trailing commas: {e}")

    # 尝试5: 修复未转义的换行符（只在字符串值内部）
    try:
        def escape_newlines_in_strings(s):
            """只转义字符串值中的换行符，不影响 JSON 结构"""
            result = []
            in_string = False
            escape_next = False

            for i, char in enumerate(s):
                if escape_next:
                    result.append(char)
                    escape_next = False
                    continue

                if char == '\\':
                    result.append(char)
                    escape_next = True
                    continue

                if char == '"':
                    in_string = not in_string
                    result.append(char)
                    continue

                if in_string and char in ('\n', '\r', '\t'):
                    if char == '\n':
                        result.append('\\n')
                    elif char == '\r':
                        result.append('\\r')
                    elif char == '\t':
                        result.append('\\t')
                else:
                    result.append(char)

            return ''.join(result)

        json_str_fixed = escape_newlines_in_strings(json_str)
        result = json.loads(json_str_fixed)
        logger.info("JSON parsed successfully after smart escaping")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed after smart escaping: {e}")

    # 尝试6: 使用 json5 或其他宽松解析器（如果可用）
    try:
        import json5
        result = json5.loads(json_str)
        logger.info("JSON parsed successfully using json5")
        return result
    except ImportError:
        logger.debug("json5 not available")
    except Exception as e:
        logger.warning(f"JSON5 parse failed: {e}")

    # 所有尝试都失败
    logger.error(f"All JSON parsing attempts failed. Full JSON:\n{json_str}")

    if fallback is not None:
        logger.warning("Using fallback value")
        return fallback

    raise ValueError(f"Failed to parse JSON after all attempts. Last error: {e}")


async def robust_json_parse_with_llm(text: str, model, fallback=None) -> dict:
    """
    鲁棒的 JSON 解析：先尝试常规解析，全部失败后用 LLM 修复 JSON 格式。

    Args:
        text: 要解析的文本
        model: LLM model 对象（可调用，支持 async）
        fallback: 最终兜底的默认返回值

    Returns:
        解析后的字典
    """
    # 先尝试常规的 6 层解析
    try:
        return robust_json_parse(text, fallback=None)
    except (ValueError, Exception) as e:
        logger.warning(f"All regular JSON parsing failed, attempting LLM repair: {e}")

    # 提取原始 JSON 部分用于修复
    raw = text.strip()
    if raw.startswith('```json'):
        raw = raw[7:]
    elif raw.startswith('```'):
        raw = raw[3:]
    if raw.endswith('```'):
        raw = raw[:-3]
    raw = raw.strip()

    start_idx = raw.find('{')
    end_idx = raw.rfind('}')
    if start_idx != -1 and end_idx > start_idx:
        raw = raw[start_idx:end_idx + 1]

    # 截断过长文本，避免超出 LLM context
    if len(raw) > 12000:
        raw = raw[:12000] + "\n... (truncated)"

    repair_prompt = f"""以下是一段格式有错误的 JSON 文本，请修复其中的语法错误并输出**正确的 JSON**。

常见的错误包括：缺少引号、多余逗号、未闭合的字符串、非法字符等。
你只需要输出修复后的纯 JSON，不要添加任何解释、markdown标记或其他内容。

有错误的 JSON:
{raw}"""

    try:
        response = await model([{"role": "user", "content": repair_prompt}])

        repaired_text = await extract_json_from_async_response(response)

        # 清理 LLM 输出
        repaired_text = repaired_text.strip()
        if repaired_text.startswith('```json'):
            repaired_text = repaired_text[7:]
        elif repaired_text.startswith('```'):
            repaired_text = repaired_text[3:]
        if repaired_text.endswith('```'):
            repaired_text = repaired_text[:-3]
        repaired_text = repaired_text.strip()

        s = repaired_text.find('{')
        e = repaired_text.rfind('}')
        if s != -1 and e > s:
            repaired_text = repaired_text[s:e + 1]

        result = json.loads(repaired_text)
        logger.info("JSON parsed successfully after LLM repair")
        return result

    except Exception as repair_err:
        logger.error(f"LLM JSON repair also failed: {repair_err}")

    if fallback is not None:
        return fallback
    raise ValueError(f"Failed to parse JSON even after LLM repair")


def extract_json_from_response(response, field_name="content") -> str:
    """
    从各种响应格式中提取 JSON 字符串

    Args:
        response: 模型响应（可能是异步生成器、字典、字符串等）
        field_name: 要提取的字段名

    Returns:
        提取的文本内容
    """
    text = ""

    # 处理不同的响应格式
    if hasattr(response, 'text'):
        text = response.text
    elif hasattr(response, field_name):
        content = getattr(response, field_name)
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get('type') == 'text':
                    text = item.get('text', '')
                    break
    elif isinstance(response, dict) and field_name in response:
        text = response[field_name]
    elif isinstance(response, str):
        text = response
    else:
        text = str(response) if response else ""

    return text


async def extract_json_from_async_response(response, field_name="content") -> str:
    """
    从异步响应中提取 JSON 字符串

    Args:
        response: 模型响应（可能是异步生成器）
        field_name: 要提取的字段名

    Returns:
        提取的文本内容
    """
    text = ""

    # 处理异步生成器
    if hasattr(response, '__aiter__'):
        async for chunk in response:
            if isinstance(chunk, str):
                text = chunk
            elif hasattr(chunk, field_name):
                content = getattr(chunk, field_name)
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get('type') == 'text':
                            text = item.get('text', '')
    else:
        # 非异步响应，使用同步方法
        text = extract_json_from_response(response, field_name)

    return text
