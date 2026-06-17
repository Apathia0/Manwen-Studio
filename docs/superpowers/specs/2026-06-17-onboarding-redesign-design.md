# 开书引导深度对话式重构设计

## 背景与问题

当前开书引导（OnboardingPage）存在以下核心问题：

1. **AI 没有真正"理解"**：`_merge_onboarding_collected_info()` 直接 `collected[field] = latest_user_text`，用户的随口回答（如"偏喜剧"、"a"）被原样塞进结构化字段
2. **步骤推进是机械计数**：`_infer_onboarding_next_step()` 只数有几个字段被填了，填了 3 个就到第 4 步，完全不管内容质量
3. **对话是"问答-填表"循环**：系统 prompt 说"你是创作伙伴"，但代码结构把 AI 逼成了表单收集器
4. **结束条件太草率**：5 个字段都有值就触发 `is_complete`，弹出创意理解卡，对话戛然而止

## 设计目标

- AI 像真正的创作顾问一样，根据用户的回答追问、解读、提炼
- 每轮对话都有实质内容推进，而不是机械的 5 步问卷
- 对话轮次不固定，由 AI 根据理解深度自主决定
- 用户可以在 AI 输出创意分析卡后继续对话修改
- 对话式迭代确认，而非一次性弹窗

## 方案选择

采用**方案 B：软阶段 + 自然过渡**：
- 保留"概念→设定→基调→目标→综合"五个软阶段
- 去掉步骤编号，用"理解深度"进度条
- AI 自然过渡，不机械推进

---

## 一、对话模型重构

### 现状

AI 每轮返回：
```python
{
    "reply": "...",
    "collected_info": {"story_concept": "用户原文", ...},  # 原样填充
    "step": 2,          # 机械计数
    "is_complete": False  # 布尔值
}
```

### 新模型

AI 每轮返回：
```python
{
    "reply": "自然语言回复",
    "understanding": {
        "concept": "AI 提炼的故事概念（非用户原文）",
        "setting": "AI 提炼的世界观/设定",
        "tone": "AI 提炼的风格基调",
        "goals": "AI 提炼的创作目标",
        "synthesis": "AI 对整体创意的综合理解"
    },
    "understanding_depth": 65,  # 0-100，AI 自评理解深度
    "phase": "exploring",       # exploring | refining | synthesizing
    "has_brief": false,         # 是否已输出创意分析卡
    "creative_brief": null      # 创意分析卡内容（仅 has_brief=true 时有值）
}
```

### 关键变化

| 字段 | 旧 | 新 | 说明 |
|------|----|----|------|
| `collected_info` | 5 个字符串字段 | `understanding` 5 个 AI 提炼的结构化理解 | AI 解读后输出，非用户原文 |
| `step` | 1-5 机械计数 | `understanding_depth` 0-100 + `phase` 三阶段 | AI 自评深度 |
| `is_complete` | 布尔值 | `has_brief` | 是否输出分析卡 |

### 废弃

- `_merge_onboarding_collected_info()` 函数 → 由 AI prompt 直接输出结构化理解
- `_infer_onboarding_next_step()` 函数 → 由 AI 自评 understanding_depth
- 前端 `step`/`totalSteps` 状态 → 改为 `understandingDepth`

---

## 二、系统 Prompt 与 AI 行为

### 新 Prompt（替换 ONBOARDING_PROMPT_SEED）

```
你是「灵感捕手」——一位资深小说创作顾问。

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
- 不要使用选择题清单，用引导性问题
```

---

## 三、前端 UI 改动

### 1. 顶部栏

**移除**：
- "第 1 步 / 共 5 步" 文本
- 步骤进度条（5 个圆点）

**替换为**：
```
理解深度 [████████░░] 80%
```

实现：
```tsx
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
```

### 2. 右侧摘要面板

**移除**：静态字段列表（故事概念、题材方向、核心卖点等）

**替换为**：动态理解卡片，根据 `understanding` 对象渲染

