# 异步任务机制增强设计

## 概述

本设计旨在增强现有异步任务机制，解决以下6个核心问题：
1. 后台任务缺乏错误恢复机制
2. 数据库会话管理不一致
3. 乐观锁仅基于内容比较
4. 视频任务轮询间隔固定
5. 批量操作并发安全
6. 前端任务状态不持久

**设计原则**：
- 保持现有 `asyncio.create_task()` 调用方式不变
- 通过装饰器和上下文管理器添加增强功能
- 任务状态持久化到数据库，支持重启后恢复
- 无新外部依赖，保持轻量级

## 架构概览

```
┌─────────────────────────────────────────────────────────┐
│                     FastAPI 应用                        │
├─────────────────────────────────────────────────────────┤
│  asyncio.create_task()  ← 保持现有调用方式              │
│         ↓                                               │
│  ┌─────────────────────────────────────────────────┐   │
│  │           TaskManager（新增）                    │   │
│  │  ├── 重试装饰器（指数退避）                      │   │
│  │  ├── 并发限制（asyncio.Semaphore）               │   │
│  │  ├── 超时控制                                    │   │
│  │  └── 状态持久化                                  │   │
│  └─────────────────────────────────────────────────┘   │
│         ↓                                               │
│  ┌─────────────────────────────────────────────────┐   │
│  │           BackgroundTask（新增模型）             │   │
│  │  ├── task_id: str                               │   │
│  │  ├── task_type: str                             │   │
│  │  ├── status: pending/running/succeeded/failed   │   │
│  │  ├── retry_count: int                           │   │
│  │  ├── max_retries: int                           │   │
│  │  ├── error_message: str                         │   │
│  │  └── result_json: dict                          │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

## 组件设计

### 1. TaskManager 服务

**文件位置**：`backend/services/task_manager.py`

**职责**：
- 任务提交和生命周期管理
- 重试机制（指数退避）
- 并发控制
- 超时管理
- 状态持久化

**核心接口**：

```python
class TaskManager:
    def __init__(self, max_concurrent: int = 5):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running_tasks: dict[str, asyncio.Task] = {}
    
    def with_retry(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
    ) -> Callable:
        """重试装饰器，支持指数退避"""
        ...
    
    async def submit_task(
        self,
        task_id: str,
        task_type: str,
        coro_func: Callable,
        *args,
        timeout: float = 300.0,
        max_retries: int = 3,
        **kwargs
    ) -> str:
        """提交任务到后台执行"""
        ...
    
    async def cleanup_stale_tasks(self, max_age_hours: int = 24) -> int:
        """清理超时的僵尸任务"""
        ...
