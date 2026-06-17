# 开书引导深度对话式重构 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将开书引导从机械的5步问卷重构为深度对话式引导，让 AI 像真正的创作顾问一样理解用户创意

**Architecture:** 重构对话模型（collected_info → understanding），修改系统 Prompt 让 AI 主动追问和解读，前端移除步骤进度条改为理解深度进度条，创意分析卡从弹窗改为内嵌对话流

**Tech Stack:** Python/FastAPI (backend), React/TypeScript (frontend), DeepSeek API

---

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/schemas.py` | 修改 | 新增 Understanding 模型，修改 OnboardingMessageOut |
| `backend/services/deepseek.py` | 修改 | 重构 generate_onboarding_response，新增 understanding 解析 |
| `backend/main.py` | 修改 | 修改 onboarding_send_message 和 onboarding_confirm |
| `frontend/src/api.ts` | 修改 | 更新 OnboardingMessageOut 接口 |
| `frontend/src/components/OnboardingPage.tsx` | 重写 | 移除步骤进度条，新增理解深度进度条，分析卡内嵌 |
| `backend/tests/test_onboarding.py` | 新增 | onboarding 相关单元测试 |

---

### Task 1: 后端 Schema 定义

**Files:**
- Modify: `backend/schemas.py:282-303`

- [ ] **Step 1: 在 schemas.py 中添加 Understanding 模型**

在 `# ─── Onboarding / Story Bible ─────` 注释之后、`OnboardingMessageIn` 之前添加：

```python
class Understanding(BaseModel):
    """AI 对用户创意的理解（结构化）"""
    concept: str = ""      # 故事概念
    setting: str = ""      # 世界观/设定
    tone: str = ""         # 风格基调
    goals: str = ""        # 创作目标
    synthesis: str = ""    # 综合理解
```

- [ ] **Step 2: 修改 OnboardingMessageOut 模型**

将现有的 `OnboardingMessageOut` 替换为：

```python
class OnboardingMessageOut(BaseModel):
    """AI 引导回复"""
    reply: str
    # 新字段：结构化理解
    understanding: Understanding = Understanding()
    understanding_depth: int = 0
    phase: str = "exploring"  # exploring | refining | synthesizing
    has_brief: bool = False
    creative_brief: dict[str, Any] | None = None
    # 保留兼容字段
    collected_info: dict[str, Any] = {}
    step: int = 1
    total_steps: int = 5
    is_complete: bool = False
```

- [ ] **Step 3: 验证 schema 无语法错误**

Run: `cd backend && python -c "from schemas import OnboardingMessageOut, Understanding; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add backend/schemas.py
git commit -m "feat(onboarding): add Understanding model and update OnboardingMessageOut"
```

---

### Task 2: 后端 Prompt 重构

**Files:**
- Modify: `backend/main.py:1597-1633`

- [ ] **Step 1: 替换 ONBOARDING_PROMPT_SEED**

将 `backend/main.py` 中第 1597-1633 行的 `ONBOARDING_PROMPT_SEED` 替换为：

