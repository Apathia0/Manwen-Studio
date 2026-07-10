import asyncio
import contextvars
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator

import httpx

from database import SessionLocal
from models import AgentPendingChange, Chapter, ChapterVideoShot, ChapterVideoWorkflow, DeconstructionResult, Story, VideoAsset
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from services import deepseek as _deepseek_service
from services.writing_utils import (
    get_banned_words,
    get_banned_patterns,
    get_quality_checklist,
)
from services.deepseek import (
    _deepseek_auth_headers,
    _build_story_snapshot_tiered,
    adjust_framework_with_chat,
    adjust_chapter_content,
    build_agent_chapter_system_prompt,
    expand_chapter_to_content,
)
from services.chapter_quality import finalize_generated_chapter_content, format_quality_gate_detail
from services.prompt_template import get_effective_prompt
from services.story_state import build_story_bible_compact, build_story_memory_compact
from services.framework_utils import (
    _build_current_snapshot_data,
    _build_outline_compact,
    _enforce_framework_snapshot_limit,
    _extract_outline_chapters,
    _merge_framework_outline,
    _normalize_characters_payload,
    _normalize_framework_outline,
    _save_framework_snapshot,
    apply_framework_operations,
)


# ── 待确认修改追踪 ──────────────────────────────────────


@dataclass
class PendingChange:
    """单次修改的快照记录，用于确认或撤回。"""
    type: str  # "chapter" | "story" | "scenes_file" | "story_bible" | "video_shot" | "video_workflow"
    record_id: int
    display_name: str  # 用户可读的名称，如"第1章"
    field: str  # 修改的字段名，如"novel_content"
    old_value: Any
    new_value: Any

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "record_id": self.record_id,
            "display_name": self.display_name,
            "field": self.field,
        }


class PendingChangesTracker:
    """追踪 Agent 运行期间的所有修改，支持一键撤回。"""

    def __init__(self):
        self._changes: list[PendingChange] = []
        self._seen: set[tuple[str, int, str]] = set()  # 去重：(type, record_id, field)

    def record(self, change: PendingChange) -> None:
        key = (change.type, change.record_id, change.field)
        if key not in self._seen:
            self._seen.add(key)
            self._changes.append(change)

    def record_chapter_field(self, chapter: Chapter, field: str) -> None:
        """记录章节某个字段修改前的值（仅首次记录生效）。"""
        old = getattr(chapter, field, None)
        display = f"第{chapter.chapter_number}章" + (f" · {chapter.title}" if chapter.title else "")
        self.record(PendingChange(
            type="chapter",
            record_id=chapter.id,
            display_name=display,
            field=field,
            old_value=old,
            new_value=None,  # 工具执行后会自动填充
        ))

    def record_story_field(self, story: Story, field: str) -> None:
        """记录故事某个字段修改前的值。"""
        old = getattr(story, field, None)
        self.record(PendingChange(
            type="story",
            record_id=story.id,
            display_name=story.title,
            field=field,
            old_value=old,
            new_value=None,
        ))

    def update_new_value(self, change_type: str, record_id: int, field: str, new_value: Any) -> None:
        """工具执行后更新 new_value。"""
        for c in self._changes:
            if c.type == change_type and c.record_id == record_id and c.field == field:
                c.new_value = new_value
                break

    def has_changes(self) -> bool:
        return len(self._changes) > 0

    def get_summary(self) -> list[dict]:
        """返回给前端的摘要（不含实际数据，仅描述）。"""
        return [c.to_dict() for c in self._changes if c.new_value is not None]

    def get_full_data(self) -> list[dict]:
        """返回完整的变更数据（含 old_value 和 new_value），供前端展示差异对比。"""
        return [
            {
                "type": c.type,
                "record_id": c.record_id,
                "display_name": c.display_name,
                "field": c.field,
                "old_value": _serialize_for_diff(c.old_value),
                "new_value": _serialize_for_diff(c.new_value),
            }
            for c in self._changes
            if c.new_value is not None
        ]

    def rollback(self, db: Session) -> list[dict]:
        """撤回所有修改，恢复旧值。返回操作结果列表。"""
        results = []
        for change in reversed(self._changes):
            try:
                if change.type == "chapter":
                    obj = db.get(Chapter, change.record_id)
                    if obj:
                        setattr(obj, change.field, change.old_value)
                        results.append({"ok": True, "type": "chapter", "id": change.record_id, "field": change.field})
                elif change.type == "story":
                    obj = db.get(Story, change.record_id)
                    if obj:
                        setattr(obj, change.field, change.old_value)
                        results.append({"ok": True, "type": "story", "id": change.record_id, "field": change.field})
                elif change.type == "story_bible":
                    obj = db.get(Story, change.record_id)
                    if obj:
                        setattr(obj, change.field, change.old_value)
                        results.append({"ok": True, "type": "story_bible", "id": change.record_id, "field": change.field})
                elif change.type == "video_shot":
                    obj = db.get(ChapterVideoShot, change.record_id)
                    if obj:
                        setattr(obj, change.field, change.old_value)
                        results.append({"ok": True, "type": "video_shot", "id": change.record_id, "field": change.field})
                elif change.type == "video_workflow":
                    obj = db.get(ChapterVideoWorkflow, change.record_id)
                    if obj:
                        setattr(obj, change.field, change.old_value)
                        results.append({"ok": True, "type": "video_workflow", "id": change.record_id, "field": change.field})
                elif change.type == "scenes_file":
                    scenes_path = _scenes_path(change.record_id)
                    if change.old_value:
                        scenes_path.parent.mkdir(parents=True, exist_ok=True)
                        scenes_path.write_text(change.old_value, encoding="utf-8")
                    elif scenes_path.exists():
                        scenes_path.unlink()
                    results.append({"ok": True, "type": "scenes_file", "id": change.record_id})
            except Exception as e:
                results.append({"ok": False, "error": str(e)})
        if any(r.get("ok") for r in results):
            db.commit()
        self.clear()
        return results

    def clear(self) -> None:
        self._changes.clear()
        self._seen.clear()


AgentMode = str
AGENT_MODES: set[AgentMode] = {"chat", "analyze", "execute"}
READ_ONLY_AGENT_MODES: set[AgentMode] = {"chat", "analyze"}


# ── Skills 技能系统 ──────────────────────────────────────


@dataclass
class SkillDef:
    """Agent 技能定义：一组工具 + System Prompt 片段 + 元数据。"""
    name: str              # 技能标识名，如 "chapter_writer"
    display_name: str      # 中文显示名，如 "章节写作"
    description: str       # 技能描述
    icon: str              # 图标（emoji）
    tool_names: list[str]  # 关联的工具名列表
    system_prompt_fragment: str  # 注入到 System Prompt 的片段


class SkillRegistry:
    """管理所有 Agent Skills 的注册和查询。"""

    def __init__(self):
        self._skills: dict[str, SkillDef] = {}

    def register(self, skill: SkillDef) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillDef | None:
        return self._skills.get(name)

    def list_all(self) -> list[SkillDef]:
        return list(self._skills.values())

    def get_tool_set(self, skill_names: list[str]) -> set[str]:
        """获取指定 Skills 涵盖的所有工具名集合。"""
        tools: set[str] = set()
        for name in skill_names:
            skill = self._skills.get(name)
            if skill:
                tools.update(skill.tool_names)
        return tools

    def build_fragment(self, skill_names: list[str], db=None) -> str:
        """构建指定 Skills 的 System Prompt 注入片段。

        chapter_writer 的方法论从 DB 动态读取（管理员后台修改后即时生效）。
        """
        if not skill_names:
            return ""
        fragments = []
        for name in skill_names:
            skill = self._skills.get(name)
            if not skill:
                continue
            fragment = skill.system_prompt_fragment
            if name == "chapter_writer":
                from services.writing_utils import get_methodology_from_db
                methodology = get_methodology_from_db(db) if db else ""
                if methodology:
                    fragment = fragment + "\n\n" + methodology
            if fragment.strip():
                fragments.append(f"## 🎯 {skill.icon} {skill.display_name}\n\n{fragment.strip()}")
        return "\n\n" + "\n\n".join(fragments) if fragments else ""


# ── 内置 Skills 定义 ──────────────────────────────────────

skill_registry = SkillRegistry()

# Skill 1: 章节写作（方法论由 build_fragment 从 DB 动态注入，无需写在 system_prompt_fragment 中）
skill_registry.register(SkillDef(
    name="chapter_writer",
    display_name="章节写作",
    description="提供章节的读取、修改、重写、批量调整能力，遵循网文写作方法论",
    icon="✍️",
    tool_names=[
        "get_chapter_full", "get_all_chapters_summary",
        "update_chapter_content", "batch_update_chapters",
        "adjust_chapter_by_instruction", "rewrite_text_segment",
        "add_chapter_plan", "bulk_add_chapter_plans",
        "batch_adjust_chapters",
    ],
    system_prompt_fragment="你是一位专业的小说章节写手。使用提供的工具完成章节的读取、修改、重写和批量调整操作。遵循用户指示，严格按照下方写作方法论输出高质量内容。",
))

# Skill 2: 框架设计
skill_registry.register(SkillDef(
    name="framework_designer",
    display_name="框架设计",
    description="提供故事框架、角色、世界观的读取和调整能力",
    icon="🏗️",
    tool_names=[
        "get_framework_detail", "get_story_bible",
        "get_character_profiles", "get_scenes",
        "update_story_info", "update_story_bible",
        "update_characters", "adjust_framework",
        "apply_framework_ops", "update_scenes",
    ],
    system_prompt_fragment="""你是一位专业的故事框架设计师。调整框架时遵循以下原则：

**框架设计原则**：
1. **三幕结构**：第一卷（铺垫，建立世界观和核心冲突），第二卷（发展，升级冲突和角色成长），第三卷（高潮，收束所有线索）
2. **角色驱动力**：每个角色必须有明确的核心动机，动机驱动行为，行为引发冲突
3. **世界观一致性**：设定一旦建立，不可随意修改。新设定必须与已有设定兼容

**操作指南**：
- 明确修改（改名/删角色/加章节）→ 用 `apply_framework_ops` 直接执行
- 需要 AI 创作（重设计第二幕/让故事更悬疑）→ 用 `adjust_framework`
- 能用 `apply_framework_ops` 解决的，不要用 `adjust_framework`（节省配额）

**角色设计**：
- 主角必须有核心特质（2-3 个关键词）+ 金手指/核心能力 + 弱点/缺陷 + 核心动机
- 反派必须有明确动机和阶梯式作恶（小恶→中恶→大恶）
- 配角的出场必须服务于主线或角色弧光，不冗余

**情节设计**：
- 每章必须有明确的核心事件，推动主线或辅线
- 爽点密度：每 3000-5000 字必须有一个让读者"爽"的情绪节点
- 伏笔埋设：铺垫→揭露→回收，三阶段完整""",
))

# Skill 3: 质量审查
skill_registry.register(SkillDef(
    name="quality_reviewer",
    display_name="质量审查",
    description="提供全文质量检查，包括结构分析、一致性检查、AI味检测、节奏评估",
    icon="🔍",
    tool_names=[
        "get_chapter_full", "get_all_chapters_summary",
        "get_framework_detail", "get_story_bible",
        "get_scenes", "get_character_profiles",
        "check_ai_flavor",
    ],
    system_prompt_fragment="""你是一位专业的网文质量审查员。审查时遵循以下标准：

**审查维度**：
1. **结构完整性**：三幕结构是否清晰，每章是否有明确的核心事件
2. **角色一致性**：角色行为是否符合其动机和性格，前后是否一致
3. **节奏评估**：情绪曲线是否合理（铺垫→升温→释放→反转），是否连续 2 节以上无情绪变化
4. **AI味检测**：使用 `check_ai_flavor` 工具检测 AI 写作指纹，包括：
   - 禁用词命中（"眼中闪过一丝""深吸一口气""嘴角勾起一抹"等）
   - 句式套路（"……，带着……""声音不大，却带着……"）
   - 心理描写外化（"他很紧张"→ 应改为动作展示）
   - 段落匀称度（AI 倾向每段 4-6 句整齐排列）
   - 结尾升华（"他知道……""这一刻……"→ 应删）
   - 解释腔/上帝感（"她不知道的是……""殊不知……"→ 应删）
5. **钩子质量**：章首是否有钩子，章尾是否有悬念

**审查流程**：
- 先读取所有相关数据（章节内容、框架、角色设定）
- 输出系统性分析，逐项标注问题等级（S1=致命/S2=明显/S3=局部/S4=建议）
- 每个问题必须附带原文证据和具体修改建议
- 等待用户确认后再执行修改

**输出格式**：
```
## 审查报告
### 整体评估
- 结构：{评分}
- 角色：{评分}
- 节奏：{评分}
- AI味等级：{轻度/中度/重度}
### 问题清单
| 严重度 | 类别 | 位置 | 原文证据 | 问题描述 | 修改建议 |
```""" + "\n\n" + get_quality_checklist(),
))

# Skill 4: 视频工作流
skill_registry.register(SkillDef(
    name="video_workflow",
    display_name="视频工作流",
    description="提供视频工作流的查看、修改、优化能力",
    icon="🎬",
    tool_names=[
        "get_video_workflow", "get_workflow_shots",
        "get_shot_detail", "get_video_assets",
        "get_screenplay", "update_shot_prompts",
        "update_shot_fields", "update_screenplay",
        "batch_update_shot_prompts", "batch_update_shot_fields",
    ],
    system_prompt_fragment="""你是一位专业的视频工作流制作人。操作视频工作流时遵循以下原则：

**视频工作流概念**：
- 每个镜头（shot）包含：故事版 prompt（描述画面内容）、视频 prompt（描述运镜和动作）、场景 prompt、角色 prompt
- 15 秒视频容量：一个镜头通常对应 15 秒视频，需要动态决定分镜段落数量

**操作指南**：
- 批量操作优先：修改多个镜头时用 `batch_update_shot_prompts` / `batch_update_shot_fields`
- 故事版 prompt 和视频 prompt 必须描述同一场景，不能出现内容不一致
- 角色素材引用必须合理，检查角色在当前镜头中是否应该出现

**镜头连续性检查**：
- 角色、场景、情绪是否连贯
- 相邻镜头之间的时间和空间逻辑是否合理
- 运镜方向是否保持一致（避免跳轴）""",
))

# Skill 5: 拆书学习
skill_registry.register(SkillDef(
    name="deconstruction_reader",
    display_name="拆书学习",
    description="读取拆书分析结果，学习爆款小说的写作手法，辅助用户创作",
    icon="📚",
    tool_names=[
        "get_deconstruction_data", "get_deconstruction_techniques",
        "get_deconstruction_plots", "get_deconstruction_rhythm",
        "get_framework_detail", "get_story_bible",
        "get_all_chapters_summary", "get_chapter_full",
    ],
    system_prompt_fragment="""你是一位专业的网文写作学习顾问。你可以读取拆书分析数据，帮助用户学习爆款小说的写作手法。

**拆书数据包含**：
- 黄金三章深度拆解（开篇钩子、主角塑造、爽点设计、世界观铺设、章尾悬念）
- 逐章摘要（每章的情节点、关键信息、扩写技法）
- 剧情线分析（主线/支线/爱情线/成长线等）
- 节奏分析（关键信息推进、情绪触动点、爽点循环）
- 情绪模块（读者需求、情绪引擎、可复现模块）
- 角色档案（主角/反派/核心配角/功能角色）
- 角色关系（关系本质、演变轨迹）
- 世界观设定（力量体系、地理、势力、金手指）
- 文风分析（句长、标点、对话潜台词、情绪交替周期）
- 写作手法清单（可复用的技法，含使用条件和风险）

**你可以帮用户做什么**：

1. **学习写作手法**：用户问"这本小说的开篇钩子怎么设计的？"→ 读取黄金三章数据，分析钩子类型、铺垫手法、效果
2. **参考调整大纲**：用户说"参考遮天的节奏，调整我的大纲"→ 读取拆书节奏数据，对比用户当前大纲，给出调整建议
3. **学习扩写技法**：用户问"这段怎么扩写才能有爽感？"→ 读取拆书的关键信息与扩写技法，给出具体建议
4. **对比分析**：用户说"我的小说和这本比，哪里不足？"→ 读取拆书数据，与用户当前作品对比分析
5. **生成写作指导**：用户说"根据拆书结果，给我写一份写作指导"→ 汇总拆书数据，生成定制化写作指导

**使用指南**：
- 先用 `get_deconstruction_data` 获取拆书概览，了解有哪些数据可用
- 根据用户具体问题，用对应工具获取详细数据
- 拆书数据是"参考"而非"照搬"——抽象出可复用的模式和逻辑，而不是直接复制具体桥段
- 对比分析时，注重"为什么这个写法有效"而非"这里写得好"的主观评价""",
))


@dataclass(frozen=True)
class AgentPendingChangeKey:
    user_id: int
    story_id: int
    conversation_id: int


@dataclass
class AgentRunContext:
    story_id: int
    api_key: str | None
    mode: AgentMode
    pending_changes: PendingChangesTracker
    pending_change_key: AgentPendingChangeKey | None = None
    workflow_type: str | None = None
    workflow_id: int | None = None
    shot_id: int | None = None


class AgentPendingChangeStore:
    """In-memory pending change store scoped to one user/story/conversation."""

    def __init__(self):
        self._items: dict[AgentPendingChangeKey, PendingChangesTracker] = {}
        self._lock = threading.RLock()

    def set(self, key: AgentPendingChangeKey, tracker: PendingChangesTracker) -> None:
        with self._lock:
            if tracker.has_changes():
                self._items[key] = tracker
                _persist_pending_changes(key, tracker)
            else:
                self._items.pop(key, None)

    def get(self, key: AgentPendingChangeKey) -> PendingChangesTracker | None:
        with self._lock:
            return self._items.get(key)

    def clear(self, key: AgentPendingChangeKey) -> None:
        with self._lock:
            self._items.pop(key, None)


