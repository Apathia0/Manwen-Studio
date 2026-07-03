# 轻量作者风格拆书 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增单本书抽样式作者风格/套路提取能力，让用户无需完整逐章拆书即可获得可引用的作者画像。

**Architecture:** 后端在独立拆书库 `DeconstructionWork` 上新增作者画像字段，新增 `services/author_style.py` 执行抽样、模型分析与结果保存。前端在 `DeconstructionWorkPage.tsx` 增加启动、轮询和结果展示入口，完整拆书 Stage 0-6 不改变。

**Tech Stack:** Python 3.10+ / FastAPI / SQLAlchemy 2.0 / PostgreSQL / React 19 / TypeScript / Vite / Tailwind CSS v4。

---

## File Structure

- Modify: `backend/models.py` — 给 `DeconstructionWork` 增加作者画像状态、任务、结果和进度字段。
- Modify: `backend/database.py` — 增加幂等迁移，补齐 `deconstruction_works` 新列。
- Modify: `backend/prompts/deconstruction.py` — 增加作者风格样本分析、合并画像、报告生成 Prompt。
- Create: `backend/services/author_style.py` — 轻量作者画像服务，包含抽样策略与管线。
- Create: `backend/author_style_test.py` — 后端抽样策略和结果合并单元测试。
- Modify: `backend/routers/deconstruct_library.py` — 新增启动、状态、结果 API。
- Modify: `frontend/src/api.ts` — 新增作者画像类型和 API 函数。
- Modify: `frontend/src/api.test.ts` — 覆盖新增 API 函数请求路径。
- Modify: `frontend/src/components/DeconstructionWorkPage.tsx` — 增加启动按钮、状态轮询、结果 tab。

---

### Task 1: 后端模型与迁移

**Files:**
- Modify: `backend/models.py:847`
- Modify: `backend/database.py:1011`

- [ ] **Step 1: 写模型字段**

在 `DeconstructionWork` 的 `writing_techniques` 后追加字段：

```python
    author_style_status: Mapped[str] = mapped_column(String(30), default="not_started")
    author_style_task_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    author_style_profile: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    author_style_report_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_style_progress_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 2: 写幂等迁移**

在 `database.py` 的 `_migrate_deconstruction_library_tables()` 中，创建表逻辑之后追加列检查：

```python
        works_cols = {c["name"] for c in insp.get_columns("deconstruction_works")}
        if "author_style_status" not in works_cols:
            conn.execute(text("ALTER TABLE deconstruction_works ADD COLUMN author_style_status VARCHAR(30) DEFAULT 'not_started'"))
        if "author_style_task_id" not in works_cols:
            conn.execute(text("ALTER TABLE deconstruction_works ADD COLUMN author_style_task_id VARCHAR(80)"))
        if "author_style_profile" not in works_cols:
            conn.execute(text("ALTER TABLE deconstruction_works ADD COLUMN author_style_profile JSON"))
        if "author_style_report_markdown" not in works_cols:
            conn.execute(text("ALTER TABLE deconstruction_works ADD COLUMN author_style_report_markdown TEXT"))
        if "author_style_progress_markdown" not in works_cols:
            conn.execute(text("ALTER TABLE deconstruction_works ADD COLUMN author_style_progress_markdown TEXT"))
```

- [ ] **Step 3: 运行语法检查**

Run: `python -m py_compile backend/models.py backend/database.py`

Expected: exit code 0。

---

### Task 2: Prompt 与抽样服务

**Files:**
- Modify: `backend/prompts/deconstruction.py`
- Create: `backend/services/author_style.py`
- Create: `backend/author_style_test.py`

- [ ] **Step 1: 写抽样策略测试**

创建 `backend/author_style_test.py`：

```python
from services.author_style import select_author_style_samples


def test_select_author_style_samples_uses_all_when_short():
    chapters = list(range(1, 8))

    assert select_author_style_samples(chapters) == chapters


def test_select_author_style_samples_caps_long_books():
    chapters = list(range(1, 201))

    selected = select_author_style_samples(chapters)

    assert selected == sorted(set(selected))
    assert selected[:3] == [1, 2, 3]
    assert 199 in selected
    assert 200 in selected
    assert 16 <= len(selected) <= 20