```python
ONBOARDING_PROMPT_SEED = """你是「灵感捕手」——一位资深小说创作顾问。

## 你的角色
你是一个有温度的创作伙伴，不是表单收集器。你的目标是通过自然对话，
深度理解用户的创作意图，帮助他们把模糊的想法变成清晰的方向。

## 对话策略

1. **主动追问**：当用户的描述模糊时，追问具体细节
   - 用户说"写个玄幻" → 追问"是什么类型的玄幻？修仙？异世？都市异能？"
   - 用户说"主角很厉害" → 追问"厉害在哪？战斗力？智慧？特殊能力？"

2. **深度解读**：不只是记录，而是理解并反馈
   - 用户说"偏喜剧" → 你理解为"轻松幽默的基调，用喜剧手法处理严肃主题"
   - 在回复中展示你的理解，让用户确认

3. **渐进深入**：从核心灵感出发，逐步扩展到设定、基调、目标
   - 不要一次性问完所有问题
   - 根据用户的回答自然推进

4. **阶段感知**（内部，不告诉用户）：
   - exploring：探索核心灵感和概念
   - refining：深化设定、基调、目标
   - synthesizing：综合所有信息，输出分析卡

## 输出格式
每轮回复必须包含 JSON（在回复文本之后）：
{
    "reply": "你的自然语言回复",
    "understanding": {
        "concept": "提炼的故事概念",
        "setting": "提炼的世界观设定",
        "tone": "提炼的风格基调",
        "goals": "提炼的创作目标",
        "synthesis": "综合理解"
    },
    "understanding_depth": 65,
    "phase": "exploring",
    "has_brief": false,
    "creative_brief": null
}

## understanding_depth 参考标准
- 有核心概念（故事类型+核心创意）：+20
- 有世界观/设定（背景+力量体系）：+20
- 有风格基调（幽默/严肃/热血等+读者定位）：+20
- 有创作目标（篇幅+连载计划+商业目标）：+20
- 有综合理解（能用一段话概括整个故事）：+20

## 输出创意分析卡的时机
当你对用户的创意有了充分理解（understanding_depth >= 80）时：
1. 设置 has_brief = true
2. 在 creative_brief 中输出完整的创意分析卡：
{
    "project_positioning": "作品定位",
    "genre": "题材",
    "audience": "目标读者",
    "tone": "风格基调",
    "core_hook": "核心卖点",
    "one_line_premise": "一句话梗概",
    "protagonist_core": "主角核心设定",
    "main_conflict": "主线矛盾",
    "longline_mystery": "长线悬念",
    "serial_length_target": "目标篇幅",
    "must_keep_rules": ["必保留设定"],
    "reveal_strategy": "揭秘策略",
    "pacing_strategy": "节奏策略"
}
3. 在 reply 中说"我已经理解了你的想法，这是我的分析..."

## 迭代修改
用户可能在分析卡输出后继续对话，修改任何不满意的地方。
此时你需要更新 understanding 和 creative_brief，而不是从头开始。
当用户说"确认"或"可以了"时，设置 has_brief = true 输出最终版本。

## 重要规则
- 保持轻松但有创作专业感的语气
- 对模糊回答做适当解读并请作者确认，不要强行归类
- 如果用户明确传递了某个信息，即使没按顺序，也应更新到 understanding
- 当信息足够充分时，可以直接输出分析卡
- 不要使用选择题清单，用引导性问题"""
```

- [ ] **Step 2: 验证 Python 语法**

Run: `cd backend && python -c "import main; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat(onboarding): rewrite system prompt for deep conversational guidance"
```

---

### Task 3: 后端 generate_onboarding_response 重构

**Files:**
- Modify: `backend/services/deepseek.py:2501-2577`
- Modify: `backend/services/deepseek.py:540-614` (废弃函数)

- [ ] **Step 1: 重构 generate_onboarding_response 函数签名**

将 `backend/services/deepseek.py` 中第 2501-2577 行的 `generate_onboarding_response` 替换为：

```python
async def generate_onboarding_response(
    messages: list[dict],
    understanding: dict[str, str] | None = None,
    api_key: str | None = None,
    max_retries: int = 2,
    system_prompt: str | None = None,
) -> dict:
    """生成引导建书对话中 AI 的下一轮回复，含自动重试韧性"""
    last_error: Exception | None = None
    understanding_snapshot = json.dumps(understanding or {}, ensure_ascii=False)
    onboarding_state_hint = (
        "\n\n## 当前已确认理解\n"
        f"- current_understanding: {understanding_snapshot}\n"
        "请在此基础上更新 understanding。对于「是的/嗯/对」这类确认回答，"
        "不要把这些确认词直接写入字段，而应保留上一轮你已经判断出的内容。"
    )

    for attempt in range(max_retries + 1):
        try:
            payload = {
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": (system_prompt or "") + onboarding_state_hint},
                    *messages,
                ],
                "stream": False,
                "max_tokens": 4096,
            }

            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{DEEPSEEK_BASE_URL}/chat/completions",
                    json=payload,
                    headers=_deepseek_auth_headers(api_key),
                )
                resp.raise_for_status()
                data = _response_json(resp, context="DeepSeek")
                content = data["choices"][0]["message"]["content"]

            try:
                result = _extract_json_object(content)
            except ValueError:
                # fallback：从纯文本提取 reply
                return {
                    "reply": content.strip(),
                    "understanding": understanding or {},
                    "understanding_depth": 0,
                    "phase": "exploring",
                    "has_brief": False,
                    "creative_brief": None,
                }

            # 验证必要字段
            reply = result.get("reply", "")
            if not reply.strip():
                raise ValueError("AI 返回空回复")

            # 提取 understanding
            ai_understanding = result.get("understanding", {})
            if not isinstance(ai_understanding, dict):
                ai_understanding = {}

            # 合并：AI 输出的 understanding 覆盖旧值
            merged_understanding = {**(understanding or {}), **ai_understanding}

            return {
                "reply": reply,
                "understanding": merged_understanding,
                "understanding_depth": int(result.get("understanding_depth", 0)),
                "phase": str(result.get("phase", "exploring")),
                "has_brief": bool(result.get("has_brief", False)),
                "creative_brief": result.get("creative_brief"),
            }

        except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError) as e:
            last_error = e
            if attempt < max_retries:
                wait = 1.5 * (attempt + 1)
                await asyncio.sleep(wait)
                continue
            raise ValueError(f"Onboarding response generation failed after {max_retries + 1} attempts: {last_error}")

    raise ValueError(f"Onboarding response generation failed: {last_error}")
```

