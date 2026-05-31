# 提示词模板系统设计文档

## 1. 概述

### 1.1 背景

当前系统的提示词（框架生成、正文扩写、角色生成、漫画风格）都是硬编码在代码中，缺乏灵活性。用户无法根据自己的创作风格和需求自定义这些提示词。

**现状问题**：
- 框架生成提示词固定在 `backend/services/deepseek.py` 的 `FRAMEWORK_SYSTEM_PROMPT`
- 正文扩写、角色生成、漫画风格提示词分散在各个服务文件中
- 用户无法调整 AI 生成的风格和偏好
- 缺少模板分享和复用机制，无法形成创作生态

### 1.2 目标

- 允许用户自定义提示词模板
- 支持模板保存和复用，跨作品使用
- 建立模板分享社区生态
- 提供简单和专家两种编辑模式，兼顾易用性和灵活性
- 管理员审核机制保障内容质量

### 1.3 实施策略

采用渐进式实现，分两个阶段：

- **第一阶段（MVP，约 1 周）**：核心模板功能 + 基础审核 + 简单广场
- **第二阶段（社区生态，约 1 周）**：评论系统 + 排行榜 + 通知

---

## 2. 核心概念

### 2.1 模板套装

一个模板包含 4 类提示词，形成完整的创作风格配置：

| 类型 | 用途 | 当前系统对应 |
|------|------|-------------|
| 框架生成提示词 | 生成故事大纲、角色设定、章节规划 | `FRAMEWORK_SYSTEM_PROMPT` 和 `_long_form_framework_rules()` |
| 正文扩写提示词 | 章节内容生成、对话扩写、场景描写 | Agent system prompt 中的章节编辑指令 |
| 角色生成提示词 | 生成角色外貌卡和性格描述 | `image2.py` 中的角色外貌卡生成 prompt |
| 漫画风格提示词 | 图像生成的风格控制、画面氛围 | `image2.py` 中的漫画图像生成 prompt |

### 2.2 编辑模式

**简单模式**：通过参数化字段配置，系统自动生成完整 prompt
- 适合普通用户，降低使用门槛
- 提供下拉选择和预设选项
- 实时预览生成的完整 prompt

**专家模式**：直接编辑完整的 prompt 文本
- 适合高级用户，完全自由控制
- 可精细调整每个细节
- 支持代码编辑器（语法高亮）

两种模式的数据同时保存：参数化配置存入 `*_params` 字段，完整 prompt 存入 `*_prompt` 字段。用户可以随时切换模式。

### 2.3 作用范围

- 模板绑定到**作品级别**
- 一个作品使用一个模板
- 该作品的所有章节和操作共用该模板
- 用户可在作品设置中随时切换模板

### 2.4 公开机制

- 用户创建的模板默认私有（`visibility=private`）
- 可申请公开，需管理员审核
- 审核通过后所有用户可见和使用
- 管理员可标记"官方推荐"、拒绝或下架
- 模板广场支持按分类、热度排序

---

## 3. 数据模型设计

### 3.1 模板主表（prompt_templates）

```sql
CREATE TABLE prompt_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    author_user_id INTEGER REFERENCES users(id),

    -- 四类提示词的完整内容（专家模式）
    framework_prompt TEXT,
    chapter_prompt TEXT,
    character_prompt TEXT,
    manga_style_prompt TEXT,

    -- 四类提示词的参数化配置（简单模式）
    framework_params JSONB,
    chapter_params JSONB,
    character_params JSONB,
    manga_style_params JSONB,

    -- 状态管理
    is_public BOOLEAN DEFAULT FALSE,
    status VARCHAR(20) DEFAULT 'draft',
    visibility VARCHAR(20) DEFAULT 'private',

    -- 统计数据
    usage_count INTEGER DEFAULT 0,
    like_count INTEGER DEFAULT 0,

    -- 分类标签
    category VARCHAR(50),
    tags JSONB,

    -- 审核信息
    submitted_at TIMESTAMP,
    reviewed_at TIMESTAMP,
    reviewed_by INTEGER REFERENCES users(id),
    review_note TEXT,

    -- fork 来源
    forked_from INTEGER REFERENCES prompt_templates(id),

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_templates_status ON prompt_templates(status);
CREATE INDEX idx_templates_visibility ON prompt_templates(visibility);
CREATE INDEX idx_templates_author ON prompt_templates(author_user_id);
CREATE INDEX idx_templates_category ON prompt_templates(category);
```

**状态字段说明**：

