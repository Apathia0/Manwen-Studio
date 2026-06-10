# 框架调整快照回档功能设计

## 问题

当前小说框架调整（页面对话框 / Agent 助手）在执行后直接覆写数据库中的 `description/tags/characters/outline` 字段，没有保存调整前的状态。如果 AI 调整不符合预期或改错，用户无法撤销恢复。

## 方案概要

采用独立数据库表 `framework_snapshots` 存储每次调整前的完整框架快照。每次框架调整前自动创建快照（无需用户手动操作），保留最近 20 条，用户可通过 UI 浏览历史版本并一键回滚。

## 数据模型

### FrameworkSnapshot 表

```python
class FrameworkSnapshot(Base):
    __tablename__ = "framework_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("stories.id"), nullable=False, index=True)
    snapshot_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="adjust")
    reply_summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    story: Mapped["Story"] = relationship("Story", back_populates="framework_snapshots")
```

### snapshot_data JSON 结构

```json
{
  "description": "作品描述",
  "tags": {"type": "...", "theme": "...", "style": "...", "audience": "..."},
  "characters": [{"name": "...", "role": "...", ...}],
  "outline": {"three_acts": [...], "themes": [...], "foreshadowing": [...], "serial_strategy": {...}}
}
```

### retention 策略

每次插入新快照后执行：
```sql
DELETE FROM framework_snapshots
WHERE story_id = ?
AND id NOT IN (
    SELECT id FROM framework_snapshots
    WHERE story_id = ?
    ORDER BY created_at DESC
    LIMIT 20
)
```

在 Story 模型上加 relationship：
```python
framework_snapshots: Mapped[list["FrameworkSnapshot"]] = relationship(
    "FrameworkSnapshot", back_populates="story",
    order_by="FrameworkSnapshot.created_at.desc()",
    cascade="all, delete-orphan",
)
```

## 后端 API

### 1. 获取快照列表

```
GET /api/stories/{story_id}/framework/snapshots
```

返回：
```json
{
  "snapshots": [
    {"id": 42, "source": "panel_adjust", "reply_summary": "已删除第8章", "created_at": "2026-05-28T10:30:00"},
    {"id": 41, "source": "agent_adjust", "reply_summary": "强化主角动机", "created_at": "2026-05-28T10:15:00"}
  ]
}
```

不返回完整 `snapshot_data`（列表页不需要）。按 `created_at DESC` 排序。

### 2. 回滚到指定快照

```
POST /api/stories/{story_id}/framework/snapshots/{snapshot_id}/restore
```

流程：
1. 查询快照是否存在且属于该 story
2. **自动保存当前状态为快照**（防止误回滚丢失工作，`source="auto_before_restore"`）
3. 将 `snapshot_data` 的 4 个字段覆写到 `story.description / tags / characters / outline`
4. 提交事务
5. 返回新的 story 状态

```python
def restore_framework_snapshot(story, snapshot, db):
    # 先保存当前状态
    _save_framework_snapshot(
        story_id=story.id,
        snapshot_data={
            "description": story.description,
            "tags": story.tags,
            "characters": story.characters,
            "outline": story.outline,
        },
        source="auto_before_restore",
        reply_summary=f"回滚前自动保存（目标快照 #{snapshot.id}）",
        db=db,
    )
    # 恢复快照
    data = snapshot.snapshot_data
    story.description = str(data.get("description") or "").strip()
    story.tags = data.get("tags") if isinstance(data.get("tags"), dict) else story.tags
    story.characters = _normalize_characters_payload(data.get("characters"))
    story.outline = data.get("outline") if isinstance(data.get("outline"), dict) else story.outline
    db.commit()
    _enforce_snapshot_limit(story.id, max_count=20, db=db)
```

### 3. 自动快照（嵌入现有调整流程）

改造 `adjust_framework_endpoint`（main.py）和 `adjust_framework`（agent_service.py）：

- **插入点**：在 `apply_framework_operations` 之前，即调整尚未持久化时
- **确保位置**：在 `_release_db_transaction(db)` 重新获取 story 之后，但在 commit 之前

`adjust_framework_endpoint` 中改造后的伪流程：

```python
# 释放事务后重新获取 story
story = _require_story_for_user(story_id, user, db)
# ★ 快照当前状态
_save_framework_snapshot(story_id=story.id, snapshot_data={...}, source="panel_adjust", ...)
_enforce_snapshot_limit(story_id, max_count=20, db=db)

# 执行调整（现有逻辑）
plan = await adjust_framework_with_chat(...)
apply_result = apply_framework_operations(existing_framework, plan.operations, plan.patches)
# ... 校验、持久化 ...
```

`agent_service.adjust_framework` 中同理，在 `apply_framework_operations` 调用前插入。

## 前端 UI

### FrameworkPanel（左侧框架对话）

在对话区域的标题栏右侧增加「历史版本」按钮：

```
┌─ 框架 AI 对话 ───────────────── [历史版本] [一键续写] [清空] ─┐
│  ...对话气泡...                                                │
└────────────────────────────────────────────────────────────────┘
```

点击后展开一个下拉面板，展示快照列表（时间倒序），每条显示：
- 创建时间（格式化，如 `28/05 10:30`）
- 来源（AI 对话 / Agent / 回滚前自动保存）
- reply_summary 摘要（如果有）
- 「回滚到此」按钮（当前版本标记为 `●`）

最后一条始终标记为「当前版本」。

回滚操作需要一次确认弹窗：「回滚将先保存当前状态再恢复所选版本，确认继续？」。

### AgentPanel（Agent 助手）

在 Agent 工具调用 `adjust_framework` 的结果卡片底部，追加一行提示：

```
📋 当前版本已自动备份，可在左侧「历史版本」中回滚
```

Agent 助手不实现独立的回滚 UI——引导用户使用左侧面板的统一回滚入口。

## 错误处理

| 场景 | 处理方式 |
|---|---|
| 回滚目标不存在（已被淘汰） | 返回 404 |
| snapshot_data 缺失某个顶级字段 | 缺失的字段保留当前值，不覆盖 |
| 并发保存快照 | 快照在同一个事务 session 内，由数据库事务保证一致性 |
| 快照达到上限 | 每次插入后执行 DELETE OFFSET 20 |
| Story 删除时级联清理 | SQLAlchemy cascade="all, delete-orphan" |

## 不纳入范围

- 不提供快照间 diff 对比（以后可以加）
- 不提供命名快照功能（目前只自动创建）
- 不修改 `/framework/generate`（首次生成不需要快照）