- [ ] **Step 2: 废弃旧函数（保留但标记过时）**

在 `_merge_onboarding_collected_info` 函数（第 566 行）前添加注释：

```python
# DEPRECATED: 旧的 collected_info 合并逻辑，已被 understanding 替代
# 保留用于向后兼容，新代码不要使用
def _merge_onboarding_collected_info(
```

- [ ] **Step 3: 验证语法**

Run: `cd backend && python -c "from services.deepseek import generate_onboarding_response; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add backend/services/deepseek.py
git commit -m "feat(onboarding): refactor generate_onboarding_response to use understanding"
```

---

### Task 4: 后端 API 端点重构

**Files:**
- Modify: `backend/main.py:7722-7785`

- [ ] **Step 1: 修改 onboarding_send_message 端点**

将 `backend/main.py` 中第 7722-7785 行的 `onboarding_send_message` 替换为：

```python
@app.post("/api/stories/{story_id}/onboarding/message", response_model=OnboardingMessageOut)
async def onboarding_send_message(story_id: int, request: Request, db: Session = Depends(get_db)):
    """发送引导对话消息，获取 AI 回复"""
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    body = await request.json()
    messages_raw = body.get("messages", [])
    previous_understanding = body.get("understanding", {})
    if not isinstance(messages_raw, list) or len(messages_raw) == 0:
        raise HTTPException(400, "消息必填")
    if not isinstance(previous_understanding, dict):
        previous_understanding = {}

    safe_messages = [
        {"role": msg["role"], "content": str(msg["content"])}
        for msg in messages_raw
        if isinstance(msg, dict) and msg.get("role") in ("user", "assistant") and str(msg.get("content", "")).strip()
    ]
    if not safe_messages:
        raise HTTPException(400, "没有有效消息")

    # 配额预检
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)

    creative_brief = None
    deepseek_api_key = _user_deepseek_api_key(request)
    onboard_prompt = get_system_prompt("prompt.onboarding", db) or None
    _release_db_transaction(db)
    try:
        result = await generate_onboarding_response(
            safe_messages,
            understanding=previous_understanding,
            api_key=deepseek_api_key,
            system_prompt=onboard_prompt,
        )
        # 如果 AI 输出了分析卡，提取 creative_brief
        if bool(result.get("has_brief")) and result.get("creative_brief"):
            creative_brief = result["creative_brief"]
    except Exception as e:
        raise HTTPException(502, f"AI 服务调用失败: {e}")

    # 配额扣减
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)

    # 构建兼容的 collected_info
    understanding = result.get("understanding", {})
    collected_info = {
        "story_concept": understanding.get("concept", ""),
        "genre_audience": understanding.get("setting", ""),
        "core_hook": understanding.get("tone", ""),
        "target_length": understanding.get("goals", ""),
        "must_keep": understanding.get("synthesis", ""),
    }

    return OnboardingMessageOut(
        reply=result.get("reply", ""),
        understanding=understanding,
        understanding_depth=int(result.get("understanding_depth", 0)),
        phase=str(result.get("phase", "exploring")),
        has_brief=bool(result.get("has_brief", False)),
        creative_brief=creative_brief,
        collected_info=collected_info,
        step=1,
        total_steps=5,
        is_complete=bool(result.get("has_brief", False)),
    )
```

- [ ] **Step 2: 修改 onboarding_confirm 端点**