_AGENT_RUN_CONTEXT: contextvars.ContextVar[AgentRunContext | None] = contextvars.ContextVar(
    "agent_run_context",
    default=None,
)
agent_pending_change_store = AgentPendingChangeStore()


def _persist_pending_changes(key: AgentPendingChangeKey, tracker: PendingChangesTracker) -> None:
    db = SessionLocal()
    try:
        db.query(AgentPendingChange).filter(
            AgentPendingChange.user_id == key.user_id,
            AgentPendingChange.story_id == key.story_id,
            AgentPendingChange.conversation_id == key.conversation_id,
        ).delete()

        for change in tracker._changes:
            if change.new_value is not None:
                db.add(AgentPendingChange(
                    user_id=key.user_id,
                    story_id=key.story_id,
                    conversation_id=key.conversation_id,
                    change_type=change.type,
                    record_id=change.record_id,
                    display_name=change.display_name,
                    field=change.field,
                    old_value=change.old_value,
                    new_value=change.new_value,
                ))
        db.commit()
    except Exception as e:
        logger.warning("持久化 pending changes 失败: %s", e)
    finally:
        db.close()


def normalize_agent_mode(mode: str | None) -> AgentMode:
    normalized = str(mode or "execute").strip().lower()
    if normalized not in AGENT_MODES:
        return "execute"
    return normalized


def _current_run_context() -> AgentRunContext | None:
    return _AGENT_RUN_CONTEXT.get()


def _current_story_id() -> int | None:
    context = _current_run_context()
    return context.story_id if context else None


def _current_api_key() -> str | None:
    context = _current_run_context()
    return context.api_key if context else None


def _current_pending_changes() -> PendingChangesTracker | None:
    context = _current_run_context()
    return context.pending_changes if context else None


async def _refresh_agent_memory(chapter, db: Session) -> None:
    try:
        story_id = _current_story_id()
        api_key = _current_api_key()
        if not api_key:
            return
        import sys
        _main = sys.modules.get("main")
        if not _main:
            return
        from services.story_state import refresh_chapter_memory_for_content
        from services.deepseek import summarize_chapter_memory
        refreshed = await refresh_chapter_memory_for_content(
            chapter=chapter,
            api_key=api_key,
            story_context_func=lambda story: _main._build_framework_ai_context(story),
            summarize_chapter_memory_func=summarize_chapter_memory,
            merge_story_memory_func=_main._merge_story_memory,
        )
        if refreshed:
            logger.info("Agent 写章节后已刷新连续记忆 story=%s chapter=%s", story_id, chapter.id)
    except Exception as e:
        logger.warning("Agent 刷新连续记忆失败 story=%s chapter=%s: %s", _current_story_id(), chapter.id, e)


def _serialize_for_diff(value: Any) -> str:
    """将各种类型的值序列化为适合对比展示的字符串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


logger = logging.getLogger("agent_service")

# ── 文件系统辅助 ──────────────────────────────────────────

BACKEND_DIR = Path(__file__).resolve().parent.parent

# 批量操作的并发限制
BATCH_CONCURRENCY_LIMIT = 3


def _chapter_dir(chapter_id: int) -> Path:
    return BACKEND_DIR / "manga_outputs" / f"chapter_{chapter_id}"


def _scenes_path(chapter_id: int) -> Path:
    return _chapter_dir(chapter_id) / "scenes.txt"


def _characters_file_path(chapter_id: int) -> Path:
    return _chapter_dir(chapter_id) / "characters.txt"


def _parse_scenes_text(raw: str) -> list[str]:
    import re
    parts = [p.strip() for p in re.split(r"(?m)^=== .*? ===\n", raw) if p.strip()]
    return parts


# ── 小工具注册器 ──────────────────────────────────────────


class ToolRegistry:
    """管理 Agent 可见的工具列表，支持装饰器注册模式。"""

    def __init__(self):
        self._tools: dict[str, dict[str, Any]] = {}
        self._write_tool_names: set[str] = set()
        self._workflow_types: dict[str, set[str]] = {}

    def register(self, name: str, description: str, parameters: dict, is_write: bool = False, workflow_types: list[str] | None = None):
        """装饰器：注册一个工具处理函数。

        workflow_types: 工具所属的工作流类型列表。None 表示所有类型都可用。
        """
        def decorator(func):
            self._tools[name] = {
                "handler": func,
                "spec": {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                    },
                },
            }
            if is_write:
                self._write_tool_names.add(name)
            if workflow_types is not None:
                self._workflow_types[name] = set(workflow_types)
            return func
        return decorator

    def is_write_tool(self, name: str) -> bool:
        return name in self._write_tool_names

    def get_tool_specs(self, mode: AgentMode = "execute", workflow_type: str | None = None, enabled_skills: list[str] | None = None) -> list[dict]:
        """返回 DeepSeek/OpenAI function calling 格式的工具清单。

        workflow_type: 如果指定，只返回与该工作流类型匹配的工具（含未指定类型的通用工具）。
        enabled_skills: 如果指定，只返回这些 Skills 涵盖的工具。为空列表时返回全部工具。
        """
        if normalize_agent_mode(mode) in READ_ONLY_AGENT_MODES:
            candidates = [
                (name, info["spec"])
                for name, info in self._tools.items()
                if name not in self._write_tool_names
            ]
        else:
            candidates = [(name, info["spec"]) for name, info in self._tools.items()]

        if workflow_type is not None:
            candidates = [
                (name, spec)
                for name, spec in candidates
                if name not in self._workflow_types or workflow_type in self._workflow_types[name]
            ]
        else:
            candidates = [
                (name, spec)
                for name, spec in candidates
                if name not in self._workflow_types
            ]

        # Skills 过滤：如果指定了 enabled_skills，只保留这些技能涵盖的工具
        if enabled_skills:
            allowed_tools = skill_registry.get_tool_set(enabled_skills)
            if allowed_tools:
                candidates = [
                    (name, spec)
                    for name, spec in candidates
                    if name in allowed_tools
                ]

        return [spec for _, spec in candidates]

    async def execute(self, name: str, args: dict) -> str:
        """按名称执行工具，返回 JSON 字符串。"""
        info = self._tools.get(name)
        if not info:
            raise ValueError(f"未知工具: {name}")
        context = _current_run_context()
        if name in self._write_tool_names and (context is None or context.mode != "execute"):
            return json.dumps(
                {
                    "error": "当前 Agent 模式不允许写入。请切换到执行模式后再保存修改。",
                    "write_denied": True,
                    "mode": context.mode if context else None,
                },
                ensure_ascii=False,
            )
        result = await info["handler"](**args)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False)


# ── 所有权校验辅助 ──────────────────────────────────────────

def _validate_chapter_ownership(db: Session, chapter_id: int, expected_story_id: int | None) -> Chapter | None:
    """校验章节是否属于指定故事。返回章节对象，失败返回 None。"""
    if expected_story_id is None:
        return None
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        return None
    if chapter.story_id != expected_story_id:
        return None
    return chapter


def _validate_story_ownership(db: Session, story_id: int, expected_story_id: int | None) -> Story | None:
    """校验故事 ID 是否与当前上下文一致。返回故事对象，失败返回 None。"""
    if expected_story_id is None:
        return None
    story = db.get(Story, story_id)
    if not story:
        return None
    if story.id != expected_story_id:
        return None
    return story


def _require_current_video_workflow(db: Session, workflow_id: int) -> ChapterVideoWorkflow | None:
    """校验视频工作流是否属于当前上下文。返回工作流对象，失败返回 None。"""
    context = _current_run_context()
    if not context or not context.workflow_id:
        return None
    if workflow_id != context.workflow_id:
        return None
    return db.get(ChapterVideoWorkflow, workflow_id)


def _require_current_video_shot(db: Session, shot_id: int) -> ChapterVideoShot | None:
    """校验视频镜头是否属于当前上下文的工作流。返回镜头对象，失败返回 None。"""
    context = _current_run_context()
    if not context or not context.workflow_id:
        return None
    shot = db.get(ChapterVideoShot, shot_id)
    if not shot:
        return None
    if shot.workflow_id != context.workflow_id:
        return None
    return shot


# ── 全局注册器 ──────────────────────────────────────────

tool_registry = ToolRegistry()


# ────────────────────────────────────────────────────────────
# 读取工具（6 个）
# ────────────────────────────────────────────────────────────


@tool_registry.register(
    name="get_chapter_full",
    description="读取指定章节的完整正文内容，包括标题、正文、关键事件、质量评分等。",
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
        },
        "required": ["chapter_id"],
    },
)
async def get_chapter_full(chapter_id: int) -> dict:
    """读取完整的章节信息。"""
    db = SessionLocal()
    try:
        chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
        if not chapter:
            return {"error": "章节不存在或无权访问"}
        return {
            "id": chapter.id,
            "story_id": chapter.story_id,
            "chapter_number": chapter.chapter_number,
            "title": chapter.title or "",
            "act": chapter.act or "",
            "content": chapter.novel_content or "",
            "key_events": chapter.key_events or [],
            "quality_score": chapter.quality_score or {},
            "status": chapter.status,
            "word_count": chapter.word_count or 0,
        }
    finally:
        db.close()


@tool_registry.register(
    name="get_all_chapters_summary",
    description="获取故事所有章节的摘要列表，包含章节号、标题、字数、状态。",
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
        },
        "required": ["story_id"],
    },
)
async def get_all_chapters_summary(story_id: int) -> dict:
    """列出故事下所有章节的基本信息。"""
    db = SessionLocal()
    try:
        if story_id != _current_story_id():
            return {"error": "故事 ID 与当前上下文不匹配"}
        chapters = (
            db.query(Chapter)
            .filter(Chapter.story_id == story_id)
            .order_by(Chapter.chapter_number)
            .all()
        )
        return {
            "chapters": [
                {
                    "id": ch.id,
                    "chapter_number": ch.chapter_number,
                    "title": ch.title or "",
                    "word_count": ch.word_count or 0,
                    "status": ch.status,
                    "act": ch.act or "",
                }
                for ch in chapters
            ]
        }
    finally:
        db.close()


@tool_registry.register(
    name="get_framework_detail",
    description="获取故事框架详情：标签、角色设定、故事大纲。",
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
        },
        "required": ["story_id"],
    },
)
async def get_framework_detail(story_id: int) -> dict:
    """获取故事标签、角色和大纲。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}
        return {
            "tags": story.tags or {},
            "characters": story.characters or [],
            "outline": story.outline or {},
        }
    finally:
        db.close()


@tool_registry.register(
    name="get_story_bible",
    description="获取作品圣经：创意简报和写作指导。",
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
        },
        "required": ["story_id"],
    },
)
async def get_story_bible(story_id: int) -> dict:
    """获取故事圣经中的 creative_brief 和 writing_guidance。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}
        bible = story.story_bible if isinstance(story.story_bible, dict) else {}
        return {
            "creative_brief": bible.get("creative_brief", {}),
            "writing_guidance": bible.get("writing_guidance", {}),
            "import_guidance": bible.get("import_guidance", {}),
            "raw_input": bible.get("raw_input", {}),
        }
    finally:
        db.close()


@tool_registry.register(
    name="get_scenes",
    description="获取指定章节的分镜列表。",
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
        },
        "required": ["chapter_id"],
    },
)
async def get_scenes(chapter_id: int) -> dict:
    """从文件读取章节分镜列表。"""
    db = SessionLocal()
    try:
        chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
        if not chapter:
            return {"error": "章节不存在或无权访问"}
    finally:
        db.close()
    scenes_file = _scenes_path(chapter_id)
    if not scenes_file.exists():
        return {"scenes": []}
    try:
        raw = scenes_file.read_text(encoding="utf-8")
        scenes = _parse_scenes_text(raw)
        return {"scenes": scenes}
    except Exception as exc:
        logger.warning("读取分镜文件失败 chapter_id=%s: %s", chapter_id, exc)
        return {"scenes": [], "error": str(exc)}


@tool_registry.register(
    name="get_character_profiles",
    description="获取章节的角色外貌设定。优先读取章节独立设定，没有则返回故事级设定。",
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
        },
        "required": ["chapter_id"],
    },
)
async def get_character_profiles(chapter_id: int) -> dict:
    """获取角色外貌设定。"""
    db = SessionLocal()
    try:
        chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
        if not chapter:
            return {"error": "章节不存在或无权访问"}
        cfile = _characters_file_path(chapter_id)
        if cfile.exists():
            text = cfile.read_text(encoding="utf-8").strip()
            if text:
                return {"source": "chapter", "content": text}
        if chapter.story and chapter.story.character_profiles:
            text = chapter.story.character_profiles.strip()
            if text:
                return {"source": "story", "content": text}
        return {"source": "none", "content": ""}
    finally:
        db.close()


# 拆书数据读取工具
@tool_registry.register(
    name="get_deconstruction_data",
    description="获取作品的拆书分析概览（摘要、黄金三章评分、角色列表、剧情线概览、技法数量）",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_deconstruction_data() -> dict:
    """获取拆书分析概览。"""
    db = SessionLocal()
    try:
        story_id = _current_story_id()
        decon = db.query(DeconstructionResult).filter(
            DeconstructionResult.story_id == story_id,
            DeconstructionResult.status == "completed",
        ).order_by(DeconstructionResult.created_at.desc()).first()

        if not decon:
            return {"error": "该作品尚未完成拆书分析"}

        golden_rating = None
        if decon.golden_chapters and isinstance(decon.golden_chapters, dict):
            golden_rating = decon.golden_chapters.get("golden_three_rating")

        return {
            "summary": decon.summary,
            "golden_chapters_rating": golden_rating,
            "character_count": len(decon.characters or []),
            "character_names": [c.get("name") for c in (decon.characters or [])],
            "plot_line_count": len(decon.plot_lines or []),
            "plot_line_titles": [p.get("title") for p in (decon.plot_lines or [])],
            "technique_count": len(decon.writing_techniques or []),
            "has_report": bool(decon.report_markdown),
        }
    finally:
        db.close()


@tool_registry.register(
    name="get_deconstruction_techniques",
    description="获取拆书提取的写作手法清单（可复用的技法，含使用条件和风险）",
    parameters={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "手法类别筛选：开篇钩子/角色塑造/爽点设计/章节结尾/对话手法/信息控制/节奏控制/反转设计/伏笔/情绪操控",
            },
        },
        "required": [],
    },
)
async def get_deconstruction_techniques(category: str | None = None) -> dict:
    """获取写作手法清单。"""
    db = SessionLocal()
    try:
        story_id = _current_story_id()
        decon = db.query(DeconstructionResult).filter(
            DeconstructionResult.story_id == story_id,
            DeconstructionResult.status == "completed",
        ).order_by(DeconstructionResult.created_at.desc()).first()

        if not decon or not decon.writing_techniques:
            return {"techniques": []}

        techniques = decon.writing_techniques
        if category:
            techniques = [t for t in techniques if t.get("category") == category]

        return {"techniques": techniques[:20]}
    finally:
        db.close()


@tool_registry.register(
    name="get_deconstruction_plots",
    description="获取拆书提取的剧情线详情（主线和支线的因果链、核心冲突、章节范围）",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_deconstruction_plots() -> dict:
    """获取剧情线详情。"""
    db = SessionLocal()
    try:
        story_id = _current_story_id()
        decon = db.query(DeconstructionResult).filter(
            DeconstructionResult.story_id == story_id,
            DeconstructionResult.status == "completed",
        ).order_by(DeconstructionResult.created_at.desc()).first()

        if not decon:
            return {"plot_lines": []}

        return {"plot_lines": decon.plot_lines or []}
    finally:
        db.close()


@tool_registry.register(
    name="get_deconstruction_rhythm",
    description="获取拆书提取的节奏分析（关键信息推进、情绪触动点、爽点循环模式）",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_deconstruction_rhythm() -> dict:
    """获取节奏分析。"""
    db = SessionLocal()
    try:
        story_id = _current_story_id()
        decon = db.query(DeconstructionResult).filter(
            DeconstructionResult.story_id == story_id,
            DeconstructionResult.status == "completed",
        ).order_by(DeconstructionResult.created_at.desc()).first()

        if not decon:
            return {"rhythm": {}}

        return {"rhythm": decon.rhythm or {}}
    finally:
        db.close()


# ────────────────────────────────────────────────────────────
# 写入工具（8 个）
# ────────────────────────────────────────────────────────────


@tool_registry.register(
    name="update_chapter_content",
    description="保存/更新章节正文。仅当用户已给出完整改写文本时使用。如果用户要求AI「写出」「生成」「创作」正文，请使用 generate_chapter_content 委托框架引擎生成。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
            "content": {"type": "string", "description": "新的章节正文内容"},
        },
        "required": ["chapter_id", "content"],
    },
)
async def update_chapter_content(chapter_id: int, content: str) -> dict:
    """直接更新章节正文。"""
    db = SessionLocal()
    try:
        chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
        if not chapter:
            return {"error": "章节不存在或无权访问"}
        if _current_pending_changes():
            _current_pending_changes().record_chapter_field(chapter, "novel_content")
        chapter.novel_content = content
        if _current_pending_changes():
            _current_pending_changes().update_new_value("chapter", chapter.id, "novel_content", content)
        await _refresh_agent_memory(chapter, db)
        db.commit()
        logger.info("Agent tool=update_chapter_content story=%s chapter=%s len=%s", _current_story_id(), chapter_id, len(content or ""))
        return {"ok": True, "chapter_id": chapter_id}
    finally:
        db.close()


@tool_registry.register(
    name="create_chapter",
    description="在数据库中创建一个新的章节记录并返回其ID。创建后可以用 generate_chapter_content 委托框架引擎生成正文。"
               "通常先通过 get_framework_detail 查看现有章节的最大编号，确认下一章编号后再调用此工具。"
               "注意：此工具只创建章节行，不写入正文。创建后调用 generate_chapter_content 委托框架引擎生成正文。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "title": {"type": "string", "description": "章节标题（可选，默认自动生成）"},
        },
        "required": ["story_id"],
    },
)
async def create_chapter(story_id: int, title: str | None = None) -> dict:
    """创建新的章节行并返回章节 ID。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}

        max_num = (
            db.query(Chapter.chapter_number)
            .filter(Chapter.story_id == story_id)
            .order_by(Chapter.chapter_number.desc())
            .first()
        )
        next_num = (max_num[0] + 1) if max_num else 1
        chapter = Chapter(
            story_id=story_id,
            chapter_number=next_num,
            title=title or f"第{next_num}话",
            status="pending",
        )
        db.add(chapter)
        db.flush()
        db.commit()
        db.refresh(chapter)
        logger.info(
            "Agent tool=create_chapter story=%s chapter=%s num=%s",
            _current_story_id(), chapter.id, next_num,
        )
        return {
            "ok": True,
            "chapter_id": chapter.id,
            "chapter_number": next_num,
            "title": chapter.title,
        }
    except Exception as e:
        logger.error("Agent tool=create_chapter failed story=%s: %s", _current_story_id(), e)
        return {"error": f"创建章节失败: {e}"}
    finally:
        db.close()