`status`（审核状态）：
- `draft`：草稿，用户创建但未提交审核
- `pending`：待审核，已提交等待管理员审核
- `approved`：已通过，审核通过可以公开
- `rejected`：已拒绝，审核未通过

`visibility`（可见性）：
- `private`：私有，仅创建者可见
- `public`：公开，所有用户可见
- `official`：官方推荐，管理员精选标记

### 3.2 作品绑定表（story_template_bindings）

```sql
CREATE TABLE story_template_bindings (
    id SERIAL PRIMARY KEY,
    story_id INTEGER REFERENCES stories(id) ON DELETE CASCADE,
    template_id INTEGER REFERENCES prompt_templates(id),
    bound_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(story_id)
);

CREATE INDEX idx_bindings_story ON story_template_bindings(story_id);
```

### 3.3 点赞表（template_likes）

```sql
CREATE TABLE template_likes (
    id SERIAL PRIMARY KEY,
    template_id INTEGER REFERENCES prompt_templates(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(template_id, user_id)
);
```

### 3.4 评论表（template_comments，第二阶段）

```sql
CREATE TABLE template_comments (
    id SERIAL PRIMARY KEY,
    template_id INTEGER REFERENCES prompt_templates(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    content TEXT NOT NULL,
    parent_id INTEGER REFERENCES template_comments(id),
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 4. 参数化配置设计

### 4.1 框架生成参数（framework_params）

```json
{
  "story_length": "long",
  "pacing": "steady",
  "structure": "flexible",
  "chapter_detail_level": "high",
  "character_depth": "deep",
  "world_building": "rich",
  "tone": "serious",
  "custom_rules": ""
}
```

| 参数 | 可选值 | 说明 |
|------|--------|------|
| story_length | short / medium / long | 小说篇幅 |
| pacing | fast / steady / slow | 叙事节奏 |
| structure | three_act / flexible / custom | 故事结构 |
| chapter_detail_level | high / medium / low | 章节规划详细度 |
| character_depth | shallow / medium / deep | 角色刻画深度 |
| world_building | simple / moderate / rich | 世界观复杂度 |
| tone | light / balanced / serious / dark | 故事基调 |
| custom_rules | 任意文本 | 用户自定义规则 |

### 4.2 正文扩写参数（chapter_params）

```json
{
  "writing_style": "descriptive",
  "dialogue_ratio": "medium",
  "scene_detail": "rich",
  "inner_monologue": "moderate",
  "pacing_preference": "varied",
  "vocabulary_level": "advanced",
  "custom_style_notes": ""
}
```

| 参数 | 可选值 | 说明 |
|------|--------|------|
| writing_style | concise / balanced / descriptive | 写作风格 |
| dialogue_ratio | low / medium / high | 对话与叙述比例 |
| scene_detail | minimal / moderate / rich | 场景描写详细度 |
| inner_monologue | minimal / moderate / extensive | 内心独白量 |
| pacing_preference | fast / varied / slow | 节奏偏好 |
| vocabulary_level | simple / moderate / advanced | 词汇水平 |
| custom_style_notes | 任意文本 | 自定义风格说明 |

### 4.3 角色生成参数（character_params）

```json
{
  "detail_level": "high",
  "appearance_focus": "balanced",
  "personality_depth": "deep",
  "relationship_emphasis": "high",
  "arc_planning": "complete",
  "custom_requirements": ""
}
```

| 参数 | 可选值 | 说明 |
|------|--------|------|
| detail_level | basic / medium / high | 角色卡详细度 |
| appearance_focus | minimal / balanced / detailed | 外貌描写重点 |
| personality_depth | simple / moderate / deep | 性格刻画深度 |
| relationship_emphasis | low / medium / high | 人际关系强调 |
| arc_planning | basic / moderate / complete | 角色成长弧光 |
| custom_requirements | 任意文本 | 自定义要求 |

### 4.4 漫画风格参数（manga_style_params）

```json
{
  "art_style": "anime",
  "color_scheme": "vibrant",
  "detail_level": "high",
  "composition": "dynamic",
  "lighting": "dramatic",
  "mood": "epic",
  "custom_style_prompt": ""
}
```

| 参数 | 可选值 | 说明 |
|------|--------|------|
| art_style | realistic / anime / cartoon / ink | 画风 |
| color_scheme | monochrome / muted / balanced / vibrant | 配色方案 |
| detail_level | low / medium / high | 细节程度 |
| composition | static / balanced / dynamic | 构图风格 |
| lighting | flat / natural / dramatic | 光影处理 |
| mood | calm / neutral / intense / epic | 画面氛围 |
| custom_style_prompt | 任意文本 | 自定义风格关键词 |

---

## 5. 业务流程设计

### 5.1 模板创建与编辑

```
用户进入模板编辑器
    ↓