def test_select_author_style_samples_medium_books_include_tail():
    chapters = list(range(1, 41))

    selected = select_author_style_samples(chapters)

    assert selected == sorted(set(selected))
    assert selected[:3] == [1, 2, 3]
    assert 40 in selected
    assert 12 <= len(selected) <= 15
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest backend/author_style_test.py -q`

Expected: FAIL，提示 `ModuleNotFoundError: No module named 'services.author_style'`。

- [ ] **Step 3: 添加 Prompt 常量**

在 `backend/prompts/deconstruction.py` 文件末尾追加：

```python
# ── 作者风格/套路轻量提取 ───────────────────────────────

AUTHOR_STYLE_SAMPLE_SYSTEM = """你是网络小说作者风格分析师。你的任务是从单章样本中提取可复用写作特征。

输出要求：严格返回 JSON，不要包含解释文字。

{
  "chapter_number": 1,
  "chapter_role": "开篇/中段/高潮/结尾/过渡",
  "style_features": {
    "sentence": ["句式特征"],
    "dialogue": ["对话特征"],
    "description": ["描写特征"],
    "emotion_expression": ["情绪表达特征"],
    "pov_and_narration": ["视角与叙述特征"]
  },
  "rhythm_features": {
    "opening_hook": "本章钩子",
    "chapter_end_hook": "章尾钩子",
    "info_release": "信息释放方式",
    "emotion_curve": "情绪曲线"
  },
  "routine_candidates": [
    {
      "name": "套路名称",
      "category": "开篇钩子/爽点设计/反转/关系拉扯/升级推进/章节结尾/信息控制",
      "structure": ["步骤1", "步骤2"],
      "emotion_curve": "情绪曲线",
      "evidence_summary": "证据说明"
    }
  ]
}
"""

AUTHOR_STYLE_SAMPLE_USER = """请分析以下章节样本。

作品：{title}
作者：{author}
章节：第{chapter_number}章 {chapter_title}
章节字数：{word_count}

章节正文：
{chapter_text}

仅返回 JSON。"""

AUTHOR_ROUTINE_MERGE_SYSTEM = """你是作者风格画像合成师。你需要将多个章节样本分析合并为单本书的作者风格画像。

输出要求：严格返回 JSON，不要包含解释文字。routine_cards 必须是可执行写作模板，不能只写抽象评价。
"""

AUTHOR_ROUTINE_MERGE_USER = """请合并以下样本分析，输出作者风格画像。

作品：{title}
作者：{author}
样本章节：{sampled_chapters}

样本分析 JSON：
{sample_results}

输出 JSON schema：
{
  "schema_version": 1,
  "sampled_chapters": [],
  "style_profile": {
    "sentence": {},
    "dialogue": {},
    "description": {},
    "emotion_expression": {},
    "pov_and_narration": {}
  },
  "rhythm_profile": {
    "opening_hook": {},
    "chapter_end_hooks": [],
    "emotion_cycle": {},
    "info_release_pattern": {}
  },
  "routine_cards": [],
  "writing_guide": {
    "do": [],
    "avoid": [],
    "prompt_notes": []
  },
  "confidence": 0.0
}

仅返回 JSON。"""

AUTHOR_STYLE_REPORT_SYSTEM = """你是小说写作教练。请把作者风格画像整理成中文 Markdown 报告，重点服务创作者学习，不要照搬原文。"""

AUTHOR_STYLE_REPORT_USER = """请基于以下作者风格画像生成 Markdown 报告。

作品：{title}
作者：{author}

画像 JSON：
{profile_json}

报告必须包含：文风画像、节奏习惯、套路卡、复用建议、风险提醒。"""
```

- [ ] **Step 4: 实现服务模块**

创建 `backend/services/author_style.py`：

```python
import asyncio
import json
import logging

from sqlalchemy.orm import Session

from database import SessionLocal
from models import DeconstructionWork, DeconstructionChapter
from prompts.deconstruction import (
    AUTHOR_ROUTINE_MERGE_SYSTEM,
    AUTHOR_ROUTINE_MERGE_USER,
    AUTHOR_STYLE_REPORT_SYSTEM,
    AUTHOR_STYLE_REPORT_USER,
    AUTHOR_STYLE_SAMPLE_SYSTEM,
    AUTHOR_STYLE_SAMPLE_USER,
)
from services.deconstruction import (
    _call_deepseek_json,
    _call_deepseek_text,
    _configure_deepseek_from_db,
    _count_words,
    _get_api_key_from_db,
    _truncate_json_for_context,
)

