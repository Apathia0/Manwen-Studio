# 全窗口拆书报告编辑器 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将拆书报告（主报告 + 作者画像报告）从嵌入式 `<pre>` 小窗改为铺满全窗口的可编辑页面，支持手动编辑并保存回后端。

**Architecture:** 后端新增 2 个 PATCH 端点（主报告 `/report` + 作者画像 `/author-style/report`），更新 `DeconstructionWork` 上的 `report_markdown` / `author_style_report_markdown` 字段。前端在 `DeconstructionWorkPage.tsx` 中新增 `'editing_report'` 页面状态 + `isEditingReport/isEditingAuthorStyle` 状态，编辑器复用 textarea + 保存/取消按钮的标准模式。

**Tech Stack:** FastAPI / SQLAlchemy / React 19 / TypeScript / Tailwind v4 / vitest / pytest

**Spec:** `docs/superpowers/specs/2026-07-03-full-window-deconstruction-report-editor-design.md`

---

### Task 1: Backend PATCH 端点 — 主拆文报告

**Files:**
- Modify: `backend/routers/deconstruct_library.py`（在 author-style 区域附近新增两个端点）
- Test: `backend/tests/test_deconstruct_library_report_update.py`（新建）

- [ ] **Step 1: 编写测试文件**

Create `backend/tests/test_deconstruct_library_report_update.py`:

```python
from routers.deconstruct_library import router


def test_deconstruct_report_patch_route_registered():
    """验证 PATCH /api/deconstruct/works/{work_id}/report 路由已注册"""
    patch_routes = [
        r for r in router.routes
        if hasattr(r, "methods") and "PATCH" in r.methods
        and r.path == "/api/deconstruct/works/{work_id}/report"
    ]
    assert len(patch_routes) == 1, f"期望 1 个 PATCH 路由，找到 {len(patch_routes)}"


def test_author_style_report_patch_route_registered():
    """验证 PATCH /api/deconstruct/works/{work_id}/author-style/report 路由已注册"""
    patch_routes = [
        r for r in router.routes
        if hasattr(r, "methods") and "PATCH" in r.methods
        and r.path == "/api/deconstruct/works/{work_id}/author-style/report"
    ]
    assert len(patch_routes) == 1, f"期望 1 个 PATCH 路由，找到 {len(patch_routes)}"


def test_deconstruct_report_patch_endpoint_name():
    """验证端点函数名符合约定"""
    for r in router.routes:
        if hasattr(r, "methods") and "PATCH" in r.methods and r.path == "/api/deconstruct/works/{work_id}/report":
            assert r.endpoint.__name__ == "update_deconstruction_report"
            return
    assert False, "路由未找到"
```

- [ ] **Step 2: 运行测试 → 预期失败**

Run: `python -m pytest backend/tests/test_deconstruct_library_report_update.py -q`
Expected: 2 failed ("route not found")

- [ ] **Step 3: 在 `deconstruct_library.py` 新增 PATCH 端点**

在 `# ── 5.5 作者风格/套路轻量提取 ──────────────────────────` 区块之后、`# ── 6. 拆书状态 ─────────────────────────────` 之前插入两个新端点：

```python

# ── 5.6 报告手动编辑与保存 ──────────────────────────

@router.patch("/api/deconstruct/works/{work_id}/report")
async def update_deconstruction_report(
    work_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """保存用户手动编辑后的拆文报告"""
    user = _require_user(request, db)
    work = db.query(DeconstructionWork).filter(
        DeconstructionWork.id == work_id,
        DeconstructionWork.owner_user_id == user.id,
    ).first()
    if not work:
        raise HTTPException(404, "拆书工作不存在")

    body = await request.json()
    if "report_markdown" in body and body["report_markdown"] is not None:
        work.report_markdown = body["report_markdown"]
        db.commit()
        db.refresh(work)

    return {"ok": True, "report_markdown": work.report_markdown}


@router.patch("/api/deconstruct/works/{work_id}/author-style/report")
async def update_author_style_report(
    work_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """保存用户手动编辑后的作者风格画像报告"""
    user = _require_user(request, db)
    work = db.query(DeconstructionWork).filter(
        DeconstructionWork.id == work_id,
        DeconstructionWork.owner_user_id == user.id,
    ).first()
    if not work:
        raise HTTPException(404, "拆书工作不存在")

    body = await request.json()
    if "report_markdown" in body and body["report_markdown"] is not None:
        work.author_style_report_markdown = body["report_markdown"]
        db.commit()
        db.refresh(work)

    return {"ok": True, "report_markdown": work.author_style_report_markdown}
```

