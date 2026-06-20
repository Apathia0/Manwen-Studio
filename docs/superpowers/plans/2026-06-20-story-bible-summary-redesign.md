# 作品圣经摘要显示优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 StoryBibleSummaryCard 的显示层，分组展示字段、消除嵌套边框、适配大量设定场景

**Architecture:** 仅在单个前端组件 `StoryBibleSummaryCard.tsx` 内做渲染层改版。新增 `SectionCard` 和 `InfoRow` 两个小型展示组件替换 `InfoItem`；重构 `WorldSettingNode` 和 `GenericJsonNode` 去掉多层 border，改用背景色/左边框线表示层级。

**Tech Stack:** React 19 / TypeScript / Tailwind v4

**File:** `frontend/src/components/StoryBibleSummaryCard.tsx`（仅修改此文件）

---

### Task 1: 新增 SectionCard + InfoRow 展示组件

**Files:**
- Modify: `frontend/src/components/StoryBibleSummaryCard.tsx`（在文件底部新增）

- [ ] **Step 1: 在 InfoItem 定义之后添加 SectionCard 组件**

```tsx
function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-[#e5edf8] bg-white/80 p-3 sm:col-span-2 lg:col-span-3">
      <div className="mb-2.5 text-[11px] font-semibold tracking-wide text-slate-500">
        {title}
      </div>
      <div className="divide-y divide-[#eef3f9]">{children}</div>
    </div>
  );
}
```

- [ ] **Step 2: 替换 InfoItem 添加紧凑 InfoRow 组件**

```tsx
function InfoRow({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div className="flex items-start gap-3 py-1.5">
      <span className="w-[76px] shrink-0 text-[10px] font-medium leading-5 text-slate-400">
        {label}
      </span>
      <span className="min-w-0 text-xs leading-5 text-slate-700">{value}</span>
    </div>
  );
}
```

- [ ] **Step 3: 缩短 InfoItem 的内边距（保留给 List 场景）**

将 `InfoItem` 的 padding `p-3` 改为 `p-2.5`，保留作为少数独立字段的可选渲染方式。

---

### Task 2: 重构展开区为分组卡片结构

**Files:**
- Modify: `frontend/src/components/StoryBibleSummaryCard.tsx:112-165`

- [ ] **Step 1: 替换展开区的网格布局为分组布局**

将：
```tsx
<div className="max-h-[min(65vh,720px)] overflow-y-auto pr-1">
  <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
    {brief?.project_positioning ? <InfoItem ... /> : null}
    ...15+ 独立 InfoItem/ListItem...
  </div>
</div>
```

替换为：
```tsx
<div className="max-h-[min(65vh,720px)] overflow-y-auto pr-1">
  <div className="space-y-3">
    {/* 基础设定 */}
    <SectionCard title="基础设定">
      <InfoRow label="作品定位" value={brief?.project_positioning} />
      <InfoRow label="题材" value={brief?.genre} />
      <InfoRow label="受众" value={brief?.audience} />
      <InfoRow label="风格基调" value={brief?.tone} />
      <InfoRow label="核心卖点" value={brief?.core_hook} />
      <InfoRow label="一句话梗概" value={brief?.one_line_premise} />
      <InfoRow label="目标篇幅" value={brief?.serial_length_target} />
    </SectionCard>

    {/* 故事核心 */}
    <SectionCard title="故事核心">
      <InfoRow label="主角核心" value={brief?.protagonist_core} />
      <InfoRow label="主线矛盾" value={brief?.main_conflict} />
      <InfoRow label="长线悬念" value={brief?.longline_mystery} />
      <InfoRow label="揭秘策略" value={brief?.reveal_strategy} />
      <InfoRow label="节奏策略" value={brief?.pacing_strategy} />
    </SectionCard>

    {/* 世界观设定 */}
    {brief?.world_setting ? (
      typeof brief.world_setting === 'object' ? (
        <SectionCard title="世界观设定">
          <div className="grid gap-1.5 sm:grid-cols-2">
            {Object.entries(brief.world_setting)
              .filter(([, v]) => v != null)
              .map(([key, val]) => (
                <WorldSettingNode key={key} label={key} value={val} />
              ))}
          </div>
        </SectionCard>
      ) : (
        <SectionCard title="世界观设定">
          <InfoRow label="世界观设定" value={brief.world_setting as string} />
        </SectionCard>
      )
    ) : null}

    {/* 开放故事笔记 */}
    {brief?.open_story_notes ? (
      <SectionCard title="开放笔记">
        <div className="whitespace-pre-wrap text-xs leading-5 text-slate-700">
          {brief.open_story_notes}
        </div>
      </SectionCard>
    ) : null}

    {/* 必保留设定 */}
    {mustKeepRules.length > 0 ? (
      <SectionCard title="必保留设定">
        <ul className="list-inside list-disc space-y-0.5 text-xs leading-5 text-slate-600">
          {mustKeepRules.map((item, idx) => (
            <li key={idx} className="text-[#2563eb]">{item}</li>
          ))}
        </ul>
      </SectionCard>
    ) : null}

    {/* 写作指导 */}
    {guidance ? (
      <SectionCard title="写作指导">
        <InfoRow label="开书策略" value={guidance.opening_strategy} />
        <InfoRow label="章节密度策略" value={guidance.chapter_density_strategy} />
        <InfoRow label="中段驱动力" value={guidance.midgame_engine} />
        <InfoRow label="后期方向" value={guidance.late_game_direction} />
      </SectionCard>
    ) : null}

    {/* 避免的模式 */}
    {forbiddenPatterns.length > 0 ? (
      <SectionCard title="避免的模式">
        <ul className="list-inside list-disc space-y-0.5 text-xs leading-5 text-rose-500">
          {forbiddenPatterns.map((item, idx) => (
            <li key={idx}>{item}</li>
          ))}
        </ul>
      </SectionCard>
    ) : null}

    {/* 推荐情节模式 */}
    {preferredPlotPatterns.length > 0 ? (
      <SectionCard title="推荐情节模式">
        <ul className="list-inside list-disc space-y-0.5 text-xs leading-5 text-emerald-600">
          {preferredPlotPatterns.map((item, idx) => (
            <li key={idx}>{item}</li>
          ))}
        </ul>
      </SectionCard>
    ) : null}

    <StoryBibleFullView storyBible={storyBible} />
  </div>
</div>
```