logger = logging.getLogger(__name__)

AUTHOR_STYLE_SAMPLE_CONCURRENCY = 4
AUTHOR_STYLE_CHAPTER_TEXT_LIMIT = 6000


def select_author_style_samples(chapter_numbers: list[int]) -> list[int]:
    ordered = sorted(set(int(n) for n in chapter_numbers if n is not None))
    total = len(ordered)
    if total <= 12:
        return ordered

    selected: set[int] = set(ordered[:3])
    if total <= 80:
        for ratio in (0.25, 0.4, 0.55, 0.7, 0.82, 0.9):
            idx = min(total - 1, max(0, round((total - 1) * ratio)))
            selected.add(ordered[idx])
        selected.update(ordered[-5:])
    else:
        for ratio in (0.2, 0.24, 0.4, 0.44, 0.6, 0.64, 0.8, 0.84):
            idx = min(total - 1, max(0, round((total - 1) * ratio)))
            selected.add(ordered[idx])
        selected.update(ordered[-2:])

    return sorted(selected)[:20]


def _update_author_style_progress(work: DeconstructionWork, db: Session, message: str) -> None:
    work.author_style_progress_markdown = (work.author_style_progress_markdown or "") + f"\n- {message}"
    db.commit()


async def run_author_style_pipeline(work_id: int, api_key: str | None, task_id: str | None = None, **kwargs) -> dict:
    db = SessionLocal()
    try:
        _configure_deepseek_from_db(db)
        if not api_key:
            api_key = _get_api_key_from_db(db)

        work = db.query(DeconstructionWork).filter(DeconstructionWork.id == work_id).first()
        if not work:
            raise ValueError(f"拆书工作 {work_id} 不存在")

        chapters = db.query(DeconstructionChapter).filter(
            DeconstructionChapter.work_id == work_id,
            DeconstructionChapter.content.isnot(None),
            DeconstructionChapter.content != "",
        ).order_by(DeconstructionChapter.chapter_number).all()
        if len(chapters) < 3:
            raise ValueError(f"至少需要 3 章有内容的章节才能提取作者风格（当前 {len(chapters)} 章）")

        by_number = {ch.chapter_number: ch for ch in chapters}
        sampled_numbers = select_author_style_samples(list(by_number))
        sampled_chapters = [by_number[n] for n in sampled_numbers if n in by_number]

        work.author_style_status = "running"
        work.author_style_task_id = task_id
        work.author_style_progress_markdown = ""
        db.commit()
        _update_author_style_progress(work, db, f"已选择 {len(sampled_chapters)} 个样本章节：{sampled_numbers}")

        semaphore = asyncio.Semaphore(AUTHOR_STYLE_SAMPLE_CONCURRENCY)

        async def analyze_one(ch: DeconstructionChapter) -> dict:
            async with semaphore:
                text = (ch.content or "")[:AUTHOR_STYLE_CHAPTER_TEXT_LIMIT]
                return await _call_deepseek_json(
                    AUTHOR_STYLE_SAMPLE_SYSTEM,
                    AUTHOR_STYLE_SAMPLE_USER.format(
                        title=work.title,
                        author=work.author or "未知",
                        chapter_number=ch.chapter_number,
                        chapter_title=ch.title or "",
                        word_count=ch.word_count or _count_words(ch.content),
                        chapter_text=text,
                    ),
                    api_key,
                )

        sample_results = await asyncio.gather(*[analyze_one(ch) for ch in sampled_chapters], return_exceptions=True)
        usable_results: list[dict] = []
        for ch, result in zip(sampled_chapters, sample_results):
            if isinstance(result, Exception):
                logger.warning("作者画像样本章节 %s 分析失败: %s", ch.chapter_number, result)
                _update_author_style_progress(work, db, f"第{ch.chapter_number}章样本分析失败：{result}")
                continue
            usable_results.append(result)

        if len(usable_results) < 3:
            raise ValueError("可用样本少于 3 章，无法合成作者风格画像")

        _update_author_style_progress(work, db, f"样本分析完成：成功 {len(usable_results)}/{len(sampled_chapters)} 章")
        profile = await _call_deepseek_json(
            AUTHOR_ROUTINE_MERGE_SYSTEM,
            AUTHOR_ROUTINE_MERGE_USER.format(
                title=work.title,
                author=work.author or "未知",
                sampled_chapters=json.dumps(sampled_numbers, ensure_ascii=False),
                sample_results=_truncate_json_for_context(usable_results, 30000),
            ),
            api_key,
        )
        profile["sampled_chapters"] = sampled_numbers
        profile.setdefault("schema_version", 1)

        report = await _call_deepseek_text(
            AUTHOR_STYLE_REPORT_SYSTEM,
            AUTHOR_STYLE_REPORT_USER.format(
                title=work.title,
                author=work.author or "未知",
                profile_json=json.dumps(profile, ensure_ascii=False, indent=2),
            ),
            api_key,
        )

        work.author_style_profile = profile
        work.author_style_report_markdown = report
        work.author_style_status = "completed"
        db.commit()
        _update_author_style_progress(work, db, "作者风格画像已生成")
        return {"status": "completed", "work_id": work.id}
    except Exception as exc:
        work = db.query(DeconstructionWork).filter(DeconstructionWork.id == work_id).first()
        if work:
            work.author_style_status = "failed"
            work.author_style_progress_markdown = (work.author_style_progress_markdown or "") + f"\n- 作者画像分析失败：{exc}"
            db.commit()
        raise
    finally:
        db.close()