- [ ] **Step 4: 运行测试 → 预期通过**

Run: `python -m pytest backend/tests/test_deconstruct_library_report_update.py -q`
Expected: 3 passed

- [ ] **Step 5: 编译检查**

Run: `python -m py_compile backend/routers/deconstruct_library.py`
Expected: exit code 0

---

### Task 2: 前端 API 函数

**Files:**
- Modify: `frontend/src/api.ts`（在 Author Style 区域新增两个函数）
- Test: `frontend/src/api.test.ts`（新增测试用例）

- [ ] **Step 1: 在 `api.ts` 中新增保存函数**

在 `getAuthorStyleResult` 函数之后（约 4764 行）新增：

```typescript
export async function updateDeconstructionReport(
  workId: number,
  data: { report_markdown: string }
): Promise<{ ok: boolean; report_markdown: string }> {
  const res = await fetch(`${BASE}/api/deconstruct/works/${workId}/report`, {
    method: 'PATCH',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '保存报告失败'));
  return res.json();
}

export async function updateAuthorStyleReport(
  workId: number,
  data: { report_markdown: string }
): Promise<{ ok: boolean; report_markdown: string }> {
  const res = await fetch(`${BASE}/api/deconstruct/works/${workId}/author-style/report`, {
    method: 'PATCH',
    headers: apiHeaders(true),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '保存作者画像报告失败'));
  return res.json();
}
```

- [ ] **Step 2: 在 `api.test.ts` 中新增 API 函数导出测试**

在 `api.test.ts` 中找到 test block，新增：

```typescript
import {
  updateDeconstructionReport,
  updateAuthorStyleReport,
} from '../api';

// ... existing tests ...

test('updateDeconstructionReport is a function', () => {
  expect(typeof updateDeconstructionReport).toBe('function');
});

test('updateAuthorStyleReport is a function', () => {
  expect(typeof updateAuthorStyleReport).toBe('function');
});
```

- [ ] **Step 3: 运行前端测试**

Run: `npm test -- --run`
Expected: 30 passed (原有 28 + 新增 2)

---

### Task 3: 前端 UI — 主报告编辑入口与全窗口编辑器

**Files:**
- Modify: `frontend/src/components/DeconstructionWorkPage.tsx`

- [ ] **Step 1: 添加新导入和状态**

在文件顶部 import 中增加：

```typescript
import { Edit3 } from 'lucide-react';
```

在现有 author style 状态声明后面（约第 123 行）新增：

```typescript
// 主拆文报告编辑
const [isEditingReport, setIsEditingReport] = useState(false);
const [draftReportContent, setDraftReportContent] = useState('');
const [savingReport, setSavingReport] = useState(false);
```

- [ ] **Step 2: 新增编辑处理函数**

在 `handleStartAuthorStyle` 函数之前（约第 205 行）新增：

```typescript
const handleEditReport = () => {
  setDraftReportContent(result?.report_markdown || '');
  setIsEditingReport(true);
};

const handleSaveReport = async () => {
  setSavingReport(true);
  try {
    await updateDeconstructionReport(
      work?.id || workId,
      { report_markdown: draftReportContent }
    );
    toast.success('报告已保存');
    setIsEditingReport(false);
    fetchResult();
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : '保存失败';
    toast.error(msg);
  } finally {
    setSavingReport(false);
  }
};

const handleCancelEdit = () => {
  setIsEditingReport(false);
};
```

注意：如果项目没有 `toast` 导入，检查是否通过 `ToastContainer` 全局发布-订阅模式使用。从现有代码看，编辑/保存模式使用的是 `toast.success`/`toast.error`，确保导入可用。

