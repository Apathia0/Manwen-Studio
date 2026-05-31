# 提示词模板系统实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建提示词模板系统，允许用户自定义框架生成、正文扩写、角色生成、漫画风格四类提示词，支持简单/专家双模式编辑、公开审核、模板广场和社区互动。

**Architecture:** 采用渐进式实施。第一阶段（MVP）实现模板 CRUD + 审核 + 广场；第二阶段实现评论 + 排行榜 + 通知。后端在 `main.py` 中新增路由，`models.py` 新增模型，`schemas.py` 新增 Pydantic schema，`database.py` 新增迁移。前端新增 `TemplateEditor`、`TemplateMarket` 组件。

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic（后端），React + TypeScript（前端），PostgreSQL

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `backend/models.py` | 修改 | 新增 PromptTemplate、StoryTemplateBinding、TemplateLike 模型 |
| `backend/schemas.py` | 修改 | 新增模板相关 Pydantic schema |
| `backend/database.py` | 修改 | 新增数据库迁移和 `_migrate_prompt_templates()` |
| `backend/main.py` | 修改 | 新增模板管理、绑定、广场、审核路由 |
| `backend/services/prompt_template.py` | 新建 | 参数→prompt 转换逻辑、`get_effective_prompt()` |
| `frontend/src/api.ts` | 修改 | 新增模板相关 API 调用函数 |
| `frontend/src/components/TemplateEditor.tsx` | 新建 | 模板编辑器组件（简单/专家模式） |
| `frontend/src/components/TemplateMarket.tsx` | 新建 | 模板广场组件 |
| `frontend/src/components/TemplateSelectModal.tsx` | 新建 | 作品绑定模板选择弹窗 |

---

## 第一阶段：MVP（任务 1-8）

### 任务 1：数据库模型与迁移

**Files:**
- Modify: `backend/models.py`（末尾新增 3 个模型）
- Modify: `backend/database.py`（新增迁移函数）

- [ ] **Step 1：新增 SQLAlchemy 模型**

在 `backend/models.py` 末尾添加：

```python
class PromptTemplate(Base):
    """提示词模板"""
    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # 四类提示词的完整内容（专家模式）
    framework_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    chapter_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    character_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    manga_style_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 四类提示词的参数化配置（简单模式）
    framework_params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    chapter_params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    character_params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    manga_style_params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # 状态管理
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    visibility: Mapped[str] = mapped_column(String(20), default="private")

    # 统计数据
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)

    # 分类标签
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # 审核信息
    submitted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # fork 来源
    forked_from: Mapped[int | None] = mapped_column(Integer, ForeignKey("prompt_templates.id"), nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    author: Mapped["User | None"] = relationship("User", foreign_keys=[author_user_id])


class StoryTemplateBinding(Base):
    """作品-模板关联"""
    __tablename__ = "story_template_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id"), nullable=False)
    template_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompt_templates.id"), nullable=True)
    bound_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("story_id", name="uq_story_template_binding"),)

    story: Mapped["Story"] = relationship("Story")
    template: Mapped["PromptTemplate | None"] = relationship("PromptTemplate")


class TemplateLike(Base):
    """模板点赞记录"""
    __tablename__ = "template_likes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompt_templates.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("template_id", "user_id", name="uq_template_like"),)
```

- [ ] **Step 2：新增数据库迁移函数**

在 `backend/database.py` 的 `_migrate()` 函数末尾（`_migrate_video_character_tables()` 之后）添加：

```python
def _migrate_prompt_templates():
    from sqlalchemy import inspect, text

    insp = inspect(engine)

    # 新表：prompt_templates
    if "prompt_templates" not in insp.get_table_names():
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                CREATE TABLE prompt_templates (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    description TEXT,
                    author_user_id INTEGER REFERENCES users(id),
                    framework_prompt TEXT,
                    chapter_prompt TEXT,
                    character_prompt TEXT,
                    manga_style_prompt TEXT,
                    framework_params JSONB,
                    chapter_params JSONB,
                    character_params JSONB,
                    manga_style_params JSONB,
                    is_public BOOLEAN DEFAULT FALSE,
                    status VARCHAR(20) DEFAULT 'draft',
                    visibility VARCHAR(20) DEFAULT 'private',
                    usage_count INTEGER DEFAULT 0,
                    like_count INTEGER DEFAULT 0,
                    category VARCHAR(50),
                    tags JSONB,
                    submitted_at TIMESTAMP,
                    reviewed_at TIMESTAMP,
                    reviewed_by INTEGER REFERENCES users(id),
                    review_note TEXT,
                    forked_from INTEGER REFERENCES prompt_templates(id),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX idx_templates_status ON prompt_templates(status)"))
            conn.execute(text("CREATE INDEX idx_templates_visibility ON prompt_templates(visibility)"))
            conn.execute(text("CREATE INDEX idx_templates_author ON prompt_templates(author_user_id)"))

    # 新表：story_template_bindings
    if "story_template_bindings" not in insp.get_table_names():
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                CREATE TABLE story_template_bindings (
                    id SERIAL PRIMARY KEY,
                    story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    template_id INTEGER REFERENCES prompt_templates(id),
                    bound_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(story_id)
                )
            """))
            conn.execute(text("CREATE INDEX idx_bindings_story ON story_template_bindings(story_id)"))

    # 新表：template_likes
    if "template_likes" not in insp.get_table_names():
        with engine.begin() as conn:
            _prepare_migration_conn(conn)
            conn.execute(text("""
                CREATE TABLE template_likes (
                    id SERIAL PRIMARY KEY,
                    template_id INTEGER NOT NULL REFERENCES prompt_templates(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(template_id, user_id)
                )
            """))
```

在 `_migrate()` 函数末尾调用 `_migrate_prompt_templates()`：

```python
# 在 _migrate() 函数最后「_cleanup_duplicate_manga_images()」调用的下方添加：
_migrate_prompt_templates()
```

- [ ] **Step 3：验证迁移**

```bash
cd backend && python -c "
from database import init_db; init_db(run_migrations=True)
from database import engine; from sqlalchemy import inspect
insp = inspect(engine)
tables = ['prompt_templates', 'story_template_bindings', 'template_likes']
for t in tables:
    print(f'{t}: {\"OK\" if t in insp.get_table_names() else \"MISSING\"}')"
```

预期输出：三个表都显示 OK

- [ ] **Step 4：测试模型导入**

```bash
cd backend && python -c "from models import PromptTemplate, StoryTemplateBinding, TemplateLike; print('Models OK')"
```

- [ ] **Step 5：提交**

