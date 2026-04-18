# 技能加载器 (SkillLoader)

**源文件**: `utils/skill_loader.py`

## 概述

`SkillLoader` 是 CEOClaw **插件系统**的核心读取器——它扫描 `.claude/skills/*/SKILL.md`,解析 YAML frontmatter(元数据)和正文(指令内容),供两类消费者使用:

1. **IntentionAgent**: 只需要 frontmatter(`name` + `description`),用于构建意图识别 prompt 中可调度 agent 的描述清单(Progressive Disclosure)。
2. **Skill agent**(MarketingAgent / ProductAgent / ResearchAgent 等): 需要 SKILL.md 去掉 frontmatter 后的**正文**,作为 LLM prompt 的任务说明和输出格式要求。

这意味着:修改 SKILL.md 就能调整 agent 行为,无需改 Python 代码。

---

## SKILL.md 格式约定

每个 skill 目录(`.claude/skills/<name>/`)下都有一个 SKILL.md,结构:

```markdown
---
name: research
description: Use this skill when the user needs market research...
---

# Research (市场调研)

生成**调研报告**、**竞品分析**、**创意验证**等...

## 输出格式
(严格JSON)
{
    "findings": "...",
    "results": {...}
}
```

- frontmatter 用 `---` 包围,YAML 语法
- `name` 字段是内部 id(对应 intent type),`description` 供 LLM 判断何时触发
- frontmatter 之后的所有内容是"指令正文",通过 `get_skill_content` 读取

---

## 类: `SkillLoader`

### `__init__(self, skills_dir: str = ".claude/skills")`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `skills_dir` | `str` | `.claude/skills` | 相对**项目根目录**的 skills 目录路径 |

**路径解析**:

```python
current_file_path = os.path.abspath(__file__)                 # utils/skill_loader.py 的绝对路径
project_root = os.path.dirname(os.path.dirname(current_file_path))  # 项目根目录
self.skills_dir = os.path.join(project_root, skills_dir)
```

关键点:**不依赖 `cwd`**。无论从哪个目录运行 `python cli.py`,都能正确解析到 `<project>/.claude/skills`。

**内部状态**:
- `self.skills: Dict[str, Dict]` — 缓存已加载的 skill frontmatter,初始为空 dict。按需懒加载。

---

### `load_skills(self) -> Dict[str, Dict]`

扫描 `skills_dir`,解析所有 `*/SKILL.md` 的 frontmatter,填充 `self.skills`。

**返回结构**:

```python
{
    "research": {"name": "research", "description": "..."},
    "marketing": {"name": "marketing", "description": "..."},
    ...
}
```

**逻辑**:

1. 若 `skills_dir` 不存在 → 打印 warning 并返回 `{}`。**不抛异常**——允许项目在无 skills 时启动。
2. 遍历 `skills_dir` 下每个子目录,若包含 `SKILL.md` 就解析 frontmatter。
3. **key 取自 frontmatter 的 `name` 字段**;若缺失则 fallback 到目录名。
4. 失败的文件静默跳过(打印 error,但不中断)。

**注意**: 方法会**累积**到 `self.skills`,不会先清空。重复调用只会追加/覆盖,不会删除磁盘上已消失的 skill。

---

### `_parse_skill_md(self, file_path) -> Optional[Dict]`

解析单个 SKILL.md 的 YAML frontmatter。

**逻辑**:

1. 读文件全文
2. 若以 `---` 开头 → 找第二个 `---` 的位置(从索引 3 开始搜,跳过开头的三个连字符)
3. 取两个 `---` 之间的内容,用 `yaml.safe_load` 解析
4. 返回 dict;失败 / 无 frontmatter → 返回 `None`

**设计要点**:

- **手写 frontmatter 分隔**: 不用专门的 frontmatter 解析库(如 `python-frontmatter`),省一个依赖。代价是不支持"内容中有 `---` 分隔线"的极端情况——但 SKILL.md 的 YAML 区域不会有这种情况。
- **`yaml.safe_load` 而非 `yaml.load`**: 防止 YAML 反序列化注入任意 Python 对象。
- **只抽 frontmatter,不处理正文**: 正文由 `get_skill_content` 读取,职责分离。

---

### `get_skill_prompt(self, skill_mapping: Optional[Dict[str, str]] = None) -> str`

生成**可调度 agent 的描述清单**,注入 IntentionAgent 的 prompt。

**参数**:

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `skill_mapping` | `Optional[Dict[str,str]]` | `None` | skill name → intent name 的映射,支持把显示名替换成系统内部 id |

**输出示例**(无 mapping):

```
1. marketing - Use this skill when the user needs marketing strategy generation...

2. monitoring - Use this skill when the user needs performance tracking...

3. product - Use this skill when the user needs product strategy...

4. research - Use this skill when the user needs market research...

5. sales - Use this skill when the user needs customer discovery...

6. web - Use this skill when the user needs landing page generation...
```

**逻辑**:

1. 若 `self.skills` 为空 → 调 `load_skills()` 填充
2. 按 skill name **字母排序**(保证确定性,便于 prompt 缓存命中)
3. 对每个 skill,输出 `{index}. {display_name} - {description}`
4. **用空行分隔**(`\n\n`)——比单换行更清晰,避免 LLM 把多个 skill 描述看成一段