---

### Task 3: 重构 WorldSettingNode 去掉嵌套边框

**Files:**
- Modify: `frontend/src/components/StoryBibleSummaryCard.tsx:338-411`

- [ ] **Step 1: 修改 WorldSettingNode 去掉 border，改用背景色分层**

标量节点：
```tsx
function WorldSettingNode({ label, value, depth = 0 }: { label: string; value: unknown; depth?: number }) {
  if (value == null) return null;
  const displayLabel = translateLabel(label);
  const bgClass = depth === 0 ? 'bg-[#f8faff]' : depth === 1 ? 'bg-white' : 'bg-[#fafdff]';

  if (typeof value !== 'object') {
    const text = String(value).trim();
    if (!text) return null;
    return (
      <div className={`rounded-lg ${bgClass} p-2`}>
        <div className="text-[10px] font-medium text-slate-500">{displayLabel}</div>
        <div className="mt-0.5 text-xs leading-5 text-slate-600">{text}</div>
      </div>
    );
  }

  if (Array.isArray(value)) {
    const items = value.filter((v) => v != null);
    if (!items.length) return null;

    if (items.every((v) => typeof v !== 'object')) {
      return (
        <div className={`rounded-lg ${bgClass} p-2`}>
          <div className="text-[10px] font-medium text-slate-500">{displayLabel}</div>
          <ul className="mt-1 list-inside list-disc space-y-0.5 text-xs leading-5 text-slate-600">
            {items.map((item, i) => (
              <li key={i}>{String(item)}</li>
            ))}
          </ul>
        </div>
      );
    }

    return (
      <div className={`rounded-lg ${bgClass} p-2 ${depth > 0 ? 'ml-2' : ''}`}>
        <div className="text-[10px] font-medium text-slate-500">{displayLabel}</div>
        <div className="mt-1 space-y-1.5">
          {items.map((item, i) => {
            if (typeof item !== 'object' || item == null) {
              return <div key={i} className="text-xs leading-5 text-slate-600">{String(item)}</div>;
            }
            const entries = Object.entries(item as Record<string, unknown>).filter(
              ([, v]) => v != null && String(v).trim(),
            );
            if (!entries.length) return null;
            return (
              <div key={i} className="rounded-md bg-white/80 p-2">
                {entries.map(([sk, sv]) => (
                  <WorldSettingNode key={sk} label={sk} value={sv} depth={depth + 1} />
                ))}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  const entries = Object.entries(value as Record<string, unknown>).filter(([, v]) => v != null && String(v).trim());
  if (!entries.length) return null;

  return (
    <div className={`rounded-lg ${bgClass} p-2 ${depth > 0 ? 'ml-2' : ''}`}>
      <div className="text-[10px] font-medium text-slate-500">{displayLabel}</div>
      <div className="mt-1 space-y-1">
        {entries.map(([k, v]) => (
          <WorldSettingNode key={k} label={k} value={v} depth={depth + 1} />
        ))}
      </div>
    </div>
  );
}
```

---

### Task 4: 重构 GenericJsonNode / StoryBibleFullView 为扁平可折叠

**Files:**
- Modify: `frontend/src/components/StoryBibleSummaryCard.tsx:421-468`