```bash
git add backend/models.py backend/database.py
git commit -m "feat: add PromptTemplate, StoryTemplateBinding, TemplateLike models and migration"
```

---

### 任务 2：Pydantic Schema 定义

**Files:**
- Modify: `backend/schemas.py`（末尾新增）

- [ ] **Step 1：新增模板相关 schema**

在 `backend/schemas.py` 末尾添加：

```python
# --- Prompt Template ---

class TemplateFrameworkParams(BaseModel):
    story_length: str = "long"
    pacing: str = "steady"
    structure: str = "flexible"
    chapter_detail_level: str = "high"
    character_depth: str = "deep"
    world_building: str = "rich"
    tone: str = "serious"
    custom_rules: str = ""


class TemplateChapterParams(BaseModel):
    writing_style: str = "descriptive"
    dialogue_ratio: str = "medium"
    scene_detail: str = "rich"
    inner_monologue: str = "moderate"
    pacing_preference: str = "varied"
    vocabulary_level: str = "advanced"
    custom_style_notes: str = ""


class TemplateCharacterParams(BaseModel):
    detail_level: str = "high"
    appearance_focus: str = "balanced"
    personality_depth: str = "deep"
    relationship_emphasis: str = "high"
    arc_planning: str = "complete"
    custom_requirements: str = ""


class TemplateMangaStyleParams(BaseModel):
    art_style: str = "anime"
    color_scheme: str = "vibrant"
    detail_level: str = "high"
    composition: str = "dynamic"
    lighting: str = "dramatic"
    mood: str = "epic"
    custom_style_prompt: str = ""


class PromptTemplateCreate(BaseModel):
    name: str
    description: str = ""
    category: str = ""
    tags: list[str] = []
    framework_prompt: Optional[str] = None
    chapter_prompt: Optional[str] = None
    character_prompt: Optional[str] = None
    manga_style_prompt: Optional[str] = None
    framework_params: Optional[TemplateFrameworkParams] = None
    chapter_params: Optional[TemplateChapterParams] = None
    character_params: Optional[TemplateCharacterParams] = None
    manga_style_params: Optional[TemplateMangaStyleParams] = None


class PromptTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    framework_prompt: Optional[str] = None
    chapter_prompt: Optional[str] = None
    character_prompt: Optional[str] = None
    manga_style_prompt: Optional[str] = None
    framework_params: Optional[TemplateFrameworkParams] = None
    chapter_params: Optional[TemplateChapterParams] = None
    character_params: Optional[TemplateCharacterParams] = None
    manga_style_params: Optional[TemplateMangaStyleParams] = None


class TemplateAuthorOut(BaseModel):
    id: int
    username: str


class PromptTemplateOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = ""
    author: Optional[TemplateAuthorOut] = None
    category: Optional[str] = None
    tags: Optional[list] = None
    status: str
    visibility: str
    is_public: bool
    usage_count: int
    like_count: int
    framework_prompt: Optional[str] = None
    chapter_prompt: Optional[str] = None
    character_prompt: Optional[str] = None
    manga_style_prompt: Optional[str] = None
    framework_params: Optional[dict] = None
    chapter_params: Optional[dict] = None
    character_params: Optional[dict] = None
    manga_style_params: Optional[dict] = None
    forked_from: Optional[int] = None
    submitted_at: Optional[str] = None
    reviewed_at: Optional[str] = None
    review_note: Optional[str] = None
    created_at: str
    updated_at: str


class TemplateListOut(BaseModel):
    templates: list[PromptTemplateOut]
    total: int
    page: int
    page_size: int


class BindTemplateRequest(BaseModel):
    template_id: int


class AdminReviewRequest(BaseModel):
    visibility: str = "public"
    note: str = ""
```

- [ ] **Step 2：验证 Schema 导入**

```bash
cd backend && python -c "from schemas import PromptTemplateCreate, PromptTemplateOut, BindTemplateRequest; print('Schemas OK')"
```

- [ ] **Step 3：提交**

```bash
git add backend/schemas.py
git commit -m "feat: add prompt template Pydantic schemas"
```

---

### 任务 3：参数→Prompt 转换服务

**Files:**
- Create: `backend/services/prompt_template.py`

- [ ] **Step 1：创建转换服务文件**

新建 `backend/services/prompt_template.py`：

