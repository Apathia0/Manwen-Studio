# 视频工作流全局角色库设计

> 状态：设计完成，待用户审核
> 日期：2026-05-23

## 一、背景与问题

### 当前痛点

1. **操作繁琐**：视频工作流需要 加载章节 → AI拆场次 → 选场次 → 选镜头 → 资产生成，每次都要多点
2. **角色不一致**：每个 Shot 独立调用 `parse_shot_asset_prompts` 重新 AI 解析角色提示词，再调用 `generate_shot_character_asset` 重新生成角色图片
3. **资源浪费**：同一角色在不同 Shot 中反复生成，既费 API 额度又无法保证形象一致
4. **无全局角色概念**：`_select_character_reference_assets_for_scene` 仅按 `chapter_id` 筛选，跨章节/跨镜头角色不共享

### 漫画工作流的成功模式

- 角色卡在 Story 级一次性生成
- 文本外貌卡（`character_profiles`）和参考图分开管理
- 所有章节共享同一套角色卡，章节可覆盖
- 漫画生成时后端自动加载角色数据，前端无需每次传参

## 二、设计目标

1. **Story 级统一**：角色卡在故事级别一次性生成，所有章节/场景/镜头自动继承
2. **多版本管理**：每个角色支持多个服装/形象版本，用户可随时切换默认版本
3. **全流程自动继承**：分镜图、首尾帧、视频生成自动读取 Story 级角色参考图，无需手动勾选
4. **强制图生模式**：只要存在用户选中的参考资产，生成端点自动切换到图生图/图生视频模式
5. **零重复生成**：角色 prompt 从角色库直接读取，不依赖 AI 重新解析

## 三、数据模型

### 3.1 新增表：`story_character_versions`

```sql
CREATE TABLE story_character_versions (
    id SERIAL PRIMARY KEY,
    story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    character_name VARCHAR(100) NOT NULL,
    version_label VARCHAR(50) NOT NULL DEFAULT 'v1-默认',
    appearance_card TEXT NOT NULL DEFAULT '',
    ref_asset_id INTEGER REFERENCES video_assets(id),
    is_default BOOLEAN DEFAULT FALSE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(story_id, character_name, version_label)
);
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | SERIAL | 主键 |
| `story_id` | FK → stories | 所属故事 |
| `character_name` | VARCHAR(100) | 角色名 |
| `version_label` | VARCHAR(50) | 版本标签，如 `v1-学生装`、`v2-战士装` |
| `appearance_card` | TEXT | 纯文本外貌卡，格式同漫画的 `character_profiles` |
| `ref_asset_id` | FK → video_assets | 该版本的参考图资产 ID |
| `is_default` | BOOLEAN | 该角色当前默认版本，后续镜头自动使用 |
| `sort_order` | INTEGER | 排序 |

唯一约束 `(story_id, character_name, version_label)` 保证同一故事下每个角色的版本标签不重复。

### 3.2 Story 新增字段

```python
# models.py - Story
video_character_profiles: Mapped[str | None] = mapped_column(Text, nullable=True)
```

纯文本，由 AI 从 `story.characters`（结构化角色 JSON）一次生成，存储为类似漫画的格式：

```
角色名：林墨
身份定位：主角
外貌描述：黑色短发，剑眉星目，身形修长
服装要点：白色校服衬衫，深蓝长裤
气质与表情：沉稳冷静，眼神坚定
绘制注意：保持面部特征一致
```

### 3.3 文件存储路径

```
backend/video_outputs/
└── story_{story_id}/
    └── characters/
        ├── 林墨_v1_default.png
        ├── 林墨_v2_combat.png
        ├── 苏晚晴_v1_default.png
        └── ...
```

## 四、后端 API

### 4.1 新增端点（Story 级角色库）

#### ① 获取所有角色版本列表
```
GET /api/stories/{story_id}/video-characters

Response:
{
  characters: [
    {
      name: "林墨",
      versions: [
        { id: 101, label: "v1-学生装", is_default: true, ref_asset_id: 201, appearance_card: "..." },
        { id: 102, label: "v2-战士装", is_default: false, ref_asset_id: 202, appearance_card: "..." }
      ]
    }
  ]
}
```

#### ② AI 生成角色外貌卡（首次使用/重新生成）
```
POST /api/stories/{story_id}/video-characters/generate