@tool_registry.register(
    name="generate_chapter_content",
    description="委托框架创作引擎生成章节正文。适用于用户要求「写出」「生成」「创作」「写」某章正文时。"
               "内部使用与框架直出完全相同的 DeepSeek 创作管道（含字数铁律/场景经济性/对话铁律/章末钩子/AI写作禁令），"
               "生成质量与框架直出完全一致。\n\n"
               "前置条件：该章节必须在 story.outline 中有章节规划（含完整的 goal/conflict/hook/payoff/highlight 任务卡）。"
               "如果任务卡不完整，请先用 adjust_framework 或 add_chapter_plan 补充。\n\n"
               "推荐使用流程：\n"
               "1. 先调 get_framework_detail 确认章节规划完整\n"
               "2. 如果章节行尚未创建，调 create_chapter 创建章节记录\n"
               "3. 调此工具委托框架引擎生成正文\n"
               "4. 完成后告知用户章节已生成（含字数）\n\n"
               "注意：此工具生成质量高但速度较慢（约10-30秒），请告知用户稍候。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "chapter_number": {"type": "integer", "description": "章节号（必须是 outline 中已规划的章节号）"},
            "instruction": {
                "type": "string",
                "description": "用户对本章正文的额外写作要求，如「节奏快一点」「多写擂台打斗细节」「氛围要阴郁」「增加主角和配角的对话」等。"
                               "可选，不传时按大纲任务卡默认生成。",
            },
        },
        "required": ["story_id", "chapter_number"],
    },
)
async def generate_chapter_content(story_id: int, chapter_number: int, instruction: str | None = None) -> dict:
    """委托框架创作引擎生成章节正文（与框架直出质量完全一致）。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}

        story_context = _build_story_context_dict(story, user_instruction=instruction or "")

        outline = story.outline if isinstance(story.outline, dict) else {}
        chapters = _extract_outline_chapters(outline)
        chapter_info = None
        for ch in chapters:
            if ch.get("chapter_number") == chapter_number:
                chapter_info = dict(ch)
                break

        if not chapter_info:
            return {"error": f"大纲中未找到第 {chapter_number} 章的规划。请先用 adjust_framework 或 add_chapter_plan 添加章节规划（含完整的 goal/conflict/hook/payoff/highlight 任务卡字段）"}

        missing_fields = [f for f in ["goal", "conflict", "hook", "payoff", "highlight"] if not str(chapter_info.get(f) or "").strip()]
        if missing_fields:
            return {"error": f"第 {chapter_number} 章的任务卡字段 {', '.join(missing_fields)} 为空。请先用 adjust_framework 补充章节任务卡，确保 goal/conflict/hook/payoff/highlight 全部完整"}

        if instruction and instruction.strip():
            chapter_info["user_instruction"] = instruction.strip()

        api_key = _current_api_key()
        if not api_key:
            return {"error": "DeepSeek API Key 未配置，请在设置中填写"}

        previous_chapter_summary = ""
        if isinstance(chapter_number, int) and chapter_number > 1:
            prev_chapter = (
                db.query(Chapter)
                .filter(
                    Chapter.story_id == story_id,
                    Chapter.chapter_number < chapter_number,
                    Chapter.novel_content.isnot(None),
                    Chapter.status.in_(["completed", "draft", "reviewed"]),
                )
                .order_by(Chapter.chapter_number.desc())
                .first()
            )
            if prev_chapter:
                prev_title = prev_chapter.title or f"第{prev_chapter.chapter_number}章"
                memory_summary = prev_chapter.memory_summary if isinstance(prev_chapter.memory_summary, dict) else {}
                chapter_summary = memory_summary.get("chapter_summary") if isinstance(memory_summary.get("chapter_summary"), dict) else {}
                handoff = memory_summary.get("chapter_handoff") if isinstance(memory_summary.get("chapter_handoff"), dict) else {}
                ending_scene = str(chapter_summary.get("ending_scene") or memory_summary.get("ending_scene") or "").strip()
                summary_text = str(chapter_summary.get("summary") or memory_summary.get("summary") or "").strip()
                fallback_tail = (prev_chapter.novel_content or "")[-800:].strip()

                bridge_parts = [f"上一章《第{prev_chapter.chapter_number}章：{prev_title}》"]
                if summary_text:
                    bridge_parts.append(f"章节摘要：{summary_text}")
                if ending_scene:
                    bridge_parts.append(f"结尾场景：{ending_scene}")
                if fallback_tail and not ending_scene:
                    bridge_parts.append(f"正文结尾片段：\n{fallback_tail}")
                if handoff.get("opening_must_continue"):
                    bridge_parts.append(f"下一章必须承接：{handoff['opening_must_continue']}")
                if handoff.get("active_conflict"):
                    bridge_parts.append(f"即时冲突：{handoff['active_conflict']}")
                previous_chapter_summary = "\n".join(bridge_parts)[:2400]

        recent_chapter_memories_text = ""
        if isinstance(chapter_number, int) and chapter_number > 1:
            recent_candidates = (
                db.query(Chapter)
                .filter(
                    Chapter.story_id == story_id,
                    Chapter.chapter_number < chapter_number,
                )
                .order_by(Chapter.chapter_number.desc())
                .limit(3)
                .all()
            )
            recent_compact = []
            for item in reversed(recent_candidates):
                item_ms = item.memory_summary if isinstance(item.memory_summary, dict) else {}
                item_cs = item_ms.get("chapter_summary") if isinstance(item_ms.get("chapter_summary"), dict) else {}
                item_summary = str(item_cs.get("summary") or item_ms.get("summary") or "").strip()
                if item_summary:
                    recent_compact.append(f"第{item.chapter_number}章：{item_summary}")
            if recent_compact:
                recent_chapter_memories_text = "近期章节摘要：\n" + "\n".join(recent_compact)

        if recent_chapter_memories_text:
            previous_chapter_summary = (previous_chapter_summary + "\n\n" + recent_chapter_memories_text).strip()

        system_prompt = get_effective_prompt(story_id, "chapter", db)

        novel_content = await expand_chapter_to_content(
            story_context=story_context,
            chapter_info=chapter_info,
            api_key=api_key,
            previous_chapter_summary=previous_chapter_summary,
            system_prompt=system_prompt or None,
            db=db,
        )

        if not novel_content or not novel_content.strip():
            return {"error": "生成内容为空，请重试"}

        story_context["current_chapter"] = {key: value for key, value in chapter_info.items() if value not in (None, "", [], {})}
        quality_gate = await finalize_generated_chapter_content(
            content=novel_content,
            story_context=story_context,
            chapter_info=chapter_info,
            api_key=api_key,
            system_prompt=system_prompt or None,
            source="agent_generate_chapter_content",
            allow_pipeline_rerun=False,
        )
        if not quality_gate.get("ok"):
            return {"error": "生成正文未通过质量门禁", "detail": format_quality_gate_detail(quality_gate)}
        novel_content = quality_gate["content"]

        chapter = (
            db.query(Chapter)
            .filter(Chapter.story_id == story_id, Chapter.chapter_number == chapter_number)
            .first()
        )
        if chapter is None:
            chapter = Chapter(
                story_id=story_id,
                chapter_number=chapter_number,
                title=chapter_info.get("title") or f"第{chapter_number}章",
                status="completed",
            )
            db.add(chapter)
            db.flush()

        if _current_pending_changes():
            _current_pending_changes().record_chapter_field(chapter, "novel_content")
        chapter.novel_content = novel_content
        chapter.quality_score = quality_gate.get("report")
        chapter.content_source = "framework_generation"
        if _current_pending_changes():
            _current_pending_changes().update_new_value("chapter", chapter.id, "novel_content", novel_content)

        db.commit()
        await _refresh_agent_memory(chapter, db)

        logger.info(
            "Agent tool=generate_chapter_content story=%s chapter=%s len=%s instruction=%s",
            story_id, chapter_number, len(novel_content), instruction or "(无)",
        )

        preview = novel_content[:200] + "..." if len(novel_content) > 200 else novel_content
        return {
            "ok": True,
            "chapter_id": chapter.id,
            "chapter_number": chapter_number,
            "content_length": len(novel_content),
            "preview": preview,
        }
    except Exception as e:
        logger.error("Agent tool=generate_chapter_content failed story=%s chapter=%s: %s", story_id, chapter_number, e)
        return {"error": f"生成失败: {e}"}
    finally:
        db.close()


@tool_registry.register(
    name="batch_update_chapters",
    description="批量更新多个章节的正文内容。适用于用户给出多个章节的具体改写内容时，一次保存多章。比分别调用 update_chapter_content 更高效。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "chapters": {
                "type": "array",
                "description": "要更新的章节列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "chapter_id": {"type": "integer", "description": "章节 ID"},
                        "content": {"type": "string", "description": "新的章节正文内容"},
                    },
                    "required": ["chapter_id", "content"],
                },
            },
        },
        "required": ["chapters"],
    },
)
async def batch_update_chapters(chapters: list[dict]) -> dict:
    """批量更新多个章节正文。"""
    MAX_BATCH_SIZE = 10
    if not isinstance(chapters, list):
        return {"error": "chapters 必须是一个数组"}
    if len(chapters) > MAX_BATCH_SIZE:
        return {"error": f"一次最多更新 {MAX_BATCH_SIZE} 个章节"}

    async def _update_one(item: dict) -> dict:
        chapter_id = item.get("chapter_id")
        content = item.get("content")
        if not chapter_id or content is None:
            return {"chapter_id": chapter_id, "error": "缺少 chapter_id 或 content"}
        db = SessionLocal()
        try:
            chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
            if not chapter:
                return {"chapter_id": chapter_id, "error": "章节不存在或无权访问"}
            if _current_pending_changes():
                _current_pending_changes().record_chapter_field(chapter, "novel_content")
            chapter.novel_content = content
            if _current_pending_changes():
                _current_pending_changes().update_new_value("chapter", chapter.id, "novel_content", content)
            db.commit()
            logger.info("Agent tool=batch_update_chapters story=%s chapter=%s len=%s", _current_story_id(), chapter_id, len(content or ""))
            return {"chapter_id": chapter_id, "ok": True}
        except Exception as e:
            return {"chapter_id": chapter_id, "error": str(e)}
        finally:
            db.close()

    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY_LIMIT)

    async def _update_one_with_limit(item: dict) -> dict:
        async with semaphore:
            return await _update_one(item)

    results = await asyncio.gather(*[_update_one_with_limit(item) for item in chapters])
    return {"ok": True, "results": results}


@tool_registry.register(
    name="adjust_chapter_by_instruction",
    description="根据用户指令让 AI 重写整章正文。适用于用户要求调整风格、补充内容等场景。消耗文本配额。如果用户已给出具体改写文本，用 update_chapter_content 更直接。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "要调整的章节 ID"},
            "instruction": {"type": "string", "description": "用户的修改指令"},
        },
        "required": ["chapter_id", "instruction"],
    },
)
async def adjust_chapter_by_instruction(chapter_id: int, instruction: str) -> dict:
    """调用 DeepSeek 根据指令重写整章。"""
    db = SessionLocal()
    try:
        chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
        if not chapter:
            return {"error": "章节不存在或无权访问"}
        story_obj = db.get(Story, chapter.story_id)
        if not story_obj:
            return {"error": "所属故事不存在"}

        if _current_pending_changes():
            _current_pending_changes().record_chapter_field(chapter, "novel_content")

        story_context = _build_story_context_dict(story_obj)
        chapter_info = {
            "chapter_number": chapter.chapter_number,
            "title": chapter.title or f"第{chapter.chapter_number}章",
            "act": chapter.act or "",
            "key_events": chapter.key_events or [],
        }
        chapter_content = chapter.novel_content or ""

        api_key = _current_api_key()
        if not api_key:
            return {"error": "DeepSeek API Key 未配置"}

        template_system = get_effective_prompt(chapter.story_id, "chapter", db)
        fallback_prompt = build_agent_chapter_system_prompt(db=db)
        system_rules = template_system or fallback_prompt or ""

        from services.chapter_agents import run_chapter_creation_pipeline

        chapter_info["user_instruction"] = instruction
        pipeline_result = await run_chapter_creation_pipeline(
            story_context=story_context,
            chapter_info=chapter_info,
            api_key=api_key,
            previous_chapter_summary="",
            system_rules=system_rules,
            max_revisions=3,
            initial_content=chapter_content,
        )
        new_content = pipeline_result.get("content") or ""
        if not new_content or not new_content.strip():
            return {"error": "AI 返回内容为空"}

        chapter.novel_content = new_content
        chapter.quality_score = {
            "review": pipeline_result.get("review"),
            "creation_pack": pipeline_result.get("creation_pack"),
            "attempts": pipeline_result.get("attempts"),
            "pipeline_approved": True,
        }
        if _current_pending_changes():
            _current_pending_changes().update_new_value("chapter", chapter.id, "novel_content", new_content)
        await _refresh_agent_memory(chapter, db)
        db.commit()
        logger.info("Agent tool=adjust_chapter_by_instruction (pipeline) story=%s chapter=%s new_len=%s", _current_story_id(), chapter_id, len(new_content))
        return {"ok": True, "chapter_id": chapter_id, "content_length": len(new_content)}
    finally:
        db.close()


@tool_registry.register(
    name="rewrite_text_segment",
    description='在章节正文中精确查找并替换指定段落。适用于用户给出「把某段改成XX」的明确指令。注意：original 必须与正文完全匹配。',
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
            "original": {"type": "string", "description": "需要被替换的原文（必须完全匹配）"},
            "rewritten": {"type": "string", "description": "改写后的新文本"},
        },
        "required": ["chapter_id", "original", "rewritten"],
    },
)
async def rewrite_text_segment(chapter_id: int, original: str, rewritten: str) -> dict:
    """在章节正文中执行精确查找替换。"""
    db = SessionLocal()
    try:
        chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
        if not chapter:
            return {"error": "章节不存在或无权访问"}
        current = chapter.novel_content or ""
        if original not in current:
            return {"error": "未在正文中找到完全匹配的原文，请确认文本是否一致", "found": False}
        if _current_pending_changes():
            _current_pending_changes().record_chapter_field(chapter, "novel_content")
        new_content = current.replace(original, rewritten, 1)
        chapter.novel_content = new_content
        if _current_pending_changes():
            _current_pending_changes().update_new_value("chapter", chapter.id, "novel_content", new_content)
        db.commit()
        logger.info("Agent tool=rewrite_text_segment story=%s chapter=%s old=%s new=%s", _current_story_id(), chapter_id, len(current), len(new_content))
        return {
            "ok": True,
            "chapter_id": chapter_id,
            "replaced": True,
            "new_content_length": len(new_content),
        }
    finally:
        db.close()


@tool_registry.register(
    name="update_story_info",
    description="更新故事的基本信息（标题、描述、标签）。只更新提供的字段。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "title": {"type": "string", "description": "新标题（可选）"},
            "description": {"type": "string", "description": "新描述（可选）"},
            "tags": {
                "type": "object",
                "description": "新标签对象，例如 {\"type\": \"奇幻\", \"theme\": \"冒险\"}（可选）",
                "additionalProperties": True,
            },
        },
        "required": ["story_id"],
    },
)
async def update_story_info(story_id: int, title: str | None = None, description: str | None = None, tags: dict | None = None) -> dict:
    """更新故事基本信息。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}
        if _current_pending_changes():
            if title is not None:
                _current_pending_changes().record_story_field(story, "title")
            if description is not None:
                _current_pending_changes().record_story_field(story, "description")
            if tags is not None:
                _current_pending_changes().record_story_field(story, "tags")
        updated_fields = []
        if title is not None:
            story.title = title
            updated_fields.append("title")
        if description is not None:
            story.description = description
            updated_fields.append("description")
        if tags is not None:
            story.tags = tags
            updated_fields.append("tags")
        if _current_pending_changes():
            for f in updated_fields:
                _current_pending_changes().update_new_value("story", story.id, f, getattr(story, f))
        db.commit()
        logger.info("Agent tool=update_story_info story=%s fields=%s", _current_story_id(), updated_fields)
        return {"ok": True, "updated_fields": updated_fields}
    finally:
        db.close()