将 `backend/main.py` 中第 7788-7845 行的 `onboarding_confirm` 替换为：

```python
@app.post("/api/stories/{story_id}/onboarding/confirm")
async def onboarding_confirm(story_id: int, request: Request, db: Session = Depends(get_db)):
    """确认引导结果，生成 Story Bible 并保存"""
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)
    body = await request.json()
    understanding = body.get("understanding", {})
    creative_brief_input = body.get("creative_brief", {})
    messages_raw = body.get("messages", [])

    # 从 understanding 构建 raw_input
    raw_input = {
        "raw_idea": understanding.get("concept", ""),
        "raw_length_goal": understanding.get("goals", ""),
        "raw_must_keep": understanding.get("synthesis", ""),
        "raw_hidden_setting": "",
        "raw_notes": "",
    }

    # Captura todas as mensagens como texto bruto
    all_raw = "\n".join(
        f"{'作者' if m.get('role') == 'user' else 'AI'}: {m.get('content', '')}"
        for m in messages_raw
        if isinstance(m, dict)
    )
    raw_input["raw_notes"] = all_raw

    deepseek_api_key = _user_deepseek_api_key(request)

    # 配额预检
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=False)

    _release_db_transaction(db)
    try:
        # 优先使用前端传来的 creative_brief，否则重新生成
        if creative_brief_input and isinstance(creative_brief_input, dict):
            creative_brief = creative_brief_input
        else:
            creative_brief = await build_creative_brief(
                understanding,
                api_key=deepseek_api_key,
            )
        story_bible = await build_story_bible(
            creative_brief,
            raw_input,
            api_key=deepseek_api_key,
        )
    except Exception as e:
        raise HTTPException(502, f"Story Bible 生成失败: {e}")

    story = _require_story_for_user(story_id, user, db)
    story.story_bible = story_bible
    story.description = story_bible.get("creative_brief", {}).get("one_line_premise", story.description or "")
    story.onboarding_completed = True
    db.commit()
    # 配额扣减
    _check_and_consume_advanced_text_quota(request, user.id, db, deduct=True)
    db.refresh(story)

    return {
        "story_id": story.id,
        "story_bible": story_bible,
        "creative_brief": creative_brief,
    }
```

- [ ] **Step 3: 验证语法**

Run: `cd backend && python -c "import main; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat(onboarding): refactor API endpoints to use understanding model"
```

---

### Task 5: 前端 API 类型更新

**Files:**
- Modify: `frontend/src/api.ts:359-371`

- [ ] **Step 1: 更新 OnboardingMessageOut 接口**

将 `frontend/src/api.ts` 中第 364-371 行的 `OnboardingMessageOut` 替换为：

```typescript
export interface Understanding {
  concept: string;
  setting: string;
  tone: string;
  goals: string;
  synthesis: string;
}

export interface OnboardingMessageOut {
  reply: string;
  // 新字段
  understanding: Understanding;
  understanding_depth: number;
  phase: 'exploring' | 'refining' | 'synthesizing';
  has_brief: boolean;
  creative_brief?: CreativeBrief;
  // 保留兼容字段
  collected_info: Record<string, string>;
  step: number;
  total_steps: number;
  is_complete: boolean;
}
```

- [ ] **Step 2: 更新 OnboardingChatMessage 接口**

将 `frontend/src/api.ts` 中第 359-362 行的 `OnboardingChatMessage` 替换为：

```typescript
export interface OnboardingChatMessage {
  role: 'user' | 'assistant';
  content: string;
  creative_brief?: CreativeBrief;  // 分析卡（仅 assistant 消息）
}
```

- [ ] **Step 3: 更新 sendOnboardingMessage 函数参数**

将 `frontend/src/api.ts` 中第 2153-2166 行的 `sendOnboardingMessage` 替换为：

```typescript
export async function sendOnboardingMessage(
  storyId: number,
  messages: { role: string; content: string }[],
  understanding: Record<string, string> = {},
): Promise<OnboardingMessageOut> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/onboarding/message`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ messages, understanding }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '引导对话失败'));
  return res.json();
}
```

- [ ] **Step 4: 更新 confirmOnboarding 函数参数**

将 `frontend/src/api.ts` 中第 2168-2180 行的 `confirmOnboarding` 替换为：

```typescript
export async function confirmOnboarding(
  storyId: number,
  understanding: Record<string, string>,
  messages: { role: string; content: string }[],
  creativeBrief?: CreativeBrief,
): Promise<OnboardingConfirmResponse> {
  const res = await fetch(`${BASE}/api/stories/${storyId}/onboarding/confirm`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({ understanding, messages, creative_brief: creativeBrief }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '确认引导失败'));
  return res.json();
}
```

- [ ] **Step 5: 验证 TypeScript 编译**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api.ts
git commit -m "feat(onboarding): update API types and functions for understanding model"
```