```python
"""提示词模板服务：参数→prompt 转换、模板应用逻辑"""

from typing import Any


# ── 映射表 ─────────────────────────────────────────────

ART_STYLE_MAP = {
    "anime": "日式动漫风格，cel-shaded，鲜艳色彩，清晰线条",
    "realistic": "写实风格，电影级光影，自然色彩，高细节",
    "cartoon": "卡通风格，夸张造型，明亮配色，简洁线条",
    "ink": "中国水墨风格，笔触纹理，留白构图，墨色为主调",
}

COLOR_MAP = {
    "monochrome": "黑白单色调",
    "muted": "柔和淡雅配色",
    "balanced": "平衡自然的色彩",
    "vibrant": "鲜艳明亮的色彩",
}

MOOD_MAP = {
    "calm": "平静安宁的氛围",
    "neutral": "中性克制的情绪",
    "intense": "紧张压抑的气氛",
    "epic": "史诗宏大的气势",
}

TONE_MAP = {
    "light": "整体基调轻松愉快，可以加入幽默元素",
    "balanced": "情绪层次丰富，张弛有度",
    "serious": "保持严肃认真的态度，避免过于轻浮的描写",
    "dark": "营造压抑阴暗的氛围，强调人性阴暗面和悲剧感",
}


# ── 核心函数 ────────────────────────────────────────────

def build_prompt_from_params(base_prompt: str, params: dict | None, prompt_type: str) -> str:
    """根据参数化配置生成完整 prompt。

    Args:
        base_prompt: 系统默认的基础 prompt
        params: 参数字典（来自模板的 *_params 字段）
        prompt_type: 提示词类型（framework/chapter/character/manga_style）

    Returns:
        完整的 prompt 文本
    """
    if not params or not isinstance(params, dict):
        return base_prompt

    parts = [base_prompt]

    if prompt_type == "framework":
        _build_framework_rules(parts, params)
    elif prompt_type == "chapter":
        _build_chapter_rules(parts, params)
    elif prompt_type == "character":
        _build_character_rules(parts, params)
    elif prompt_type == "manga_style":
        _build_manga_style_rules(parts, params)

    return "\n\n".join(parts)


def _build_framework_rules(parts: list, params: dict):
    rules = []

    if params.get("story_length") == "long":
        rules.append("支持 100+ 章的持续创作，不要在前 20 章内把主线讲完")
    elif params.get("story_length") == "short":
        rules.append("适合 10 万字以内短篇，情节集中在核心冲突上")

    if params.get("pacing") == "slow":
        rules.append("采用慢热节奏，前期重点铺垫世界观和角色关系")
    elif params.get("pacing") == "fast":
        rules.append("采用快节奏，迅速推进情节，避免冗长铺垫")

    if params.get("world_building") == "rich":
        rules.append("构建详细的世界观体系，包括社会结构、历史背景、文化特色")
    elif params.get("world_building") == "simple":
        rules.append("世界观以简洁为主，不要过于复杂")

    tone = params.get("tone", "")
    if tone and tone in TONE_MAP:
        rules.append(TONE_MAP[tone])

    if params.get("custom_rules"):
        rules.append(f"用户自定义要求：{params['custom_rules']}")

    if rules:
        parts.append("## 额外要求\n" + "\n".join(f"- {r}" for r in rules))


def _build_chapter_rules(parts: list, params: dict):
    rules = []

    if params.get("writing_style") == "descriptive":
        rules.append("注重场景描写和细节刻画，营造沉浸式阅读体验")
    elif params.get("writing_style") == "concise":
        rules.append("行文简洁明快，用最少的文字传达最多的信息")

    if params.get("dialogue_ratio") == "high":
        rules.append("以对话为主要推进手段，通过人物对话展现情节和性格")
    elif params.get("dialogue_ratio") == "low":
        rules.append("以叙述为主，对话仅用于关键情节节点")

    if params.get("inner_monologue") == "extensive":
        rules.append("大量使用内心独白，深入展现角色的内心世界")
    elif params.get("inner_monologue") == "minimal":
        rules.append("通过行为和对话展现角色，减少直接内心描写")

    if params.get("vocabulary_level") == "advanced":
        rules.append("使用文学性强的词汇和修辞手法")
    elif params.get("vocabulary_level") == "simple":
        rules.append("使用通俗易懂的语言，避免生僻词汇")

    if params.get("custom_style_notes"):
        rules.append(f"风格要求：{params['custom_style_notes']}")

    if rules:
        parts.append("## 写作风格\n" + "\n".join(f"- {r}" for r in rules))


def _build_character_rules(parts: list, params: dict):
    rules = []

    if params.get("detail_level") == "high":
        rules.append("详细描写角色的外貌特征，包括发型、五官、体型、神态")
    elif params.get("detail_level") == "basic":
        rules.append("只保留核心外貌特征，简洁明确")

    if params.get("personality_depth") == "deep":
        rules.append("深入刻画角色性格，包括行为模式、价值观、内心矛盾")

    if params.get("arc_planning") == "complete":
        rules.append("明确角色的成长弧光：起始状态 → 触发事件 → 变化过程 → 最终状态")

    if params.get("custom_requirements"):
        rules.append(f"自定义要求：{params['custom_requirements']}")

    if rules:
        parts.append("## 角色塑造要求\n" + "\n".join(f"- {r}" for r in rules))


def _build_manga_style_rules(parts: list, params: dict):
    rules = []

    art = params.get("art_style", "")
    if art and art in ART_STYLE_MAP:
        rules.append(f"画风：{ART_STYLE_MAP[art]}")

    color = params.get("color_scheme", "")
    if color and color in COLOR_MAP:
        rules.append(f"配色：{COLOR_MAP[color]}")

    mood = params.get("mood", "")
    if mood and mood in MOOD_MAP:
        rules.append(f"氛围：{MOOD_MAP[mood]}")

    if params.get("composition") == "dynamic":
        rules.append("采用动态构图，大胆的角度和透视")
    elif params.get("composition") == "static":
        rules.append("采用静态平衡构图，工整对称")

    if params.get("lighting") == "dramatic":
        rules.append("使用戏剧化光影，强对比明暗")
    elif params.get("lighting") == "natural":
        rules.append("使用自然柔和的光线")

    if params.get("custom_style_prompt"):
        rules.append(f"风格补充：{params['custom_style_prompt']}")

    if rules:
        parts.append("## 画面风格指令\n" + "\n".join(f"- {r}" for r in rules))


# ── 模板应用逻辑 ────────────────────────────────────────

def get_effective_prompt(story_id: int, prompt_type: str, db) -> str:
    """获取作品实际使用的 prompt。

    优先级：模板完整 prompt > 模板参数生成 > 系统默认

    Args:
        story_id: 作品 ID
        prompt_type: framework/chapter/character/manga_style
        db: SQLAlchemy 数据库会话

    Returns:
        实际使用的 prompt 文本
    """
    from models import StoryTemplateBinding

    binding = db.query(StoryTemplateBinding).filter_by(story_id=story_id).first()

    if binding and binding.template:
        template = binding.template

        # 优先使用完整 prompt
        full_prompt = getattr(template, f"{prompt_type}_prompt", None)
        if full_prompt and full_prompt.strip():
            return full_prompt

        # 从参数生成
        params = getattr(template, f"{prompt_type}_params", None)
        if params and isinstance(params, dict):
            return build_prompt_from_params(_get_default_prompt(prompt_type), params, prompt_type)

    # 回退到系统默认
    return _get_default_prompt(prompt_type)


def _get_default_prompt(prompt_type: str) -> str:
    """返回系统默认 prompt"""
    # 这里只是占位——实际调用时应该由各服务的现有 prompt 常量替代
    return ""
```

- [ ] **Step 2：验证服务导入**

```bash
cd backend && python -c "
from services.prompt_template import build_prompt_from_params, get_effective_prompt
params = {'story_length': 'long', 'pacing': 'slow', 'tone': 'serious'}
result = build_prompt_from_params('BASE_PROMPT', params, 'framework')
assert '慢热节奏' in result
assert '严肃' in result
print('Prompt template service OK')
"
```

- [ ] **Step 3：提交**

```bash
git add backend/services/prompt_template.py
git commit -m "feat: add prompt template service with params-to-prompt conversion"
```

---

### 任务 4：模板 CRUD API

**Files:**
- Modify: `backend/main.py`（新增路由）

- [ ] **Step 1：创建模板**

在 `backend/main.py` 中添加（放在其他 `/api/` 路由附近）：

