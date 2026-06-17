# Onboarding → Framework 无缝过渡 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Onboarding 确认后自动触发生成故事框架（大纲+角色+标签+章节规划），用户进入工作台时框架已就绪。

**Architecture:** 后端 `confirm_onboarding` 端点新增 `auto_generate_framework` 逻辑，保存 story_bible 后复用现有 `generate_framework` 函数生成框架并写入 story。前端 OnboardingPage 新增三步过渡态（确认中→框架构建中→就绪），后端返回框架数据后显示"框架已就绪"再跳转。

**Tech Stack:** Python/FastAPI (backend), React/TypeScript (frontend)

---

### Task 1: 后端 — confirm_onboarding 自动生成框架

**Files:**
- Modify: `backend/main.py:7840-7897`
- Test: `backend/tests/test_onboarding.py`

- [ ] **Step 1: 读取当前 confirm_onboarding 端点完整代码**

读取 `backend/main.py` 第 7820-7900 行确认代码范围，同时读取 `generate_framework_endpoint`（8223-8355）确认配额和 snapshot 处理模式。

- [ ] **Step 2: 实现 auto_generate_framework 逻辑**

在 `confirm_onboarding` 端点中，story_bible 保存成功后新增自动框架生成块：

```python
# --- 新增：自动生成框架 ---
framework_result = None
auto_generate = body.get("auto_generate_framework", True)
if auto_generate:
    try:
        description = _build_framework_seed_description(story)
        if description.strip():
            story_context = _build_framework_ai_context(story, mode="initial_generate")
            template_fw_prompt = get_effective_prompt(story_id, "framework", db)
            # 配额预检
            _check_and_consume_feature_quota(request, user.id, "framework.generate.monthly_limit", 1, db, deduct=False, provider_kind="text")
            # 释放 DB 事务，避免 AI 调用期间长连接占用
            _release_db_transaction(db)

            framework = await generate_framework(
                description.strip(),
                api_key=deepseek_api_key,
                story_bible=story_bible,
                story_context=story_context,
                launch_ready_required=True,
                system_prompt=template_fw_prompt or None,
            )

            story = _require_story_for_user(story_id, user, db)
            story.tags = framework.get("tags") if isinstance(framework.get("tags"), dict) else story.tags
            story.characters = _normalize_characters_payload(framework.get("characters"))
            story.outline = _merge_framework_outline({}, framework.get("outline"), framework.get("chapters"))
            db.commit()

            _save_framework_snapshot(
                story_id=story.id,
                snapshot_data=_build_current_snapshot_data(story),
                source="initial_generate",
                reply_summary="引导生成初始框架",
                db=db,
            )
            _enforce_framework_snapshot_limit(story.id, max_count=20, db=db)
            db.commit()

            # 配额扣减
            _check_and_consume_feature_quota(request, user.id, "framework.generate.monthly_limit", 1, db, deduct=True, provider_kind="text")

            framework_result = {
                "tags": story.tags,
                "characters": story.characters,
                "outline": story.outline,
            }
    except Exception as e:
        logger.warning(f"[onboarding] 自动框架生成失败，优雅降级: {e}")
        framework_result = None
# --- 新增结束 ---
```

必须在 `story.onboarding_completed = True` 且 `db.commit()` 之后、`db.refresh(story)` 之前插入此块。如果 `story_bible` 构建异常则跳过。

- [ ] **Step 3: 更新返回值**

将返回值中新增 `framework` 字段：

```python
return {
    "story_id": story.id,
    "story_bible": story_bible,
    "creative_brief": creative_brief,
    "framework": framework_result,
}
```

- [ ] **Step 4: 确认导入路径**

确保 `generate_framework`、`_build_framework_seed_description`、`_build_framework_ai_context`、`get_effective_prompt` 在当前作用域内可见。它们已在 `main.py` 的其他端点中使用，通常无需额外 import。

- [ ] **Step 5: 运行现有测试确认无回归**

```bash
cd backend
python -m pytest tests/test_onboarding.py -v 2>&1
```

预期：7 个测试全部通过。

- [ ] **Step 6: 手动启动后端验证无语法错误**

```bash
cd backend
python -c "import sys; sys.path.insert(0,'.'); from main import app; print('OK')"
```

预期输出：`OK`

- [ ] **Step 7: Commit**

```bash
git add backend/main.py
git commit -m "feat: confirm_onboarding 自动生成故事框架"
```

---

### Task 2: 前端 — API 类型更新

**Files:**
- Modify: `frontend/src/api.ts:432-436`

- [ ] **Step 1: 读取当前 OnboardingConfirmResponse 定义**

确认 `api.ts:432-436` 的当前定义。

- [ ] **Step 2: 新增 framework 字段**

```typescript
export interface OnboardingConfirmResponse {
  story_id: number;
  story_bible: StoryBible;
  creative_brief: CreativeBrief;
  framework?: {           // 新增
    tags?: Tags;
    characters?: Character[];
    outline?: Outline;
  } | null;
}
```

- [ ] **Step 3: 确认类型依赖**