选择编辑模式：简单 或 专家
    ↓
简单模式：填写参数化表单 → 系统预览生成结果
专家模式：直接编辑 prompt 文本
    ↓
保存为草稿（status=draft, visibility=private）
    ↓
后续操作：继续编辑 / 应用到作品 / 申请公开 / 删除
```

### 5.2 公开审核流程

```
用户点击「申请公开」
    ↓
status: draft → pending
记录 submitted_at
    ↓
管理员查看待审核列表
    ↓
┌─ 通过 ─────────────────────────────┐
│ status=approved                    │
│ visibility=public 或 official      │
│ 记录 reviewed_at                   │
│ 模板出现在广场                      │
└────────────────────────────────────┘
┌─ 拒绝 ─────────────────────────────┐
│ status=rejected                    │
│ 记录拒绝原因 review_note           │
│ 通知创建者                          │
└────────────────────────────────────┘
```

管理员还可对已公开模板执行**下架**（visibility→archived），使模板从广场消失但不删除。

### 5.3 模板使用流程

```
用户在作品设置中选择模板
    ↓
来源：我的模板 / 广场模板 / 系统默认
    ↓
创建 story_template_bindings 记录
    ↓
作品的所有 AI 操作读取该模板的 prompt
    ↓
模板 usage_count +1
```

### 5.4 模板广场浏览

```
用户进入广场
    ↓
排序维度：
- 官方推荐（visibility=official，按热度）
- 最新上架（按 reviewed_at 倒序）
- 最受欢迎（按 usage_count 倒序）
- 分类筛选（按 category 过滤）
    ↓
操作：预览详情 / 点赞 / 应用到作品 / 复制(fork)
```

---

## 6. API 接口设计

### 6.1 模板管理

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/api/prompt-templates` | 创建模板 | 登录用户 |
| GET | `/api/prompt-templates/my` | 我的模板列表 | 登录用户 |
| GET | `/api/prompt-templates/{id}` | 模板详情 | 所有者或公开 |
| PUT | `/api/prompt-templates/{id}` | 更新模板 | 所有者 |
| DELETE | `/api/prompt-templates/{id}` | 删除模板 | 所有者 |
| POST | `/api/prompt-templates/{id}/submit-for-review` | 提交审核 | 所有者 |
| POST | `/api/prompt-templates/{id}/fork` | 复制模板 | 登录用户 |

### 6.2 作品绑定

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/api/stories/{story_id}/bind-template` | 绑定模板 | 作品所有者 |
| GET | `/api/stories/{story_id}/template` | 查看绑定 | 作品所有者 |
| DELETE | `/api/stories/{story_id}/template` | 解绑模板 | 作品所有者 |

### 6.3 模板广场

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/api/prompt-templates/public` | 公开模板列表 | 无需登录 |
| POST | `/api/prompt-templates/{id}/like` | 点赞 | 登录用户 |
| DELETE | `/api/prompt-templates/{id}/like` | 取消点赞 | 登录用户 |
| GET | `/api/prompt-templates/{id}/stats` | 统计信息 | 无需登录 |

### 6.4 管理员审核

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/api/admin/prompt-templates/pending` | 待审核列表 | 管理员 |
| POST | `/api/admin/prompt-templates/{id}/approve` | 审核通过 | 管理员 |
| POST | `/api/admin/prompt-templates/{id}/reject` | 审核拒绝 | 管理员 |
| POST | `/api/admin/prompt-templates/{id}/archive` | 下架模板 | 管理员 |

**创建模板请求示例**：
```json
POST /api/prompt-templates
{
  "name": "玄幻长篇模板",
  "description": "适合玄幻修仙类长篇小说",
  "category": "玄幻",
  "tags": ["修仙", "热血", "升级"],
  "framework_params": {
    "story_length": "long",
    "pacing": "steady",
    "tone": "serious"
  }
}
```

**审核通过请求示例**：
```json
POST /api/admin/prompt-templates/{id}/approve
{
  "visibility": "official",
  "note": "质量优秀，推荐为官方模板"
}
```

---

## 7. 技术实现要点

### 7.1 参数到 Prompt 的转换

```python
def build_prompt_from_params(base_prompt: str, params: dict, param_type: str) -> str:
    """根据参数化配置生成完整 prompt"""
    prompt = base_prompt

    if param_type == "framework":
        rules = []
        if params.get("story_length") == "long":
            rules.append("支持 100+ 章的持续创作")
        if params.get("pacing") == "slow":
            rules.append("采用慢热节奏，前期重点铺垫世界观和角色关系")
        if params.get("tone") == "serious":
            rules.append("保持严肃基调，避免过于轻松的描写")
        if rules:
            prompt += "\n\n## 额外要求\n" + "\n".join(f"- {r}" for r in rules)

    elif param_type == "manga_style":
        style_parts = []
        art_style_map = {"anime": "日式动漫风格", "realistic": "写实电影风格",
                         "cartoon": "卡通风格", "ink": "中国水墨风格"}
        if params.get("art_style"):
            style_parts.append(art_style_map.get(params["art_style"], params["art_style"]))
        color_map = {"monochrome": "黑白单色", "vibrant": "鲜艳明亮配色"}
        if params.get("color_scheme"):
            style_parts.append(color_map.get(params["color_scheme"], params["color_scheme"]))
        if style_parts:
            prompt += f"\n\n画面风格：{'，'.join(style_parts)}。{params.get('custom_style_prompt', '')}"

    # ... 其他类型的参数转换

    return prompt
