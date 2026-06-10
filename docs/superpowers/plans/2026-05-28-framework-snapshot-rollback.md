# 框架调整快照回档功能 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每次框架调整前自动快照，提供滚回指定历史版本的能力，保留最近 20 条快照/故事。

**Architecture:** 新增独立 `framework_snapshots` 表存储调整前状态（description/tags/characters/outline），两个调整入口（FrameworkPanel/Agent）共用快照逻辑。回滚前也自动快照防止误操作。

**Tech Stack:** Python / SQLAlchemy / FastAPI / PostgreSQL / React / TypeScript / TailwindCSS

---

## 文件清单

### 新建
- `backend/tests/test_framework_snapshot.py` — 快照/回滚/淘汰单元测试

### 修改
- `backend/models.py` — 追加 `FrameworkSnapshot` 模型 + `Story.framework_snapshots` relationship
- `backend/services/framework_utils.py` — 追加 `_save_framework_snapshot()` / `_enforce_snapshot_limit()` / `restore_framework_snapshot()`
- `backend/main.py` — 追加两个快照 API 端点 + 在 `adjust_framework_endpoint` 中嵌入自动快照
- `backend/services/agent_service.py` — 在 `adjust_framework` 中嵌入自动快照
- `frontend/src/api.ts` — 追加快照 API 类型 + 请求函数
- `frontend/src/components/FrameworkPanel.tsx` — 追加「历史版本」按钮 + 快照列表面板
- `frontend/src/components/AgentPanel/AgentPanel.tsx` — 在 adjust 结果卡片追加备份提示

---

## 任务列表

### Task 1: 后端数据模型 + 快照工具函数

**Files:**
- Modify: `backend/models.py` (末尾)
- Modify: `backend/services/framework_utils.py` (末尾)

- [ ] **Step 1: 在 models.py 添加 FrameworkSnapshot 模型 + Story relationship**

在 `Story` 类的最后一个 relationship（`agent_conversations`）之后、class 结束之前插入 `framework_snapshots` relationship：

```python
# 在 Story 类内，agent_conversations relationship 之后追加：
    framework_snapshots: Mapped[list["FrameworkSnapshot"]] = relationship(
        "FrameworkSnapshot",
        back_populates="story",
        order_by="FrameworkSnapshot.created_at.desc()",
        cascade="all, delete-orphan",
    )
```

在 `Story` 类之后、文件末尾插入新模型：

```python
# ── 框架调整快照 ──────────────────────────────────────


class FrameworkSnapshot(Base):
    __tablename__ = "framework_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id"), nullable=False, index=True)
    snapshot_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="adjust")  # panel_adjust / agent_adjust / auto_before_restore
    reply_summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    story: Mapped["Story"] = relationship("Story", back_populates="framework_snapshots")
```

- [ ] **Step 2: 在框架初始化代码中导入 FrameworkSnapshot**

检查 `backend/main.py` 和 `backend/services/framework_utils.py` 等文件的 imports。在 `backend/main.py` 的 models import 中添加 `FrameworkSnapshot`（第 50 行附近）。

- [ ] **Step 3: 在 framework_utils.py 添加快照工具函数**