```tsx
<div className="space-y-3">
  {understanding.concept && (
    <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
      <div className="text-[11px] font-medium text-[#2563eb]">💡 故事概念</div>
      <div className="mt-1 text-xs leading-5 text-slate-600">{understanding.concept}</div>
    </div>
  )}
  {understanding.setting && (
    <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
      <div className="text-[11px] font-medium text-[#2563eb]">🌍 世界观设定</div>
      <div className="mt-1 text-xs leading-5 text-slate-600">{understanding.setting}</div>
    </div>
  )}
  {understanding.tone && (
    <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
      <div className="text-[11px] font-medium text-[#2563eb]">🎭 风格基调</div>
      <div className="mt-1 text-xs leading-5 text-slate-600">{understanding.tone}</div>
    </div>
  )}
  {understanding.goals && (
    <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
      <div className="text-[11px] font-medium text-[#2563eb]">🎯 创作目标</div>
      <div className="mt-1 text-xs leading-5 text-slate-600">{understanding.goals}</div>
    </div>
  )}
  {understanding.synthesis && (
    <div className="rounded-2xl border border-[#d7e3f4] bg-[#eff6ff] p-3">
      <div className="text-[11px] font-medium text-[#2563eb]">📝 综合理解</div>
      <div className="mt-1 text-xs leading-5 text-slate-600">{understanding.synthesis}</div>
    </div>
  )}
  {Object.keys(understanding).length === 0 && (
    <div className="flex flex-col items-center gap-2 py-8 text-center text-xs text-slate-400">
      <MessageSquare size={24} className="opacity-40" />
      <div>AI 正在理解你的创意...</div>
      <div>在左侧对话后，这里会显示实时摘要</div>
    </div>
  )}
</div>
```

### 3. 创意分析卡

**移除**：弹窗式 `showConfirm` 状态 + 固定弹窗组件

**替换为**：内嵌在对话流中的分析卡

当 AI 返回 `has_brief: true` 时，将 `creative_brief` 附加到最后一条 assistant 消息上。渲染时检测消息是否包含 `creative_brief`，如有则渲染分析卡组件。

```tsx
interface OnboardingChatMessage {
  role: 'user' | 'assistant';
  content: string;
  creative_brief?: CreativeBrief;  // 新增字段
}
```

分析卡组件（内嵌版）：
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
    <div className="mt-2 rounded-2xl border border-[#bfdbfe] bg-[#f0f7ff] p-4">
      <div className="flex items-center gap-2 text-sm font-semibold text-[#1d4ed8]">
        <Sparkles size={14} />
        创意分析卡
      </div>
      <p className="mt-1 text-xs text-slate-500">
        我已经理解了你的创作构思，请确认以下分析是否准确：
      </p>
      <div className="mt-3 space-y-2">
        <BriefField label="作品定位" value={brief.project_positioning} />
        <div className="grid gap-2 sm:grid-cols-2">
          <BriefField label="一句话梗概" value={brief.one_line_premise} />
          <BriefField label="核心卖点" value={brief.core_hook} />
          <BriefField label="主线矛盾" value={brief.main_conflict} />
          <BriefField label="长线悬念" value={brief.longline_mystery} />
          <BriefField label="目标篇幅" value={brief.serial_length_target} />
          <BriefField label="揭秘策略" value={brief.reveal_strategy} />
          <BriefField label="节奏策略" value={brief.pacing_strategy} />
          <BriefField label="主角核心" value={brief.protagonist_core} />
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

### 4. 确认流程

**新流程**：
1. AI 输出分析卡（`has_brief: true`）→ 分析卡出现在对话流中
2. 用户点击"继续对话修改" → 分析卡折叠，用户继续输入
3. 用户在对话中说"改一下核心卖点" → AI 更新 `understanding` 和 `creative_brief`
4. AI 重新输出更新后的分析卡
5. 用户点击"确认生成" → 调用 `confirmOnboarding` → 进入工作台

**状态管理**：
```tsx
const [understandingDepth, setUnderstandingDepth] = useState(0);
const [understanding, setUnderstanding] = useState<Understanding>({});
const [showBrief, setShowBrief] = useState(false);
const [creativeBrief, setCreativeBrief] = useState<CreativeBrief | null>(null);
```

**handleSend 修改**：
```tsx
const handleSend = useCallback(async () => {
  // ... 现有逻辑 ...
  
  const result = await sendOnboardingMessage(story.id, updatedMessages, step);
  
  // 更新理解状态
  setUnderstanding(result.understanding || {});
  setUnderstandingDepth(result.understanding_depth || 0);
  
  // 处理分析卡
  if (result.has_brief && result.creative_brief) {
    setCreativeBrief(result.creative_brief);
    setShowBrief(true);
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
  
  setStep(result.step);
}, [...]);
```