```

### 7.2 模板应用逻辑

```python
def get_effective_prompt(story_id: int, prompt_type: str) -> str:
    """获取作品实际使用的 prompt"""
    binding = db.query(StoryTemplateBinding).filter_by(story_id=story_id).first()

    if binding and binding.template:
        template = binding.template

        # 优先使用完整 prompt（专家模式）
        full_prompt = getattr(template, f"{prompt_type}_prompt", None)
        if full_prompt:
            return full_prompt

        # 从参数生成（简单模式）
        params = getattr(template, f"{prompt_type}_params", None)
        if params:
            return build_prompt_from_params(get_default_prompt(prompt_type), params, prompt_type)

    # 回退到系统默认
    return get_default_prompt(prompt_type)
```

### 7.3 热度计算（第二阶段排行榜用）

```python
def calculate_hotness(template: PromptTemplate) -> float:
    usage_score = template.usage_count * 2      # 每次使用 +2
    like_score = template.like_count * 5         # 每次点赞 +5

    days = max((datetime.now() - template.reviewed_at).days, 1)
    time_decay = 1 / (1 + days / 30)             # 30天半衰期

    official_bonus = 1.5 if template.visibility == "official" else 1.0

    return (usage_score + like_score) * time_decay * official_bonus
```

---

## 8. 实施计划

### 8.1 第一阶段（MVP，约 1 周）

| 天 | 任务 | 产出 |
|----|------|------|
| Day 1-2 | 数据库表创建 + 模板 CRUD 接口 + 参数→prompt 转换 | 后端核心功能可用 |
| Day 3-4 | 前端模板编辑器（简单/专家）+ 作品绑定 + 集成到现有 AI 流程 | 用户可创建和使用模板 |
| Day 5-6 | 审核工作流 + 管理员后台 + 模板广场（列表/搜索/点赞）| 公开分享功能可用 |
| Day 7 | 端到端测试 + 性能优化 + 创建 3-5 个官方默认模板 | 上线就绪 |

### 8.2 第二阶段（社区生态，约 1 周）

| 天 | 任务 | 产出 |
|----|------|------|
| Day 1-2 | 评论系统（评论/回复/管理）+ 通知 | 用户互动功能 |
| Day 3-4 | 排行榜算法 + 排行榜展示 + 统计详情 | 内容发现机制 |
| Day 5-6 | 模板版本管理 + 收藏功能 + 举报机制 | 功能完善 |
| Day 7 | 性能优化 + UX 优化 + 数据分析面板 | 社区生态完备 |

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Prompt 注入攻击 | 恶意指令影响 AI 行为 | 内容安全检查，限制特殊字符 |
| 低质量模板泛滥 | 降低社区价值 | 审核机制 + 社区评分 + 举报 |
| 大量模板查询性能 | API 响应慢 | 缓存热门模板，分页加载 |
| 专家模式学习成本高 | 新手弃用 | 默认简单模式，提供文档和示例 |
| 模板内容违规 | 平台风险 | 审核前置，关键词过滤，举报机制 |

---

## 10. 未来扩展

- **模板市场**：付费模板、打赏、创作者收益分成
- **AI 辅助**：AI 推荐模板、自动优化 prompt、智能参数建议
- **协作功能**：模板协作编辑、版本对比、模板合并
- **模板评测**：基于实际生成效果的用户评价和对比

---

**文档版本**: v1.0  
**创建日期**: 2026-05-31  
**作者**: Dreams & Claude Code  
**状态**: 待审核