- [ ] **Step 1: StoryBibleFullView 改为可折叠 + 扁平展示**

```tsx
function StoryBibleFullView({ storyBible }: { storyBible: StoryBible }) {
  const entries = Object.entries(storyBible).filter(([, value]) => hasRenderableValue(value));
  if (!entries.length) return null;

  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    raw_input: false, // 默认收起
  });

  const toggle = (key: string) => setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));

  // 对 creative_brief 和 writing_guidance 已经在上面展示过的跳过
  const filteredEntries = entries.filter(
    ([key]) => key !== 'creative_brief' && key !== 'writing_guidance' && key !== 'import_guidance',
  );

  if (!filteredEntries.length) return null;

  return (
    <div className="sm:col-span-2 lg:col-span-3">
      <div className="rounded-xl border border-[#e5edf8] bg-white/80 p-3">
        <div className="mb-2 text-[11px] font-semibold tracking-wide text-slate-500">完整作品圣经</div>
        <div className="space-y-2">
          {filteredEntries.map(([key, value]) => {
            const isOpen = openSections[key] ?? (key !== 'raw_input');
            return (
              <div key={key} className="rounded-lg border border-[#eef3f9]">
                <button
                  onClick={() => toggle(key)}
                  className="flex w-full items-center justify-between px-3 py-2 text-left text-xs font-medium text-slate-600 hover:bg-[#f8faff]"
                >
                  <span>{STORY_BIBLE_SECTION_LABELS[key] ?? key}</span>
                  {isOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                </button>
                {isOpen ? (
                  <div className="border-t border-[#eef3f9] px-3 py-2">
                    <GenericJsonNode label={''} value={value} depth={0} compact />
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 引入 useState**

添加 import：
```tsx
import { useEffect, useMemo, useState } from 'react';
```
（`useState` 已导入，无需额外操作）

- [ ] **Step 3: GenericJsonNode 改为 compact 模式**

```tsx
function GenericJsonNode({ label, value, depth = 0, compact = false }: {
  label: string;
  value: unknown;
  depth?: number;
  compact?: boolean;
}) {
  if (!hasRenderableValue(value)) return null;

  const indentStyle = depth > 0 ? 'ml-3 border-l-2 border-[#eef3f9] pl-2' : '';

  if (Array.isArray(value)) {
    return (
      <div className={`${indentStyle} ${depth > 0 ? 'py-0.5' : ''}`}>
        {label ? <div className="text-[10px] font-medium text-slate-400 mb-0.5">{label}</div> : null}
        <div className="space-y-0.5">
          {value.map((item, index) => (
            <GenericJsonNode key={index} label={`#${index + 1}`} value={item} depth={depth + 1} compact />
          ))}
        </div>
      </div>
    );
  }

  if (typeof value === 'object' && value !== null) {
    return (
      <div className={`${indentStyle}`}>
        {label ? <div className="text-[10px] font-medium text-slate-400 mb-0.5">{label}</div> : null}
        <div className="space-y-0.5">
          {Object.entries(value as Record<string, unknown>).map(([key, child]) => (
            <GenericJsonNode key={key} label={translateLabel(key)} value={child} depth={depth + 1} compact />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className={`flex items-start gap-2 py-0.5 ${indentStyle}`}>
      {label ? (
        <span className="shrink-0 text-[10px] font-medium leading-5 text-slate-400 min-w-[60px]">
          {label}
        </span>
      ) : null}
      <span className="text-xs leading-5 text-slate-600 whitespace-pre-wrap break-words">
        {String(value)}
      </span>
    </div>
  );
}
```

---

### Task 5: 补全标签中文化映射

**Files:**
- Modify: `frontend/src/components/StoryBibleSummaryCard.tsx:414-419`

- [ ] **Step 1: 补全 STORY_BIBLE_SECTION_LABELS**

```tsx
const STORY_BIBLE_SECTION_LABELS: Record<string, string> = {
  raw_input: '原始输入',
  creative_brief: '创意摘要',
  writing_guidance: '写作指导',
  import_guidance: '导入指导',
  world_setting: '世界观设定',
  raw_idea: '原始创意',
  raw_length_goal: '篇幅目标',
  raw_must_keep: '必保留要素',
  raw_notes: '原始笔记',
};
```

- [ ] **Step 2: 删除不再使用的 ListItem 函数（如果不再被引用）**

检查文件中是否有其他位置调用 `ListItem`，如已无引用则删除 `ListItem` 函数。

---

### Task 6: 验证

- [ ] **Step 1: 运行 lsp_diagnostics**

```bash
npx tsc --noEmit --pretty
```
或使用 `lsp_diagnostics` 工具检查文件。

- [ ] **Step 2: 运行前端构建**

```bash
cd frontend && npm run build
```

期望：构建成功，无错误。