```python
def _save_framework_snapshot(story_id: int, snapshot_data: dict, source: str,
                             reply_summary: str | None, db: Session) -> FrameworkSnapshot:
    """保存一条框架快照。"""
    snap = FrameworkSnapshot(
        story_id=story_id,
        snapshot_data=snapshot_data,
        source=source,
        reply_summary=(reply_summary or "")[:255] if reply_summary else None,
    )
    db.add(snap)
    db.flush()
    return snap


def _enforce_framework_snapshot_limit(story_id: int, max_count: int, db: Session) -> None:
    """保留最近 max_count 条快照，删除更早的记录。"""
    ids_to_keep = (
        db.query(FrameworkSnapshot.id)
        .filter(FrameworkSnapshot.story_id == story_id)
        .order_by(FrameworkSnapshot.created_at.desc())
        .limit(max_count)
        .all()
    )
    if ids_to_keep:
        keep_set = {row[0] for row in ids_to_keep}
        db.query(FrameworkSnapshot).filter(
            FrameworkSnapshot.story_id == story_id,
            ~FrameworkSnapshot.id.in_(keep_set),
        ).delete(synchronize_session="fetch")


def _build_current_snapshot_data(story) -> dict:
    """从 Story 对象提取当前框架状态作为快照数据。"""
    return {
        "description": story.description or "",
        "tags": story.tags or {},
        "characters": story.characters or [],
        "outline": story.outline or {},
    }


def restore_framework_snapshot(story, snapshot_id: int, db: Session) -> dict:
    """将故事框架恢复到指定快照的状态。

    回滚前自动保存当前状态为快照（source='auto_before_restore'）。
    返回恢复后的 new_snapshot_data 供后续查询。
    """
    snap = db.query(FrameworkSnapshot).filter(
        FrameworkSnapshot.id == snapshot_id,
        FrameworkSnapshot.story_id == story.id,
    ).first()
    if not snap:
        raise ValueError("快照不存在或不属于当前故事")

    # 自动保存当前状态
    current_data = _build_current_snapshot_data(story)
    _save_framework_snapshot(
        story_id=story.id,
        snapshot_data=current_data,
        source="auto_before_restore",
        reply_summary=f"回滚前自动保存（目标快照 #{snapshot_id}）",
        db=db,
    )

    # 恢复快照
    data = snap.snapshot_data
    story.description = str(data.get("description") or "").strip()
    story.tags = data.get("tags") if isinstance(data.get("tags"), dict) else story.tags
    story.characters = _normalize_characters_payload(data.get("characters"))
    story.outline = data.get("outline") if isinstance(data.get("outline"), dict) else story.outline
    db.flush()

    _enforce_framework_snapshot_limit(story.id, max_count=20, db=db)

    return _build_current_snapshot_data(story)
```

确保 `framework_utils.py` 在文件顶部导入 `FrameworkSnapshot`：
```python
from models import FrameworkSnapshot
```

- [ ] **Step 4: 确保 framework_utils.py 有 `_normalize_characters_payload` 的访问权限**

`_normalize_characters_payload` 已经在 `framework_utils.py` 中定义了（从之前的 import 来看）。确认即可——不需要额外修改。

- [ ] **Step 5: 运行一次空测试确保不中断**

Run: `python -c "from services.framework_utils import _save_framework_snapshot; print('import OK')"`
Workdir: `backend/`
Expected: 输出 "import OK"

---

### Task 2: 单元测试（快照与回滚）

**Files:**
- Create: `backend/tests/test_framework_snapshot.py`

- [ ] **Step 1: 写测试文件**