确认 `Tags`、`Character`、`Outline` 类型在当前文件已有定义（它们通常在 api.ts 文件头部附近定义）。如果缺失则追加 import。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api.ts
git commit -m "feat: OnboardingConfirmResponse 新增 framework 字段"
```

---

### Task 3: 前端 — OnboardingPage 三步过渡态

**Files:**
- Modify: `frontend/src/components/OnboardingPage.tsx`
- Confirm: `frontend/src/api.ts` 中 `confirmOnboarding` 函数签名

- [ ] **Step 1: 读取 OnboardingPage.tsx 完整文件**

确认当前 `handleConfirm`、`handleSkipOnboarding`、渲染逻辑的完整代码。

- [ ] **Step 2: 新增状态变量**

在 `useState` 声明区域新增：

```typescript
type OnboardingPhase = 'chatting' | 'confirming' | 'ready' | 'error';
const [phase, setPhase] = useState<OnboardingPhase>('chatting');
const [confirmError, setConfirmError] = useState('');
```

- [ ] **Step 3: 重构 handleConfirm**

```typescript
const handleConfirm = async () => {
  setLoading(true);
  setPhase('confirming');
  setConfirmError('');
  try {
    const result = await confirmOnboarding(
      story.id,
      understanding as Record<string, string>,
      messages,
      creativeBrief ?? undefined,
    );
    // framework 已由后端生成并存入 DB
    setPhase('ready');
  } catch (err: any) {
    setConfirmError(err.message || '确认失败');
    setPhase('error');
  } finally {
    setLoading(false);
  }
};
```

- [ ] **Step 4: 新增过渡态渲染块**

在聊天区域底部（现有消息列表之后）、输入区域之前，根据 `phase` 渲染不同内容。当 `phase === 'chatting'` 时渲染现有输入区域，否则渲染过渡态 UI：

```typescript
// 在 return 语句中，条件渲染过渡态或输入区
{phase === 'chatting' ? (
  /* 现有输入区域 - 不变 */
) : (
  /* 过渡态/就绪态 UI */
  <div className="border-t border-[#e5edf8] bg-white px-5 py-4">
    {phase === 'confirming' && (
      <div className="flex items-center gap-3 py-2">
        <Loader2 size={20} className="animate-spin text-[#2563eb]" />
        <div>
          <div className="text-sm font-medium text-slate-800">正在构建故事框架...</div>
          <div className="mt-0.5 text-xs text-slate-500">
            生成大纲 · 角色设定 · 标签 · 章节规划
          </div>
        </div>
        <div className="ml-auto">
          <div className="h-2 w-24 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full w-2/3 animate-pulse rounded-full bg-[#2563eb]" />
          </div>
        </div>
      </div>
    )}
    {phase === 'ready' && (
      <div>
        <div className="flex items-center gap-3 rounded-2xl border border-[#bbf7d0] bg-[#f0fdf4] px-4 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#22c55e] text-white text-sm font-bold">✓</div>
          <div>
            <div className="text-sm font-medium text-slate-800">故事框架已就绪！</div>
            <div className="mt-0.5 text-xs text-slate-500">
              大纲、角色、标签已自动生成，进入工作台即可查看
            </div>
          </div>
        </div>
        <div className="mt-3 flex items-center justify-between">
          <button
            onClick={() => void handleSkipOnboarding()}
            className="rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2 text-sm text-slate-500 transition hover:bg-[#f8fbff]"
          >
            跳过引导，直接开始
          </button>
          <button
            onClick={() => onComplete(story.id)}
            className="rounded-2xl bg-[#2563eb] px-6 py-2 text-sm font-medium text-white transition hover:bg-[#1d4ed8]"
          >
            进入工作台
          </button>
        </div>
      </div>
    )}
    {phase === 'error' && (
      <div>
        <div className="rounded-2xl border border-[#fecaca] bg-[#fef2f2] px-4 py-3 text-sm text-rose-700">
          {confirmError}
        </div>
        <div className="mt-3 flex gap-2">
          <button
            onClick={() => void handleConfirm()}
            disabled={loading}
            className="rounded-2xl bg-[#2563eb] px-4 py-2 text-sm font-medium text-white transition hover:bg-[#1d4ed8] disabled:opacity-60"
          >
            重试
          </button>
          <button
            onClick={() => { setPhase('chatting'); setError(''); }}
            className="rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2 text-sm text-slate-600"
          >
            返回对话
          </button>
        </div>
      </div>
    )}
  </div>
)}
```

- [ ] **Step 5: 调整 handleSkipOnboarding**

跳过引导无需等待框架生成，可以直接调用：

```typescript
const handleSkipOnboarding = async () => {
  setLoading(true);
  setError('');
  try {
    await skipOnboarding(story.id);
    onComplete(story.id);
  } catch (err: any) {
    setError(err.message || '跳过引导失败，请重试');
  } finally {
    setLoading(false);
  }
};
```

- [ ] **Step 6: 调整 error 显示**

原有的 `${error}` 显示改为同时兼容 `confirmError`：

```typescript
{error && <div className="mt-2 text-xs text-rose-600">{error}</div>}
```

- [ ] **Step 7: TypeScript 编译验证**

```bash
cd frontend
npx tsc --noEmit -b 2>&1
```

预期输出：无类型错误。

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/OnboardingPage.tsx
git commit -m "feat: OnboardingPage 三步过渡态支持自动框架生成"
```

---

### Task 4: 集成验证

**Files:**
- Run: `backend/main.py` 启动
- Run: `frontend` TypeScript + Vite build

- [ ] **Step 1: 后端启动验证**

```bash
cd backend
python main.py
```

等3秒后 Ctrl+C 退出。日志中不应有 ImportError 或语法错误。

- [ ] **Step 2: 前端 build 验证**

```bash
cd frontend
npm run build 2>&1
```

预期：`vite build` 成功，无 TypeScript 错误。

- [ ] **Step 3: 全量测试**

```bash
cd backend
python -m pytest tests/ -v 2>&1
```

确认新增测试通过，既有测试无回归（预存失败测试除外）。

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: 集成验证通过"
```