---

## 四、后端改动

### 1. 新增 Understanding 模型（schemas.py）

```python
class Understanding(BaseModel):
    concept: str = ""
    setting: str = ""
    tone: str = ""
    goals: str = ""
    synthesis: str = ""

class OnboardingMessageOut(BaseModel):
    reply: str
    understanding: Understanding
    understanding_depth: int = 0
    phase: str = "exploring"
    has_brief: bool = False
    creative_brief: Optional[dict] = None
    # 保留兼容字段
    collected_info: dict = {}
    step: int = 1
    total_steps: int = 5
```

### 2. 修改 generate_onboarding_response（deepseek.py）

- 移除 `previous_collected_info` 和 `current_step` 参数
- 改为接收 `understanding`（当前理解状态）
- AI 在 prompt 中输出结构化理解
- 解析 AI 返回的 JSON，提取 `understanding`、`understanding_depth`、`phase`、`has_brief`、`creative_brief`

### 3. 废弃函数

- `_merge_onboarding_collected_info()` → 不再需要
- `_infer_onboarding_next_step()` → 不再需要
- `_build_onboarding_fallback_response()` → 简化为只提取 reply

### 4. 修改 onboarding_send_message（main.py）

- 传入 `understanding` 而非 `collected_info`
- 返回新的响应格式
- 保留 `collected_info` 兼容字段（从 understanding 映射）

### 5. 修改 onboarding_confirm（main.py）

- 接收 `understanding` 而非 `collected_info`
- 用 `understanding` 生成 Story Bible
- 保留 `collected_info` 兼容

---

## 五、兼容性处理

### 向后兼容

- `collected_info` 字段保留，从 `understanding` 映射：
  ```python
  collected_info = {
      "story_concept": understanding.get("concept", ""),
      "genre_audience": understanding.get("setting", ""),
      "core_hook": understanding.get("tone", ""),
      "target_length": understanding.get("goals", ""),
      "must_keep": understanding.get("synthesis", ""),
  }
  ```
- `step` 和 `total_steps` 字段保留，前端不显示但后端仍返回
- `confirmOnboarding` API 签名不变

### 数据库

- 无需迁移，`story.story_bible` JSON 字段结构不变
- `creative_brief` 结构不变

---

## 六、测试策略

### 单元测试

1. `test_generate_onboarding_response_returns_understanding` - 验证返回新的 understanding 结构
2. `test_generate_onboarding_response_has_brief_when_depth_high` - 验证深度足够时输出分析卡
3. `test_generate_onboarding_response_iterative_update` - 验证迭代修改分析卡

### 集成测试

1. `test_onboarding_full_flow` - 完整对话流程测试
2. `test_onboarding_confirm_with_understanding` - 确认流程测试

### 手动测试

1. 创建新故事 → 进入引导 → 验证对话自然流畅
2. 验证理解深度进度条实时更新
3. 验证分析卡在对话流中正确渲染
4. 验证"继续对话修改"功能
5. 验证"确认生成"功能

---

## 七、文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/services/deepseek.py` | 修改 | 重构 `generate_onboarding_response`，废弃合并函数 |
| `backend/main.py` | 修改 | 修改 `onboarding_send_message` 和 `onboarding_confirm` |
| `backend/schemas.py` | 修改 | 新增 `Understanding` 模型，修改 `OnboardingMessageOut` |
| `frontend/src/components/OnboardingPage.tsx` | 重写 | 移除步骤进度条，新增理解深度进度条，分析卡内嵌 |
| `frontend/src/api.ts` | 修改 | 更新 `OnboardingMessageOut` 接口 |
| `frontend/src/App.tsx` | 微调 | 移除步骤相关状态（如有） |

---

## 八、风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| AI 输出格式不稳定 | 使用 `_extract_json_object` 解析，fallback 机制保留 |
| understanding_depth 计算不准 | 允许 AI 自评，但设置合理范围（0-100） |
| 分析卡在对话流中渲染复杂 | 简化为消息附件，不使用弹窗 |
| 向后兼容问题 | 保留旧字段，从新字段映射 |