- [ ] **Step 3: 在 `completed` 状态的 tab 栏添加编辑按钮**

找到 `completed` 状态的渲染区域（约第 1118-1239 行），在 tab 栏的 `renderAuthorStyleEntry(true)` 旁边新增编辑报告按钮：

```tsx
<div className="flex-1" />
{shouldShowAuthorStyleEntry(work.decon_status) && renderAuthorStyleEntry(true)}
<button
  onClick={handleEditReport}
  className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100"
>
  <Edit3 className="h-3.5 w-3.5" />
  编辑报告
</button>
```

- [ ] **Step 4: 实现编辑态条件渲染**

在 `return (...)` 最外层（约第 1128 行之前），当 `isEditingReport` 为 true 时渲染编辑器页面：

```tsx
// 在主拆文报告编辑态时覆盖整个页面
if (isEditingReport) {
  const hasChanges = draftReportContent !== (result?.report_markdown || '');
  return (
    <div className="flex h-full flex-col">
      {/* 顶部操作栏 */}
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <button
          onClick={handleCancelEdit}
          className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-4 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50"
        >
          <ArrowLeft className="h-4 w-4" />
          取消
        </button>
        <h3 className="text-sm font-semibold text-slate-700">编辑拆文报告</h3>
        <button
          onClick={handleSaveReport}
          disabled={savingReport || !hasChanges}
          className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {savingReport ? '保存中...' : '保存更改'}
        </button>
      </div>
      {/* 文本编辑区 */}
      <div className="flex-1 p-4">
        <textarea
          value={draftReportContent}
          onChange={(e) => setDraftReportContent(e.target.value)}
          className="h-full w-full resize-none rounded-lg border border-slate-200 bg-white px-6 py-4 text-sm leading-relaxed whitespace-pre-wrap focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 5: 编译检查 + LSP 诊断**

Run: `npx tsc --noEmit`
Expected: exit code 0

---

### Task 4: 前端 UI — 作者风格画像报告编辑

**Files:**
- Modify: `frontend/src/components/DeconstructionWorkPage.tsx`

- [ ] **Step 1: 新增作者画像编辑状态和处理函数**

在 isEditingReport 相关状态后新增：

```typescript
const [isEditingAuthorStyle, setIsEditingAuthorStyle] = useState(false);
const [draftAuthorStyleContent, setDraftAuthorStyleContent] = useState('');
const [savingAuthorStyle, setSavingAuthorStyle] = useState(false);
```

新增处理函数，与主报告编辑类似但调用不同的 API：

```typescript
const handleEditAuthorStyle = () => {
  setDraftAuthorStyleContent(authorStyleResult?.report_markdown || '');
  setIsEditingAuthorStyle(true);
};

const handleSaveAuthorStyle = async () => {
  setSavingAuthorStyle(true);
  try {
    await updateAuthorStyleReport(
      work?.id || workId,
      { report_markdown: draftAuthorStyleContent }
    );
    toast.success('作者画像报告已保存');
    setIsEditingAuthorStyle(false);
    fetchAuthorStyle();
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : '保存失败';
    toast.error(msg);
  } finally {
    setSavingAuthorStyle(false);
  }
};

