# Onboarding → Framework 无缝过渡

## 问题

当前的 AI 引导建书（Onboarding）结束后，只将 creative brief 保存到 `story_bible`，然后直接跳转到工作台。用户面对空白的 FrameworkPanel（没有大纲、角色、标签），需要自己发现并手动触发框架生成，引导链条断裂。

## 目标

Onboarding 确认后**自动触发生成故事框架**（大纲 + 角色 + 标签 + 章节规划），让用户进入工作台时框架已经就绪，零操作即可看到完整的创作蓝本。

## 设计

### 数据流

```
Onboarding 对话 (Understanding)
  ↓
confirm_onboarding API
  ├─ Step 1: 构建 story_bible (现有逻辑)
  ├─ Step 2: 自动调用 generate_framework (新增)
  │     ├─ 从 story_bible.creative_brief 构建 seed description
  │     ├─ 传递 story_bible 作为 context
  │     └─ 保存生成的 tags/characters/outline 到 story
  └─ 返回 {story_bible, creative_brief, framework}
  ↓
前端 OnboardingPage 过渡动画
  ├─ 创意分析卡已确认 ✓
  ├─ 正在构建故事框架... (等待后端)
  └─ 框架就绪 → 进入工作台
```

### 后端改动（main.py）

**`confirm_onboarding` 端点**：在现有逻辑后增加自动框架生成。

```python
# 伪代码改动
def confirm_onboarding(..., auto_generate=True):
    # 1. 现有逻辑：构建 story_bible
    story_bible = await build_story_bible(creative_brief, raw_input, api_key=...)
    story.story_bible = story_bible
    story.description = ...
    story.onboarding_completed = True
    db.commit()

    # 2. 新增：自动生成框架
    framework_result = None
    if auto_generate:
        try:
            description = _build_framework_seed_description(story)
            if description.strip():
                story_context = _build_framework_ai_context(story, mode="initial_generate")
                framework = await generate_framework(
                    description, api_key=..., story_bible=story_bible,
                    story_context=story_context, launch_ready_required=True,
                )
                story.tags = normalize_tags(framework.get("tags"))
                story.characters = normalize_characters(framework.get("characters"))
                story.outline = framework.get("outline", {})
                _save_framework_snapshot(...)
                db.commit()
                framework_result = {"tags": ..., "characters": ..., "outline": ...}
        except Exception:
            pass  # 优雅降级

    return {story_id, story_bible, creative_brief, framework: framework_result}
```

**关键设计决定**：
- 捕获所有异常，框架生成失败不影响 onboarding 完成
- 复用 `_build_framework_seed_description` 和 `_build_framework_ai_context`（已有函数）
- 复用 `generate_framework`（已有函数），传 `story_bible` 和 `story_context`
- 自动保存初始快照（`_save_framework_snapshot`）
- 配额扣减：在调用 `generate_framework` 前 pre-check（`deduct=False`），保存成功后 deduct（`deduct=True`），与 `generate_framework_endpoint` 中的模式一致

### 前端改动

**api.ts** — `OnboardingConfirmResponse` 新增字段：
```typescript
export interface OnboardingConfirmResponse {
  story_id: number;
  story_bible: StoryBible;
  creative_brief: CreativeBrief;
  framework?: {  // 新增
    tags?: Tags;
    characters?: Character[];
    outline?: Outline;
  } | null;
}
```

**OnboardingPage.tsx** — `handleConfirm` 改为三步过渡：
1. **Phase 1 - confirming**: 调用 `confirmOnboarding`，显示"正在生成创意分析卡..."
2. **Phase 2 - generating_framework**: 等待后端返回（框架已在后端生成），显示"正在构建故事框架..."带进度动画
3. **Phase 3 - ready**: 显示"故事框架已就绪！"和"进入工作台"按钮

过渡态 UI 替换原来的 "确认生成" 按钮区域，不离开当前页面。点击"进入工作台"再跳转到 workspace。

**App.tsx** — 无需改动。`getStory` 返回完整 `Story` 对象（含 tags/outline/characters），框架数据已在 DB 中。

### 边界情况

| 场景 | 处理 |
|------|------|
| DeepSeek 超时或异常 | 捕获异常，`framework_result = None`，前端显示降级提示 |
| 已有框架数据（二次引导） | `_build_framework_seed_description` 返回空时跳过 |
| 跳过引导（skip） | 不变，不走框架生成 |
| 配额不足 | generate_framework 内会抛异常，捕获后优雅降级 |

### 不变的部分

- FrameworkPanel 的 AI 对话继续可用（用户可后续调整框架）
- `generate_framework_endpoint`、`adjust_framework_endpoint` 不受影响
- `skip_onboarding` 端点不变
- 导入作品的引导（import-context）不变

## 文件清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `backend/main.py` | 修改 | confirm_onboarding 新增 auto_generate 逻辑 |
| `frontend/src/api.ts` | 修改 | OnboardingConfirmResponse 新增 framework 字段 |
| `frontend/src/components/OnboardingPage.tsx` | 修改 | handleConfirm 三步过渡 + 过渡态 UI |
| `backend/tests/test_onboarding.py` | 修改 | 新增 confirm→auto_framework 测试 |

## 不做

- 不做 FrameworkPanel 改造
- 不做框架预览编辑（用户可在工作台用现有功能调整）
- 不做背景渐进式加载 —— 同步等框架生成完再返回
- 不做 SSE 流式框架生成（当前 generate_framework 已是同步调用）