@tool_registry.register(
    name="update_story_bible",
    description="更新作品圣经（Story Bible），只更新提供的字段，未提供的字段保留原值。用户要求调整世界观、修改核心设定、改创意简报时用此工具。\n\n⚠️ 一次只更新一个模块：creative_brief、writing_guidance、import_guidance 每次选一个更新。world_setting 是 creative_brief 下的嵌套字段，更新 world_setting 请在 creative_brief 中传入 world_setting 字段。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "story_bible": {
                "type": "object",
                "description": "要更新的作品圣经字段（partial merge）。顶层 key 可包括 creative_brief、writing_guidance、import_guidance。只需提供要修改的部分，未提供的会保留原值。",
                "additionalProperties": True,
            },
        },
        "required": ["story_id", "story_bible"],
    },
)
async def update_story_bible(story_id: int, story_bible: dict) -> dict:
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}
        if not isinstance(story_bible, dict) or not story_bible:
            return {"error": "story_bible 必须是非空对象"}

        if _current_pending_changes():
            _current_pending_changes().record(PendingChange(
                type="story_bible",
                record_id=story.id,
                display_name=story.title,
                field="story_bible",
                old_value=dict(story.story_bible) if isinstance(story.story_bible, dict) else {},
                new_value=None,
            ))

        from services.story_state import deep_merge_story_bible

        current = deep_merge_story_bible(story.story_bible, story_bible)
        story.story_bible = current
        flag_modified(story, "story_bible")

        creative_brief = current.get("creative_brief") if isinstance(current.get("creative_brief"), dict) else {}
        next_description = str(creative_brief.get("one_line_premise") or "").strip()
        if not next_description:
            next_description = str(creative_brief.get("project_positioning") or "").strip()
        if next_description:
            story.description = next_description

        if _current_pending_changes():
            _current_pending_changes().update_new_value("story_bible", story.id, "story_bible", dict(story.story_bible))

        db.commit()
        logger.info("Agent tool=update_story_bible story=%s sections=%s", _current_story_id(), list(story_bible.keys()))
        updated_sections = list(story_bible.keys())
        return {"ok": True, "updated_sections": updated_sections}
    finally:
        db.close()


@tool_registry.register(
    name="update_characters",
    description="替换故事的角色设定列表。用户要求修改角色时，必须用此工具保存更改。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "characters": {
                "type": "array",
                "description": "角色列表，每个角色包含 name、role、description 等字段",
                "items": {"type": "object"},
            },
        },
        "required": ["story_id", "characters"],
    },
)
async def update_characters(story_id: int, characters: list[dict]) -> dict:
    """替换整个角色设定列表。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}
        if _current_pending_changes():
            _current_pending_changes().record_story_field(story, "characters")
        story.characters = characters
        if _current_pending_changes():
            _current_pending_changes().update_new_value("story", story.id, "characters", characters)
        db.commit()
        logger.info("Agent tool=update_characters story=%s count=%s", _current_story_id(), len(characters) if characters else 0)
        return {"ok": True, "count": len(characters)}
    finally:
        db.close()


@tool_registry.register(
    name="adjust_framework",
    description="通过自然语言指令调整故事框架（标签、角色、大纲、章节规划）。调用 AI 理解指令并生成精准的框架编辑操作。此操作会消耗高级文本配额。\n\n💡 分批处理：对于复杂、跨多模块的修改（如同时改角色、大纲、章节规划），建议分多次调用，每次聚焦一个模块。Agent 循环会持续运行直到全部完成，不需要一次塞进全部需求。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "instruction": {"type": "string", "description": "调整指令，描述要做的修改"},
        },
        "required": ["story_id", "instruction"],
    },
)
async def adjust_framework(story_id: int, instruction: str) -> dict:
    """根据自然语言指令调整故事框架。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}

        if _current_pending_changes():
            _current_pending_changes().record_story_field(story, "description")
            _current_pending_changes().record_story_field(story, "tags")
            _current_pending_changes().record_story_field(story, "characters")
            _current_pending_changes().record_story_field(story, "outline")

        api_key = _current_api_key()
        if not api_key:
            return {"error": "DeepSeek API Key 未配置"}

        existing_framework = {
            "description": story.description or "",
            "tags": story.tags or {},
            "characters": story.characters or [],
            "outline": story.outline or {},
        }

        story_context = _build_story_context_dict(story, user_instruction=instruction)

        messages = [{"role": "user", "content": instruction}]
        template_fw_system = get_effective_prompt(story.id, "framework_editing", db)

        from .deepseek import _infer_story_length
        story_length = _infer_story_length(story_context, description=instruction, messages=messages)

        if "【仅分析模式" in (instruction or ""):
            try:
                plan = await adjust_framework_with_chat(
                    story_context=story_context,
                    messages=messages,
                    api_key=api_key,
                    existing_framework=existing_framework,
                    story_length=story_length,
                    system_prompt=template_fw_system or None,
                )
            except ValueError as exc:
                return {"error": f"AI 返回格式无效: {exc}"}
            return {
                "ok": True,
                "reply": plan.get("reply", ""),
                "applied_operations": [],
                "warnings": ["仅分析模式：未写入数据库"],
            }

        try:
            plan = await adjust_framework_with_chat(
                story_context=story_context,
                messages=messages,
                api_key=api_key,
                existing_framework=existing_framework,
                story_length=story_length,
                system_prompt=template_fw_system or None,
            )
        except ValueError as exc:
            return {"error": f"AI 返回格式无效: {exc}"}

        apply_result = apply_framework_operations(
            existing_framework=existing_framework,
            operations=plan.get("operations"),
            patches=plan.get("patches"),
        )

        if apply_result.get("errors"):
            return {"error": "；".join(apply_result["errors"])}

        framework = apply_result["framework"]

        # ★ 自动快照：保存调整前的当前状态（用于回退）
        _save_framework_snapshot(
            story_id=story.id,
            snapshot_data=_build_current_snapshot_data(story),
            source="agent_adjust",
            reply_summary=(plan.get("reply") or "")[:255] if plan.get("reply") else None,
            db=db,
        )
        _enforce_framework_snapshot_limit(story.id, max_count=20, db=db)

        story.description = str(framework.get("description") or existing_framework["description"] or "").strip()
        story.tags = framework.get("tags") if isinstance(framework.get("tags"), dict) else existing_framework["tags"]
        story.characters = _normalize_characters_payload(framework.get("characters"))
        story.outline = framework.get("outline") if isinstance(framework.get("outline"), dict) else existing_framework["outline"]

        # ★ 任务卡完整性验证：检查保存后的章节规划是否包含 goal/conflict/hook/payoff/highlight
        saved_chapters = _extract_outline_chapters(story.outline)
        _REQUIRED_TASKCARD_FIELDS = ("goal", "conflict", "hook", "payoff", "highlight")
        for ch in saved_chapters:
            cn = ch.get("chapter_number", "?")
            missing = [f for f in _REQUIRED_TASKCARD_FIELDS if not str(ch.get(f) or "").strip()]
            if missing:
                msg = "第%s章（%s）缺少任务卡字段: %s" % (cn, (ch.get("title") or "?"), ", ".join(missing))
                warnings.append(msg)
                logger.warning("Agent tool=adjust_framework story=%s %s", _current_story_id(), msg)

        if _current_pending_changes():
            for f in ("description", "tags", "characters", "outline"):
                _current_pending_changes().update_new_value("story", story.id, f, getattr(story, f))

        db.commit()
        logger.info("Agent tool=adjust_framework story=%s ops=%s", _current_story_id(), len(plan.get("operations", [])) if isinstance(plan.get("operations"), list) else 0)

        warnings = [*plan.get("warnings", []), *apply_result.get("warnings", [])]
        return {
            "ok": True,
            "reply": plan.get("reply", ""),
            "applied_operations": apply_result.get("applied_operations", []),
            "warnings": warnings,
            "_generated_operations": plan.get("operations", []),
        }
    finally:
        db.close()


@tool_registry.register(
    name="apply_framework_ops",
    description="直接执行框架编辑操作。接收结构化的 operations 数组，立即应用到故事数据库。不调用 AI，适合你已经明确知道要做什么修改的场景（如'把主角改名为李明'、'添加一个反派角色'、'修改第三幕概要'）。复杂创作需求（如'帮我重新设计第二幕'）请用 adjust_framework。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "operations": {
                "type": "array",
                "description": "编辑操作列表，每项格式: {\"op\": \"操作名\", \"target\": {...}, \"changes\": {...}}",
                "items": {"type": "object"},
            },
            "patches": {
                "type": "array",
                "description": "JSON Patch 列表（可选）",
                "items": {"type": "object"},
            },
            "dry_run": {
                "type": "boolean",
                "description": "为 true 时只校验不执行，返回预览结果而不写入数据库（默认 false）",
            },
        },
        "required": ["story_id", "operations"],
    },
)
async def apply_framework_ops(story_id: int, operations: list, patches: list | None = None, dry_run: bool = False) -> dict:
    """直接应用框架编辑操作，不调用 AI。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}

        existing_framework = {
            "description": story.description or "",
            "tags": story.tags or {},
            "characters": story.characters or [],
            "outline": story.outline or {},
        }

        apply_result = apply_framework_operations(
            existing_framework=existing_framework,
            operations=operations,
            patches=patches or [],
        )

        if apply_result["errors"]:
            return {"error": "；".join(apply_result["errors"])}

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "preview_framework": apply_result["framework"],
                "applied_operations": apply_result["applied_operations"],
                "warnings": apply_result.get("warnings", []),
            }

        if _current_pending_changes():
            _current_pending_changes().record_story_field(story, "description")
            _current_pending_changes().record_story_field(story, "tags")
            _current_pending_changes().record_story_field(story, "characters")
            _current_pending_changes().record_story_field(story, "outline")

        framework = apply_result["framework"]
        story.description = str(framework.get("description") or "").strip()
        story.tags = framework.get("tags") if isinstance(framework.get("tags"), dict) else existing_framework["tags"]
        story.characters = _normalize_characters_payload(framework.get("characters"))
        story.outline = framework.get("outline") if isinstance(framework.get("outline"), dict) else existing_framework["outline"]

        if _current_pending_changes():
            _current_pending_changes().update_new_value("story", story.id, "description", story.description)
            _current_pending_changes().update_new_value("story", story.id, "tags", story.tags)
            _current_pending_changes().update_new_value("story", story.id, "characters", story.characters)
            _current_pending_changes().update_new_value("story", story.id, "outline", story.outline)

        _save_framework_snapshot(
            story_id=story.id,
            snapshot_data=_build_current_snapshot_data(story),
            source="agent_direct_ops",
            reply_summary=None,
            db=db,
        )
        _enforce_framework_snapshot_limit(story.id, max_count=20, db=db)
        db.commit()
        logger.info("Agent tool=apply_framework_ops story=%s ops=%s", _current_story_id(), len(operations) if operations else 0)

        return {
            "ok": True,
            "applied_operations": apply_result["applied_operations"],
            "warnings": apply_result.get("warnings", []),
        }
    finally:
        db.close()


@tool_registry.register(
    name="batch_adjust_chapters",
    description="批量调整多个章节的正文内容。适用于用户要求统一调整多章风格、同时优化多个章节等场景。每次调用可调整多章，比分别调用 adjust_chapter_by_instruction 更高效。消耗高级文本配额。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "chapters": {
                "type": "array",
                "description": "要调整的章节列表，每项包含 chapter_id 和 instruction",
                "items": {
                    "type": "object",
                    "properties": {
                        "chapter_id": {"type": "integer", "description": "章节 ID"},
                        "instruction": {"type": "string", "description": "该章节的调整指令"},
                    },
                    "required": ["chapter_id", "instruction"],
                },
            },
        },
        "required": ["chapters"],
    },
)
async def batch_adjust_chapters(chapters: list[dict]) -> dict:
    """批量调整多个章节正文。"""
    MAX_BATCH_SIZE = 10
    if not isinstance(chapters, list):
        return {"error": "chapters 必须是一个数组"}
    if len(chapters) > MAX_BATCH_SIZE:
        return {"error": f"一次最多调整 {MAX_BATCH_SIZE} 个章节"}
    api_key = _current_api_key()
    if not api_key:
        return {"error": "DeepSeek API Key 未配置"}

    async def _adjust_one(item: dict) -> dict:
        chapter_id = item.get("chapter_id")
        instruction = str(item.get("instruction") or "").strip()
        if not chapter_id or not instruction:
            return {"chapter_id": chapter_id, "error": "缺少 chapter_id 或 instruction"}
        db = SessionLocal()
        try:
            chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
            if not chapter:
                return {"chapter_id": chapter_id, "error": "章节不存在或无权访问"}
            story_obj = db.get(Story, chapter.story_id)
            if not story_obj:
                return {"chapter_id": chapter_id, "error": "所属故事不存在"}
            if _current_pending_changes():
                _current_pending_changes().record_chapter_field(chapter, "novel_content")
            story_context = _build_story_context_dict(story_obj)
            chapter_info = {
                "chapter_number": chapter.chapter_number,
                "title": chapter.title or f"第{chapter.chapter_number}章",
                "act": chapter.act or "",
                "key_events": chapter.key_events or [],
            }
            chapter_content = chapter.novel_content or ""
            template_system = get_effective_prompt(chapter.story_id, "chapter", db)
            fallback_prompt = build_agent_chapter_system_prompt(db=db)
            system_rules = template_system or fallback_prompt or ""

            from services.chapter_agents import run_chapter_creation_pipeline

            chapter_info["user_instruction"] = instruction
            pipeline_result = await run_chapter_creation_pipeline(
                story_context=story_context,
                chapter_info=chapter_info,
                api_key=api_key,
                previous_chapter_summary="",
                system_rules=system_rules,
                max_revisions=3,
                initial_content=chapter_content,
            )
            new_content = pipeline_result.get("content") or ""
            if not new_content or not new_content.strip():
                return {"chapter_id": chapter_id, "error": "AI 返回内容为空"}
            chapter.novel_content = new_content
            chapter.quality_score = {
                "review": pipeline_result.get("review"),
                "creation_pack": pipeline_result.get("creation_pack"),
                "attempts": pipeline_result.get("attempts"),
                "pipeline_approved": True,
            }
            if _current_pending_changes():
                _current_pending_changes().update_new_value("chapter", chapter.id, "novel_content", new_content)
            await _refresh_agent_memory(chapter, db)
            db.commit()
            return {"chapter_id": chapter_id, "ok": True}
        except Exception as e:
            return {"chapter_id": chapter_id, "error": str(e)}
        finally:
            db.close()

    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY_LIMIT)

    async def _adjust_one_with_limit(item: dict) -> dict:
        async with semaphore:
            return await _adjust_one(item)

    results = await asyncio.gather(*[_adjust_one_with_limit(item) for item in chapters])
    return {"ok": True, "results": results}


@tool_registry.register(
    name="add_chapter_plan",
    description="在大纲中添加一个新的章节计划。\n\n⚠️ 章节规划规则：\n- 每章必须包含 summary/goal/conflict/hook/payoff/highlight（缺一不可），这些是AI生成正文时的唯一叙事指南\n- 不要一次性规划所有卷的章节——后续卷只需幕级大纲",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "chapter": {
                "type": "object",
                "description": "章节计划对象",
                "properties": {
                    "chapter_number": {"type": "integer", "description": "章节号"},
                    "title": {"type": "string", "description": "章节标题"},
                    "summary": {"type": "string", "description": "章节概要"},
                    "act": {"type": "string", "description": "所属幕/阶段标识"},
                    "goal": {"type": "string", "description": "【前10章必填】本章叙事目标"},
                    "conflict": {"type": "string", "description": "【前10章必填】本章核心冲突"},
                    "hook": {"type": "string", "description": "【前10章必填】开篇钩子"},
                    "payoff": {"type": "string", "description": "【前10章必填】本章回报/高潮"},
                    "highlight": {"type": "string", "description": "【前10章必填】本章最大亮点"},
                    "key_events": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "关键事件列表",
                    },
                },
                "required": ["chapter_number", "title"],
            },
        },
        "required": ["story_id", "chapter"],
    },
)
async def add_chapter_plan(story_id: int, chapter: dict) -> dict:
    """在故事大纲中添加章节计划。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}

        if _current_pending_changes():
            _current_pending_changes().record_story_field(story, "outline")

        outline = story.outline if isinstance(story.outline, dict) else {}
        three_acts = outline.get("three_acts")
        if not isinstance(three_acts, list):
            three_acts = []
            outline["three_acts"] = three_acts

        act_label = chapter.get("act", "")
        # 找到或创建对应的 act
        target_act = None
        for act in three_acts:
            if isinstance(act, dict) and act.get("act") == act_label:
                target_act = act
                break
        if not target_act:
            target_act = {
                "act": act_label or f"act_{len(three_acts) + 1}",
                "title": act_label or f"第{len(three_acts) + 1}幕",
                "summary": "",
                "key_events": [],
                "chapters": [],
            }
            three_acts.append(target_act)

        act_chapters = target_act.get("chapters")
        if not isinstance(act_chapters, list):
            act_chapters = []
            target_act["chapters"] = act_chapters

        # 检查是否已存在同号章节
        chapter_number = chapter.get("chapter_number")
        for existing in act_chapters:
            if isinstance(existing, dict) and existing.get("chapter_number") == chapter_number:
                # 更新已有章节
                existing.update(chapter)
                story.outline = outline
                flag_modified(story, "outline")
                if _current_pending_changes():
                    _current_pending_changes().update_new_value("story", story.id, "outline", outline)
                db.commit()
                logger.info("Agent tool=add_chapter_plan story=%s chapter=%s action=updated", _current_story_id(), chapter_number)
                return {"ok": True, "action": "updated", "chapter_number": chapter_number}

        # 新增章节
        new_chapter = {
            "chapter_number": chapter_number,
            "title": chapter.get("title", ""),
            "summary": chapter.get("summary", ""),
            "act": act_label,
            "key_events": chapter.get("key_events", []),
            "goal": chapter.get("goal", ""),
            "conflict": chapter.get("conflict", ""),
            "hook": chapter.get("hook", ""),
            "payoff": chapter.get("payoff", ""),
            "highlight": chapter.get("highlight", ""),
        }
        # 去除空值
        new_chapter = {k: v for k, v in new_chapter.items() if v not in (None, "", [], {})}
        new_chapter["chapter_number"] = chapter_number
        new_chapter["title"] = chapter.get("title", "")

        act_chapters.append(new_chapter)

        # 按章节号排序
        act_chapters.sort(key=lambda x: x.get("chapter_number", 0) if isinstance(x, dict) else 0)

        story.outline = outline
        flag_modified(story, "outline")
        if _current_pending_changes():
            _current_pending_changes().update_new_value("story", story.id, "outline", outline)
        db.commit()
        logger.info("Agent tool=add_chapter_plan story=%s chapter=%s action=added", _current_story_id(), chapter_number)
        return {"ok": True, "action": "added", "chapter_number": chapter_number}
    finally:
        db.close()