```python
# ── 提示词模板 API ──────────────────────────────────────

@app.post("/api/prompt-templates")
def create_prompt_template(body: dict, request: Request, db: Session = Depends(get_db)):
    user = _get_current_user(request, db)
    if not user:
        raise HTTPException(401, "请先登录")

    template = PromptTemplate(
        name=body.get("name", "").strip()[:100],
        description=body.get("description", "").strip(),
        author_user_id=user.id,
        category=body.get("category", "").strip(),
        tags=body.get("tags", []),
        framework_prompt=body.get("framework_prompt", "").strip() or None,
        chapter_prompt=body.get("chapter_prompt", "").strip() or None,
        character_prompt=body.get("character_prompt", "").strip() or None,
        manga_style_prompt=body.get("manga_style_prompt", "").strip() or None,
        framework_params=body.get("framework_params"),
        chapter_params=body.get("chapter_params"),
        character_params=body.get("character_params"),
        manga_style_params=body.get("manga_style_params"),
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return _serialize_template(template, user.id, db)


@app.get("/api/prompt-templates/my")
def list_my_templates(request: Request, page: int = 1, page_size: int = 20, status: str = "", db: Session = Depends(get_db)):
    user = _get_current_user(request, db)
    if not user:
        raise HTTPException(401, "请先登录")

    query = db.query(PromptTemplate).filter(PromptTemplate.author_user_id == user.id)
    if status:
        query = query.filter(PromptTemplate.status == status)
    query = query.order_by(PromptTemplate.updated_at.desc())

    total = query.count()
    templates = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "templates": [_serialize_template(t, user.id, db) for t in templates],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/api/prompt-templates/{template_id}")
def get_prompt_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")

    # 私有模板仅所有者可见
    if template.visibility == "private":
        user = _get_current_user(request, db)
        if not user or user.id != template.author_user_id:
            raise HTTPException(403, "无权访问此模板")

    user_id = _get_current_user(request, db).id if _get_current_user(request, db) else None
    return _serialize_template(template, user_id, db)


@app.put("/api/prompt-templates/{template_id}")
def update_prompt_template(template_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    user = _get_current_user(request, db)
    if not user:
        raise HTTPException(401, "请先登录")

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")
    if template.author_user_id != user.id:
        raise HTTPException(403, "只能编辑自己的模板")

    # 只更新传入的字段
    updatable = ["name", "description", "category", "tags",
                 "framework_prompt", "chapter_prompt", "character_prompt", "manga_style_prompt",
                 "framework_params", "chapter_params", "character_params", "manga_style_params"]
    for key in updatable:
        if key in body:
            if key == "name":
                setattr(template, key, str(body[key]).strip()[:100])
            elif key in ("tags",):
                setattr(template, key, body[key] if isinstance(body[key], list) else [])
            elif key.endswith("_params"):
                setattr(template, key, body[key] if isinstance(body[key], dict) else None)
            else:
                val = body[key]
                setattr(template, key, str(val).strip() if isinstance(val, str) else val)

    template.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(template)
    return _serialize_template(template, user.id, db)


@app.delete("/api/prompt-templates/{template_id}")
def delete_prompt_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    user = _get_current_user(request, db)
    if not user:
        raise HTTPException(401, "请先登录")

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")
    if template.author_user_id != user.id:
        raise HTTPException(403, "只能删除自己的模板")

    # 解绑使用此模板的作品
    db.query(StoryTemplateBinding).filter(StoryTemplateBinding.template_id == template_id).delete()
    db.delete(template)
    db.commit()
    return {"ok": True}


@app.post("/api/prompt-templates/{template_id}/submit-for-review")
def submit_template_for_review(template_id: int, request: Request, db: Session = Depends(get_db)):
    user = _get_current_user(request, db)
    if not user:
        raise HTTPException(401, "请先登录")

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")
    if template.author_user_id != user.id:
        raise HTTPException(403, "只能提交自己的模板")
    if template.status not in ("draft", "rejected"):
        raise HTTPException(400, "无法提交：当前状态不允许提交审核")

    template.status = "pending"
    template.submitted_at = datetime.now(timezone.utc)
    db.commit()
    return _serialize_template(template, user.id, db)


@app.post("/api/prompt-templates/{template_id}/fork")
def fork_prompt_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    user = _get_current_user(request, db)
    if not user:
        raise HTTPException(401, "请先登录")

    source = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not source:
        raise HTTPException(404, "模板不存在")
    if source.visibility == "private" and source.author_user_id != user.id:
        raise HTTPException(403, "无权复制此模板")

    new_template = PromptTemplate(
        name=f"{source.name}（副本）",
        description=source.description,
        author_user_id=user.id,
        category=source.category,
        tags=source.tags,
        framework_prompt=source.framework_prompt,
        chapter_prompt=source.chapter_prompt,
        character_prompt=source.character_prompt,
        manga_style_prompt=source.manga_style_prompt,
        framework_params=source.framework_params,
        chapter_params=source.chapter_params,
        character_params=source.character_params,
        manga_style_params=source.manga_style_params,
        forked_from=source.id,
    )
    db.add(new_template)
    db.commit()
    db.refresh(new_template)
    return _serialize_template(new_template, user.id, db)


# ── 序列化辅助函数 ──

def _serialize_template(template, current_user_id, db) -> dict:
    author = None
    if template.author_user_id:
        u = db.query(User).filter(User.id == template.author_user_id).first()
        author = {"id": u.id, "username": u.username} if u else None

    is_liked = False
    if current_user_id:
        like = db.query(TemplateLike).filter(
            TemplateLike.template_id == template.id,
            TemplateLike.user_id == current_user_id,
        ).first()
        is_liked = like is not None

    def _json_or_none(val):
        return val if isinstance(val, (dict, list, type(None))) else None

    return {
        "id": template.id,
        "name": template.name,
        "description": template.description or "",
        "author": author,
        "category": template.category,
        "tags": template.tags or [],
        "status": template.status,
        "visibility": template.visibility,
        "is_public": template.is_public,
        "usage_count": template.usage_count,
        "like_count": template.like_count,
        "is_liked": is_liked,
        "framework_prompt": template.framework_prompt,
        "chapter_prompt": template.chapter_prompt,
        "character_prompt": template.character_prompt,
        "manga_style_prompt": template.manga_style_prompt,
        "framework_params": _json_or_none(template.framework_params),
        "chapter_params": _json_or_none(template.chapter_params),
        "character_params": _json_or_none(template.character_params),
        "manga_style_params": _json_or_none(template.manga_style_params),
        "forked_from": template.forked_from,
        "submitted_at": template.submitted_at.isoformat() if template.submitted_at else None,
        "reviewed_at": template.reviewed_at.isoformat() if template.reviewed_at else None,
        "review_note": template.review_note,
        "created_at": template.created_at.isoformat() if template.created_at else "",
        "updated_at": template.updated_at.isoformat() if template.updated_at else "",
    }
```