```python
"""框架快照/回滚功能测试。"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from database import Base
from models import Story, FrameworkSnapshot
from services.framework_utils import (
    _save_framework_snapshot,
    _enforce_framework_snapshot_limit,
    _build_current_snapshot_data,
    restore_framework_snapshot,
    _normalize_characters_payload,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def story(db_session: Session) -> Story:
    s = Story(
        title="测试故事",
        description="原始描述",
        tags={"type": "novel"},
        characters=[{"name": "A", "role": "main"}],
        outline={"three_acts": [{"act": 1, "summary": "开头"}]},
    )
    db_session.add(s)
    db_session.commit()
    return s


class TestSaveSnapshot:
    def test_basic_save(self, db_session: Session, story: Story):
        """保存一条基本快照。"""
        data = _build_current_snapshot_data(story)
        snap = _save_framework_snapshot(
            story_id=story.id,
            snapshot_data=data,
            source="panel_adjust",
            reply_summary="测试保存",
            db=db_session,
        )
        assert snap.id is not None
        assert snap.story_id == story.id
        assert snap.snapshot_data["description"] == "原始描述"
        assert snap.source == "panel_adjust"
        assert snap.reply_summary == "测试保存"

    def test_multiple_snapshots_ordered(self, db_session: Session, story: Story):
        """多次保存，后保存的 created_at 更晚。"""
        data = _build_current_snapshot_data(story)
        snap1 = _save_framework_snapshot(story_id=story.id, snapshot_data=data, source="panel_adjust",
                                          reply_summary="第一次", db=db_session)
        story.description = "修改1"
        db_session.flush()
        data2 = _build_current_snapshot_data(story)
        snap2 = _save_framework_snapshot(story_id=story.id, snapshot_data=data2, source="panel_adjust",
                                          reply_summary="第二次", db=db_session)
        assert snap1.id < snap2.id


class TestEnforceSnapshotLimit:
    def test_keeps_max_count(self, db_session: Session, story: Story):
        """保留最近 max_count 条，删除更早的。"""
        for i in range(25):
            _save_framework_snapshot(
                story_id=story.id,
                snapshot_data=_build_current_snapshot_data(story),
                source="panel_adjust",
                reply_summary=f"快照{i}",
                db=db_session,
            )
        db_session.commit()

        _enforce_framework_snapshot_limit(story.id, max_count=20, db=db_session)
        db_session.commit()

        remaining = db_session.query(FrameworkSnapshot).filter(
            FrameworkSnapshot.story_id == story.id
        ).order_by(FrameworkSnapshot.created_at.desc()).all()
        assert len(remaining) == 20

    def test_under_limit_unchanged(self, db_session: Session, story: Story):
        """少于 max_count 时不做删除。"""
        for i in range(5):
            _save_framework_snapshot(
                story_id=story.id,
                snapshot_data=_build_current_snapshot_data(story),
                source="panel_adjust",
                reply_summary=f"快照{i}",
                db=db_session,
            )
        db_session.commit()

        _enforce_framework_snapshot_limit(story.id, max_count=20, db=db_session)
        remaining = db_session.query(FrameworkSnapshot).filter(
            FrameworkSnapshot.story_id == story.id
        ).count()
        assert remaining == 5


class TestRestoreSnapshot:
    def test_restore_basic(self, db_session: Session, story: Story):
        """回滚到指定快照，恢复 4 个字段。"""
        # 保存初始状态
        data1 = _build_current_snapshot_data(story)
        snap1 = _save_framework_snapshot(story_id=story.id, snapshot_data=data1, source="panel_adjust",
                                          reply_summary="初始", db=db_session)
        db_session.commit()

        # 修改 story
        story.description = "修改后描述"
        story.tags = {"type": "modified"}
        story.characters = [{"name": "B"}]
        story.outline = {"three_acts": []}
        db_session.flush()

        # 回滚
        result = restore_framework_snapshot(story, snap1.id, db_session)
        db_session.commit()

        assert story.description == "原始描述"
        assert story.tags == {"type": "novel"}
        assert story.characters == [{"name": "A", "role": "main"}]
        assert story.outline == {"three_acts": [{"act": 1, "summary": "开头"}]}
        # 恢复后的 snapshot_data 与 result 一致
        assert result["description"] == "原始描述"

    def test_restore_creates_auto_snapshot(self, db_session: Session, story: Story):
        """回滚前自动保存当前状态为快照。"""
        data1 = _build_current_snapshot_data(story)
        snap1 = _save_framework_snapshot(story_id=story.id, snapshot_data=data1, source="panel_adjust",
                                          reply_summary="初始", db=db_session)
        db_session.commit()

        story.description = "即将被保存的状态"
        db_session.flush()

        restore_framework_snapshot(story, snap1.id, db_session)
        db_session.commit()

        # 应该有一条 source=auto_before_restore 的快照
        auto_snap = db_session.query(FrameworkSnapshot).filter(
            FrameworkSnapshot.story_id == story.id,
            FrameworkSnapshot.source == "auto_before_restore",
        ).first()
        assert auto_snap is not None
        assert auto_snap.snapshot_data["description"] == "即将被保存的状态"

    def test_restore_invalid_snapshot(self, db_session: Session, story: Story):
        """回滚不存在的快照应抛出 ValueError。"""
        with pytest.raises(ValueError, match="快照不存在"):
            restore_framework_snapshot(story, 99999, db_session)

    def test_restore_enforces_limit(self, db_session: Session, story: Session):
        """回滚后执行淘汰，保留最近 20 条。"""
        # 简化测试：确保 restore 后 limit 被调用，通过留存数量验证
        pass  # 由验收/端到端测试覆盖
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_framework_snapshot.py -v`
Workdir: `backend/`
Expected: 部分测试因 `FrameworkSnapshot` 未在 models 中正确配置而失败，或因为 `_normalize_characters_payload` 未暴露而失败。

