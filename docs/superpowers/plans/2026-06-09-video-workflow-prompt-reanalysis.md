# 视频工作流提示词重分析实现计划

> **对于代理工作者：** 必须使用子技能：推荐使用 superpowers:subagent-driven-development 或 superpowers:executing-plans 来逐任务实现此计划。步骤使用复选框（`- [ ]`）语法进行跟踪。

**目标：** 为章节视频工作流补齐单分镜整镜头提示词重分析，以及角色资产二级工作台只重分析当前角色提示词的能力。

**架构：** 复用现有章节工作流 `reanalyze-prompt` 接口，分镜列表按钮负责刷新单镜头全部提示词展示；角色工作台按钮在同一次重分析后只提取当前角色名对应的提示词并原位刷新。前端新增一个小型纯函数工具文件来承载角色匹配逻辑，并用最小测试覆盖严格绑定角色名的规则。

**技术栈：** React 19、TypeScript 6、Vite 8、Vitest、FastAPI（复用现有接口）

---

## 文件结构

### 新建文件
- `frontend/src/components/videoWorkbenchUtils.ts` — 角色工作台资源构建与角色提示词匹配纯函数
- `frontend/src/components/videoWorkbenchUtils.test.ts` — 纯函数测试

### 修改文件
- `frontend/package.json` — 增加测试脚本与 Vitest 依赖
- `frontend/tsconfig.app.json` — 增加 Vitest 类型
- `frontend/src/api.ts` — 如有必要补齐重分析接口类型
- `frontend/src/components/ChapterVideoWorkflowPanel.tsx` — 分镜按钮常驻化、工作台回调接入
- `frontend/src/components/VideoCardWorkbench.tsx` — 角色工作台支持“当前角色提示词重分析”文案与状态刷新
- `frontend/src/components/VideoStoryboardLayout.tsx` — 串联重分析请求、刷新 workflow、提示失败信息

---

## 任务1：补齐测试基础并锁定角色匹配规则

**文件：**
- 修改：`frontend/package.json`
- 修改：`frontend/tsconfig.app.json`
- 创建：`frontend/src/components/videoWorkbenchUtils.test.ts`

- [ ] **步骤1：编写失败测试，描述严格绑定当前角色名规则**

```ts
import { describe, expect, it } from 'vitest';
import { findCharacterPromptByName } from './videoWorkbenchUtils';

describe('findCharacterPromptByName', () => {
  it('按角色名精确匹配并忽略大小写与首尾空格', () => {
    expect(
      findCharacterPromptByName(
        [
          { name: '林秋', prompt: '角色A' },
          { name: ' 陈伯 ', prompt: '角色B' },
        ],
        '  陈伯'
      )
    ).toEqual({ name: ' 陈伯 ', prompt: '角色B' });
  });

  it('重分析后未识别到当前角色时返回 null', () => {
    expect(findCharacterPromptByName([{ name: '林秋', prompt: '角色A' }], '周临')).toBeNull();
  });
});
```

- [ ] **步骤2：运行测试，确认先失败**

Run: `npm run test -- videoWorkbenchUtils.test.ts`
Expected: FAIL，提示 `videoWorkbenchUtils` 或 `findCharacterPromptByName` 尚不存在

- [ ] **步骤3：补齐最小测试运行配置**

```json
{
  "scripts": {
    "test": "vitest run"
  },
  "devDependencies": {
    "vitest": "^2.1.8"
  }
}
```

```json
{
  "compilerOptions": {
    "types": ["vite/client", "vitest/globals"]
  }
}
```

---

## 任务2：实现角色工作台纯函数并让测试转绿

**文件：**
- 创建：`frontend/src/components/videoWorkbenchUtils.ts`
- 测试：`frontend/src/components/videoWorkbenchUtils.test.ts`

- [ ] **步骤1：实现纯函数**

```ts
export interface CharacterPromptItem {
  name: string;
  prompt: string;
}

export function normalizeCharacterName(name: string | null | undefined): string {
  return (name || '').trim().toLowerCase();
}

export function findCharacterPromptByName(
  prompts: CharacterPromptItem[] | null | undefined,
  targetName: string | null | undefined,
): CharacterPromptItem | null {
  const normalizedTarget = normalizeCharacterName(targetName);
  if (!normalizedTarget || !prompts?.length) return null;
  return prompts.find((item) => normalizeCharacterName(item.name) === normalizedTarget) || null;
}
```