**注意**：所有 `_serialize_template(template, user_id)` 调用处需改为 `_serialize_template(template, user_id, db)`。

- [ ] **Step 2：验证 API 可用**

```bash
# 启动后端后测试
curl -X POST http://localhost:8000/api/prompt-templates \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"测试模板","description":"测试描述","category":"玄幻","tags":["测试"]}'
# 预期返回 200 + 模板 JSON
```

- [ ] **Step 3：提交**

```bash
git add backend/main.py
git commit -m "feat: add prompt template CRUD API endpoints"
```

---

### 任务 5：作品绑定与模板广场 API

**Files:**
- Modify: `backend/main.py`（新增路由，在任务 4 的路由之后）

- [ ] **Step 1：作品绑定接口**

在 `backend/main.py` 中任务 4 的路由之后添加：

```python
# ── 作品-模板绑定 ──────────────────────────────────────

@app.post("/api/stories/{story_id}/bind-template")
def bind_story_template(story_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    user = _get_current_user(request, db)
    if not user:
        raise HTTPException(401, "请先登录")

    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(404, "作品不存在")
    if story.owner_user_id != user.id:
        raise HTTPException(403, "只能修改自己的作品")

    template_id = body.get("template_id")
    if not template_id:
        raise HTTPException(400, "请提供 template_id")

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")

    # 删除旧绑定
    db.query(StoryTemplateBinding).filter(StoryTemplateBinding.story_id == story_id).delete()
    # 创建新绑定
    binding = StoryTemplateBinding(story_id=story_id, template_id=template_id)
    db.add(binding)

    # 增加使用计数
    template.usage_count = (template.usage_count or 0) + 1

    db.commit()
    db.refresh(binding)
    return {"story_id": story_id, "template_id": template_id, "bound_at": binding.bound_at.isoformat() if binding.bound_at else ""}


@app.get("/api/stories/{story_id}/template")
def get_story_template(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _get_current_user(request, db)
    if not user:
        raise HTTPException(401, "请先登录")

    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(404, "作品不存在")
    if story.owner_user_id != user.id:
        raise HTTPException(403, "权限不足")

    binding = db.query(StoryTemplateBinding).filter(StoryTemplateBinding.story_id == story_id).first()
    if not binding or not binding.template:
        return {"template": None}

    return {"template": _serialize_template(binding.template, user.id, db)}


@app.delete("/api/stories/{story_id}/template")
def unbind_story_template(story_id: int, request: Request, db: Session = Depends(get_db)):
    user = _get_current_user(request, db)
    if not user:
        raise HTTPException(401, "请先登录")

    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(404, "作品不存在")
    if story.owner_user_id != user.id:
        raise HTTPException(403, "只能修改自己的作品")

    db.query(StoryTemplateBinding).filter(StoryTemplateBinding.story_id == story_id).delete()
    db.commit()
    return {"ok": True}


# ── 模板广场 ──────────────────────────────────────────

@app.get("/api/prompt-templates/public")
def list_public_templates(
    request: Request,
    sort: str = "popular",
    category: str = "",
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    query = db.query(PromptTemplate).filter(
        PromptTemplate.status == "approved",
        PromptTemplate.visibility.in_(["public", "official"]),
    )

    if category:
        query = query.filter(PromptTemplate.category == category)

    if sort == "official":
        query = query.filter(PromptTemplate.visibility == "official")
        query = query.order_by(PromptTemplate.usage_count.desc())
    elif sort == "latest":
        query = query.order_by(PromptTemplate.reviewed_at.desc().nullslast())
    else:  # popular
        query = query.order_by(PromptTemplate.usage_count.desc())

    total = query.count()
    templates = query.offset((page - 1) * page_size).limit(page_size).all()

    user_id = None
    u = _get_current_user(request, db)
    if u:
        user_id = u.id

    return {
        "templates": [_serialize_template(t, user_id, db) for t in templates],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/api/prompt-templates/{template_id}/stats")
def get_template_stats(template_id: int, db: Session = Depends(get_db)):
    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")

    return {
        "usage_count": template.usage_count or 0,
        "like_count": template.like_count or 0,
        "status": template.status,
        "visibility": template.visibility,
    }


# ── 点赞 ──────────────────────────────────────────────

@app.post("/api/prompt-templates/{template_id}/like")
def like_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    user = _get_current_user(request, db)
    if not user:
        raise HTTPException(401, "请先登录")

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")

    existing = db.query(TemplateLike).filter(
        TemplateLike.template_id == template_id,
        TemplateLike.user_id == user.id,
    ).first()

    if not existing:
        db.add(TemplateLike(template_id=template_id, user_id=user.id))
        template.like_count = (template.like_count or 0) + 1
        db.commit()

    return {"like_count": template.like_count, "is_liked": True}


@app.delete("/api/prompt-templates/{template_id}/like")
def unlike_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    user = _get_current_user(request, db)
    if not user:
        raise HTTPException(401, "请先登录")

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")

    existing = db.query(TemplateLike).filter(
        TemplateLike.template_id == template_id,
        TemplateLike.user_id == user.id,
    ).first()

    if existing:
        db.delete(existing)
        template.like_count = max(0, (template.like_count or 0) - 1)
        db.commit()

    return {"like_count": template.like_count, "is_liked": False}
```

- [ ] **Step 2：提交**

```bash
git add backend/main.py
git commit -m "feat: add story-template binding, public market, and like API endpoints"
```

---

### 任务 6：管理员审核 API

**Files:**
- Modify: `backend/main.py`（新增路由）

- [ ] **Step 1：管理员审核接口**

在 `backend/main.py` 中任务 5 的路由之后添加：

```python
# ── 管理员审核 ──────────────────────────────────────────

@app.get("/api/admin/prompt-templates/pending")
def admin_list_pending_templates(request: Request, page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    _require_admin(request, db)

    query = db.query(PromptTemplate).filter(PromptTemplate.status == "pending")
    query = query.order_by(PromptTemplate.submitted_at.asc().nullslast())

    total = query.count()
    templates = query.offset((page - 1) * page_size).limit(page_size).all()

    user = _get_current_user(request, db)
    return {
        "templates": [_serialize_template(t, user.id if user else None, db) for t in templates],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.post("/api/admin/prompt-templates/{template_id}/approve")
def admin_approve_template(template_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")
    if template.status != "pending":
        raise HTTPException(400, "只能审核待审核状态的模板")

    user = _get_current_user(request, db)

    template.status = "approved"
    template.visibility = body.get("visibility", "public")
    template.is_public = True
    template.reviewed_at = datetime.now(timezone.utc)
    template.reviewed_by = user.id if user else None
    template.review_note = body.get("note", "")

    db.commit()
    return _serialize_template(template, user.id if user else None, db)


@app.post("/api/admin/prompt-templates/{template_id}/reject")
def admin_reject_template(template_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")

    template.status = "rejected"
    template.is_public = False
    template.visibility = "private"
    template.reviewed_at = datetime.now(timezone.utc)
    template.review_note = body.get("note", "")

    user = _get_current_user(request, db)
    if user:
        template.reviewed_by = user.id

    db.commit()
    return _serialize_template(template, user.id if user else None, db)


@app.post("/api/admin/prompt-templates/{template_id}/archive")
def admin_archive_template(template_id: int, body: dict, request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)

    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "模板不存在")

    template.visibility = "archived"
    template.is_public = False
    template.review_note = body.get("reason", "管理员下架")

    db.commit()
    return {"ok": True, "id": template_id, "visibility": "archived"}
```