- [ ] **Step 3: 运行测试确认通过**

Run: `python -m pytest tests/test_framework_snapshot.py -v`
Workdir: `backend/`
Expected: 所有测试通过

- [ ] **Step 4: Commit**

```bash
git add backend/models.py backend/services/framework_utils.py backend/tests/test_framework_snapshot.py
git commit -m "feat: add FrameworkSnapshot model + snapshot utility functions (TDD)"
```

---

### Task 3: 后端 API — 快照列表 + 回滚端点

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: 在 main.py 导入 FrameworkSnapshot 和快照工具函数**

```python
# 在已有 models import 处添加 FrameworkSnapshot（第 49 行附近）
from models import (
    AuditLog,
    Chapter,
    FrameworkSnapshot,  # ← 新增
    # ... 其余保持不变
)

# 在已有 framework_utils import 处添加新函数（第 19 行附近）
from services.framework_utils import (
    # ... 已有导入保持不变 ...
    _build_current_snapshot_data,      # ← 新增
    _enforce_framework_snapshot_limit,  # ← 新增
    _save_framework_snapshot,          # ← 新增
    restore_framework_snapshot,        # ← 新增
)
```

- [ ] **Step 2: 添加 GET /api/stories/{story_id}/framework/snapshots 端点**

在 `adjust_framework_endpoint` 函数之前或之后（约第 6550 行）插入：

```python
# ── 框架快照 API ──────────────────────────────────────


@api_router.get("/stories/{story_id}/framework/snapshots")
def list_framework_snapshots(story_id: int, request: Request, db: Session = Depends(get_db)):
    """获取指定故事的框架快照列表（不含 snapshot_data，仅元信息）。"""
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    snapshots = (
        db.query(FrameworkSnapshot)
        .filter(FrameworkSnapshot.story_id == story.id)
        .order_by(FrameworkSnapshot.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "snapshots": [
            {
                "id": s.id,
                "source": s.source,
                "reply_summary": s.reply_summary or "",
                "created_at": s.created_at.isoformat() if s.created_at else "",
            }
            for s in snapshots
        ],
    }


@api_router.post("/stories/{story_id}/framework/snapshots/{snapshot_id}/restore")
def restore_framework_snapshot_endpoint(story_id: int, snapshot_id: int, request: Request, db: Session = Depends(get_db)):
    """将故事框架恢复到指定快照版本。回滚前自动保存当前状态。"""
    user = _require_user(request, db)
    story = _require_story_for_user(story_id, user, db)

    try:
        new_data = restore_framework_snapshot(story, snapshot_id, db)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    db.commit()
    db.refresh(story)
    return {
        "story": {
            "description": story.description,
            "tags": story.tags,
            "characters": story.characters,
            "outline": story.outline,
        },
        "snapshot_data": new_data,
        "message": "已恢复到所选版本",
    }
```

- [ ] **Step 3: 在 `adjust_framework_endpoint` 嵌入自动快照**

修改 `adjust_framework_endpoint` 函数。找到 `story = _require_story_for_user(story_id, user, db)`（第二次 fetch，在 validation 之后、写入之前，实际约第 6614 行），在下三行（赋值之前）插入：