@tool_registry.register(
    name="bulk_add_chapter_plans",
    description="批量添加多个章节计划到故事大纲中。如果用户给出了明确的章节列表，用此工具一次添加多章。如果用户只说帮我规划后续章节，用 adjust_framework 更合适。比分别调用 add_chapter_plan 更高效。\n\n⚠️ 章节规划规则：\n- 每章必须包含 summary/goal/conflict/hook/payoff/highlight（缺一不可），这些是AI生成正文时的唯一叙事指南\n- 不要一次性规划所有卷的章节——后续卷只需幕级大纲，等前卷写完后用 adjust_framework 续写",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "story_id": {"type": "integer", "description": "故事 ID"},
            "chapters": {
                "type": "array",
                "description": "章节计划列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "chapter_number": {"type": "integer", "description": "章节号"},
                        "title": {"type": "string", "description": "章节标题"},
                        "summary": {"type": "string", "description": "章节概要"},
                        "act": {"type": "string", "description": "所属幕（如 1, 2, 3）"},
                        "goal": {"type": "string", "description": "【前10章必填】本章叙事目标——推进什么情节、展示什么核心卖点"},
                        "conflict": {"type": "string", "description": "【前10章必填】本章核心冲突——谁和谁在什么层面产生对抗"},
                        "hook": {"type": "string", "description": "【前10章必填】开篇钩子——本章第一段如何抓住读者"},
                        "payoff": {"type": "string", "description": "【前10章必填】本章回报/高潮——读者读完本章能获得什么满足感"},
                        "highlight": {"type": "string", "description": "【前10章必填】本章最大亮点——区别于其他章节的独特记忆点"},
                    },
                    "required": ["chapter_number", "title"],
                },
            },
        },
        "required": ["story_id", "chapters"],
    },
)
async def bulk_add_chapter_plans(story_id: int, chapters: list[dict]) -> dict:
    """批量添加章节计划到故事大纲。"""
    db = SessionLocal()
    try:
        story = _validate_story_ownership(db, story_id, _current_story_id())
        if not story:
            return {"error": "故事不存在或无权访问"}
        if _current_pending_changes():
            _current_pending_changes().record_story_field(story, "outline")
        outline = story.outline if isinstance(story.outline, dict) else {}
        three_acts = outline.get("three_acts")
        if not isinstance(three_acts, list):
            three_acts = []
            outline["three_acts"] = three_acts

        results = []
        for chapter in chapters:
            if not isinstance(chapter, dict):
                results.append({"chapter_number": None, "ok": False, "error": "无效的章节数据"})
                continue
            chapter_number = chapter.get("chapter_number")
            act_label = str(chapter.get("act") or "").strip() or "1"
            target_act = None
            for act in three_acts:
                if isinstance(act, dict) and act.get("act") == act_label:
                    target_act = act
                    break
            if not target_act:
                target_act = {
                    "act": act_label,
                    "title": f"阶段 {act_label}",
                    "summary": "",
                    "chapters": [],
                }
                three_acts.append(target_act)
            act_chapters = target_act.get("chapters")
            if not isinstance(act_chapters, list):
                act_chapters = []
                target_act["chapters"] = act_chapters
            existing = None
            for item in act_chapters:
                if isinstance(item, dict) and item.get("chapter_number") == chapter_number:
                    existing = item
                    break
            entry = {
                "chapter_number": chapter_number,
                "title": chapter.get("title", ""),
                "summary": chapter.get("summary", ""),
                "act": act_label,
            }
            entry = {k: v for k, v in entry.items() if v not in (None, "", [], {})}
            if chapter_number is not None:
                entry["chapter_number"] = chapter_number
                entry["title"] = chapter.get("title", "")
            if existing is not None:
                existing.update(entry)
                results.append({"chapter_number": chapter_number, "ok": True, "action": "updated"})
            else:
                act_chapters.append(entry)
                results.append({"chapter_number": chapter_number, "ok": True, "action": "added"})
            act_chapters.sort(key=lambda x: x.get("chapter_number", 0) if isinstance(x, dict) else 0)
        story.outline = outline
        flag_modified(story, "outline")
        if _current_pending_changes():
            _current_pending_changes().update_new_value("story", story.id, "outline", outline)
        db.commit()
        logger.info("Agent tool=bulk_add_chapter_plans story=%s count=%s", _current_story_id(), len(chapters))
        return {"ok": True, "results": results}
    finally:
        db.close()


@tool_registry.register(
    name="update_scenes",
    description="更新/替换指定章节的分镜列表。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
            "scenes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "分镜描述字符串列表",
            },
        },
        "required": ["chapter_id", "scenes"],
    },
)
async def update_scenes(chapter_id: int, scenes: list[str]) -> dict:
    """写入章节分镜文件。"""
    db = SessionLocal()
    try:
        chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
        if not chapter:
            return {"error": "章节不存在或无权访问"}
        # 记录旧分镜内容用于撤回
        if _current_pending_changes():
            old_scenes_text = _scenes_path(chapter_id).read_text("utf-8") if _scenes_path(chapter_id).exists() else ""
            _current_pending_changes().record(PendingChange(
                type="scenes_file",
                record_id=chapter_id,
                display_name=f"第{chapter.chapter_number}章分镜",
                field="scenes_file",
                old_value=old_scenes_text,
                new_value=None,
            ))
    finally:
        db.close()
    prompts_dir = _chapter_dir(chapter_id)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    prompts_file = prompts_dir / "scenes.txt"
    new_text = ""
    try:
        for idx, scene in enumerate(scenes, start=1):
            new_text += f"=== 第{idx}格 ===\n{scene.strip()}\n\n"
        with open(prompts_file, "w", encoding="utf-8") as f:
            f.write(new_text)
        if _current_pending_changes():
            _current_pending_changes().update_new_value("scenes_file", chapter_id, "scenes_file", new_text)
        logger.info("Agent tool=update_scenes story=%s chapter=%s scenes=%s", _current_story_id(), chapter_id, len(scenes))
        return {"ok": True, "chapter_id": chapter_id, "scene_count": len(scenes)}
    except OSError as exc:
        logger.warning("写入分镜文件失败 chapter_id=%s: %s", chapter_id, exc)
        return {"error": f"写入分镜文件失败: {exc}"}


# ────────────────────────────────────────────────────────────
# 视频工作流工具 - 读取
# ────────────────────────────────────────────────────────────


@tool_registry.register(
    name="get_video_workflow",
    description="获取视频工作流状态概览：工作流状态、风格、分镜数量、进度等。",
    parameters={
        "type": "object",
        "properties": {
            "workflow_id": {"type": "integer", "description": "工作流 ID"},
        },
        "required": ["workflow_id"],
    },
    workflow_types=["video"],
)
async def get_video_workflow(workflow_id: int) -> dict:
    db = SessionLocal()
    try:
        workflow = _require_current_video_workflow(db, workflow_id)
        if not workflow:
            return {"error": "视频工作流不存在或无权访问"}
        return {
            "id": workflow.id,
            "chapter_id": workflow.chapter_id,
            "story_id": workflow.story_id,
            "workflow_status": workflow.workflow_status,
            "screenplay_status": workflow.screenplay_status,
            "video_style": workflow.video_style,
            "style_reference_image_url": workflow.style_reference_image_url,
            "duration_per_shot": workflow.duration_per_shot,
            "character_reference_ids": workflow.character_reference_ids,
            "total_shots": workflow.total_shots,
            "completed_shots": workflow.completed_shots,
            "failed_shots": workflow.failed_shots,
        }
    finally:
        db.close()


@tool_registry.register(
    name="get_workflow_shots",
    description="获取视频工作流的所有镜头摘要列表，包含镜头编号、场景、角色、状态、是否有故事版/视频。",
    parameters={
        "type": "object",
        "properties": {
            "workflow_id": {"type": "integer", "description": "工作流 ID"},
        },
        "required": ["workflow_id"],
    },
    workflow_types=["video"],
)
async def get_workflow_shots(workflow_id: int) -> dict:
    db = SessionLocal()
    try:
        workflow = _require_current_video_workflow(db, workflow_id)
        if not workflow:
            return {"error": "视频工作流不存在或无权访问"}
        shots = (
            db.query(ChapterVideoShot)
            .filter(ChapterVideoShot.workflow_id == workflow_id)
            .order_by(ChapterVideoShot.shot_index)
            .all()
        )
        return {
            "shots": [
                {
                    "id": s.id,
                    "shot_index": s.shot_index,
                    "scene_location": s.scene_location,
                    "time_of_day": s.time_of_day,
                    "characters": s.characters,
                    "status": s.status,
                    "has_storyboard": bool(s.storyboard_image_url),
                    "has_video": bool(s.video_url),
                }
                for s in shots
            ],
            "total": len(shots),
        }
    finally:
        db.close()


@tool_registry.register(
    name="get_shot_detail",
    description="获取指定镜头的完整详情，包含所有可编辑字段（prompt、镜头规划、引用等）。",
    parameters={
        "type": "object",
        "properties": {
            "shot_id": {"type": "integer", "description": "镜头 ID"},
        },
        "required": ["shot_id"],
    },
    workflow_types=["video"],
)
async def get_shot_detail(shot_id: int) -> dict:
    db = SessionLocal()
    try:
        shot = _require_current_video_shot(db, shot_id)
        if not shot:
            return {"error": "镜头不存在或无权访问"}
        return {
            "id": shot.id,
            "workflow_id": shot.workflow_id,
            "shot_index": shot.shot_index,
            "scene_location": shot.scene_location,
            "time_of_day": shot.time_of_day,
            "characters": shot.characters,
            "story_summary": shot.story_summary,
            "dialogue_or_narration": shot.dialogue_or_narration,
            "camera_plan": shot.camera_plan,
            "motion_plan": shot.motion_plan,
            "emotion_plan": shot.emotion_plan,
            "continuity_notes": shot.continuity_notes,
            "storyboard_prompt": shot.storyboard_prompt,
            "video_prompt": shot.video_prompt,
            "scene_prompt": shot.scene_prompt,
            "character_prompts_json": shot.character_prompts_json,
            "prop_prompts_json": shot.prop_prompts_json,
            "character_reference_ids": shot.character_reference_ids,
            "scene_reference_ids": shot.scene_reference_ids,
            "prop_reference_ids": shot.prop_reference_ids,
            "storyboard_image_url": shot.storyboard_image_url,
            "video_url": shot.video_url,
            "status": shot.status,
            "narrative_purpose": shot.narrative_purpose,
            "beat_density": shot.beat_density,
            "transition_to_next": shot.transition_to_next,
        }
    finally:
        db.close()


@tool_registry.register(
    name="get_video_assets",
    description="获取指定章节的视频资产列表（角色图、场景图、故事版等）。",
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "章节 ID"},
        },
        "required": ["chapter_id"],
    },
    workflow_types=["video"],
)
async def get_video_assets(chapter_id: int) -> dict:
    """获取视频资产列表。"""
    db = SessionLocal()
    try:
        assets = (
            db.query(VideoAsset)
            .filter(VideoAsset.chapter_id == chapter_id)
            .order_by(VideoAsset.asset_type, VideoAsset.name)
            .all()
        )
        return {
            "assets": [
                {
                    "id": a.id,
                    "asset_type": a.asset_type,
                    "name": a.name,
                    "file_path": a.file_path,
                    "provider": a.provider,
                    "prompt": a.prompt,
                    "meta_json": a.meta_json,
                    "status": a.status,
                    "locked": a.locked,
                    "usage_scope": a.usage_scope,
                }
                for a in assets
            ],
            "total": len(assets),
        }
    finally:
        db.close()


@tool_registry.register(
    name="get_screenplay",
    description="获取视频工作流的剧本内容（文本版和结构化 JSON）。",
    parameters={
        "type": "object",
        "properties": {
            "workflow_id": {"type": "integer", "description": "工作流 ID"},
        },
        "required": ["workflow_id"],
    },
    workflow_types=["video"],
)
async def get_screenplay(workflow_id: int) -> dict:
    db = SessionLocal()
    try:
        workflow = _require_current_video_workflow(db, workflow_id)
        if not workflow:
            return {"error": "视频工作流不存在或无权访问"}
        return {
            "workflow_id": workflow.id,
            "screenplay_text": workflow.screenplay_text,
            "screenplay_json": workflow.screenplay_json,
            "screenplay_status": workflow.screenplay_status,
            "screenplay_version": workflow.screenplay_version,
        }
    finally:
        db.close()


# ────────────────────────────────────────────────────────────
# 视频工作流工具 - 写入
# ────────────────────────────────────────────────────────────


@tool_registry.register(
    name="update_shot_prompts",
    description="更新指定镜头的 prompt 字段（storyboard_prompt, video_prompt, scene_prompt, character_prompts_json, prop_prompts_json）。只更新提供的字段。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "shot_id": {"type": "integer", "description": "镜头 ID"},
            "storyboard_prompt": {"type": "string", "description": "故事版生成提示词（可选）"},
            "video_prompt": {"type": "string", "description": "视频生成提示词（可选）"},
            "scene_prompt": {"type": "string", "description": "场景提示词（可选）"},
            "character_prompts_json": {"type": "object", "description": "角色提示词 JSON（可选）"},
            "prop_prompts_json": {"type": "object", "description": "道具提示词 JSON（可选）"},
        },
        "required": ["shot_id"],
    },
    workflow_types=["video"],
)
async def update_shot_prompts(shot_id: int, storyboard_prompt: str | None = None, video_prompt: str | None = None,
                               scene_prompt: str | None = None, character_prompts_json: dict | None = None,
                               prop_prompts_json: dict | None = None) -> dict:
    db = SessionLocal()
    try:
        shot = _require_current_video_shot(db, shot_id)
        if not shot:
            return {"error": "镜头不存在或无权访问"}
        field_map = {
            "storyboard_prompt": storyboard_prompt,
            "video_prompt": video_prompt,
            "scene_prompt": scene_prompt,
            "character_prompts_json": character_prompts_json,
            "prop_prompts_json": prop_prompts_json,
        }
        updated = []
        for field, value in field_map.items():
            if value is not None:
                if _current_pending_changes():
                    _current_pending_changes().record(PendingChange(
                        type="video_shot",
                        record_id=shot.id,
                        display_name=f"镜头 {shot.shot_index}",
                        field=field,
                        old_value=getattr(shot, field, None),
                        new_value=None,
                    ))
                setattr(shot, field, value)
                if _current_pending_changes():
                    _current_pending_changes().update_new_value("video_shot", shot.id, field, value)
                updated.append(field)
        if not updated:
            return {"ok": True, "message": "没有提供任何需要更新的字段"}
        db.commit()
        return {"ok": True, "shot_id": shot_id, "updated_fields": updated}
    finally:
        db.close()


@tool_registry.register(
    name="update_shot_fields",
    description="更新指定镜头的非 prompt 字段（场景、时间、角色、镜头规划、引用 ID 等）。只允许白名单字段。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "shot_id": {"type": "integer", "description": "镜头 ID"},
            "scene_location": {"type": "string", "description": "场景地点（可选）"},
            "time_of_day": {"type": "string", "description": "时间（可选）"},
            "characters": {"type": "array", "description": "角色列表（可选）", "items": {"type": "string"}},
            "story_summary": {"type": "string", "description": "故事摘要（可选）"},
            "camera_plan": {"type": "string", "description": "镜头规划（可选）"},
            "motion_plan": {"type": "string", "description": "运动规划（可选）"},
            "emotion_plan": {"type": "string", "description": "情感规划（可选）"},
            "character_reference_ids": {"type": "array", "description": "角色参考资产 ID 列表（可选）", "items": {"type": "integer"}},
            "scene_reference_ids": {"type": "array", "description": "场景参考资产 ID 列表（可选）", "items": {"type": "integer"}},
            "prop_reference_ids": {"type": "array", "description": "道具参考资产 ID 列表（可选）", "items": {"type": "integer"}},
        },
        "required": ["shot_id"],
    },
    workflow_types=["video"],
)
async def update_shot_fields(shot_id: int, scene_location: str | None = None, time_of_day: str | None = None,
                              characters: list | None = None, story_summary: str | None = None,
                              camera_plan: str | None = None, motion_plan: str | None = None,
                              emotion_plan: str | None = None, character_reference_ids: list | None = None,
                              scene_reference_ids: list | None = None, prop_reference_ids: list | None = None) -> dict:
    db = SessionLocal()
    try:
        shot = _require_current_video_shot(db, shot_id)
        if not shot:
            return {"error": "镜头不存在或无权访问"}
        field_map = {
            "scene_location": scene_location,
            "time_of_day": time_of_day,
            "characters": characters,
            "story_summary": story_summary,
            "camera_plan": camera_plan,
            "motion_plan": motion_plan,
            "emotion_plan": emotion_plan,
            "character_reference_ids": character_reference_ids,
            "scene_reference_ids": scene_reference_ids,
            "prop_reference_ids": prop_reference_ids,
        }
        updated = []
        for field, value in field_map.items():
            if value is not None:
                if _current_pending_changes():
                    _current_pending_changes().record(PendingChange(
                        type="video_shot",
                        record_id=shot.id,
                        display_name=f"镜头 {shot.shot_index}",
                        field=field,
                        old_value=getattr(shot, field, None),
                        new_value=None,
                    ))
                setattr(shot, field, value)
                if _current_pending_changes():
                    _current_pending_changes().update_new_value("video_shot", shot.id, field, value)
                updated.append(field)
        if not updated:
            return {"ok": True, "message": "没有提供任何需要更新的字段"}
        db.commit()
        return {"ok": True, "shot_id": shot_id, "updated_fields": updated}
    finally:
        db.close()