逻辑：
1. 读取 story.characters（结构化角色 JSON）
2. 调用 DeepSeek 生成纯文本外貌卡 → 写入 story.video_character_profiles
3. 解析外貌卡，为每个角色创建 v1-默认 版本（存入 story_character_versions）
4. 返回角色列表
```

#### ③ 创建/更新角色版本
```
POST /api/stories/{story_id}/video-characters/{character_name}/versions

Body: { version_label: "v2-战斗装", appearance_card: "...", set_default: true }

逻辑：
1. 新建或更新 version_label 对应的版本
2. 可同时设为该角色的 is_default
3. 返回版本对象
```

#### ④ 删除角色版本
```
DELETE /api/stories/{story_id}/video-characters/{character_name}/versions/{version_id}
```

#### ⑤ 生成版本参考图
```
POST /api/stories/{story_id}/video-characters/{character_name}/versions/{version_id}/generate-ref

逻辑：
1. 读取版本 appearance_card 作为 prompt
2. 调用 image2.generate_reference_image()
3. 保存到 video_outputs/story_{id}/characters/{name}_{version}.png
4. 创建 VideoAsset（asset_type="story_character_reference", story_id=story_id）
5. 更新 version.ref_asset_id
```

### 4.2 现有端点改造

#### `parse_shot_asset_prompts` — 角色维度不再调用 AI

（`backend/routers/video.py` — `POST /api/shots/{shot_id}/asset-prompts/parse`）

现有行为：为每个角色调用 DeepSeek 生成 `character_prompts`

改造后：
1. 从 `scene.characters_json` 提取角色名列表
2. 查 `story_character_versions` 取每个角色 `is_default=true` 的版本
3. `character_prompts` 直接从版本 `appearance_card` 转换，无需 AI
4. 其他 prompt（storyboard/frame/video）保持现有 AI 解析逻辑不变
5. 结果仍持久化到 `shot.character_prompts_json`

#### `generate_shot_character_asset` — 不再需要

保留端点（向后兼容），但逻辑简化：如其被调用，仅作为单镜头覆盖的特殊情况使用。正常流程中不触发。

#### `_select_character_reference_assets_for_scene` — 重构

（`backend/routers/video.py`）

现有行为：按 `chapter_id` 筛选 `character_reference` 资产

改造后（两级 fallback）：
1. 查 Story 级：从 `story_character_versions` 找场景登场角色的 `is_default=true` 版本的 `ref_asset_id`
2. 查 Chapter 级：从 `video_assets` 表找同章节的 `character_reference` 资产（兜底）
3. 合并去重返回

#### `_collect_shot_reference_asset_ids` — 增强

（`backend/routers/video.py`）

当 `include_characters=True` 时，新增调用 `_get_story_character_reference_asset_ids(story_id, db)` 自动合并 Story 级角色参考图。

### 4.3 辅助函数

#### `_get_story_character_reference_asset_ids(story_id, db) → list[int]`

```python
def _get_story_character_reference_asset_ids(story_id: int, db: Session) -> list[int]:
    """获取 Story 级所有角色默认版本的参考图 asset ID。"""
    versions = db.query(StoryCharacterVersion).filter(
        StoryCharacterVersion.story_id == story_id,
        StoryCharacterVersion.is_default == True,
        StoryCharacterVersion.ref_asset_id.isnot(None),
    ).all()
    return [v.ref_asset_id for v in versions]
```

### 4.4 视频生成 i2v 判定加强

（`backend/routers/video.py` — 两个 `render_shot_video` 端点）

当前 `input_mode` 判定：
```python
if source_storyboard_asset_id and shot.storyboard_locked:
    input_mode = "image_to_video"
else:
    input_mode = "text_to_video"
```

加强后：
```python
has_ref_images = bool(reference_image_urls)
has_storyboard = source_storyboard_asset_id and shot.storyboard_locked
if has_storyboard:
    input_mode = "image_to_video"
elif has_ref_images:
    input_mode = "image_to_video"  # 有角色参考图也走图生视频
else:
    input_mode = "text_to_video"