---

### Task 6: 前端 OnboardingPage 重构

**Files:**
- Modify: `frontend/src/components/OnboardingPage.tsx`

- [ ] **Step 1: 重写状态管理**

替换 `OnboardingPage.tsx` 中第 33-48 行的状态定义：

```typescript
export default function OnboardingPage({ story, onComplete, onBack }: Props) {
  const [messages, setMessages] = useState<OnboardingChatMessage[]>([
    { role: 'assistant', content: INITIAL_PROMPT },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [understanding, setUnderstanding] = useState<Record<string, string>>({});
  const [understandingDepth, setUnderstandingDepth] = useState(0);
  const [showBrief, setShowBrief] = useState(false);
  const [creativeBrief, setCreativeBrief] = useState<CreativeBrief | null>(null);
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
```

- [ ] **Step 2: 重写 handleSend 函数**

替换 `OnboardingPage.tsx` 中第 60-92 行的 `handleSend`：

```typescript
const handleSend = useCallback(async () => {
  const text = input.trim();
  if (!text || loading) return;

  setInput('');
  setError('');

  const userMsg: OnboardingChatMessage = { role: 'user', content: text };
  const updatedMessages = [...messages, userMsg];
  setMessages(updatedMessages);
  setLoading(true);

  try {
    const result = await sendOnboardingMessage(story.id, updatedMessages, understanding);
    
    // 更新理解状态
    setUnderstanding(result.understanding || {});
    setUnderstandingDepth(result.understanding_depth || 0);
    
    // 处理分析卡
    if (result.has_brief && result.creative_brief) {
      setCreativeBrief(result.creative_brief);
      setShowBrief(true);
      setIsComplete(true);
      // 将分析卡附加到最后一条消息
      const briefMsg: OnboardingChatMessage = {
        role: 'assistant',
        content: result.reply,
        creative_brief: result.creative_brief,
      };
      setMessages(prev => [...prev, briefMsg]);
    } else {
      // 普通消息
      const assistantMsg: OnboardingChatMessage = {
        role: 'assistant',
        content: result.reply,
      };
      setMessages(prev => [...prev, assistantMsg]);
    }
  } catch (err: any) {
    setError(err.message || '对话失败，请重试');
  } finally {
    setLoading(false);
  }
}, [understanding, input, loading, messages, story.id]);
```

- [ ] **Step 3: 重写 handleConfirm 函数**

替换 `OnboardingPage.tsx` 中第 101-112 行的 `handleConfirm`：

```typescript
const handleConfirm = async () => {
  setLoading(true);
  setError('');
  try {
    await confirmOnboarding(story.id, understanding, messages, creativeBrief ?? undefined);
    onComplete(story.id);
  } catch (err: any) {
    setError(err.message || '确认失败，请重试');
  } finally {
    setLoading(false);
  }
};
```

- [ ] **Step 4: 添加 handleContinueEdit 函数**

替换 `OnboardingPage.tsx` 中第 114-118 行的 `handleContinueEdit`：

```typescript
const handleContinueEdit = () => {
  setShowBrief(false);
  setInput('');
  inputRef.current?.focus();
};
```

- [ ] **Step 5: 重写顶部栏（移除步骤进度条）**

替换 `OnboardingPage.tsx` 中第 133-159 行的顶部栏 JSX：

```tsx
return (
  <div className="mx-auto flex h-[calc(100vh-120px)] max-w-7xl flex-col overflow-hidden rounded-2xl border border-[#d7e3f4] bg-white shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
    {/* 顶部栏 */}
    <div className="flex items-center justify-between border-b border-[#d7e3f4] bg-[#f8fbff] px-5 py-3">
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="rounded-full border border-[#d7e3f4] bg-white p-1.5 text-slate-500 transition hover:bg-[#eff6ff]"
          title="返回"
        >
          <ArrowLeft size={16} />
        </button>
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Sparkles size={16} className="text-[#2563eb]" />
            AI 引导建书
          </div>
          <div className="text-xs text-slate-500">{story.title}</div>
        </div>
      </div>
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <Cpu size={14} />
        <span>理解深度</span>
        <div className="w-24 h-1.5 bg-slate-100 rounded-full overflow-hidden">
          <div 
            className="h-full bg-[#2563eb] rounded-full transition-all duration-500"
            style={{ width: `${understandingDepth}%` }}
          />
        </div>
        <span>{understandingDepth}%</span>
      </div>
    </div>
```