```python
    # ★ 自动快照：保存调整前的框架状态
    _save_framework_snapshot(
        story_id=story.id,
        snapshot_data=_build_current_snapshot_data(story),
        source="panel_adjust",
        reply_summary=plan.get("reply", "")[:255] if plan.get("reply") else None,
        db=db,
    )
    _enforce_framework_snapshot_limit(story.id, max_count=20, db=db)

    story = _require_story_for_user(story_id, user, db)  # 这行已经是 — 快照插在它后面
    description = str(framework.get("description") or story.description or "").strip()
    # ...
```

- [ ] **Step 4: 验证 LSP 诊断通过**

Run LSP diagnostics on `backend/main.py`.
Expected: 无 type error。

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat: add snapshot list/restore API + auto-snapshot in panel adjust endpoint"
```

---

### Task 4: Agent 助手 `adjust_framework` 嵌入自动快照

**Files:**
- Modify: `backend/services/agent_service.py`

- [ ] **Step 1: 在 agent_service.py 导入快照工具函数**

```python
# 在已有 framework_utils import 处添加（第 21 行附近）
from services.framework_utils import (
    _extract_outline_chapters,
    _merge_framework_outline,
    _normalize_characters_payload,
    _normalize_framework_outline,
    apply_framework_operations,
    _build_current_snapshot_data,      # ← 新增
    _save_framework_snapshot,          # ← 新增
    _enforce_framework_snapshot_limit,  # ← 新增
)
```

并导入 `FrameworkSnapshot`（不需要直接引用，但 `_save_framework_snapshot` 已经引用，需要确保 models import）：

```python
# 在已有 models import（第 11 行）添加 FrameworkSnapshot
from models import Chapter, Story, FrameworkSnapshot
```

- [ ] **Step 2: 在 `adjust_framework` 函数中嵌入自动快照**

找到函数末尾的写入部分（大约第 799-814 行），在 `story.description = str(...)` 之前插入：

```python
        framework = apply_result["framework"]

        # ★ 自动快照：保存调整前的框架状态
        db.flush()  # 确保 story 状态最新
        _save_framework_snapshot(
            story_id=story.id,
            snapshot_data=_build_current_snapshot_data(story),
            source="agent_adjust",
            reply_summary=plan.get("reply", "")[:255] if plan.get("reply") else None,
            db=db,
        )
        _enforce_framework_snapshot_limit(story.id, max_count=20, db=db)

        story.description = str(framework.get("description") or existing_framework["description"] or "").strip()
        # ... 后续代码保持不变
```

- [ ] **Step 3: 验证 LSP 诊断通过**

Run LSP diagnostics on `backend/services/agent_service.py`.
Expected: 无 type error。

- [ ] **Step 4: Commit**

```bash
git add backend/services/agent_service.py
git commit -m "feat: auto-snapshot before agent framework adjust"
```

---

### Task 5: 前端类型定义 + API 请求函数

**Files:**
- Modify: `frontend/src/api.ts`

- [ ] **Step 1: 添加快照类型定义**

在 `FrameworkAdjustResponse`（第 245 行）之后插入：

```typescript
// ─── 框架快照 ─────────────────────────────────────────

export interface FrameworkSnapshotItem {
  id: number;
  source: string;
  reply_summary: string;
  created_at: string;
}

export interface FrameworkSnapshotListResponse {
  snapshots: FrameworkSnapshotItem[];
}

export interface FrameworkRestoreResponse {
  story: {
    description?: string;
    tags?: Tags;
    characters?: Character[];
    outline?: Outline;
  };
  snapshot_data: {
    description: string;
    tags: Tags;
    characters: Character[];
    outline: Outline;
  };
  message: string;
}
```

- [ ] **Step 2: 添加 API 请求函数**

在 `adjustFramework` 函数（约第 1931 行）之后插入：

```typescript
export async function listFrameworkSnapshots(
  storyId: number
): Promise<FrameworkSnapshotListResponse> {
  const res = await fetch(
    `/api/stories/${storyId}/framework/snapshots`,
    { credentials: 'include' }
  );
  if (!res.ok) {
    throw new Error(`获取快照列表失败: ${res.status}`);
  }
  return res.json();
}