- [ ] **Step 2：提交**

```bash
git add backend/main.py
git commit -m "feat: add admin review API for prompt templates"
```

---

### 任务 7：前端 API 调用层

**Files:**
- Modify: `frontend/src/api.ts`（末尾新增）

- [ ] **Step 1：新增前端 API 函数**

在 `frontend/src/api.ts` 末尾添加：

```typescript
// ─── Prompt Template API ─────────────────────────────────

export interface PromptTemplateItem {
  id: number;
  name: string;
  description: string;
  author: { id: number; username: string } | null;
  category: string | null;
  tags: string[];
  status: string;
  visibility: string;
  is_public: boolean;
  usage_count: number;
  like_count: number;
  is_liked?: boolean;
  framework_prompt?: string | null;
  chapter_prompt?: string | null;
  character_prompt?: string | null;
  manga_style_prompt?: string | null;
  framework_params?: Record<string, string> | null;
  chapter_params?: Record<string, string> | null;
  character_params?: Record<string, string> | null;
  manga_style_params?: Record<string, string> | null;
  forked_from?: number | null;
  submitted_at?: string | null;
  reviewed_at?: string | null;
  review_note?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TemplateListResponse {
  templates: PromptTemplateItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface TemplateStatsResponse {
  usage_count: number;
  like_count: number;
  status: string;
  visibility: string;
}

// 创建模板
export async function createPromptTemplate(data: {
  name: string;
  description?: string;
  category?: string;
  tags?: string[];
  framework_prompt?: string;
  chapter_prompt?: string;
  character_prompt?: string;
  manga_style_prompt?: string;
  framework_params?: Record<string, string>;
  chapter_params?: Record<string, string>;
  character_params?: Record<string, string>;
  manga_style_params?: Record<string, string>;
}): Promise<PromptTemplateItem> {
  const res = await fetch(`${BASE}/api/prompt-templates`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '创建模板失败'));
  return res.json();
}

// 我的模板列表
export async function listMyTemplates(params?: { page?: number; page_size?: number; status?: string }): Promise<TemplateListResponse> {
  const query = new URLSearchParams();
  if (params?.page) query.set('page', String(params.page));
  if (params?.page_size) query.set('page_size', String(params.page_size));
  if (params?.status) query.set('status', params.status);
  const res = await fetch(`${BASE}/api/prompt-templates/my?${query}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取模板列表失败'));
  return res.json();
}