```

### 4.5 图生图模式保证

分镜图、首尾帧、场景图三个端点使用 `image2_service.generate_reference_image(ref_image_paths=...)`。只要 `ref_paths` 非空，`image2.py` 自动走 `/images/edits` 端点（图生图模式）。此逻辑已在之前的改造中生效。

## 五、前端

### 5.1 新增组件：`VideoCharacterLibrary.tsx`

位于 `VideoPanel.tsx` 顶部 Tab 中，三栏布局：

```
左栏 — 角色列表          中栏 — 当前角色版本管理      右栏 — 参考图预览
─────────────────────  ──────────────────────────  ──────────────────────
[★] 林墨              当前版本: v1-学生装 ▼        ┌──────────────────┐
[ ] 苏晚晴            版本历史:                    │                  │
[ ] 萧然              ○ v1-学生装 (默认)           │   参考图预览      │
                       ○ v2-战士装                 │                  │
[ 生成全部角色卡 ]                                 │   点击可放大     │
[ 生成全部参考图 ]    外貌卡:                       └──────────────────┘
                       ┌─────────────────────┐
                       │ 黑色短发，剑眉星目， │    [ 重绘参考图 ]
                       │ 身形修长...          │    [ 设为默认版本 ]
                       │ (可编辑 textarea)    │
                       └─────────────────────┘
                       [ 保存外貌卡 ]
                       [ 新建版本 ]
                       [ 生成参考图 ]