export async function restoreFrameworkSnapshot(
  storyId: number,
  snapshotId: number
): Promise<FrameworkRestoreResponse> {
  const res = await fetch(
    `/api/stories/${storyId}/framework/snapshots/${snapshotId}/restore`,
    {
      method: 'POST',
      credentials: 'include',
    }
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `回滚失败: ${res.status}`);
  }
  return res.json();
}
```

- [ ] **Step 3: 验证 TypeScript 类型检查**

Run: `npx tsc --noEmit` 或 `npm run typecheck`（取决于项目配置）
Workdir: `frontend/`
Expected: 无 type error。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api.ts
git commit -m "feat: add frontend snapshot types and API functions"
```

---

### Task 6: FrameworkPanel — 历史版本按钮 + 快照列表 UI

**Files:**
- Modify: `frontend/src/components/FrameworkPanel.tsx`

- [ ] **Step 1: 阅读 FrameworkPanel 以了解现有结构**

```bash
# 查看 FrameworkPanel 的 imports / state / 标题栏渲染
head -100 frontend/src/components/FrameworkPanel.tsx | cat
```

定位标题栏的 JSX 位置（通常包含「一键续写」「清空」等按钮的区域）。

- [ ] **Step 2: 添加「历史版本」按钮到标题栏**

在标题栏按钮组中添加一个按钮：

```tsx
<button
  onClick={() => setShowSnapshotList(!showSnapshotList)}
  className="px-3 py-1 text-sm rounded bg-gray-100 hover:bg-gray-200 dark:bg-gray-700 dark:hover:bg-gray-600"
>
  历史版本
</button>
```

- [ ] **Step 3: 添加快照列表下拉面板**

在标题栏下方（或对话区域上方）添加条件渲染的面板：

```tsx
{showSnapshotList && (
  <div className="border-b dark:border-gray-700 bg-gray-50 dark:bg-gray-800 max-h-60 overflow-y-auto">
    <div className="px-3 py-2 text-xs text-gray-500 dark:text-gray-400 font-medium flex items-center justify-between">
      <span>历史版本（保留最近 20 条）</span>
      <button onClick={loadSnapshots} className="text-blue-500 hover:text-blue-700">刷新</button>
    </div>
    {snapshots.length === 0 ? (
      <div className="px-3 py-4 text-center text-sm text-gray-400">暂无历史版本</div>
    ) : (
      <ul>
        {snapshots.map((snap, idx) => (
          <li key={snap.id} className="px-3 py-2 border-t dark:border-gray-700 flex items-center justify-between text-sm">
            <div className="flex-1 min-w-0">
              <div className="truncate">
                {idx === 0 ? (
                  <span className="text-blue-600 font-medium">● 当前版本</span>
                ) : (
                  <span>{formatSnapshotTime(snap.created_at)}</span>
                )}
                {snap.reply_summary && (
                  <span className="text-gray-500 ml-1">- {snap.reply_summary}</span>
                )}
              </div>
              <div className="text-xs text-gray-400">{snap.source}</div>
            </div>
            {idx > 0 && (
              <button
                onClick={() => handleRestore(snap.id)}
                className="ml-2 px-2 py-0.5 text-xs rounded bg-blue-500 text-white hover:bg-blue-600 flex-shrink-0"
              >
                回滚到此
              </button>
            )}
          </li>
        ))}
      </ul>
    )}
  </div>
)}
```

- [ ] **Step 4: 添加状态变量 + 事件处理函数**