- [ ] **Step 6: 移除步骤进度条 JSX**

删除 `OnboardingPage.tsx` 中第 161-193 行的步骤进度条代码（整个 `{/* 步骤进度条 */}` 注释块）。

- [ ] **Step 7: 重写右侧摘要面板**

替换 `OnboardingPage.tsx` 中第 282-346 行的右侧面板：

```tsx
{/* 右侧摘要面板 */}
<div className="hidden w-72 shrink-0 border-l border-[#e5edf8] bg-[#f8fbff] p-4 lg:block">
  <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
    当前理解
  </div>
  <div className="mt-3 space-y-3">
    {understanding.concept ? (
      <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
        <div className="text-[11px] font-medium text-[#2563eb]">💡 故事概念</div>
        <div className="mt-1 text-xs leading-5 text-slate-600 line-clamp-4">
          {understanding.concept}
        </div>
      </div>
    ) : null}
    {understanding.setting ? (
      <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
        <div className="text-[11px] font-medium text-[#2563eb]">🌍 世界观设定</div>
        <div className="mt-1 text-xs leading-5 text-slate-600">
          {understanding.setting}
        </div>
      </div>
    ) : null}
    {understanding.tone ? (
      <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
        <div className="text-[11px] font-medium text-[#2563eb]">🎭 风格基调</div>
        <div className="mt-1 text-xs leading-5 text-slate-600">
          {understanding.tone}
        </div>
      </div>
    ) : null}
    {understanding.goals ? (
      <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
        <div className="text-[11px] font-medium text-[#2563eb]">🎯 创作目标</div>
        <div className="mt-1 text-xs leading-5 text-slate-600">
          {understanding.goals}
        </div>
      </div>
    ) : null}
    {understanding.synthesis ? (
      <div className="rounded-2xl border border-[#d7e3f4] bg-[#eff6ff] p-3">
        <div className="text-[11px] font-medium text-[#2563eb]">📝 综合理解</div>
        <div className="mt-1 text-xs leading-5 text-slate-600">
          {understanding.synthesis}
        </div>
      </div>
    ) : null}
    {Object.keys(understanding).length === 0 && (
      <div className="flex flex-col items-center gap-2 py-8 text-center text-xs text-slate-400">
        <MessageSquare size={24} className="opacity-40" />
        <div>AI 正在理解你的创意...</div>
        <div>在左侧对话后，这里会显示实时摘要</div>
      </div>
    )}
  </div>
</div>
```

- [ ] **Step 8: 移除创意理解卡弹窗**

删除 `OnboardingPage.tsx` 中第 349-459 行的 `{/* 创意理解卡确认弹窗 */}` 代码块。

- [ ] **Step 9: 更新消息渲染逻辑（支持分析卡）**

替换 `OnboardingPage.tsx` 中第 205-220 行的消息渲染：