```

#### 核心交互

| 操作 | 说明 |
|------|------|
| 点击角色名 | 右侧显示该角色的所有版本 + 详情 |
| ★ 标记 | 当前 Story 的有效角色（从各场景 `characters_json` 汇总） |
| 下拉切换版本 | 选择该角色当前使用的版本 → 自动调用后端更新 `is_default` |
| 新建版本 | 弹出框输入版本标签 + 复制当前外貌卡作为模板 → 保存 |
| 生成全部角色卡 | 调 AI 从 `story.characters` 生成外貌卡 → 为每个角色创建 v1 |
| 生成全部参考图 | 逐个角色调后端生成参考图（带进度显示） |
| 编辑外貌卡 | textarea 直接编辑 → 调用版本更新端点 |
| 设为此角色的默认版本 | 该角色在后续所有镜头中自动使用 |
| 重绘参考图 | 复用已有的 `ImageRedrawModal` 组件 |

### 5.2 `ShotAssetWorkflowPanel.tsx` 改造

#### 角色部分（characters Tab）改为只读继承

- 角色名称列表 → 从角色库读取
- 角色 prompt → 从角色库读取（只读展示，允许单镜头微调但不覆盖 Story 级）
- 去掉"生成角色图"按钮 → 改为引导用户去"角色库"Tab 生成
- 角色下拉和 textarea 保留 → 但 prompt 来源改为角色库

#### 资产包部分（bundle Tab）

- 角色资产自动从 Story 级继承，不显示在手动勾选列表中
- 场景图/分镜图/首尾帧的继承选项保留
- 手动检查项保留（用户仍可追加额外资产）

### 5.3 `VideoPanel.tsx` 改造

顶部导航新增 Tab：
```
[ 剧本 ] [ 分镜 ] [ 资产管理 ] [ ★ 角色库 ] [ 结果 ]
```

### 5.4 `api.ts` 新增函数

```typescript
// 角色库
getVideoCharacters(storyId: number): Promise<VideoCharactersResponse>
generateVideoCharacters(storyId: number): Promise<VideoCharactersResponse>
createCharacterVersion(storyId: number, name: string, payload: CreateVersionPayload): Promise<CharacterVersion>
deleteCharacterVersion(storyId: number, name: string, versionId: number): Promise<void>
generateCharacterRefImage(storyId: number, name: string, versionId: number): Promise<{ ref_asset_id: number }>
```

## 六、数据库迁移

`database.py` 新增 `_migrate_video_character_tables()` 函数：

```python
def _migrate_video_character_tables():
    """Phase 2: Story-level character library for video workflow."""
    insp = inspect(engine)
    
    # stories.video_character_profiles
    stories_cols = {c["name"] for c in insp.get_columns("stories")} if "stories" in insp.get_table_names() else set()
    if stories_cols and "video_character_profiles" not in stories_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE stories ADD COLUMN video_character_profiles TEXT"))
    
    # story_character_versions table
    if "story_character_versions" not in insp.get_table_names():
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE story_character_versions (
                    id SERIAL PRIMARY KEY,
                    story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
                    character_name VARCHAR(100) NOT NULL,
                    version_label VARCHAR(50) NOT NULL DEFAULT 'v1-默认',
                    appearance_card TEXT NOT NULL DEFAULT '',
                    ref_asset_id INTEGER REFERENCES video_assets(id),
                    is_default BOOLEAN DEFAULT FALSE,
                    sort_order INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(story_id, character_name, version_label)
                )
            """))
```

在 `_migrate` 末尾调用 `_migrate_video_character_tables()`。

## 七、实现计划

### 阶段 1：数据库 + 模型（3 个文件，~60 行）

| # | 任务 | 文件 |
|---|------|------|
| 1.1 | Story 新增 `video_character_profiles` 字段 | `backend/models.py` |
| 1.2 | 新增 `StoryCharacterVersion` 模型 | `backend/models.py` |
| 1.3 | 新增 `_migrate_video_character_tables()` | `backend/database.py` |

### 阶段 2：Story 级 API（1 个文件，~200 行）

| # | 任务 |
|---|------|
| 2.1 | `GET /api/stories/{id}/video-characters` |
| 2.2 | `POST /api/stories/{id}/video-characters/generate` |
| 2.3 | `POST .../{name}/versions` |
| 2.4 | `DELETE .../{name}/versions/{version_id}` |
| 2.5 | `POST .../versions/{id}/generate-ref` |
| 2.6 | `_get_story_character_reference_asset_ids()` 辅助函数 |

### 阶段 3：现有端点改造（1 个文件，~100 行）

| # | 任务 |
|---|------|
| 3.1 | `parse_shot_asset_prompts` — 角色维度改从角色库读取 |
| 3.2 | `_select_character_reference_assets_for_scene` — 重构两级 fallback |
| 3.3 | `_collect_shot_reference_asset_ids` — 新增 Story 级角色参考图合并 |
| 3.4 | `render_shot_video` ×2 — `input_mode` 判定加强 |

### 阶段 4：前端（4 个文件，~450 行）

| # | 任务 |
|---|------|
| 4.1 | `api.ts` 新增 5 个角色库 API 函数 + TypeScript 类型 |
| 4.2 | 新建 `VideoCharacterLibrary.tsx` 组件 |
| 4.3 | `VideoPanel.tsx` 顶部新增 Tab + 角色库集成 |
| 4.4 | `ShotAssetWorkflowPanel.tsx` 角色部分改为只读继承 |

### 总计

| 维度 | 数值 |
|------|------|
| 新增表 | 1 张（story_character_versions）|
| 新增端点 | 5 个 |
| 改造端点 | 5 个 |
| 新增前端组件 | 1 个（VideoCharacterLibrary.tsx）|
| 预估代码量 | ~800 行（后端 ~360 / 前端 ~450）|

## 八、验收标准

1. [ ] 用户进入视频工作台 → 角色库 Tab 可见
2. [ ] 首次使用 → 点击"生成全部角色卡" → AI 生成外貌卡 → 每个角色创建 v1
3. [ ] "生成全部参考图" → 逐个角色调用 Image2 API → 参考图存储到正确路径
4. [ ] 点击角色名 → 显示所有版本 → 可切换默认版本
5. [ ] 新建版本 → 编辑外貌卡 → 生成参考图 → 设为默认
6. [ ] 切换到任意镜头 → `parse_shot_asset_prompts` 不再调用 AI 解析角色维度
7. [ ] 角色 prompt 从角色库读取 → 展示在 ShotAssetWorkflowPanel
8. [ ] 生成分镜图 → 自动继承角色默认版本参考图 → 日志显示 `[edits(N refs)]`
9. [ ] 生成首尾帧 → 同上
10. [ ] 生成视频 → 自动继承角色参考图 → 日志显示 `input_mode=image_to_video`
11. [ ] 切换角色版本 → 后续镜头使用新版本 → 已生成的历史镜头不受影响