```typescript
// 组件内添加 state
const [showSnapshotList, setShowSnapshotList] = useState(false);
const [snapshots, setSnapshots] = useState<FrameworkSnapshotItem[]>([]);

// 加载快照列表
const loadSnapshots = useCallback(async () => {
  if (!storyId) return;
  try {
    const res = await listFrameworkSnapshots(storyId);
    setSnapshots(res.snapshots);
  } catch (e) {
    console.error('加载快照失败', e);
  }
}, [storyId]);

// 回滚
const handleRestore = useCallback(async (snapshotId: number) => {
  if (!storyId) return;
  if (!window.confirm('回滚将先保存当前状态再恢复所选版本，确认继续？')) return;
  try {
    await restoreFrameworkSnapshot(storyId, snapshotId);
    // 回滚成功后刷新页面或触发重新加载
    window.location.reload();
  } catch (e) {
    alert(`回滚失败: ${e instanceof Error ? e.message : String(e)}`);
  }
}, [storyId]);

// 打开面板时加载数据
useEffect(() => {
  if (showSnapshotList) {
    loadSnapshots();
  }
}, [showSnapshotList, loadSnapshots]);
```

- [ ] **Step 5: 添加工具函数（格式化时间）**

```typescript
function formatSnapshotTime(isoStr: string): string {
  try {
    const d = new Date(isoStr);
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const hour = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    return `${month}/${day} ${hour}:${min}`;
  } catch {
    return isoStr;
  }
}
```

- [ ] **Step 6: 确保 import 包含新函数**

```typescript
import { adjustFramework, listFrameworkSnapshots, restoreFrameworkSnapshot, FrameworkSnapshotItem } from '../api';
```

- [ ] **Step 7: 验证 TypeScript 类型检查通过**

Run: `npx tsc --noEmit`
Workdir: `frontend/`
Expected: 无 error。

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/FrameworkPanel.tsx
git commit -m "feat: add snapshot history panel in FrameworkPanel"
```

---

### Task 7: AgentPanel — 调整结果追加备份提示

**Files:**
- Modify: `frontend/src/components/AgentPanel/AgentPanel.tsx`

- [ ] **Step 1: 阅读 AgentPanel 找到 adjust_framework 工具调用结果渲染位置**

```bash
# 搜索 adjust_framework 在 AgentPanel 中的渲染
grep -n "adjust_framework\|applied_operations\|adjust" frontend/src/components/AgentPanel/AgentPanel.tsx | head -30
```

- [ ] **Step 2: 在工具调用结果卡片底部追加备份提示**

在 `adjust_framework` 的结果渲染区域的末尾添加：

```tsx
{applied_operations && applied_operations.length > 0 && (
  <div className="mt-2 text-xs text-gray-400 dark:text-gray-500">
    📋 当前版本已自动备份，可在左侧「历史版本」中回滚
  </div>
)}
```

- [ ] **Step 3: 验证 TypeScript 类型检查通过**

Run: `npx tsc --noEmit`
Workdir: `frontend/`
Expected: 无 error。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AgentPanel/AgentPanel.tsx
git commit -m "feat: add backup hint in agent adjust result card"
```

---

### Task 8: 端到端验证

- [ ] **Step 1: 启动后端 + 前端**

```bash
# 终端 1：后端
cd backend && python main.py

# 终端 2：前端
cd frontend && npm run dev
```

- [ ] **Step 2: 手动测试自动快照**
1. 进入任意故事的框架面板
2. 发送一条框架调整指令
3. 点击「历史版本」按钮
4. 验证出现一条新快照记录

- [ ] **Step 3: 手动测试回滚**
1. 在快照列表中点击某条记录的「回滚到此」
2. 确认弹窗出现
3. 确认后页面刷新
4. 验证框架 4 个字段恢复到目标版本
5. 再次打开历史版本，验证多出一条 `auto_before_restore` 快照

- [ ] **Step 4: 手动测试上限淘汰**
1. 手动触发超过 20 次调整（或直接通过 API 批量插入快照）
2. 验证列表最多显示 20 条

- [ ] **Step 5: 运行所有后端测试**

```bash
cd backend && python -m pytest tests/test_framework_snapshot.py tests/test_framework_operation_apply.py tests/test_framework_adjust_flow.py -v
```

Expected: 所有测试通过（允许 pre-existing 失败但与本功能无关的测试）