```

**重试策略**：
- 默认最多重试3次
- 指数退避：1s → 2s → 4s（最大60s）
- 每次重试更新数据库状态
- 最终失败标记为 `failed`

**并发限制**：
- 默认5个并发任务
- 使用 `asyncio.Semaphore` 控制
- 超出限制的任务排队等待

**超时管理**：
- 默认5分钟超时
- 使用 `asyncio.wait_for` 实现
- 超时任务自动标记为失败

### 2. BackgroundTask 模型

**文件位置**：`backend/models.py`

**表名**：`background_tasks`

**字段**：
```python
class BackgroundTask(Base):
    __tablename__ = "background_tasks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(50), unique=True, nullable=False, index=True)
    task_type = Column(String(50), nullable=False)  # quality_check, video_render, etc.
    status = Column(String(20), default="pending")  # pending/running/succeeded/failed/retrying
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    error_message = Column(Text, nullable=True)
    result_json = Column(JSON, nullable=True)
    
    # 关联实体
    story_id = Column(Integer, nullable=True)
    chapter_id = Column(Integer, nullable=True)
    shot_id = Column(Integer, nullable=True)
    
    # 时间戳
    created_at = Column(DateTime, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # 元数据
    metadata_json = Column(JSON, nullable=True)
```

**状态机**：
```
pending → running → succeeded
                 → failed
                 → retrying → running
                           → failed
```

### 3. 前端状态持久化

**文件位置**：`frontend/src/videoGenStore.ts`

**增强内容**：
- 状态变更时自动保存到localStorage
- 24小时自动过期
- 页面刷新后自动恢复
- 存储失败静默处理

**新增接口**：
```typescript
export const videoGenStore = {
  // 现有接口保持不变...
  
  // 新增：从localStorage恢复状态
  _loadPersistedStates(): Map<number, VideoGenState>
  
  // 新增：持久化到localStorage
  _persistStates(): void
  
  // 新增：清理过期状态
  cleanupExpired(): void
}
```

### 4. 现有任务集成

**修改文件**：
- `backend/main.py`：集成TaskManager到现有任务
- `backend/routers/video.py`：视频任务使用TaskManager

**集成方式**：
```python
# main.py
task_manager = TaskManager(max_concurrent=5)

# 现有代码改造
async def _background_quality_check(...):
    # 保持现有逻辑不变
    ...

# 提交任务时使用TaskManager
task_manager.submit_task(
    task_id=f"quality_check_{story.id}",
    task_type="quality_check",
    coro_func=_background_quality_check,
    story.id, story_description, api_key, ...
)
```

## 错误处理

### 1. 重试失败
- 记录详细错误日志
- 更新任务状态为 `failed`
- 保留错误消息供调试

### 2. 超时处理
- 自动取消超时任务
- 标记为失败并记录超时信息
- 清理相关资源

### 3. 并发限制
- 超出限制的任务排队等待
- 不会因为并发过高导致系统过载

## 监控和日志

### 1. 结构化日志
```python
logger.info(
    "Task submitted",
    extra={
        "task_id": task_id,
        "task_type": task_type,
        "max_retries": max_retries,
    }
)
```

### 2. 任务状态查询
```python
# API端点
GET /api/tasks/{task_id}
GET /api/tasks?status=failed&type=quality_check
```

## 测试策略

### 1. 单元测试
- TaskManager 重试逻辑
- 并发限制行为
- 超时处理
- 状态持久化

### 2. 集成测试
- 端到端任务流程
- 重启后状态恢复
- 并发任务执行

### 3. 性能测试
- 并发任务负载测试
- 数据库连接池压力测试

## 部署考虑

### 1. 数据库迁移
- 新增 `background_tasks` 表
- 无破坏性变更

### 2. 配置参数
```python
# 环境变量
TASK_MAX_CONCURRENT=5
TASK_DEFAULT_TIMEOUT=300
TASK_MAX_RETRIES=3
TASK_CLEANUP_INTERVAL=3600
```

### 3. 监控指标
- 任务成功率
- 平均执行时间
- 重试次数分布
- 并发任务数

## 风险评估

### 1. 低风险
- 无新外部依赖
- 保持现有API兼容
- 渐进式部署

### 2. 中风险
- 数据库连接池压力增加
- 需要监控并发任务数

### 3. 缓解措施
- 连接池大小配置
- 并发限制可调
- 优雅降级机制

## 后续扩展

### 1. 短期（1-2周）
- 添加任务取消API
- 实现任务优先级
- 添加执行时间统计

### 2. 中期（1-2月）
- 任务依赖关系
- 批量任务管理
- 任务调度优化

### 3. 长期（3-6月）
- 分布式任务支持
- 任务队列可视化
- 智能重试策略

## 附录

### A. 参考代码

**TaskManager 完整实现**：
```python
# 详见 services/task_manager.py
```

**BackgroundTask 模型**：
```python
# 详见 models.py
```

### B. 配置示例

```python
# .env
TASK_MAX_CONCURRENT=5
TASK_DEFAULT_TIMEOUT=300
TASK_MAX_RETRIES=3
TASK_CLEANUP_INTERVAL=3600
TASK_STATE_EXPIRY=86400
```

### C. API文档

```yaml
# 获取任务状态
GET /api/tasks/{task_id}
Response:
  - task_id: string
  - task_type: string
  - status: string
  - retry_count: integer
  - error_message: string
  - result_json: object
  - created_at: datetime
  - completed_at: datetime

# 列出任务
GET /api/tasks?status={status}&type={type}&limit={limit}&offset={offset}
Response:
  - tasks: array of task objects
  - total: integer
  - limit: integer
  - offset: integer
```

---

**设计完成日期**：2026-05-29
**设计者**：Sisyphus
**状态**：待审查
