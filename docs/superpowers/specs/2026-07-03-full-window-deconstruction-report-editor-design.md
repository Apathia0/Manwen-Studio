# 全窗口拆书报告编辑器

## 概述

当前拆书报告（主拆文报告 `DeconstructionWork.report_markdown` 和作者风格画像报告 `DeconstructionWork.author_style_report_markdown`）在 `DeconstructionWorkPage.tsx` 中以 `<pre>` 小块展示，受 tab 面板大小限制，不可编辑。

本设计将报告展示改为**全窗口编辑器页面**，支持手动编辑并在后端持久化保存。

## 架构

### 数据流

```
┌─────────────────┐     PATCH /report_markdown      ┌────────────────────┐
│  Deconstruction │  ◄────────────────────────────  │  Frontend Editor   │
│  Work (DB)      │  ────────────────────────────►  │  (full-window)     │
│                 │    返回更新后状态                  │                    │
│ report_markdown │                                  │ textarea + 保存按钮│
│ author_style_   │                                  │                    │
│ report_markdown │                                  └────────────────────┘
└─────────────────┘
```

### 后端新增端点

两个独立的 PATCH 端点，路径模型参考现有 `/api/deconstruct/works/{work_id}/author-style/{action}` 风格。

#### 端点 1：主拆文报告保存

```
PATCH /api/deconstruct/works/{work_id}/report
```

```python
@router.patch("/api/deconstruct/works/{work_id}/report")
async def update_deconstruction_report(
    work_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
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
```

#### 端点 2：作者风格画像报告保存

```
PATCH /api/deconstruct/works/{work_id}/author-style/report
```

实现逻辑与端点 1 相同，更新 `work.author_style_report_markdown`。

### 认证

- 两个端点均使用 `_require_user(request, db)` 认证
- 通过 `DeconstructionWork.owner_user_id == user.id` 校验资源所有权
- 参考现有 `start_author_style_analysis` 的模式

### 前端 API 新增

`frontend/src/api.ts` 新增两个函数，风格与项目中已有的 `saveChapterContent`、`updateStoryBible` 一致：

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

## 前端 UI 设计

### 页面状态机扩展

`DeconstructionWorkPage.tsx` 的 `PageState` 类型新增 `'editing_report'`：

```typescript
type PageState = 'loading' | 'search' | 'crawling' | 'deconstructing'
               | 'completed' | 'failed' | 'not_found' | 'editing_report';
```

### 新增状态

```typescript
// 主拆文报告编辑
const [isEditingReport, setIsEditingReport] = useState(false);
const [draftReportContent, setDraftReportContent] = useState('');
const [savingReport, setSavingReport] = useState(false);

// 作者风格报告编辑
const [isEditingAuthorStyle, setIsEditingAuthorStyle] = useState(false);
const [draftAuthorStyleContent, setDraftAuthorStyleContent] = useState('');
const [savingAuthorStyle, setSavingAuthorStyle] = useState(false);
```

### 交互流程

#### 入口

在 `completed` 状态的 tab 栏右侧增加"编辑报告"按钮：

```
[拆文报告] [角色档案] [剧情线] [文风分析]    [编辑报告]
```

点击 → 进入 `editing_report` pageState。

#### 编辑页布局

```
┌───────────────────────────────────────────────┐
│ [← 取消]  编辑拆文报告        [保存更改]       │ ← 顶部操作栏
├───────────────────────────────────────────────┤
│                                               │
│  ┌─────────────────────────────────────────┐  │
│  │                                         │  │
│  │  textarea (flex-1, resize-none)         │  │
│  │  完整 report_markdown 内容               │  │
│  │  自动滚动                                │  │
│  │                                         │  │
│  │                                         │  │
│  └─────────────────────────────────────────┘  │
└───────────────────────────────────────────────┘
```

#### 按钮行为

| 操作 | 行为 |
|------|------|
| 点击"编辑报告" | `setDraftReportContent(result.report_markdown)` → `setIsEditingReport(true)` |
| 点击"保存更改" | `setSavingReport(true)` → `updateDeconstructionReport(...)` → `toast.success('报告已保存')` → `setIsEditingReport(false)` → `fetchResult()` |
| 点击"← 取消" | `setIsEditingReport(false)`，丢弃草稿 |
| 保存失败 | `toast.error('保存失败')`，编辑器保持打开，内容不丢失 |