**设计要点**:

- **排序保证确定性**: Python 3.7+ dict 按插入序迭代,但文件系统的 `os.listdir` 顺序不保证。排序让相同的 skills 集总是生成相同的 prompt,利于 LLM 端的 prompt 缓存。
- **description 里的换行被压平**: `desc.replace("\n", " ")`——避免多行 description 破坏 `{index}. ...` 的编号结构。
- **`skill_mapping` 当前没用**: 代码里有它的参数,但 CEOClaw 实际调用时没传。保留是为了未来"skill 展示名"和"intent id"解耦的需求。

---

### `get_skill_content(self, skill_name: str) -> Optional[str]`

读取指定 skill 的 **SKILL.md 正文**(去除 frontmatter),供 skill agent 做 prompt 注入。

**参数**:

| 参数 | 类型 | 说明 |
|---|---|---|
| `skill_name` | `str` | skill 标识(通常就是目录名) |

**查找策略**(两级 fallback):

1. **目录名直接匹配**(快路径): 检查 `<skills_dir>/<skill_name>/SKILL.md` 是否存在
2. **frontmatter name 匹配**(慢路径): 遍历所有子目录,解析 frontmatter,`name == skill_name` 则匹配

**返回**:
- 成功: SKILL.md 去掉 frontmatter 后的字符串(已 `strip`)
- 任一步失败:`None`

**去除 frontmatter 逻辑**:

```python
if content.startswith('---'):
    end_idx = content.find('---', 3)
    if end_idx != -1:
        content = content[end_idx+3:].strip()
```

与 `_parse_skill_md` 对应——一个取 frontmatter,一个取剩余。

**设计要点**:

- **两级 fallback 的价值**: 大部分情况下目录名和 `name` 字段相同(`research/SKILL.md` 里 `name: research`),走快路径;但如果未来出现目录名和 name 不一致的 skill,慢路径也能找到。
- **`_parse_skill_md` 会被调用多次**: 慢路径里每个目录都会 parse 一次 frontmatter。若 skill 很多,有轻微重复开销。不过 SKILL.md 只有十几个,没必要优化。
- **正文不缓存**: 每次调用都重新读文件。允许开发时修改 SKILL.md 立即生效,无需重启。代价是每次 skill agent 调用都有一次小 I/O——可忽略。
- **错误不抛异常**: 文件读取失败只 `print` 不 raise,调用方拿到 `None` 自行降级(skill agent 会用"请根据用户需求生成XX"当默认指令)。

---

## 典型调用链

**IntentionAgent 启动时**:

```python
loader = SkillLoader()
skill_prompt = loader.get_skill_prompt()  # 触发 load_skills()
# skill_prompt 注入到 IntentionAgent 的 system prompt 的"可调度agent清单"部分
```

**MarketingAgent 每次 reply()**:

```python
self.skill_loader = SkillLoader()  # 每个 agent 持有自己的 loader 实例
skill_instruction = self.skill_loader.get_skill_content("marketing")
if not skill_instruction:
    skill_instruction = "默认指令..."
# 注入到发给 LLM 的 prompt 的"任务说明"部分
```

注意:每个 agent 都新建一个 `SkillLoader`,`self.skills` 各自缓存。这是小浪费但无正确性问题(yaml 解析本身快)。

---

## 与 Progressive Disclosure 模式的契合

SkillLoader 的双 API 设计(`get_skill_prompt` 只返回元数据,`get_skill_content` 才返回全文)完美契合**渐进式披露**:

| 层 | 调用 API | 信息量 | 时机 |
|---|---|---|---|
| L1 意图识别 | `get_skill_prompt()` | 只有 name + description(一行) | IntentionAgent 一次启动 |
| L2 具体执行 | `get_skill_content(name)` | 完整指令正文 | 被选中的 skill agent 每次 reply |

这样 IntentionAgent 的 prompt 不会因为 skill 的详细指令膨胀(即使有 20 个 skill,每个 skill 只贡献一行),而具体执行时又能拿到足够的上下文。

---

## 设计要点

- **插件热加载**: 正文不缓存 + 每次读盘,意味着编辑 SKILL.md 立即生效,不用重启 CLI。元数据缓存(`self.skills`)只在 `load_skills` / `get_skill_prompt` 时用,首次加载后不会重读 frontmatter。
- **路径锚定到项目根**: 用 `__file__` 定位项目根,而不是依赖 `os.getcwd()`。这让 CLI 无论在哪个目录执行都能找到 skills。
- **失败优先静默**: YAML 解析失败、文件读取失败都是 `print` 而不是抛异常。CEOClaw 希望"缺一个 skill 不影响其他 skill"的韧性。
- **`print` 而不是 `logger`**: 其他 utils 模块用 `logger`,本文件用 `print`——风格不一致。可能是早期代码残留。
- **字母排序的稳定性**: `get_skill_prompt` 里 `sorted(self.skills.items())` 保证输出顺序可复现。对 LLM prompt 缓存和调试都有帮助。
- **`load_skills` 累积不重置**: 重复调用会往 `self.skills` 追加,**不会**同步文件系统删除的 skill。对 CEOClaw 足够——进程运行期间 skill 集不变。若未来需要"热删除"一个 skill,需要额外清理逻辑。