```

- [ ] **Step 5: 运行抽样测试**

Run: `pytest backend/author_style_test.py -q`

Expected: 3 passed。

---

### Task 3: 作者画像 API

**Files:**
- Modify: `backend/routers/deconstruct_library.py`

- [ ] **Step 1: 添加 import**

在文件顶部现有 imports 附近增加：

```python
from services.author_style import run_author_style_pipeline
```

- [ ] **Step 2: 添加启动端点**

在拆书状态端点前增加：

```python
@router.post("/api/deconstruct/works/{work_id}/author-style/start")
async def start_author_style_analysis(
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
    if work.author_style_status in ("pending", "running"):
        raise HTTPException(400, "已有进行中的作者画像分析任务")

    chapter_count = db.query(DeconstructionChapter).filter(
        DeconstructionChapter.work_id == work_id,
        DeconstructionChapter.content.isnot(None),
        DeconstructionChapter.content != "",
    ).count()
    if chapter_count < 3:
        raise HTTPException(400, f"至少需要 3 章有内容的章节才能提取作者风格（当前 {chapter_count} 章）")

    from main import _check_and_consume_feature_quota, _refund_quota, _user_deepseek_api_key
    import datetime, uuid

    api_key = _user_deepseek_api_key(request)
    task_id_str = f"author_style_{work_id}_{int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1_000_000)}_{uuid.uuid4().hex[:6]}"

    quota_result = _check_and_consume_feature_quota(
        request,
        user.id,
        "deconstruction.run.monthly_limit",
        1,
        db,
        deduct=True,
        provider_kind="text",
    )
    quota_period_key = quota_result.get("period_key")
    quota_amount = 0 if quota_result.get("skipped") else 1

    work.author_style_status = "pending"
    work.author_style_task_id = task_id_str
    work.author_style_progress_markdown = "- 作者画像分析已提交"
    db.commit()

    try:
        await task_manager.submit_task(
            task_id=task_id_str,
            task_type="author_style",
            coro_func=run_author_style_pipeline,
            work_id=work_id,
            api_key=api_key,
            timeout=1800,
            max_retries=0,
            quota_user_id=user.id,
            quota_feature_key="deconstruction.run.monthly_limit",
            quota_amount=quota_amount,
            quota_period_key=quota_period_key,
        )
    except Exception:
        if quota_amount > 0:
            _refund_quota(user.id, "deconstruction.run.monthly_limit", quota_amount, db, quota_period_key)
        work.author_style_status = "failed"
        db.commit()
        raise

    return {"task_id": task_id_str, "message": "作者画像分析已启动"}
```

- [ ] **Step 3: 添加状态和结果端点**

追加：

```python
@router.get("/api/deconstruct/works/{work_id}/author-style/status")
async def get_author_style_status(
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
    return {
        "status": work.author_style_status or "not_started",
        "progress": work.author_style_progress_markdown,
        "task_id": work.author_style_task_id,
        "work_id": work.id,
    }


@router.get("/api/deconstruct/works/{work_id}/author-style/result")
async def get_author_style_result(
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
    if work.author_style_status != "completed":
        raise HTTPException(400, "作者画像分析尚未完成")
    return {
        "work_id": work.id,
        "title": work.title,
        "author": work.author,
        "status": work.author_style_status,
        "profile": work.author_style_profile,
        "report_markdown": work.author_style_report_markdown,
        "progress": work.author_style_progress_markdown,
    }
```

- [ ] **Step 4: 运行语法检查**

Run: `python -m py_compile backend/routers/deconstruct_library.py backend/services/author_style.py`

Expected: exit code 0。

---

### Task 4: 前端 API 类型与测试

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/api.test.ts`

- [ ] **Step 1: 增加类型与函数**

在 `api.ts` 的拆书库 API 区域追加：

```ts
export interface AuthorStyleStatus {
  status: 'not_started' | 'pending' | 'running' | 'completed' | 'failed';
  progress?: string | null;
  task_id?: string | null;
  work_id: number;
}

export interface AuthorStyleResult {
  work_id: number;
  title: string;
  author?: string | null;
  status: string;
  profile?: Record<string, unknown> | null;
  report_markdown?: string | null;
  progress?: string | null;
}

export async function startAuthorStyleAnalysis(workId: number): Promise<{ task_id: string; message: string }> {
  const res = await fetch(`${BASE}/api/deconstruct/works/${workId}/author-style/start`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '启动作者画像失败'));
  return res.json();
}

export async function getAuthorStyleStatus(workId: number): Promise<AuthorStyleStatus> {
  const res = await fetch(`${BASE}/api/deconstruct/works/${workId}/author-style/status`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取作者画像状态失败'));
  return res.json();
}

export async function getAuthorStyleResult(workId: number): Promise<AuthorStyleResult> {
  const res = await fetch(`${BASE}/api/deconstruct/works/${workId}/author-style/result`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res, '获取作者画像结果失败'));
  return res.json();
}
```

- [ ] **Step 2: 增加 API 测试**

在 `frontend/src/api.test.ts` 中按现有 fetch mock 风格新增测试：

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { getAuthorStyleResult, getAuthorStyleStatus, startAuthorStyleAnalysis } from './api';

describe('author style API', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ task_id: 't1', message: 'ok', status: 'completed', work_id: 7 }), { status: 200 })));
  });

  it('starts author style analysis with the expected endpoint', async () => {
    await startAuthorStyleAnalysis(7);

    expect(fetch).toHaveBeenCalledWith('/api/deconstruct/works/7/author-style/start', expect.objectContaining({ method: 'POST' }));
  });

  it('loads author style status with the expected endpoint', async () => {
    await getAuthorStyleStatus(7);

    expect(fetch).toHaveBeenCalledWith('/api/deconstruct/works/7/author-style/status', expect.any(Object));
  });

  it('loads author style result with the expected endpoint', async () => {
    await getAuthorStyleResult(7);

    expect(fetch).toHaveBeenCalledWith('/api/deconstruct/works/7/author-style/result', expect.any(Object));
  });
});
```

- [ ] **Step 3: 运行前端 API 测试**

Run: `npm test -- src/api.test.ts --run`

Workdir: `frontend`

Expected: PASS。

---

### Task 5: 前端页面接入

**Files:**
- Modify: `frontend/src/components/DeconstructionWorkPage.tsx`

- [ ] **Step 1: 引入 API 与类型**

在 imports 中加入：

```ts
import type { AuthorStyleResult, AuthorStyleStatus } from '../api';
import { startAuthorStyleAnalysis, getAuthorStyleStatus, getAuthorStyleResult } from '../api';
```

- [ ] **Step 2: 增加状态**

在组件 state 区域追加：

```ts
  const [authorStyleStatus, setAuthorStyleStatus] = useState<AuthorStyleStatus | null>(null);
  const [authorStyleResult, setAuthorStyleResult] = useState<AuthorStyleResult | null>(null);
  const [authorStyleLoading, setAuthorStyleLoading] = useState(false);