#### 作者风格报告编辑

在文风分析 tab 的"作者风格画像"卡片内新增"编辑画像"按钮，点击后进入同一模式（可用同一个编辑组件，传入不同 content 和 save 函数）。

### 脏状态检测（可选增强）

```typescript
const hasChanges = draftReportContent !== (result?.report_markdown || '');
// 保存按钮 disabled={savingReport || !hasChanges}
```

### 组件复用

不创建新的独立组件文件。直接在 `DeconstructionWorkPage.tsx` 中：

- `renderReportEditor()` — 渲染主报告全窗口编辑态
- 作者画像的编辑复用 `renderAuthorStyleProgress()` / `renderAuthorStyleResult()` 同一模式，增加编辑按钮

### 样式规范

**操作栏按钮**（参考项目现有风格）：

```tsx
// 编辑入口
<button className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100">
  <Edit3 className="h-3.5 w-3.5" />
  编辑报告
</button>

// 保存按钮（主按钮）
<button
  disabled={savingReport}
  className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
>
  {savingReport ? '保存中...' : '保存更改'}
</button>

// 取消按钮
<button className="rounded-lg border border-slate-200 bg-white px-4 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50">
  取消
</button>
```

**textarea 编辑器**：

```tsx
<textarea
  value={draftReportContent}
  onChange={(e) => setDraftReportContent(e.target.value)}
  className="w-full flex-1 resize-none rounded-lg border border-slate-200 bg-white
             px-6 py-4 text-sm leading-relaxed whitespace-pre-wrap
             focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
/>
```

## 错误处理

| 场景 | 行为 |
|------|------|
| 保存 API 返回 4xx | `toast.error('保存失败：' + 错误信息)`，保持编辑态 |
| 网络中断 | `toast.error('网络连接失败')`，保持编辑态 |
| 取消未保存内容 | 直接丢弃，不加确认对话框（简洁路线） |
| 编辑时额外提取作者画像 | 不影响当前编辑状态 |

## 边界情况

1. **报告为空**：编辑入口仍然可用，textarea 打开为空内容，可输入新内容保存
2. **保存后刷新**：保存成功后调用 `fetchResult()` 刷新最新内容，编辑器退出
3. **并发编辑**：同一作品只有一个用户可操作（当前无多用户并发场景）
4. **长时间编辑未保存**：无自动保存，用户需手动点保存

## 测试策略

### 后端（pytest）

| 测试 | 说明 |
|------|------|
| `test_update_report_endpoint` | PATCH 正常保存 `report_markdown` |
| `test_update_report_empty_body` | 空 body 不应报错 |
| `test_update_report_unauthorized` | 非 owner 用户返回 404 |
| `test_update_author_style_report` | 保存 author_style_report_markdown |
| `test_update_report_not_found` | 不存在的 work_id 返回 404 |

### 前端（vitest）

| 测试 | 说明 |
|------|------|
| `test_edit_report_flow` | 点击编辑→修改内容→保存→退出编辑态 |
| `test_cancel_edit_discards_changes` | 取消编辑不保留 draft 内容 |
| `test_save_button_disabled_when_no_changes` | 无变化时保存按钮禁用 |
| `test_save_failure_keeps_editor_open` | 保存失败时编辑器不关闭 |
| `test_author_style_edit_report` | 作者画像报告同样可编辑保存 |

## 实施顺序

1. 后端：在 `deconstruct_library.py` 新增 2 个 PATCH 端点
2. 前端 API：在 `api.ts` 新增 `updateDeconstructionReport` + `updateAuthorStyleReport`
3. 前端 UI：在 `DeconstructionWorkPage.tsx` 中新增编辑态状态和渲染
4. 后端测试：pytest 覆盖 5 个测试用例
5. 前端测试：vitest 覆盖 5 个测试用例
6. 验证：`npm run build` + `npm test` + `pytest`

## 未纳入范围

- 结构化 JSON 字段（characters、plot_lines 等）的富文本编辑——本次仅编辑纯文本 markdown 报告
- 自动保存/草稿恢复——保持简洁的手动保存模式
- Markdown 预览/分栏编辑——仅纯 textarea 编辑