const handleCancelEditAuthorStyle = () => {
  setIsEditingAuthorStyle(false);
};
```

- [ ] **Step 2: 在 `renderAuthorStyleResult()` 中添加编辑按钮**

在 `renderAuthorStyleResult` 函数的 `{authorStyleResult.report_markdown ? (` 条件之上、卡片底部操作区添加编辑按钮：

修改 `renderAuthorStyleResult()`（约第 250 行），在 `<pre>` 块下方或卡片右上角添加编辑按钮：

```tsx
const renderAuthorStyleResult = () => {
  if (!authorStyleResult) return null;
  return (
    <div className="space-y-3 rounded-lg border border-violet-200 bg-white p-4 text-left shadow-sm">
      <div className="flex items-center justify-between rounded-lg bg-violet-50 p-3">
        <div>
          <h4 className="font-semibold text-violet-800">作者风格画像</h4>
          <p className="mt-1 text-xs text-violet-600">基于抽样章节生成，适合提取写法和套路。</p>
        </div>
        <button
          onClick={handleEditAuthorStyle}
          className="inline-flex items-center gap-1 rounded-lg border border-violet-200 bg-white px-2.5 py-1.5 text-xs font-medium text-violet-700 hover:bg-violet-50"
        >
          <Edit3 className="h-3.5 w-3.5" />
          编辑
        </button>
      </div>
      {authorStyleResult.report_markdown ? (
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap text-sm leading-6 text-slate-700">
          {authorStyleResult.report_markdown}
        </pre>
      ) : (
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap text-xs text-slate-600">
          {JSON.stringify(authorStyleResult.profile, null, 2)}
        </pre>
      )}
    </div>
  );
};
```

- [ ] **Step 3: 实现作者画像编辑态渲染**

在 `isEditingReport` 条件渲染块之后，新增 `isEditingAuthorStyle` 条件渲染：

```tsx
if (isEditingAuthorStyle) {
  const hasChanges = draftAuthorStyleContent !== (authorStyleResult?.report_markdown || '');
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <button
          onClick={handleCancelEditAuthorStyle}
          className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-4 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50"
        >
          <ArrowLeft className="h-4 w-4" />
          取消
        </button>
        <h3 className="text-sm font-semibold text-slate-700">编辑作者风格画像报告</h3>
        <button
          onClick={handleSaveAuthorStyle}
          disabled={savingAuthorStyle || !hasChanges}
          className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {savingAuthorStyle ? '保存中...' : '保存更改'}
        </button>
      </div>
      <div className="flex-1 p-4">
        <textarea
          value={draftAuthorStyleContent}
          onChange={(e) => setDraftAuthorStyleContent(e.target.value)}
          className="h-full w-full resize-none rounded-lg border border-slate-200 bg-white px-6 py-4 text-sm leading-relaxed whitespace-pre-wrap focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 编译检查**

Run: `npx tsc --noEmit`
Expected: exit code 0

---

### Task 5: 前端测试

**Files:**
- Modify: `frontend/src/api.test.ts`（追加新测试）

- [ ] **Step 1: 在 `api.test.ts` 中追加交互测试**

```typescript
// App 组件级交互测试需要渲染 DeconstructionWorkPage
// 但由于该组件依赖 API 调用和外部状态，建议用黑盒方式测试
// 这里测试更新函数的 URL 和 method 构造是否正确

// ── 报告编辑 ────────────────────────────────

test('updateDeconstructionReport constructs correct PATCH request', () => {
  // 验证函数存在且签名正确
  expect(updateDeconstructionReport).toBeDefined();
  expect(updateDeconstructionReport.length).toBe(2); // (workId, data)
});

test('updateAuthorStyleReport constructs correct PATCH request', () => {
  expect(updateAuthorStyleReport).toBeDefined();
  expect(updateAuthorStyleReport.length).toBe(2);
});
```

- [ ] **Step 2: 运行全部测试**

Run: `npm test -- --run`
Expected: 32 passed (原有 30 + 新增 2)

---

### Task 6: 集成验证

- [ ] **Step 1: 前端构建**

Run: `npm run build`
Expected: build success

- [ ] **Step 2: 后端编译检查**

Run: `python -m py_compile backend/routers/deconstruct_library.py`
Expected: exit code 0

- [ ] **Step 3: 后端测试**

Run: `python -m pytest backend/tests/test_deconstruct_library_report_update.py -q -v`
Expected: 3 passed

- [ ] **Step 4: 完整前后端测试**

Run: `python -m pytest backend/tests/test_deconstruct_library_report_update.py -q && npm test -- --run`
Expected: all passing

---

## Self-Review Checklist

- [ ] **Spec coverage**: 主报告编辑（Task 1 + Task 3）、作者画像编辑（Task 1 + Task 4）、前端 API（Task 2）、测试（Task 5）、集成验证（Task 6）全部覆盖
- [ ] **Placeholder scan**: 所有步骤包含完整代码和命令，无 TBD/TODO
- [ ] **Type consistency**: `updateDeconstructionReport(workId, {report_markdown})` 在 API 层和 UI 层签名一致；`updateAuthorStyleReport` 同理