```

- [ ] **Step 3: 增加启动和加载函数**

在 `fetchResult` 附近添加：

```ts
  const fetchAuthorStyle = async () => {
    try {
      const s = await getAuthorStyleStatus(work?.id || workId);
      setAuthorStyleStatus(s);
      if (s.status === 'completed') {
        const r = await getAuthorStyleResult(work?.id || workId);
        setAuthorStyleResult(r);
      }
    } catch {
      // 作者画像是附加能力，失败不影响拆书主流程。
    }
  };

  const handleStartAuthorStyle = async () => {
    setAuthorStyleLoading(true);
    setError(null);
    try {
      await startAuthorStyleAnalysis(work?.id || workId);
      setAuthorStyleStatus({ status: 'running', progress: '- 作者画像分析已启动', work_id: work?.id || workId });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '作者画像启动失败';
      setError(msg);
    } finally {
      setAuthorStyleLoading(false);
    }
  };
```

- [ ] **Step 4: 增加轮询**

添加 `useEffect`：

```ts
  useEffect(() => {
    if (!work?.id) return;
    fetchAuthorStyle();
  }, [work?.id]);

  useEffect(() => {
    if (!work?.id || authorStyleStatus?.status !== 'running') return;
    const timer = setInterval(fetchAuthorStyle, 3000);
    return () => clearInterval(timer);
  }, [work?.id, authorStyleStatus?.status]);