@tool_registry.register(
    name="update_screenplay",
    description="更新视频工作流的剧本内容（文本版和结构化 JSON）。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "workflow_id": {"type": "integer", "description": "工作流 ID"},
            "screenplay_text": {"type": "string", "description": "剧本文本（可选）"},
            "screenplay_json": {"type": "object", "description": "剧本结构化 JSON（可选）"},
        },
        "required": ["workflow_id"],
    },
    workflow_types=["video"],
)
async def update_screenplay(workflow_id: int, screenplay_text: str | None = None,
                             screenplay_json: dict | None = None) -> dict:
    db = SessionLocal()
    try:
        workflow = _require_current_video_workflow(db, workflow_id)
        if not workflow:
            return {"error": "视频工作流不存在或无权访问"}
        updated = []
        if screenplay_text is not None:
            if _current_pending_changes():
                _current_pending_changes().record(PendingChange(
                    type="video_workflow",
                    record_id=workflow.id,
                    display_name=f"工作流 {workflow.id}",
                    field="screenplay_text",
                    old_value=workflow.screenplay_text,
                    new_value=None,
                ))
            workflow.screenplay_text = screenplay_text
            if _current_pending_changes():
                _current_pending_changes().update_new_value("video_workflow", workflow.id, "screenplay_text", screenplay_text)
            updated.append("screenplay_text")
        if screenplay_json is not None:
            if _current_pending_changes():
                _current_pending_changes().record(PendingChange(
                    type="video_workflow",
                    record_id=workflow.id,
                    display_name=f"工作流 {workflow.id}",
                    field="screenplay_json",
                    old_value=workflow.screenplay_json,
                    new_value=None,
                ))
            workflow.screenplay_json = screenplay_json
            if _current_pending_changes():
                _current_pending_changes().update_new_value("video_workflow", workflow.id, "screenplay_json", screenplay_json)
            updated.append("screenplay_json")
        if not updated:
            return {"ok": True, "message": "没有提供任何需要更新的字段"}
        db.commit()
        return {"ok": True, "workflow_id": workflow_id, "updated_fields": updated}
    finally:
        db.close()


# ────────────────────────────────────────────────────────────
# 视频工作流工具 - 批量操作
# ────────────────────────────────────────────────────────────


@tool_registry.register(
    name="batch_update_shot_prompts",
    description="批量更新多个镜头的 prompt 字段（storyboard_prompt, video_prompt, scene_prompt, character_prompts_json, prop_prompts_json）。一次最多 10 个镜头，比逐个调用 update_shot_prompts 更高效。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "shots": {
                "type": "array",
                "description": "要更新的镜头列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "shot_id": {"type": "integer", "description": "镜头 ID"},
                        "storyboard_prompt": {"type": "string", "description": "故事版生成提示词（可选）"},
                        "video_prompt": {"type": "string", "description": "视频生成提示词（可选）"},
                        "scene_prompt": {"type": "string", "description": "场景提示词（可选）"},
                        "character_prompts_json": {"type": "object", "description": "角色提示词 JSON（可选）"},
                        "prop_prompts_json": {"type": "object", "description": "道具提示词 JSON（可选）"},
                    },
                    "required": ["shot_id"],
                },
            },
        },
        "required": ["shots"],
    },
    workflow_types=["video"],
)
async def batch_update_shot_prompts(shots: list[dict]) -> dict:
    MAX_BATCH_SIZE = 10
    if not isinstance(shots, list):
        return {"error": "shots 必须是一个数组"}
    if len(shots) > MAX_BATCH_SIZE:
        return {"error": f"一次最多更新 {MAX_BATCH_SIZE} 个镜头"}

    async def _update_one(item: dict) -> dict:
        shot_id = item.get("shot_id")
        if not shot_id:
            return {"shot_id": shot_id, "error": "缺少 shot_id"}
        db = SessionLocal()
        try:
            shot = _require_current_video_shot(db, shot_id)
            if not shot:
                return {"shot_id": shot_id, "error": "镜头不存在或无权访问"}
            field_map = {
                "storyboard_prompt": item.get("storyboard_prompt"),
                "video_prompt": item.get("video_prompt"),
                "scene_prompt": item.get("scene_prompt"),
                "character_prompts_json": item.get("character_prompts_json"),
                "prop_prompts_json": item.get("prop_prompts_json"),
            }
            updated = []
            for field, value in field_map.items():
                if value is not None:
                    if _current_pending_changes():
                        _current_pending_changes().record(PendingChange(
                            type="video_shot",
                            record_id=shot.id,
                            display_name=f"镜头 {shot.shot_index}",
                            field=field,
                            old_value=getattr(shot, field, None),
                            new_value=None,
                        ))
                    setattr(shot, field, value)
                    if _current_pending_changes():
                        _current_pending_changes().update_new_value("video_shot", shot.id, field, value)
                    updated.append(field)
            if not updated:
                return {"shot_id": shot_id, "ok": True, "message": "没有提供任何需要更新的字段"}
            db.commit()
            return {"shot_id": shot_id, "ok": True, "updated_fields": updated}
        except Exception as e:
            return {"shot_id": shot_id, "error": str(e)}
        finally:
            db.close()

    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY_LIMIT)

    async def _update_one_with_limit(item: dict) -> dict:
        async with semaphore:
            return await _update_one(item)

    results = await asyncio.gather(*[_update_one_with_limit(item) for item in shots])
    return {"ok": True, "results": results}


@tool_registry.register(
    name="batch_update_shot_fields",
    description="批量更新多个镜头的非 prompt 字段（场景、时间、角色、镜头规划、引用 ID 等）。一次最多 10 个镜头，比逐个调用 update_shot_fields 更高效。",
    is_write=True,
    parameters={
        "type": "object",
        "properties": {
            "shots": {
                "type": "array",
                "description": "要更新的镜头列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "shot_id": {"type": "integer", "description": "镜头 ID"},
                        "scene_location": {"type": "string", "description": "场景地点（可选）"},
                        "time_of_day": {"type": "string", "description": "时间（可选）"},
                        "characters": {"type": "array", "description": "角色列表（可选）", "items": {"type": "string"}},
                        "story_summary": {"type": "string", "description": "故事摘要（可选）"},
                        "camera_plan": {"type": "string", "description": "镜头规划（可选）"},
                        "motion_plan": {"type": "string", "description": "运动规划（可选）"},
                        "emotion_plan": {"type": "string", "description": "情感规划（可选）"},
                        "character_reference_ids": {"type": "array", "description": "角色参考资产 ID 列表（可选）", "items": {"type": "integer"}},
                        "scene_reference_ids": {"type": "array", "description": "场景参考资产 ID 列表（可选）", "items": {"type": "integer"}},
                        "prop_reference_ids": {"type": "array", "description": "道具参考资产 ID 列表（可选）", "items": {"type": "integer"}},
                    },
                    "required": ["shot_id"],
                },
            },
        },
        "required": ["shots"],
    },
    workflow_types=["video"],
)
async def batch_update_shot_fields(shots: list[dict]) -> dict:
    MAX_BATCH_SIZE = 10
    if not isinstance(shots, list):
        return {"error": "shots 必须是一个数组"}
    if len(shots) > MAX_BATCH_SIZE:
        return {"error": f"一次最多更新 {MAX_BATCH_SIZE} 个镜头"}

    async def _update_one(item: dict) -> dict:
        shot_id = item.get("shot_id")
        if not shot_id:
            return {"shot_id": shot_id, "error": "缺少 shot_id"}
        db = SessionLocal()
        try:
            shot = _require_current_video_shot(db, shot_id)
            if not shot:
                return {"shot_id": shot_id, "error": "镜头不存在或无权访问"}
            field_map = {
                "scene_location": item.get("scene_location"),
                "time_of_day": item.get("time_of_day"),
                "characters": item.get("characters"),
                "story_summary": item.get("story_summary"),
                "camera_plan": item.get("camera_plan"),
                "motion_plan": item.get("motion_plan"),
                "emotion_plan": item.get("emotion_plan"),
                "character_reference_ids": item.get("character_reference_ids"),
                "scene_reference_ids": item.get("scene_reference_ids"),
                "prop_reference_ids": item.get("prop_reference_ids"),
            }
            updated = []
            for field, value in field_map.items():
                if value is not None:
                    if _current_pending_changes():
                        _current_pending_changes().record(PendingChange(
                            type="video_shot",
                            record_id=shot.id,
                            display_name=f"镜头 {shot.shot_index}",
                            field=field,
                            old_value=getattr(shot, field, None),
                            new_value=None,
                        ))
                    setattr(shot, field, value)
                    if _current_pending_changes():
                        _current_pending_changes().update_new_value("video_shot", shot.id, field, value)
                    updated.append(field)
            if not updated:
                return {"shot_id": shot_id, "ok": True, "message": "没有提供任何需要更新的字段"}
            db.commit()
            return {"shot_id": shot_id, "ok": True, "updated_fields": updated}
        except Exception as e:
            return {"shot_id": shot_id, "error": str(e)}
        finally:
            db.close()

    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY_LIMIT)

    async def _update_one_with_limit(item: dict) -> dict:
        async with semaphore:
            return await _update_one(item)

    results = await asyncio.gather(*[_update_one_with_limit(item) for item in shots])
    return {"ok": True, "results": results}


# ── AI 味检测工具 ────────────────────────────────────────