```tsx
{messages.map((msg, idx) => (
  <div
    key={idx}
    className={`mb-4 flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
  >
    {msg.role === 'assistant' && msg.creative_brief ? (
      // 分析卡特殊渲染
      <BriefCardInline
        brief={msg.creative_brief}
        onConfirm={() => void handleConfirm()}
        onContinue={handleContinueEdit}
      />
    ) : (
      <div
        className={`max-w-[75%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-6 ${
          msg.role === 'user'
            ? 'bg-[#2563eb] text-white shadow-[0_4px_12px_rgba(37,99,235,0.2)]'
            : 'border border-[#e5edf8] bg-[#f8fbff] text-slate-700'
        }`}
      >
        {msg.content}
      </div>
    )}
  </div>
))}
```

- [ ] **Step 10: 添加 BriefCardInline 组件**

在 `OnboardingPage.tsx` 文件末尾（现有 `BriefCard` 组件之后）添加：

```tsx
function BriefCardInline({ 
  brief, 
  onConfirm, 
  onContinue 
}: { 
  brief: CreativeBrief; 
  onConfirm: () => void; 
  onContinue: () => void;
}) {
  return (
    <div className="w-full max-w-[85%] rounded-2xl border border-[#bfdbfe] bg-[#f0f7ff] p-4">
      <div className="flex items-center gap-2 text-sm font-semibold text-[#1d4ed8]">
        <Sparkles size={14} />
        创意分析卡
      </div>
      <p className="mt-1 text-xs text-slate-500">
        我已经理解了你的创作构思，请确认以下分析是否准确：
      </p>
      <div className="mt-3 space-y-2">
        {brief.project_positioning && (
          <div className="rounded-xl bg-white p-3">
            <div className="text-[11px] font-medium text-[#2563eb]">作品定位</div>
            <div className="mt-1 text-sm text-slate-700">{brief.project_positioning}</div>
          </div>
        )}
        <div className="grid gap-2 sm:grid-cols-2">
          {brief.one_line_premise && <BriefField label="一句话梗概" value={brief.one_line_premise} />}
          {brief.core_hook && <BriefField label="核心卖点" value={brief.core_hook} />}
          {brief.main_conflict && <BriefField label="主线矛盾" value={brief.main_conflict} />}
          {brief.longline_mystery && <BriefField label="长线悬念" value={brief.longline_mystery} />}
          {brief.serial_length_target && <BriefField label="目标篇幅" value={brief.serial_length_target} />}
          {brief.reveal_strategy && <BriefField label="揭秘策略" value={brief.reveal_strategy} />}
          {brief.pacing_strategy && <BriefField label="节奏策略" value={brief.pacing_strategy} />}
          {brief.protagonist_core && <BriefField label="主角核心" value={brief.protagonist_core} />}
        </div>
      </div>
      <div className="mt-4 flex gap-2">
        <button
          onClick={onContinue}
          className="rounded-xl border border-[#d7e3f4] bg-white px-4 py-2 text-sm text-slate-600 hover:bg-[#f8fbff]"
        >
          继续对话修改
        </button>
        <button
          onClick={onConfirm}
          className="rounded-xl bg-[#2563eb] px-4 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8]"
        >
          确认生成
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 11: 验证 TypeScript 编译**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 12: Commit**

```bash
git add frontend/src/components/OnboardingPage.tsx
git commit -m "feat(onboarding): rewrite OnboardingPage for deep conversational guidance"
```

---

### Task 7: 后端单元测试

**Files:**
- Create: `backend/tests/test_onboarding.py`

- [ ] **Step 1: 创建测试文件**

创建 `backend/tests/test_onboarding.py`：

```python
"""开书引导相关单元测试"""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestUnderstandingModel:
    """Understanding 模型测试"""
    
    def test_understanding_default_values(self):
        """Understanding 默认值应为空字符串"""
        from schemas import Understanding
        u = Understanding()
        assert u.concept == ""
        assert u.setting == ""
        assert u.tone == ""
        assert u.goals == ""
        assert u.synthesis == ""
    
    def test_understanding_with_values(self):
        """Understanding 应支持赋值"""
        from schemas import Understanding
        u = Understanding(
            concept="都市律师",
            setting="规则怪谈世界",
            tone="偏喜剧",
            goals="长篇连载",
            synthesis="一个关于规则与漏洞的故事"
        )
        assert u.concept == "都市律师"
        assert u.synthesis == "一个关于规则与漏洞的故事"


class TestOnboardingMessageOut:
    """OnboardingMessageOut 模型测试"""
    
    def test_has_new_fields(self):
        """应包含新的 understanding 字段"""
        from schemas import OnboardingMessageOut, Understanding
        out = OnboardingMessageOut(
            reply="test",
            understanding=Understanding(concept="test"),
            understanding_depth=50,
            phase="exploring",
            has_brief=False,
        )
        assert out.understanding.concept == "test"
        assert out.understanding_depth == 50
        assert out.phase == "exploring"
        assert out.has_brief is False
    
    def test_has_compatibility_fields(self):
        """应保留兼容字段"""
        from schemas import OnboardingMessageOut
        out = OnboardingMessageOut(
            reply="test",
            collected_info={"story_concept": "test"},
            step=1,
            total_steps=5,
            is_complete=False,
        )
        assert out.collected_info == {"story_concept": "test"}
        assert out.step == 1
        assert out.is_complete is False


class TestGenerateOnboardingResponse:
    """generate_onboarding_response 函数测试"""
    
    @pytest.mark.asyncio
    async def test_returns_understanding_structure(self):
        """应返回 understanding 结构"""
        from services.deepseek import generate_onboarding_response
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "reply": "这是一个关于律师的故事",
                "understanding": {
                    "concept": "都市律师题材",
                    "setting": "规则怪谈世界",
                    "tone": "偏喜剧",
                    "goals": "长篇连载",
                    "synthesis": "一个关于规则与漏洞的故事"
                },
                "understanding_depth": 60,
                "phase": "exploring",
                "has_brief": False,
                "creative_brief": None
            })}}]
        }
        
        with patch("services.deepseek.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_response)))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": "我想写个律师的故事"}],
                understanding={},
                api_key="test-key",
            )
            
            assert "understanding" in result
            assert result["understanding"]["concept"] == "都市律师题材"
            assert result["understanding_depth"] == 60
            assert result["has_brief"] is False
    
    @pytest.mark.asyncio
    async def test_merges_understanding(self):
        """应合并 understanding"""
        from services.deepseek import generate_onboarding_response
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "reply": "更新理解",
                "understanding": {
                    "tone": "偏喜剧"
                },
                "understanding_depth": 70,
                "phase": "refining",
                "has_brief": False,
                "creative_brief": None
            })}}]
        }
        
        with patch("services.deepseek.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_response)))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": "偏喜剧"}],
                understanding={"concept": "都市律师"},
                api_key="test-key",
            )
            
            # 应保留旧的 concept，更新 tone
            assert result["understanding"]["concept"] == "都市律师"
            assert result["understanding"]["tone"] == "偏喜剧"
    
    @pytest.mark.asyncio
    async def test_has_brief_when_depth_high(self):
        """深度足够时应输出分析卡"""
        from services.deepseek import generate_onboarding_response
        
        brief = {
            "project_positioning": "都市律师题材",
            "genre": "都市",
            "audience": "青年读者",
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "reply": "我已经理解了你的想法",
                "understanding": {
                    "concept": "都市律师",
                    "setting": "规则怪谈世界",
                    "tone": "偏喜剧",
                    "goals": "长篇连载",
                    "synthesis": "综合理解"
                },
                "understanding_depth": 85,
                "phase": "synthesizing",
                "has_brief": True,
                "creative_brief": brief
            })}}]
        }
        
        with patch("services.deepseek.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(return_value=mock_response)))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            
            result = await generate_onboarding_response(
                messages=[{"role": "user", "content": "确认"}],
                understanding={"concept": "都市律师", "setting": "规则怪谈", "tone": "喜剧", "goals": "长篇"},
                api_key="test-key",
            )
            
            assert result["has_brief"] is True
            assert result["creative_brief"]["project_positioning"] == "都市律师题材"
```

- [ ] **Step 2: 运行测试**

Run: `cd backend && python -m pytest tests/test_onboarding.py -v`
Expected: 所有测试通过

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_onboarding.py
git commit -m "test(onboarding): add unit tests for understanding model and response generation"
```

---

### Task 8: 集成验证

**Files:**
- None (验证步骤)

- [ ] **Step 1: 后端启动验证**

Run: `cd backend && python -c "from main import app; print('Backend OK')"`
Expected: Backend OK

- [ ] **Step 2: 前端编译验证**

Run: `cd frontend && npx tsc --noEmit && npx vite build`
Expected: 编译成功，无错误

- [ ] **Step 3: 运行全部测试**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: 所有测试通过（允许已存在的失败测试）

- [ ] **Step 4: 最终 Commit**

```bash
git add -A
git commit -m "feat(onboarding): complete deep conversational guidance refactor"
```

---

## 验证清单

完成所有 Task 后，验证以下内容：

1. **后端 API**：`POST /api/stories/{id}/onboarding/message` 返回新的 understanding 结构
2. **前端渲染**：理解深度进度条正常显示和更新
3. **对话流程**：AI 主动追问和解读，不再机械填表
4. **分析卡**：内嵌在对话流中，支持"继续对话修改"
5. **确认流程**：点击"确认生成"正确调用 confirmOnboarding
6. **向后兼容**：collected_info 字段仍可正常工作