```

- [ ] **Step 5: 增加按钮**

在可启动拆书的按钮区域加入：

```tsx
<button
  onClick={handleStartAuthorStyle}
  disabled={authorStyleLoading || authorStyleStatus?.status === 'running'}
  className="flex items-center gap-2 rounded-lg border border-violet-300 bg-violet-50 px-4 py-2 text-sm font-medium text-violet-700 hover:bg-violet-100 disabled:opacity-50"
>
  {authorStyleLoading || authorStyleStatus?.status === 'running' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Palette className="h-4 w-4" />}
  提取作者风格/套路
</button>
<p className="text-xs text-slate-500">抽样分析，成本低于完整拆书</p>
```

- [ ] **Step 6: 增加结果展示**

在结果 tab 区域增加 `authorStyle` tab，或在 `style` tab 内优先展示 `authorStyleResult`：

```tsx
{authorStyleResult && activeTab === 'style' && (
  <div className="space-y-4">
    <div className="rounded-lg border border-violet-200 bg-violet-50 p-4">
      <h4 className="font-semibold text-violet-800">作者风格画像</h4>
      <p className="mt-1 text-xs text-violet-600">基于抽样章节生成，适合提取写法和套路。</p>
    </div>
    {authorStyleResult.report_markdown ? (
      <pre className="whitespace-pre-wrap rounded-lg bg-white p-4 text-sm leading-6 text-slate-700">
        {authorStyleResult.report_markdown}
      </pre>
    ) : (
      <pre className="whitespace-pre-wrap rounded-lg bg-white p-4 text-xs text-slate-600">
        {JSON.stringify(authorStyleResult.profile, null, 2)}
      </pre>
    )}
  </div>
)}
```

- [ ] **Step 7: 运行前端构建**

Run: `npm run build`

Workdir: `frontend`

Expected: TypeScript 编译和 Vite build 成功。

---

### Task 6: 集成验证

**Files:**
- Verify only

- [ ] **Step 1: 后端语法检查**

Run: `python -m py_compile backend/models.py backend/database.py backend/prompts/deconstruction.py backend/services/author_style.py backend/routers/deconstruct_library.py`

Expected: exit code 0。

- [ ] **Step 2: 后端单元测试**

Run: `pytest backend/author_style_test.py -q`

Expected: PASS。

- [ ] **Step 3: 前端 API 测试**

Run: `npm test -- src/api.test.ts --run`

Workdir: `frontend`

Expected: PASS。

- [ ] **Step 4: 前端构建**

Run: `npm run build`

Workdir: `frontend`

Expected: PASS。

- [ ] **Step 5: 检查 git diff**

Run: `git diff -- backend/models.py backend/database.py backend/prompts/deconstruction.py backend/services/author_style.py backend/routers/deconstruct_library.py backend/author_style_test.py frontend/src/api.ts frontend/src/api.test.ts frontend/src/components/DeconstructionWorkPage.tsx docs/superpowers/specs/2026-07-03-lightweight-author-style-deconstruction-design.md docs/superpowers/plans/2026-07-03-lightweight-author-style-deconstruction.md`

Expected: 只包含本计划范围内的改动。