@tool_registry.register(
    name="check_ai_flavor",
    description="检测指定章节正文中的 AI 写作痕迹，包括禁用词、句式套路、心理描写外化、节奏均匀度、结尾升华、解释腔等。返回检测报告和修改建议。",
    is_write=False,
    parameters={
        "type": "object",
        "properties": {
            "chapter_id": {"type": "integer", "description": "要检测的章节 ID"},
        },
        "required": ["chapter_id"],
    },
)
async def check_ai_flavor(chapter_id: int) -> dict:
    db = SessionLocal()
    try:
        chapter = _validate_chapter_ownership(db, chapter_id, _current_story_id())
        if not chapter:
            return {"error": "章节不存在或无权访问"}
        content = chapter.novel_content or ""
        if not content.strip():
            return {"error": "章节内容为空，无法检测"}

        # 从 banned-words.md 读取禁用词表（单一数据源，修改 .md 文件即可同步）
        banned_words = get_banned_words()
        # 从 banned-words.md 读取禁用句式模式
        raw_patterns = get_banned_patterns()
        pattern_checks: dict[str, list[str]] = {}
        for p in raw_patterns:
            pattern_checks[p["name"]] = p.get("patterns", [])
        # 程序检测项（不依赖词表）
        pattern_checks.setdefault("连续排比句（3+）", [])
        pattern_checks.setdefault("结尾总结升华", [])

        lines = content.split("\n")
        non_empty_lines = [l for l in lines if l.strip()]
        total_chars = len(content)

        # 禁用词扫描
        banned_hits = []
        for word in banned_words:
            count = content.count(word)
            if count > 0:
                banned_hits.append({"词": word, "命中次数": count})

        # 句式模式扫描
        pattern_hits = []
        for pattern_name, patterns in pattern_checks.items():
            for p in patterns:
                if p in content:
                    pattern_hits.append({"模式": pattern_name, "匹配": p})

        # 段落均匀度检测
        paragraph_lengths = [len(l) for l in non_empty_lines]
        if paragraph_lengths:
            avg_len = sum(paragraph_lengths) / len(paragraph_lengths)
            too_uniform = all(abs(l - avg_len) < avg_len * 0.3 for l in paragraph_lengths) if len(paragraph_lengths) >= 3 else False
        else:
            too_uniform = False

        # 结尾检测
        last_lines = non_empty_lines[-3:] if len(non_empty_lines) >= 3 else non_empty_lines
        ending_issues = []
        for line in last_lines:
            if any(kw in line for kw in ["他知道", "她明白", "这一刻", "这一切", "终于", "新的"]):
                ending_issues.append(line.strip()[:50])

        # 心理描写外化检测
        psych_hits = content.count("他感到") + content.count("她感觉") + content.count("他觉得很") + content.count("她觉得")

        # 叙事结构检测（对抗 AI 叙事 5 大缺陷）
        narrative_issues = []

        passive_patterns = ["被动", "被迫", "不得不", "只好", "只能", "身不由己"]
        passive_count = sum(content.count(p) for p in passive_patterns)
        if passive_count > 5:
            narrative_issues.append({
                "type": "passive_protagonist",
                "severity": "high" if passive_count > 10 else "medium",
                "count": passive_count,
                "message": f"主角被动反应词出现 {passive_count} 次，建议增加主动决策",
            })

        moral_absolutes = ["天生邪恶", "骨子里坏", "纯粹的恶", "生来就是", "天性残忍"]
        moral_count = sum(content.count(m) for m in moral_absolutes)
        if moral_count > 0:
            narrative_issues.append({
                "type": "moral_simplification",
                "severity": "medium",
                "count": moral_count,
                "message": "检测到道德二元化描述，反派应有合理动机",
            })

        theme_statements = ["我终于明白", "这就是成长", "原来真正的", "成长的意义", "真正的力量"]
        theme_count = sum(content.count(t) for t in theme_statements)
        if theme_count > 0:
            narrative_issues.append({
                "type": "theme_overexplanation",
                "severity": "high",
                "count": theme_count,
                "message": f"检测到 {theme_count} 处主题直白点破，应用事件体现主题",
            })

        scene_breaks = content.count("\n\n")
        if scene_breaks < 3 and total_chars > 1000:
            narrative_issues.append({
                "type": "single_track_narrative",
                "severity": "low",
                "message": f"场景切换仅 {scene_breaks} 次，疑似单线叙事",
            })

        # 评分
        total_hits = len(banned_hits) + len(pattern_hits) + psych_hits + sum(n.get("count", 1) for n in narrative_issues)
        density = total_hits / max(total_chars / 1000, 1)
        if density <= 5:
            level = "轻度"
        elif density <= 15:
            level = "中度"
        else:
            level = "重度"

        return {
            "ok": True,
            "chapter_id": chapter_id,
            "chapter_title": chapter.title or "未命名",
            "total_chars": total_chars,
            "ai_flavor_level": level,
            "banned_word_hits": banned_hits,
            "pattern_hits": pattern_hits,
            "psych_tell_count": psych_hits,
            "narrative_issues": narrative_issues,
            "paragraphs_too_uniform": too_uniform,
            "ending_issues": ending_issues,
            "total_hits": total_hits,
            "density_per_1000_chars": round(density, 1),
            "suggestion": "请参考检测结果，对命中项逐一修改。重点关注：禁用词替换为具体动作、心理描写外化为行为展示、打破段落均匀度、结尾去升华。叙事结构问题（主角被动/道德简化/主题点破/单线叙事）需通过重构情节解决。",
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        db.close()


# ── 内部辅助 ──────────────────────────────────────────────


def _build_story_context_dict(story: Story, user_instruction: str = "") -> dict:
    """构建 story_context 字典，与 main._build_framework_ai_context 对齐。"""
    outline = story.outline if isinstance(story.outline, dict) else {}
    chapters = _extract_outline_chapters(outline)
    chapter_numbers = [item["chapter_number"] for item in chapters if isinstance(item.get("chapter_number"), int)]
    return {
        "description": story.description or "",
        "tags": story.tags,
        "characters": story.characters,
        "outline": outline,
        "story_bible": story.story_bible,
        "story_bible_compact": build_story_bible_compact(story.story_bible),
        "story_memory": story.story_memory,
        "story_memory_compact": build_story_memory_compact(story.story_memory),
        "outline_compact": _build_outline_compact(outline),
        "framework_stats": {
            "mode": "agent",
            "stage_count": len(outline.get("three_acts") or []) if isinstance(outline.get("three_acts"), list) else 0,
            "chapter_count": len(chapters),
            "last_chapter_number": max(chapter_numbers) if chapter_numbers else 0,
        },
        "user_instruction": user_instruction.strip(),
    }


# _build_bible_compact 和 _build_memory_compact 已迁移至 services.story_state
# 统一使用 build_story_bible_compact / build_story_memory_compact


# ── Agent 服务 ─────────────────────────────────────────────


class AgentService:
    """Agent 服务：构建故事上下文，调用 DeepSeek function calling，执行工具，流式返回。"""

    def __init__(self):
        self.tool_registry = tool_registry

    def _build_writing_quality_section(self, db=None) -> str:
        """构建正文写作参考规范（供 Agent 分析和评估时参考）。

        正文生成已委托给框架管道（generate_chapter_content），其中内置了字数铁律/场景经济性/
        对话铁律/章末钩子/AI禁令等完整约束。此段落仅供 Agent 做分析/评估/优化建议时参考。
        """
        full_prompt = build_agent_chapter_system_prompt(db=db)
        if not full_prompt:
            return ""
        return (
            "\n\n---\n\n"
            "## ✍️ 正文写作参考规范\n\n"
            "**正文生成已委托给框架创作引擎（generate_chapter_content 工具），引擎内置了字数铁律（2800上限）、"
            "场景经济性（400字无变化即切）、对话铁律、章末钩子强制等起点签约级质量约束。**\n\n"
            "以下规范供你在分析/评估/优化建议时参考：\n\n"
            + full_prompt
        )

    async def _compress_history_with_ai(self, old_messages: list[dict], api_key: str) -> str:
        """用 AI 调用压缩旧对话历史为结构化摘要，确保记忆不丢失。"""
        import httpx
        from services.deepseek import _deepseek_auth_headers, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
        from services.token_utils import build_history_summary_prompt, build_history_summary_system_prompt

        user_prompt = build_history_summary_prompt(old_messages)
        system_prompt = build_history_summary_system_prompt()

        payload = {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 4096,
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                json=payload,
                headers=_deepseek_auth_headers(api_key),
            )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    def _build_system_prompt(self, story_context: str, story_id: int = 0, workflow_type: str | None = None, enabled_skills: list[str] | None = None, db=None) -> str:
        """构建包含故事上下文的系统提示。"""
        story_id_line = f"\n当前作品 ID: {story_id}" if story_id else ""
        video_section = ""
        if workflow_type == "video":
            video_section = """

---

## 🎬 视频工作流助手模式

你正在视频工作流上下文中运行。除了常规的小说创作工具外，你还可以使用以下**视频专属工具**：

### 读取工具
- `get_video_workflow` — 查看工作流状态（进度、风格、分镜数量）
- `get_workflow_shots` — 列出所有分镜摘要（场景、角色、状态）
- `get_shot_detail` — 查看单个分镜的完整详情（所有 prompt、规划、引用）
- `get_video_assets` — 查看章节的视频资产列表（角色图、场景图等）
- `get_screenplay` — 查看剧本内容（文本版和结构化 JSON）

### 写入工具（仅 execute 模式）
- `update_shot_prompts` — 更新单个分镜 prompt（故事版、视频、场景、角色、道具）
- `batch_update_shot_prompts` — 批量更新多个分镜 prompt（一次最多 10 个，比逐个调用更高效）
- `update_shot_fields` — 更新单个分镜字段（场景、时间、角色、镜头/运动/情感规划、引用 ID）
- `batch_update_shot_fields` — 批量更新多个分镜字段（一次最多 10 个，比逐个调用更高效）
- `update_screenplay` — 更新剧本内容（文本和结构化 JSON）

### 批量操作建议
- 当需要修改多个镜头时，**优先使用批量工具**（`batch_update_shot_prompts` / `batch_update_shot_fields`），一次调用即可完成
- 批量和单个工具使用相同的字段名，只需将参数包装在 `shots` 数组中
- 每个镜头只需提供要修改的字段，未提供的字段保持不变

### 禁止操作
- **禁止调用小说创作相关的写入工具**（如 `update_chapter_content`、`adjust_chapter_by_instruction` 等），这些工具在视频工作流模式下不可用
- **禁止修改故事框架、角色设定、章节内容**，你只能操作视频工作流相关的数据
- 如果需要修改小说内容，请退出视频工作流模式后再操作
"""
        skills_section = ""
        if enabled_skills:
            skills_fragment = skill_registry.build_fragment(enabled_skills, db=db)
            if skills_fragment:
                active_skill_names = []
                for sn in enabled_skills:
                    sk = skill_registry.get(sn)
                    if sk:
                        active_skill_names.append(f"{sk.icon} {sk.display_name}")
                skills_section = f"""
---
## 🔧 当前激活的技能

{', '.join(active_skill_names)}

{skills_fragment}
"""
        writing_quality = self._build_writing_quality_section(db=db)
        return f"""你是 Manwen-Studio 的 AI 创作助手，拥有直接读写故事数据库的工具权限。{story_id_line}{video_section}

**你的工作方式**：每次收到用户输入，先理解用户真正想要什么，再决定怎么做。不是每次都需要调用工具——用户可以只是想聊聊天。

---

## 🧭 第一步：理解用户意图（先思考，再行动）

每次收到用户输入，先在大脑里问自己三个问题：
1. **用户这句话的核心目的是什么？** 是想讨论想法、分析问题、查询信息，还是让我动手改东西？
2. **用户预期我的角色是什么？** 是创作顾问（给建议）、执行者（动手改）、还是信息员（查资料）？
3. **我需要调用工具吗？** 还是直接用我已经知道的上下文就能回答？

完成这个思考后，按以下分类确定行为模式：

| 意图类型 | 典型用户表述 | 你的行为模式 |
|----------|-------------|-------------|
| **💬 聊天探讨 / 创意交流** | "你觉得主角动机够不够"、"我在想下一章该让谁出场"、"这样写会不会太拖"、"我想让故事更悬疑有什么方向"、"你觉得这样设计合理吗"、"我有个想法……" | **不需要调任何工具**。直接基于已有的故事上下文进行创作讨论、提供思路、探讨方向、给出专业见解。你的角色是创作顾问。 |
| **🔍 分析 / 评估** | "分析结构"、"评估节奏"、"检查伏笔"、"提出优化建议"、"有什么问题"、"review这段"、"看看哪里可以改进" | 先调用读取工具获取数据 → 输出系统性分析/评估/建议 → **等待用户确认是否修改**（禁止调用写入工具） |
| **📖 查询 / 了解** | "有哪些章节"、"写了什么"、"帮我查一下"、"告诉我……"、"当前设定是什么" | 调用读取工具获取数据并回答即可 |
| **✏️ 明确修改** | "把这段改成……"（附具体文本）、"改成这样"、"删除"、"替换为" | 先读取确认现状 → 调用写入工具执行修改 → 说明结果 |
| **🎨 模糊创作** | "帮我重写"、"优化一下"、"改得更好"（无具体改动文本） | 先读取数据 → 给出具体修改方案 → **等待用户确认后再执行** |
| **🔄 混合意图** | "先分析再优化"、"看看有什么问题然后调整" | 先分析/评估 → 输出发现和建议 → **等待用户确认后再执行修改** |

> 关键原则：**用户说"你觉得"/"我想"/"我在想"/"这样会不会"等表述时，大概率是在聊天探讨，而不是要你动手改。** 优先用已有的上下文知识和他讨论，不需要每次都要读数据、调工具。

---

## 🔧 第二步：根据意图选择合适的工具

### 读取工具（用于分析 / 查询）
- `get_chapter_full` — 读取某章节的完整正文内容
- `get_all_chapters_summary` — 列出所有章节（编号/标题/字数/状态）
- `get_framework_detail` — 读取标签、角色设定、故事大纲
- `get_story_bible` — 读取作品圣经（创意简报/写作指导）
- `get_scenes` — 读取分镜列表
- `get_character_profiles` — 读取角色外貌设定

### 写入工具（用于执行修改）
- `generate_chapter_content` — **🎯 生成章节正文的首选工具**。委托框架创作引擎生成（与框架直出质量完全一致，含字数铁律/场景经济性/对话铁律/章末钩子/AI禁令）。适用于用户要求「写出」「生成」「创作」「写」某章正文时。需先确保章节规划完整（含任务卡）。
- `update_chapter_content` — 直接保存整章正文（仅当用户已给出完整改写文本时用。如果需要 AI 生成正文，请使用 `generate_chapter_content`）
- `rewrite_text_segment` — 查找并替换章节中的特定段落（精确匹配替换）
- `adjust_chapter_by_instruction` — 根据用户指令让 AI 重写整章（消耗高级配额，仅用于已有正文章节的重写/调整风格，不用于初版生成。初版生成请用 `generate_chapter_content`）
- `update_story_info` — 修改标题/描述/标签
- `update_story_bible` — 更新作品圣经（世界观设定/创意简报/写作指导），支持部分更新。用户要求调整世界观、修改核心设定时用此工具
- `update_characters` — 替换角色设定列表
- `apply_framework_ops` — **直接执行框架编辑操作**，不调用 AI，适合明确的增删改（如"把主角改名"、"加个反派"、"改章节标题"）
- `adjust_framework` — 根据指令调整故事框架/大纲，**适合需要 AI 创作的场景**（如"帮我重新设计第二幕"、"让故事更悬疑"）。消耗高级配额。如果改动明确请优先用 apply_framework_ops
- `add_chapter_plan` — 在大纲中添加新的章节计划
- `bulk_add_chapter_plans` — **批量添加多个章节规划**（用户给出明确章节列表时用，比多次调 add_chapter_plan 更高效）
- `update_scenes` — 更新分镜列表

---

## 📋 第三步：场景 → 行动对照表

| 用户说 | 你应该 |
|--------|--------|
| "你觉得……怎么样"、"我在想……"、"这样会不会……"、"我有个想法" | **直接对话讨论**。基于故事上下文给出见解和思路，不需要调用任何工具 |
| "帮我分析一下故事结构/框架/节奏/伏笔" | 调 `get_framework_detail` + `get_all_chapters_summary`（需要时加 `get_chapter_full`）→ 给出分析 → 等待用户反馈 |
| "帮我检查这一章写得怎么样" | 调 `get_chapter_full` 读取本章 → 给出评价/问题/建议 → 等待用户反馈 |
| "提出优化建议" | 调读取工具获取数据 → 输出具体优化方案列表 → 等用户选定后执行 |
| "把这段改成……"（附具体文本） | 调 `rewrite_text_segment` 或 `update_chapter_content` 直接执行 |
| "帮我重写这一章，改成……风格"（无具体文本） | 先调 `get_chapter_full` 读取本章 → 给出重写方案/方向让用户确认 → 再调 `adjust_chapter_by_instruction` |
| "帮我修改角色设定" | 调 `get_framework_detail` 查看当前角色 → 给出修改方案 → 待确认后调 `update_characters` |
| "帮我调整世界观/修改核心设定/改作品圣经" | 调 `get_story_bible` 查看当前圣经 → 给出调整方案 → 待确认后调 `update_story_bible` |
| **用户在对话中详细描述了世界观设定**（如力量体系、势力分布、等级划分、世界历史等具体内容） | **主动调用 `update_story_bible`** 将讨论确认的内容保存到 world_setting 中。不要等用户说出"改作品圣经"才保存。world_setting 是 `creative_brief` 下的嵌套 JSON，建议包含 power_system（力量体系）、society_structure（社会结构）、key_locations（关键地点）、world_history（世界历史）、hidden_truths（隐藏真相）等子字段，也接受任意其他键名。保存后说明存入了哪些设定模块 |
| "帮我调整大纲/结构" | 调 `get_framework_detail` 查看当前大纲 → 给出调整方案 → 待确认后调 `apply_framework_ops`（明确改动）或 `adjust_framework`（需要 AI 创作） |
| "添加一个新章节" | 调 `get_framework_detail` 查看现有章节 → 给出新章节建议位置 → 待确认后调 `add_chapter_plan` |
| "写/生成/创作第X章正文" | ① 调 `get_framework_detail` 确认大纲中有该章规划且任务卡完整 → ② 调 `create_chapter` 创建章节行（如果尚未创建）→ ③ 调 `generate_chapter_content` 委托框架引擎生成正文 ★ **不要用 `update_chapter_content` 代替 `generate_chapter_content`，前者用于保存用户提供的现成文本，后者才调用 AI 生成** |
| "看看这一章写了什么" | 调 `get_chapter_full` → 总结/展示内容 |
| "有哪些章节，进展如何" | 调 `get_all_chapters_summary` → 呈现概览 |

---

## 📌 核心行为准则

1. **不是每次都要调工具**。如果用户在聊天探讨、讨论创作方向、征求意见，直接用已有的故事上下文（你下面的"故事上下文"部分已经包含了作品信息）参与讨论即可。
2. **每次收到新消息，先把历史中最后一条用户消息作为当前要处理的消息**。不要忽略最新消息去回答之前的问题。新消息是独立的请求。
3. **先理解意图，再决定行动**。每收到一条消息，先花一秒想"用户想干嘛"，而不是默认去改东西。
4. **分析/评估永远必须先读取数据**。没有数据支撑的分析等于空谈。
5. **分析/评估模式下，禁止调用任何写入工具**。输出分析建议后等待用户明确指示"好，按这个改"。如果用户接着要求"按你说的改"，再开始执行修改。
6. **明确修改时，必须先读取确认现状**，再进行修改，避免覆盖已有内容。
7. **模糊创作需求（无具体修改文本）**，先读数据 → 出方案 → 等确认 → 再执行。不要跳过确认步骤。
    8. **所有修改必须通过工具调用实际写入数据库**。文字回复不能代替工具调用。如果你在回复中说"已更新""已修改""已保存"但没有实际调用写入工具，那么修改并没有被保存——文本只是文字，只有工具调用才会真正写入数据库。请务必在每次声称修改后，检查自己是否真的调用了写入工具。
    9. **不要暴露工具名和参数等内部细节**，用自然的创作语言说明你做了什么。
    10. **可以并行调用多个读取工具**（如同时获取框架和章节列表），以提高效率。
    11. **工具调用后我会把结果返回给你**，根据返回的数据决定下一步行动。
    12. **⚠️ 工具调用失败时**：如果返回结果中包含 `"error"` 字段，说明工具执行出错。此时你应当：
        - 告知用户工具执行遇到了什么问题（用自然语言，不要暴露细节）
        - 询问用户能否提供正确的参数信息
        - 如果是因为缺少参数（如 `story_id`），当前作品 ID 已在上方注明
        - **不要默默忽略错误去用其他数据回答问题**。如果工具没法用，就想办法用已有的上下文知识给用户提供帮助，但要明确说明你目前能做什么、不能做什么
    13. **⚠️ 工具返回错误时不代表修改成功**。即使工具返回了 `{{"error": "..."}}`，也不要声称修改已完成。必须如实告知用户工具执行失败，并请用户提供正确的参数或重试。
    14. **📌 分批处理原则**：根据数据类型选择合适的策略——确定性的数据批量处理，需要 AI 创作的内容分批处理。

        **批量处理（数据确定时）**：
        - 用户给出了完整的具体内容时，使用批量工具一次提交：
          - `batch_update_chapters` — 用户已给出每章完整改写文本时
          - `bulk_add_chapter_plans` — 用户给出明确的章节列表时
          - `update_characters` — 传入完整角色列表
          - `update_scenes` — 一次替换完整分镜列表

        **分批处理（需要 AI 创作时）**：
        - 涉及 AI 生成的修改（调整世界观、重写多章风格、创作大纲调整），**优先分批处理**：
          - 每次调用只处理 2-3 个模块或章节，不要试图一次完成全部
          - 先汇报进度（已完成部分），再继续下一批
          - 利用 Agent 循环的持续迭代特性，分批完成全部工作
        - 示例：调整世界观 3 个模块 → 分 3 次调用 `update_story_bible`，每次只更新 1 个模块
        - 示例：重写 6 章内容 → 分 2-3 批使用 `batch_adjust_chapters`，每批 2-3 章

        **⚠️ 不要在一次调用中塞入过多数据**，特别是 `update_story_bible` 的 world_setting 和 `adjust_framework` 的 instruction。单次数据量过大会导致超时或截断。使用多次迭代，每次做一小批，Agent 循环会持续运行直到全部完成。

    15. **⚠️ 框架完成后禁止自动生成正文**。只有当用户明确说"生成第X章""写第X章""写正文""创作正文""续写第X章"等指令时，才调用 `generate_chapter_content` 生成章节正文。
        - 完成框架/大纲/角色设定后，应当告知用户"框架已就绪，您可以让我生成第1章正文"，然后**等待用户确认**。
        - **禁止**在用户只要求"生成框架""创建大纲""设定角色""补充章节规划"时自动生成章节正文。
        - **禁止**在框架调整、大纲续写、角色更新等操作后主动追加"顺便生成第1章"。
        - 正文生成是用户的主动决策，不是框架完成后的自动步骤。

### 📖 章节规划数量控制（强制规则）

**不要一次性输出所有卷的章节规划。** 长篇小说的框架应该分阶段构建：

| 阶段 | 规划内容 | 详细程度 |
|------|---------|---------|
| **当前卷** | 如果用户有要求多少章则严格根据用户要求进行生成规划，如果没有硬性要求则生成十章即可 | **每章必须有完整任务卡**：summary/goal/conflict/hook/payoff/highlight 缺一不可 |
| **后续卷** | 第 2-6 卷 | **只规划幕级大纲**：每幕只需 act/title/summary，chapters 设为空数组 |
| **续写时** | 查看当前最新的末尾章节内容，然后在这个基础上进行续写规划章节| 等前卷写完后，用 `adjust_framework` 为下一卷生成详细章节（含完整任务卡） |

**为什么不能一次性输出全部章节？**
1. 一次性输出 60+ 章的详细规划会导致 AI 偷懒，跳过后续章节的任务卡字段
2. 后续卷的剧情应该根据前卷的实际写作情况动态调整
3. 任务卡字段是 AI 生成正文的**唯一叙事指南**，缺少任何字段都会导致正文偏离大纲

**正确的操作流程**：
- 用户说"补充第2-6卷的章节规划" → 先创建第2-6卷的**幕级大纲**（act/title/summary），chapters 留空
- 用户说"生成第二卷的章节" → 用 `adjust_framework` 为第二卷生成前 10 章详细规划（含完整任务卡）
- 不要用 `bulk_add_chapter_plans` 一次性添加 50+ 章
- **⚠️ 使用 `bulk_add_chapter_plans` 或 `add_chapter_plan` 添加任何章节时，即使 schema 不强制，也必须传入 summary/goal/conflict/hook/payoff/highlight 全部 6 个字段，缺一不可。这些是 AI 生成正文的唯一叙事指南。**

### 框架修改工具选择决策树

框架修改时，按以下优先级选择工具：

| 场景 | 推荐工具 | 原因 |
|------|---------|------|
| 用户给出明确修改（"把 X 改成 Y"、"删除角色 Z"、"加 5 章"） | `apply_framework_ops` / `bulk_add_chapter_plans` | 一次 LLM 调用，零额外 AI 成本 |
| 用户需要 AI 创作/生成内容（"让故事更悬疑"、"重新设计第二幕"） | `adjust_framework` | 需要 AI 创作能力生成具体方案 |

原则：**能用 `apply_framework_ops` 解决的，不要用 `adjust_framework`**。

### 框架直接编辑（apply_framework_ops 操作格式参考）

`apply_framework_ops` 的 `operations` 参数结构：

```json
[
  {{"op": "操作名", "target": {{...}}, "changes": {{...}}}},
  {{"op": "操作名", "target": {{...}}, "changes": {{...}}}}
]
```

| op | target | changes | 说明 |
|----|--------|---------|------|
| `update_story_description` | — | `{{"description": "..."}}` | 更新故事描述 |
| `update_tags` | — | `{{...}}` | 更新标签（tags.type/theme/style/audience） |
| `add_character` | — | `{{"name": "...", "role": "...", ...}}` | 添加角色 |
| `update_character` | `{{"name": "角色名"}}` | `{{...}}` | 更新指定角色 |
| `remove_character` | `{{"name": "角色名"}}` | — | 删除角色 |
| `update_act_summary` | `{{"act": "幕标识"}}` | `{{"summary": "..."}}` | 更新幕概要 |
| `add_chapter` | `{{"act": "幕标识"}}` | `{{"chapter_number": N, "title": "...", ...}}` | 添加章节规划 |
| `update_chapter` | `{{"chapter_number": N}}` | `{{"title": "...", "summary": "...", ...}}` | 更新章节规划 |
| `insert_chapter_after` | `{{"chapter_number": N}}` | `{{"chapter_number": N+1, "title": "...", ...}}` | 在指定章节后插入 |
| `move_chapter_to_act` | `{{"chapter_number": N, "act": "目标幕"}}` | — | 移动章节到另一幕 |
| `delete_chapter` | `{{"chapter_number": N}}` | — | 删除章节 |

> 💡 `apply_framework_ops` 支持 `dry_run=true` 参数：设为 true 时只校验不写入数据库，返回预览结果。适合需要先看一眼改动效果再确认的场景。

示例：用户说"把主角改名为李明，添加一个反派叫张三，把第 5 章标题改为'真相'"
→ 调用 apply_framework_ops，operations:
```json
[
  {{"op": "update_character", "target": {{"name": "原主角名"}}, "changes": {{"name": "李明"}}}},
  {{"op": "add_character", "changes": {{"name": "张三", "role": "反派"}}}},
  {{"op": "update_chapter", "target": {{"chapter_number": 5}}, "changes": {{"title": "真相"}}}}
]
```

---

## 📖 故事上下文（以下是当前作品的完整信息，供你参与讨论时参考）
{story_context}
{writing_quality}
        15. **📌 圣经字段名中文化**：在与用户讨论作品圣经（story bible）内容时，**所有字段名必须使用中文**，不要直接输出英文键名。以下是字段名对照表：

        **创意摘要（creative_brief）**：作品定位、题材、受众、风格基调、核心卖点、一句话梗概、主角核心、主线矛盾、长线悬念、目标篇幅、必保留设定、揭秘策略、节奏策略、开放故事笔记、世界观设定(world_setting)

        **写作指导（writing_guidance）**：开书策略、章节密度策略、中段驱动力、后期方向、避免的模式、推荐情节模式

        **世界观设定（world_setting）**：力量体系、社会结构、关键地点、世界历史、隐藏真相、世界规则、魔法体系、科技水平、地理环境、文化背景、宗教信仰、经济体系、政治格局、势力分布、种族设定、时间线、等级划分、等级制度、组织势力、核心冲突、自然法则、宇宙观

        **原始输入（raw_input）**：原始创意、篇幅目标、必保留要素、原始笔记、隐藏设定

        **导入指导（import_guidance）**：导入素材类型、必须保留、作者目标、调整范围、长线预案、风格护栏

        **故事状态（story_state）**：故事状态、连续性事实、未闭合线索、近期章节摘要

        **示例**：❌ "longline_plan 为空" → ✅ "长线预案为空"；❌ "tone_guardrails 需要补充" → ✅ "风格护栏需要补充"；❌ "creative_brief 缺少 world_setting" → ✅ "创意摘要缺少世界观设定"。
"""

    async def run_stream(
        self,
        messages: list[dict],
        story_context: str,
        api_key: str,
        story_id: int = 0,
        mode: AgentMode = "execute",
        pending_change_key: AgentPendingChangeKey | None = None,
        workflow_type: str | None = None,
        workflow_id: int | None = None,
        shot_id: int | None = None,
        enabled_skills: list[str] | None = None,
        db=None,
    ) -> AsyncGenerator[dict[str, str], None]:
        """运行 agent 聊天循环，生成 SSE 事件。"""
        mode = normalize_agent_mode(mode)
        pending_changes = PendingChangesTracker()
        run_context = AgentRunContext(
            story_id=story_id,
            api_key=api_key,
            mode=mode,
            pending_changes=pending_changes,
            pending_change_key=pending_change_key,
            workflow_type=workflow_type,
            workflow_id=workflow_id,
            shot_id=shot_id,
        )
        context_token = _AGENT_RUN_CONTEXT.set(run_context)
        pending_changes_stored = False

        try:
            system_prompt = self._build_system_prompt(story_context, story_id=story_id, workflow_type=workflow_type, enabled_skills=enabled_skills, db=db)
            all_messages: list[dict] = [{"role": "system", "content": system_prompt}] + list(messages)

            from services.token_utils import (
                should_compress_messages,
                split_messages_for_compression,
            )

            async def _maybe_compress_history():
                nonlocal all_messages
                if not should_compress_messages(all_messages):
                    return
                system_msg = all_messages[0] if all_messages and all_messages[0].get("role") == "system" else None
                conversation_messages = all_messages[1:] if system_msg else all_messages
                old_messages, recent_messages = split_messages_for_compression(conversation_messages, keep_recent=20)
                if not old_messages:
                    return
                try:
                    summary = await self._compress_history_with_ai(old_messages, api_key)
                    compressed_msg = {"role": "system", "content": f"## 对话历史摘要\n\n以下是之前对话的关键信息摘要：\n\n{summary}"}
                    all_messages = ([system_msg] if system_msg else []) + [compressed_msg] + recent_messages
                    logger.info("Agent 对话历史已压缩: %d 条旧消息 → 摘要", len(old_messages))
                except Exception as exc:
                    logger.warning("Agent 对话历史压缩失败: %s", exc)

            await _maybe_compress_history()

            collected_content = ""
            iteration_count = 0
            SAFETY_MAX_ITERATIONS = 200  # 熔断：防止无限循环（200次迭代 = 足够分批完成大型任务）
            write_executed = False

            # 提取用户最后一条消息，判断是否涉及正文写入请求
            _last_user_msg = ""
            for m in reversed(messages):
                if isinstance(m, dict) and m.get("role") == "user":
                    _last_user_msg = (m.get("content") or "").strip()
                    break
            _CONTENT_WRITE_KEYWORDS = {
                "写正文", "写第", "写章", "写小说",
                "生成正文", "生成第", "生成章", "生成小说",
                "创作正文", "创作第", "创作章", "创作小说",
                "续写正文", "续写第", "续写章",
                "重写正文", "重写第", "重写章",
                "出正文", "出章节",
            }
            _has_content_intent = any(kw in _last_user_msg for kw in _CONTENT_WRITE_KEYWORDS)

            TOOL_EXECUTION_TIMEOUT = 300

            while iteration_count < SAFETY_MAX_ITERATIONS:
                iteration_count += 1

                current_task = asyncio.current_task()
                if current_task is not None and current_task.cancelled():
                    logger.info("Agent run_stream 检测到取消，停止循环")
                    break

                await _maybe_compress_history()

                payload = {
                    "model": _deepseek_service.DEEPSEEK_MODEL,
                    "messages": all_messages,
                    "stream": True,
                    "tools": self.tool_registry.get_tool_specs(mode=mode, workflow_type=workflow_type, enabled_skills=enabled_skills),
                    "max_tokens": 32768,
                }

                collected_content = ""
                tool_calls_acc: dict[int, dict[str, Any]] = {}
                finish_reason: str | None = None

                async with httpx.AsyncClient(timeout=600) as client:
                    async with client.stream(
                        "POST",
                        f"{_deepseek_service.DEEPSEEK_BASE_URL}/chat/completions",
                        json=payload,
                        headers=_deepseek_auth_headers(api_key),
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                choices = data.get("choices", [])
                                if not choices:
                                    continue
                                delta = choices[0].get("delta", {})
                                finish_reason = choices[0].get("finish_reason")

                                # 文本 token
                                content = delta.get("content", "")
                                if content:
                                    collected_content += content
                                    yield {"event": "token", "data": json.dumps({"content": content}, ensure_ascii=False)}

                                # 工具调用（流式累加）
                                tool_calls = delta.get("tool_calls", [])
                                for tc in tool_calls:
                                    idx = tc.get("index", 0)
                                    if idx not in tool_calls_acc:
                                        tool_calls_acc[idx] = {
                                            "id": "",
                                            "function": {"name": "", "arguments": ""},
                                        }
                                    if tc.get("id"):
                                        tool_calls_acc[idx]["id"] = tc["id"]
                                    func_data = tc.get("function", {})
                                    if func_data.get("name"):
                                        tool_calls_acc[idx]["function"]["name"] = func_data["name"]
                                    if func_data.get("arguments"):
                                        tool_calls_acc[idx]["function"]["arguments"] += func_data["arguments"]
                            except (json.JSONDecodeError, KeyError, IndexError):
                                continue

                # 构建 assistant 消息
                assistant_msg: dict[str, Any] = {"role": "assistant"}
                if collected_content:
                    assistant_msg["content"] = collected_content
                else:
                    assistant_msg["content"] = None

                if tool_calls_acc:
                    sorted_indices = sorted(tool_calls_acc.keys())
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tool_calls_acc[i]["id"],
                            "type": "function",
                            "function": {
                                "name": tool_calls_acc[i]["function"]["name"],
                                "arguments": tool_calls_acc[i]["function"]["arguments"],
                            },
                        }
                        for i in sorted_indices
                    ]
                all_messages.append(assistant_msg)

                # 章节正文写入工具名称集合（含框架委托生成工具）
                _CONTENT_TOOLS = {
                    "update_chapter_content", "batch_update_chapters",
                    "adjust_chapter_by_instruction", "rewrite_text_segment",
                    "batch_adjust_chapters",
                    "generate_chapter_content",
                }

                # 处理工具调用
                any_write_succeeded = False
                write_tool_attempted = False
                content_tool_succeeded = False
                if finish_reason == "tool_calls" and tool_calls_acc:
                    sorted_indices = sorted(tool_calls_acc.keys())
                    for i in sorted_indices:
                        tc = tool_calls_acc[i]
                        name = tc["function"]["name"]
                        raw_args_str = tc["function"]["arguments"].strip()
                        try:
                            args = json.loads(raw_args_str) if raw_args_str else {}
                        except json.JSONDecodeError:
                            logger.warning("Agent 工具 %s 参数JSON解析失败，通知AI重试", name)
                            result_str = json.dumps({"error": f"参数JSON格式解析失败，请重新调用 {name} 并确保输出合法的JSON"})
                            yield {"event": "tool_call", "data": json.dumps({"name": name, "arguments": {}}, ensure_ascii=False)}
                            yield {"event": "tool_result", "data": json.dumps({"name": name, "result": result_str}, ensure_ascii=False)}
                            all_messages.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": result_str,
                            })
                            continue

                        yield {"event": "tool_call", "data": json.dumps({"name": name, "arguments": args}, ensure_ascii=False)}

                        try:
                            result_str = await asyncio.wait_for(
                                self.tool_registry.execute(name, args),
                                timeout=TOOL_EXECUTION_TIMEOUT,
                            )
                            yield {"event": "tool_result", "data": json.dumps({"name": name, "result": result_str}, ensure_ascii=False)}
                        except asyncio.TimeoutError:
                            logger.warning("Agent 工具 %s 执行超时（%ss）", name, TOOL_EXECUTION_TIMEOUT)
                            result_str = json.dumps({"error": f"工具 {name} 执行超时（{TOOL_EXECUTION_TIMEOUT}s），操作未完成"})
                            yield {"event": "tool_result", "data": json.dumps({"name": name, "result": result_str}, ensure_ascii=False)}
                        except Exception as e:
                            error_msg = json.dumps({"error": str(e)}, ensure_ascii=False)
                            yield {"event": "tool_result", "data": json.dumps({"name": name, "result": error_msg}, ensure_ascii=False)}
                            result_str = error_msg

                        all_messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result_str,
                        })

                    # 检查是否有写工具成功执行（不含 error）
                    for i in sorted_indices:
                        tc = tool_calls_acc[i]
                        tool_name = tc["function"]["name"]
                        if self.tool_registry.is_write_tool(tool_name):
                            write_tool_attempted = True
                            tool_call_id = tc["id"]
                            for msg in all_messages:
                                if msg.get("role") == "tool" and msg.get("tool_call_id") == tool_call_id:
                                    content_str = str(msg.get("content", ""))
                                    succeeded = '"error"' not in content_str
                                    if succeeded:
                                        any_write_succeeded = True
                                        if tool_name in _CONTENT_TOOLS:
                                            content_tool_succeeded = True
                                    break

                    if any_write_succeeded:
                        write_executed = True
                        all_messages.append({
                            "role": "system",
                            "content": "写入完成。请向用户汇报本次写入的进度，然后继续处理剩余模块。如果还有更多内容需要更新，请继续调用工具。如果全部完成，请回复用户总结操作结果。",
                        })

                    # 继续循环（把工具结果送回 LLM，让 LLM 判断是否还有未完成的章节需要处理）
                    continue

                # 没有工具调用。检查Agent是否声称修改但未实际调用写入工具
                content_trimmed = (collected_content or "").strip()
                modification_keywords = [
                    "已修改", "已更新", "已保存", "已调整", "已完成", "已写入",
                    "已添加", "已删除", "已创建", "更新完成", "全部更新",
                    "全部调整", "全部完成", "写入数据库", "已全部",
                ]
                if (
                    not write_executed
                    and not write_tool_attempted
                    and content_trimmed
                    and any(kw in content_trimmed for kw in modification_keywords)
                    and iteration_count < SAFETY_MAX_ITERATIONS
                ):
                    logger.warning(
                        "Agent 声称修改但未调用写入工具，强制重试 story=%s iter=%s preview=%.80s",
                        story_id, iteration_count, content_trimmed,
                    )
                    all_messages.append({
                        "role": "system",
                        "content": (
                            "你在回复中声称已经完成了修改/更新/写入，但上一轮没有实际调用任何写入工具。"
                            "文字回复不能代替工具调用，只有工具调用才会真正写入数据库。"
                            "请立即调用相应的写入工具（adjust_framework / bulk_add_chapter_plans / "
                            "apply_framework_ops / update_story_bible / update_chapter_content 等）来实际执行修改。"
                            "不要描述你要做什么，直接调用工具去做。"
                        ),
                    })
                    yield {"event": "token", "data": json.dumps({"content": "\n\n[系统提示：检测到未实际写入，正在重新执行...]\n"}, ensure_ascii=False)}
                    continue

                # 检查2：只调了框架工具但没有调章节正文工具（仅当用户要求写正文时触发）
                if (
                    _has_content_intent
                    and write_executed
                    and not content_tool_succeeded
                    and content_trimmed
                    and any(kw in content_trimmed for kw in modification_keywords)
                    and iteration_count < SAFETY_MAX_ITERATIONS
                ):
                    logger.warning(
                        "Agent 仅写入框架但未写入正文，强制重试 story=%s iter=%s preview=%.80s",
                        story_id, iteration_count, content_trimmed,
                    )
                    all_messages.append({
                        "role": "system",
                        "content": (
                            "你只调用了框架调整工具（adjust_framework / apply_framework_ops / "
                            "bulk_add_chapter_plans 等），但没有调用章节正文生成工具。"
                            "用户明确要求了生成或写入章节正文，请调用 generate_chapter_content "
                            "（委托框架引擎生成正文）或 update_chapter_content（保存用户提供的文本）"
                            "来实际写入章节正文。不要只调整框架而不写正文。"
                        ),
                    })
                    yield {"event": "token", "data": json.dumps({"content": "\n\n[系统提示：检测到正文未写入，正在重新执行...]\n"}, ensure_ascii=False)}
                    continue

                break

            if write_executed:
                logger.info("Agent 写入操作完成，共 %s 次迭代", iteration_count)
            elif iteration_count >= SAFETY_MAX_ITERATIONS:
                logger.warning("Agent 达到安全熔断上限 %s", SAFETY_MAX_ITERATIONS)
            else:
                content_trimmed = (collected_content or "").strip()
                modification_keywords = ["已修改", "已更新", "已保存", "已调整", "已完成", "已写入", "已添加", "已删除", "已创建"]
                if content_trimmed and any(kw in content_trimmed for kw in modification_keywords):
                    logger.warning(
                        "Agent 声称进行了修改但没有调用任何写入工具 story=%s content_preview=%.120s",
                        story_id, content_trimmed,
                    )

            if pending_change_key is not None:
                agent_pending_change_store.set(pending_change_key, pending_changes)
                pending_changes_stored = True

            yield {"event": "done", "data": json.dumps({
                "content": collected_content,
                "pending_changes": pending_changes.get_summary(),
                "agent_mode": mode,
            }, ensure_ascii=False)}

        finally:
            if pending_change_key is not None and not pending_changes_stored:
                agent_pending_change_store.set(pending_change_key, pending_changes)
            _AGENT_RUN_CONTEXT.reset(context_token)


# ── 模块级单例 ──────────────────────────────────────────

agent_service = AgentService()