// 模板详情
export async function getPromptTemplate(id: number): Promise<PromptTemplateItem> {
  const res = await fetch(`${BASE}/api/prompt-templates/${id}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取模板详情失败'));
  return res.json();
}

// 更新模板
export async function updatePromptTemplate(id: number, data: Record<string, unknown>): Promise<PromptTemplateItem> {
  const res = await fetch(`${BASE}/api/prompt-templates/${id}`, {
    method: 'PUT',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '更新模板失败'));
  return res.json();
}

// 删除模板
export async function deletePromptTemplate(id: number): Promise<void> {
  const res = await fetch(`${BASE}/api/prompt-templates/${id}`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '删除模板失败'));
}

// 提交审核
export async function submitTemplateForReview(id: number): Promise<PromptTemplateItem> {
  const res = await fetch(`${BASE}/api/prompt-templates/${id}/submit-for-review`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '提交审核失败'));
  return res.json();
}

// 复制模板
export async function forkPromptTemplate(id: number): Promise<PromptTemplateItem> {
  const res = await fetch(`${BASE}/api/prompt-templates/${id}/fork`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '复制模板失败'));
  return res.json();
}

// 公开模板列表
export async function listPublicTemplates(params?: { sort?: string; category?: string; page?: number; page_size?: number }): Promise<TemplateListResponse> {
  const query = new URLSearchParams();
  if (params?.sort) query.set('sort', params.sort);
  if (params?.category) query.set('category', params.category);
  if (params?.page) query.set('page', String(params.page || 1));
  if (params?.page_size) query.set('page_size', String(params.page_size || 20));
  const res = await fetch(`${BASE}/api/prompt-templates/public?${query}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取公开模板失败'));
  return res.json();
}

// 模板统计
export async function getTemplateStats(id: number): Promise<TemplateStatsResponse> {
  const res = await fetch(`${BASE}/api/prompt-templates/${id}/stats`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取统计失败'));
  return res.json();
}

// 点赞/取消点赞
export async function likeTemplate(id: number): Promise<{ like_count: number; is_liked: boolean }> {
  const res = await fetch(`${BASE}/api/prompt-templates/${id}/like`, {
    method: 'POST',
    headers: apiHeaders(true),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '点赞失败'));
  return res.json();
}

export async function unlikeTemplate(id: number): Promise<{ like_count: number; is_liked: boolean }> {
  const res = await fetch(`${BASE}/api/prompt-templates/${id}/like`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '取消点赞失败'));
  return res.json();
}

// 作品绑定/解绑模板
export async function bindStoryTemplate(storyId: number, templateId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/bind-template`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ template_id: templateId }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '绑定模板失败'));
}

export async function getStoryTemplate(storyId: number): Promise<{ template: PromptTemplateItem | null }> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/template`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取作品模板失败'));
  return res.json();
}

export async function unbindStoryTemplate(storyId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/template`, {
    method: 'DELETE',
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '解绑模板失败'));
}
```

- [ ] **Step 2：验证编译**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

预期无错误。

- [ ] **Step 3：提交**

```bash
git add frontend/src/api.ts
git commit -m "feat: add prompt template API functions to frontend"
```

---

### 任务 8：前端模板编辑器组件

**Files:**
- Create: `frontend/src/components/TemplateEditor.tsx`
- Modify: `frontend/src/components/TemplateMarket.tsx`（新建广场组件）

- [ ] **Step 1：创建参数映射定义**

在 `TemplateEditor.tsx` 开头定义参数映射：

```typescript
import React, { useState, useEffect } from 'react';
import {
  createPromptTemplate,
  updatePromptTemplate,
  getPromptTemplate,
  type PromptTemplateItem,
} from '../api';

type PromptType = 'framework' | 'chapter' | 'character' | 'manga_style';

interface ParamDef {
  key: string;
  label: string;
  options: { value: string; label: string }[];
}

const PARAM_DEFS: Record<PromptType, ParamDef[]> = {
  framework: [
    { key: 'story_length', label: '篇幅', options: [
      { value: 'short', label: '短篇' }, { value: 'medium', label: '中篇' }, { value: 'long', label: '长篇' }
    ]},
    { key: 'pacing', label: '节奏', options: [
      { value: 'fast', label: '快节奏' }, { value: 'steady', label: '稳健' }, { value: 'slow', label: '慢热' }
    ]},
    { key: 'tone', label: '基调', options: [
      { value: 'light', label: '轻松' }, { value: 'balanced', label: '平衡' }, { value: 'serious', label: '严肃' }, { value: 'dark', label: '黑暗' }
    ]},
    { key: 'world_building', label: '世界观', options: [
      { value: 'simple', label: '简单' }, { value: 'moderate', label: '适中' }, { value: 'rich', label: '丰富' }
    ]},
    { key: 'character_depth', label: '角色深度', options: [
      { value: 'shallow', label: '浅' }, { value: 'medium', label: '中' }, { value: 'deep', label: '深' }
    ]},
    { key: 'structure', label: '结构', options: [
      { value: 'three_act', label: '三幕' }, { value: 'flexible', label: '灵活' }
    ]},
  ],
  chapter: [
    { key: 'writing_style', label: '写作风格', options: [
      { value: 'concise', label: '简洁' }, { value: 'balanced', label: '平衡' }, { value: 'descriptive', label: '描写丰富' }
    ]},
    { key: 'dialogue_ratio', label: '对话比例', options: [
      { value: 'low', label: '少' }, { value: 'medium', label: '中' }, { value: 'high', label: '多' }
    ]},
    { key: 'vocabulary_level', label: '词汇水平', options: [
      { value: 'simple', label: '简单' }, { value: 'moderate', label: '适中' }, { value: 'advanced', label: '高级' }
    ]},
  ],
  character: [
    { key: 'detail_level', label: '详细度', options: [
      { value: 'basic', label: '基础' }, { value: 'medium', label: '中等' }, { value: 'high', label: '详细' }
    ]},
    { key: 'personality_depth', label: '性格深度', options: [
      { value: 'simple', label: '简单' }, { value: 'moderate', label: '适中' }, { value: 'deep', label: '深' }
    ]},
    { key: 'arc_planning', label: '成长弧光', options: [
      { value: 'basic', label: '基础' }, { value: 'moderate', label: '适中' }, { value: 'complete', label: '完整' }
    ]},
  ],
  manga_style: [
    { key: 'art_style', label: '画风', options: [
      { value: 'realistic', label: '写实' }, { value: 'anime', label: '动漫' }, { value: 'cartoon', label: '卡通' }, { value: 'ink', label: '水墨' }
    ]},
    { key: 'color_scheme', label: '配色', options: [
      { value: 'monochrome', label: '黑白' }, { value: 'muted', label: '柔和' }, { value: 'vibrant', label: '鲜艳' }
    ]},
    { key: 'mood', label: '氛围', options: [
      { value: 'calm', label: '平静' }, { value: 'neutral', label: '中性' }, { value: 'intense', label: '紧张' }, { value: 'epic', label: '史诗' }
    ]},
  ],
};

const TAB_LABELS: Record<PromptType, string> = {
  framework: '框架生成',
  chapter: '正文扩写',
  character: '角色生成',
  manga_style: '漫画风格',
};
```

- [ ] **Step 2：创建 TemplateEditor 组件**

```typescript
interface Props {
  template?: PromptTemplateItem | null; // null = 新建模式
  onSave: () => void;
  onCancel: () => void;
}

export default function TemplateEditor({ template, onSave, onCancel }: Props) {
  const isNew = !template;
  const [name, setName] = useState(template?.name || '');
  const [description, setDescription] = useState(template?.description || '');
  const [category, setCategory] = useState(template?.category || '');
  const [tags, setTags] = useState((template?.tags || []).join(', '));
  const [expertMode, setExpertMode] = useState(false);
  const [activeTab, setActiveTab] = useState<PromptType>('framework');
  const [saving, setSaving] = useState(false);

  // 参数化配置状态
  const [fwParams, setFwParams] = useState<Record<string, string>>(template?.framework_params || {});
  const [chParams, setChParams] = useState<Record<string, string>>(template?.chapter_params || {});
  const [charParams, setCharParams] = useState<Record<string, string>>(template?.character_params || {});
  const [msParams, setMsParams] = useState<Record<string, string>>(template?.manga_style_params || {});

  // 专家模式内容
  const [fwPrompt, setFwPrompt] = useState(template?.framework_prompt || '');
  const [chPrompt, setChPrompt] = useState(template?.chapter_prompt || '');
  const [charPrompt, setCharPrompt] = useState(template?.character_prompt || '');
  const [msPrompt, setMsPrompt] = useState(template?.manga_style_prompt || '');

  const paramStates: Record<PromptType, [Record<string, string>, (v: Record<string, string>) => void]> = {
    framework: [fwParams, setFwParams],
    chapter: [chParams, setChParams],
    character: [charParams, setCharParams],
    manga_style: [msParams, setMsParams],
  };

  const promptStates: Record<PromptType, [string, (v: string) => void]> = {
    framework: [fwPrompt, setFwPrompt],
    chapter: [chPrompt, setChPrompt],
    character: [charPrompt, setCharPrompt],
    manga_style: [msPrompt, setMsPrompt],
  };

  const defs = PARAM_DEFS[activeTab];
  const [params, setParams] = paramStates[activeTab];
  const [prompt, setPrompt] = promptStates[activeTab];

  async function handleSave() {
    setSaving(true);
    try {
      const data = {
        name: name.trim(),
        description: description.trim(),
        category: category.trim(),
        tags: tags.split(',').map(t => t.trim()).filter(Boolean),
        framework_params: expertMode ? null : fwParams,
        chapter_params: expertMode ? null : chParams,
        character_params: expertMode ? null : charParams,
        manga_style_params: expertMode ? null : msParams,
        framework_prompt: expertMode ? fwPrompt : null,
        chapter_prompt: expertMode ? chPrompt : null,
        character_prompt: expertMode ? charPrompt : null,
        manga_style_prompt: expertMode ? msPrompt : null,
      };
      if (isNew) {
        await createPromptTemplate(data);
      } else {
        await updatePromptTemplate(template!.id, data);
      }
      onSave();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-bold">{isNew ? '创建模板' : '编辑模板'}</h2>

      {/* 基本信息 */}
      <input
        value={name}
        onChange={e => setName(e.target.value)}
        className="w-full rounded-xl border px-3 py-2"
        placeholder="模板名称（必填）"
      />
      <textarea
        value={description}
        onChange={e => setDescription(e.target.value)}
        className="w-full rounded-xl border px-3 py-2"
        placeholder="模板描述"
        rows={2}
      />
      <div className="flex gap-2">
        <input
          value={category}
          onChange={e => setCategory(e.target.value)}
          className="flex-1 rounded-xl border px-3 py-2"
          placeholder="分类（如：玄幻）"
        />
        <input
          value={tags}
          onChange={e => setTags(e.target.value)}
          className="flex-1 rounded-xl border px-3 py-2"
          placeholder="标签（逗号分隔）"
        />
      </div>

      {/* 模式切换 */}
      <div className="flex items-center gap-2">
        <span className="text-sm text-slate-500">编辑模式：</span>
        <button
          onClick={() => setExpertMode(false)}
          className={`rounded-xl px-3 py-1 text-sm ${!expertMode ? 'bg-blue-600 text-white' : 'border text-slate-600'}`}
        >简单模式</button>
        <button
          onClick={() => setExpertMode(true)}
          className={`rounded-xl px-3 py-1 text-sm ${expertMode ? 'bg-blue-600 text-white' : 'border text-slate-600'}`}
        >专家模式</button>
      </div>

      {/* Tab 切换 */}
      <div className="flex gap-1 border-b">
        {(Object.keys(TAB_LABELS) as PromptType[]).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`rounded-t-lg px-3 py-2 text-sm ${activeTab === tab ? 'border-b-2 border-blue-600 font-medium text-blue-600' : 'text-slate-500'}`}
          >
            {TAB_LABELS[tab]}
          </button>
        ))}
      </div>

      {/* 编辑区 */}
      {expertMode ? (
        <textarea
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          className="w-full rounded-xl border px-3 py-2 font-mono text-sm"
          placeholder={`在此编辑 ${TAB_LABELS[activeTab]} 提示词...`}
          rows={12}
        />
      ) : (
        <div className="space-y-3">
          {defs.map(def => (
            <div key={def.key}>
              <label className="mb-1 block text-sm text-slate-600">{def.label}</label>
              <select
                value={params[def.key] || def.options[0].value}
                onChange={e => setParams({ ...params, [def.key]: e.target.value })}
                className="w-full rounded-xl border px-3 py-2"
              >
                {def.options.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          ))}
          <div>
            <label className="mb-1 block text-sm text-slate-600">自定义规则</label>
            <input
              value={params.custom_rules || params.custom_style_notes || params.custom_requirements || params.custom_style_prompt || ''}
              onChange={e => setParams({ ...params, custom_rules: e.target.value })}
              className="w-full rounded-xl border px-3 py-2"
              placeholder="补充说明（可选）"
            />
          </div>
        </div>
      )}

      {/* 操作按钮 */}
      <div className="flex justify-end gap-2 pt-4 border-t">
        <button onClick={onCancel} className="rounded-xl border px-4 py-2 text-sm text-slate-600">取消</button>
        <button
          onClick={handleSave}
          disabled={saving || !name.trim()}
          className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {saving ? '保存中...' : '保存'}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2：验证编译**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "TemplateEditor" | head -10
```

- [ ] **Step 3：提交**

```bash
git add frontend/src/components/TemplateEditor.tsx
git commit -m "feat: add TemplateEditor component with simple/expert mode"
```

---

## 第二阶段：社区生态（任务 9-11）

### 任务 9：评论系统

**Files:**
- Modify: `backend/models.py`（新增 TemplateComment 模型）
- Modify: `backend/database.py`（新增迁移）
- Modify: `backend/schemas.py`（新增 schema）
- Modify: `backend/main.py`（新增评论路由）

- [ ] **Step 1：新增 TemplateComment 模型**

在 `backend/models.py` 的 `TemplateLike` 之后添加：

```python
class TemplateComment(Base):
    """模板评论"""
    __tablename__ = "template_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompt_templates.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("template_comments.id"), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    template: Mapped["PromptTemplate"] = relationship("PromptTemplate")
```

- [ ] **Step 2：新增评论迁移**

在 `_migrate_prompt_templates()` 函数末尾添加 `template_comments` 表的创建逻辑。

- [ ] **Step 3：新增评论 API**

在 `backend/main.py` 添加评论 CRUD 路由：`POST/GET/DELETE /api/prompt-templates/{id}/comments`

- [ ] **Step 4：提交**

### 任务 10：排行榜与统计

**Files:**
- Modify: `backend/main.py`（新增排行榜路由）

- [ ] **Step 1：实现排序逻辑**（已有热度计算基础）

- [ ] **Step 2：实现排行榜 API**：按热度排序的 `/api/prompt-templates/leaderboard`

- [ ] **Step 3：提交**

### 任务 11：通知系统

**Files:**
- Modify: `backend/main.py`（模板审核结果通知）

- [ ] **Step 1：审核结果通知**：审核通过/拒绝时发送站内通知

- [ ] **Step 2：评论通知**：有人评论时通知模板作者

- [ ] **Step 3：提交**

---

## 验证清单

### 第一阶段验证
- [ ] 后端启动无错误（`python main.py`）
- [ ] 数据库表创建成功（3 个新表 + 索引）
- [ ] 创建/编辑/删除模板 API 正常
- [ ] 作品绑定/解绑模板 API 正常
- [ ] 模板广场列表 API 正常（公开模板可见）
- [ ] 点赞/取消点赞 API 正常
- [ ] 管理员审核（通过/拒绝/下架）API 正常
- [ ] 前端编译无错误（`npm run build`）
- [ ] 模板编辑器（简单/专家模式）可用
- [ ] 模板广场页面可用

### 第二阶段验证
- [ ] 评论 CRUD API 正常
- [ ] 排行榜按预期排序
- [ ] 通知正确发送

---

**计划版本**: v1.0  
**创建日期**: 2026-05-31  
**对应的设计文档**: `docs/superpowers/specs/2026-05-31-prompt-template-system-design.md`