- [ ] **步骤2：重新运行测试，确认通过**

Run: `npm run test -- videoWorkbenchUtils.test.ts`
Expected: PASS

---

## 任务3：实现分镜列表整镜头重新分析按钮

**文件：**
- 修改：`frontend/src/components/ChapterVideoWorkflowPanel.tsx`
- 修改：`frontend/src/components/VideoStoryboardLayout.tsx`

- [ ] **步骤1：让“重新分析提示词”在单镜头操作区稳定可见**

```tsx
<button
  onClick={() => void onReanalyzePrompt([shot.id])}
  disabled={workflowRunning}
  className="inline-flex items-center gap-1 rounded-lg border border-amber-200 px-3 py-1.5 text-xs text-amber-700 hover:bg-amber-50 disabled:opacity-50"
>
  <Sparkles size={12} /> 重新分析提示词
</button>
```

- [ ] **步骤2：在布局层复用现有接口并刷新 workflow**

```tsx
const result = await reanalyzeChapterWorkflowStoryboardPrompt(workflow.id, { shot_ids: shotIds });
const count = (result as any).updated_shot_ids?.length ?? shotIds.length;
toast.success(`故事版提示词已重新分析（${count} 个镜头）`);
await handleRefreshWorkflow();
```

- [ ] **步骤3：验证单镜头按钮不会只在 failed 状态显示**

Run: `npm run build`
Expected: PASS

---

## 任务4：实现角色资产二级工作台“只重分析当前角色提示词”

**文件：**
- 修改：`frontend/src/components/ChapterVideoWorkflowPanel.tsx`
- 修改：`frontend/src/components/VideoCardWorkbench.tsx`
- 修改：`frontend/src/components/VideoStoryboardLayout.tsx`
- 修改：`frontend/src/components/videoWorkbenchUtils.ts`

- [ ] **步骤1：给角色工作台资源补充角色名元数据**

```ts
resources = filtered.map((asset) => ({
  id: asset.id,
  url: toAssetUrl(asset.file_path),
  prompt: asset.name,
  characterName: asset.name,
}));
```

- [ ] **步骤2：角色工作台重分析后只刷新当前角色**

```tsx
const matched = findCharacterPromptByName(parsedCharacterPrompts, currentCharacterName);
if (!matched) {
  toast.warning('未重新识别到当前角色，请改用整镜头重新分析');
  return;
}
setState((s) => ({ ...s, editingPrompt: matched.prompt }));
toast.success(`已更新角色「${matched.name}」的提示词`);
```

- [ ] **步骤3：角色工作台按钮文案改成当前角色语义**

```tsx
{state.busy === 'reanalyze' ? '分析中...' : '重新分析当前角色提示词'}
```

- [ ] **步骤4：若后端只返回 storyboard prompt，则通过刷新 workflow 后从镜头角色列表中提取当前角色数据；若根本没有角色 prompt，提示用户未识别到当前角色**

Run: `npm run test -- videoWorkbenchUtils.test.ts`
Expected: PASS

---

## 任务5：全量验证

**文件：**
- 修改：`frontend/src/components/ChapterVideoWorkflowPanel.tsx`
- 修改：`frontend/src/components/VideoCardWorkbench.tsx`
- 修改：`frontend/src/components/VideoStoryboardLayout.tsx`
- 修改：`frontend/src/components/videoWorkbenchUtils.ts`

- [ ] **步骤1：运行前端定向测试**

Run: `npm run test -- videoWorkbenchUtils.test.ts`
Expected: PASS

- [ ] **步骤2：运行前端构建验证**

Run: `npm run build`
Expected: PASS

- [ ] **步骤3：运行后端既有相关测试，确认未破坏章节视频工作流**

Run: `pytest backend/tests/test_video_chapter_pipeline.py -q`
Expected: PASS

- [ ] **步骤4：运行改动文件诊断**

Run: `lsp_diagnostics` 检查所有修改过的前端文件
Expected: 无 error
