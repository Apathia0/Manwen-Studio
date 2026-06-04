# LoreVista — AI 小说创作 + 漫画/视频生成平台

## 项目概览

LoreVista 是一个 AI 驱动的创作平台，支持小说创作、自动分镜、漫画图片生成和视频制作。

- **后端**：Python 3.10+ / FastAPI / SQLAlchemy 2.0 / PostgreSQL
- **前端**：React 19 / TypeScript 6 / Vite 8 / Tailwind CSS v4
- **移动端**：Vue 3 / uni-app（`lorevista-mobile/`）
- **AI 服务**：DeepSeek API（文本）+ Image2 API（图片）+ ComfyUI（视频）
- **部署**：PM2 + Nginx（CentOS Stream 9）

---

## 目录结构

```
LoreVista/
├── backend/                          # FastAPI 后端
│   ├── main.py                       # 主入口（8828 行）— 所有 API 路由 + 种子函数 + cron
│   ├── database.py                   # 引擎/Session + init_db + 增量迁移
│   ├── models.py                     # SQLAlchemy ORM 模型（~640 行）
│   ├── schemas.py                    # Pydantic 请求/响应模型（~876 行）
│   ├── requirements.txt              # Python 依赖
│   ├── .env                          # 环境变量
│   ├── routers/
│   │   ├── agent_router.py           # AI Agent 对话路由
│   │   └── video.py                  # 视频工作流路由
│   ├── services/
│   │   ├── task_manager.py           # 异步任务管理器（重试/取消/状态）
│   │   ├── deepseek.py               # DeepSeek API 封装（2744 行）
│   │   ├── image2.py                 # Image2 图片 API（956 行）
│   │   ├── prompt_template.py        # 提示词模板服务（326 行）
│   │   ├── agent_service.py          # AI Agent 服务层（1723 行）
│   │   ├── framework_utils.py        # 小说框架工具函数
│   │   ├── scene_safety.py           # 场景文本安全审查（替换敏感词）
│   │   ├── storyboard.py             # 分镜服务
│   │   ├── screenplay.py             # 剧本服务
│   │   ├── video_*.py                # 视频相关服务（qa/compiler/generation/api/comfyui）
│   │   ├── alipay_f2f.py             # 支付宝当面付
│   │   └── errors.py                 # 错误类型定义
│   ├── tests/                        # pytest 测试
│   ├── workflows/                    # ComfyUI JSON 工作流模板
│   ├── manual_migrate.py             # 手动数据库迁移脚本
│   ├── manga_outputs/                # 生成的漫画图片（静态文件）
│   └── video_outputs/                # 生成的视频文件（静态文件）
│
├── frontend/                         # React + Vite 前端
│   ├── vite.config.ts                # Vite 配置（代理 /api→:8000，代码分割）
│   ├── tsconfig.app.json             # TypeScript 严格模式配置
│   ├── package.json                  # 依赖：react19, tailwind v4, lucide, jszip
│   ├── index.html                    # 入口 HTML
│   ├── eslint.config.js              # ESLint flat config
│   └── src/
│       ├── main.tsx                  # 应用入口
│       ├── App.tsx                   # 根组件（路由 + 全局状态 + 页面切换）
│       ├── api.ts                    # API 客户端（3300+ 行）+ 所有类型定义
│       ├── genStore.ts               # 漫画生成状态管理（发布-订阅模块）
│       ├── videoGenStore.ts          # 视频生成状态管理（localStorage 持久化）
│       ├── index.css                 # Tailwind v4 + 全局样式
│       ├── prompts/                  # AI Prompt 模板（~10 个文件）
│       ├── lib/                      # 工具库（toast, confirm, format, cn）
│       ├── utils/                    # 差分工具
│       ├── components/
│       │   ├── ui/                   # 基础 UI 组件（Button, Input, Toast, ConfirmDialog）
│       │   ├── admin/                # 管理后台（AdminPages.tsx 1718 行）
│       │   ├── framework/            # 小说框架子组件
│       │   ├── editor/               # 编辑器子组件
│       │   ├── AgentPanel/           # AI 助手面板
│       │   ├── novel-autopilot/      # 小说自动创作
│       │   └── *Page.tsx / *Panel.tsx # 页面级组件（~30 个）
│       └── assets/                   # 静态资源
│
├── lorevista-mobile/                 # Vue 3 + uni-app 移动端
│   └── src/                          # 相同 API 层，vue 组件
│
├── .sisyphus/                        # Sisyphus AI Agent 工作文件
└── AGENTS.md                         # 本文件
```

---

## 后端架构

### 启动与运行

```bash
cd backend
python main.py                         # 开发（默认无 reload，Windows 不支持 uvicorn reload）
uvicorn main:app --host 0.0.0.0 --port 8000 --reload  # 需要 RELOAD=true 环境变量
```

环境变量由 `dotenv` 从 `backend/.env` 加载。

### 数据库

- **ORM**：SQLAlchemy 2.0（声明式映射 `Mapped` + `mapped_column`）
- **迁移策略**：无 Alembic，使用 `init_db()` 中的 `_migrate()` 函数执行**增量 DDL**
- **启动行为**：`RUN_STARTUP_MIGRATIONS=true` 时，启动时自动 `Base.metadata.create_all` + `_migrate()`
- **连接池**：`pool_size=10, max_overflow=20, pool_pre_ping=True, pool_recycle=300`
- **PostgreSQL 连接参数**：keepalives 配置确保长连接稳定

### 种子数据（重要）

种子函数在第一次请求（按需）时执行，而非启动时：

| 函数 | 触发时机 | 作用 |
|------|---------|------|
| `_ensure_platform_seed(db)` | 首次 `/api/stories` 等 API | 创建默认管理员、套餐、Feature Catalog、平台设置 |
| `_seed_system_prompts(db)` | 被 `_ensure_platform_seed` 调用 | 写入 6 条 `prompt.*` 系统默认提示词到 `PlatformSetting` |
| `_ensure_framework_prompt_synced(db)` | 部署后手动执行 | 一次性迁移，将 `FRAMEWORK_PROMPT_SEED` 写入 `PlatformSetting` |

### 单文件路由架构

所有 API 路由集中在 `main.py`（8828 行），按功能分区：
- `/api/stories/*`, `/api/chapters/*` — 作品、章节 CRUD
- `/api/framework/*` — 小说框架生成、调整
- `/api/manga/*` — 漫画生成、重绘
- `/api/screenplay/*`, `/api/shots/*` — 视频剧本、分镜
- `/api/admin/*` — 管理后台
- `/api/auth/*` — 认证
- `/api/prompt-templates/*` — 提示词模板
- `/api/billing/*` — 计费
- `/api/video/*` — 视频生成（路由在 `routers/video.py`）

### 认证系统

- JWT 模式：登录后返回 `token`，客户端存 localStorage
- `Authorization: Bearer <token>` 请求头发送
- 管理员检查：`_require_admin(request, db)` 辅助函数
- 可选的 API Token：环境变量 `API_TOKEN`，通过 `X-API-Token` 请求头验证

### 模型核心表

| 表 | 用途 |
|----|------|
| `users` | 用户 |
| `stories` | 作品（JSON 字段：outline/characters/tags/story_bible/story_memory） |
| `chapters` | 章节 |
| `chat_messages` | AI 对话消息 |
| `manga_images` | 漫画图片 |
| `background_tasks` | 异步任务状态 |
| `billing_orders` | 计费订单 |
| `plans` | 套餐定义 |
| `user_subscriptions` | 用户订阅 |
| `prompt_templates` | 用户自定义提示词模板 |
| `platform_settings` | 平台设置（key-value，含系统提示词） |
| `video_*` | 视频工作流相关表 |

### 任务管理器（`task_manager.py`）

全局单例 `task_manager`（`max_concurrent=5`）管理后台异步任务：

- **优雅取消**（`request_cancellation`）：设置 `_cancellation_flags[task_id] = True`，业务协程在每次 `await` 返回后检查 `is_cancellation_requested`，当前图片可正常完成
- **硬取消**（`cancel_task`）：直接抛 `CancelledError`
- **重试**：`with_retry` 装饰器，指数退避，超时不重试
- **状态保护**：`_mark_task_succeeded` 和 `_mark_task_failed` 都检查 `if task.status == "failed": return`，取消不覆盖失败

### 提示词模板配置化系统

提示词有三个层级：

```
系统默认（PlatformSetting table）
    ↓ 回退
用户自定义模板（PromptTemplate table / 绑定到作品）
    ↓ 优先级最高
作品的模板绑定（StoryTemplateBinding table）
```

- **4 种类型**：framework / chapter / character / manga_style
- **参数化配置**：每种类型对应 `*_params` JSON 字段（story_length, pacing, art_style 等）
- **`prompt_template.py`**：`build_prompt_from_params()` 将参数+基础 prompt 合成最终 prompt
- **`get_effective_prompt(story_id, prompt_type, db)`**：优先取模板绑定，回退到系统默认
- **`get_system_prompt` / `set_system_prompt`**：读写 `PlatformSetting` 中的 key `prompt.*`

### 计费与配额

- `FEATURE_CATALOG`（`main.py` 中定义）：功能特性注册表
- `Plan` → `PlanFeature`（套餐+特性关联）
- `PlanQuotaRule`：配额规则（重置周期/扣减方式）
- `UserUsageMonthly`：用户月度用量追踪
- `UserQuotaGrantMonthly`：月度配额授权

---

## 前端架构

### 构建与运行

```bash
cd frontend
npm install
npm run dev              # 开发（端口 5173，代理到 :8000）
npm run build            # 生产构建（tsc -b && vite build）
```

### Vite 代理规则（开发）

```ts
server: {
  host: '0.0.0.0',
  proxy: {
    '/api': 'http://localhost:8000',
    '/static': 'http://localhost:8000',
  }
}
```

### 代码分割策略

```ts
manualChunks: {
  'vendor-react': ['react', 'react-dom'],
  'vendor-lucide': ['lucide-react'],
  'vendor-utils': ['jszip', 'file-saver', 'qrcode'],
}
```

### 状态管理模式

**无 Redux / Zustand**，采用三种策略：

1. **`App.tsx` 集中管理** — 全局会话、路由、故事列表等 30+ 个 `useState`
2. **模块级 Store**（`genStore.ts` / `videoGenStore.ts`）— 发布-订阅模式，不依赖 React 状态树
3. **localStorage 直接驱动** — API Key、Auth Token、视频状态

### 路由系统

**无 react-router**，`App.tsx` 中 `RouteKey` 枚举 + `if-else` 条件渲染：
```ts
type RouteKey = 'landing' | 'login' | 'stories' | 'workspace' | 'templates' | ...
```
页面切换通过 `setRoute(key)` 驱动。

### API 客户端（`api.ts`）

- **全部原生 `fetch`**（无 Axios）
- **4 个流式（SSE）端点**：`chatStream` / `generateMangaStream` / `agentChatStream` / `generateStoryCharRefStream`
- SSE 使用 `fetch` + `ReadableStream` 手动解析
- 所有 API 返回 `AbortController` 用于取消
- 类型定义全部集中在 `api.ts`

### 关键注意事项

- **Tailwind v4**：通过 `@import "tailwindcss"` 引入，无 `tailwind.config.js`，inline utility classes
- **所有组件手写**：无 Shadcn/ui、Ant Design 等组件库
- **UI 组件**：`Button.tsx`, `Input.tsx`, `ToastContainer.tsx`, `ConfirmDialog.tsx`
- **Toast / ConfirmDialog**：模块级发布订阅 + Portal 到 `<div id="root">` 同级
- **无路径别名**：全部使用相对路径

---

## 移动端（`lorevista-mobile/`）

- Vue 3 + uni-app
- 独立构建，共享后端 API
- CSS variables + Tailwind 替代方案

---

## Prompt 模板文件（`frontend/src/prompts/`）

| 文件 | 用途 |
|------|------|
| `inkai-storyline.ts` | InkAI 框架生成 prompt |
| `inkai-chapter.ts` | InkAI 正文扩写 prompt |
| `inkai-characters.ts` | InkAI 角色生成 prompt |
| `inkai-quality.ts` | InkAI 质量评估 prompt |
| `inkai-tags.ts` | InkAI 标签生成 prompt |
| `video-screenplay.ts` | 视频剧本 prompt |
| `video-scenes.ts` | 视频场景 prompt |
| `video-shots.ts` | 视频分镜 prompt |
| `video-storyboard.ts` | 视频故事板 prompt |
| `video-continuity.ts` | 视频连续性评估 prompt |

---

## 部署

### 生产环境

- **服务器**：103.149.26.199（CentOS Stream 9）
- **项目路径**：`/www/wwwroot/canvas.aifusion6.cn/`
- **Python 虚拟环境**：`/www/wwwroot/canvas.aifusion6.cn/venv/`
- **PM2 进程**：`canvas-backend`（cwd = `.../backend/`）
- **前端**：`frontend/dist/` → Nginx 静态服务

### 部署步骤

```bash
# 1. 上传代码
# 2. 安装后端依赖（venv 中）
cd /www/wwwroot/canvas.aifusion6.cn/
source venv/bin/activate
pip install -r backend/requirements.txt

# 3. 构建前端
cd frontend
npm install && npm run build

# 4. 重启后端
pm2 reload canvas-backend --update-env

# 5. 执行数据库迁移（如有）
export RUN_STARTUP_MIGRATIONS=true; cd backend && python -c "
from main import app
from database import init_db
init_db(run_migrations=True)
"
```

### PM2 服务管理

```bash
pm2 list                           # 查看进程
pm2 logs canvas-backend            # 查看日志
pm2 reload canvas-backend --update-env  # 重启（更新环境变量）
pm2 delete canvas-backend          # 删除进程
pm2 start /www/wwwroot/.../backend/main.py --interpreter python3 --name canvas-backend
```

### 数据库迁移

```bash
# 手动执行 _ensure_framework_prompt_synced
cd /www/wwwroot/canvas.aifusion6.cn/backend
python -c "
from database import SessionLocal
from main import _ensure_framework_prompt_synced
_ensure_framework_prompt_synced(next(SessionLocal()))
"
```

---

## API 调用风格

### 后端 Helper 函数模式

后台任务通过 `task_manager.submit_task` 提交，协程签名必须是：
```python
async def my_func(*args, task_id=None, story_id=None, chapter_id=None, shot_id=None, **kwargs):
```

### 场景安全过滤

漫画/图片生成的场景描述必须通过 `sanitize_scene_text()` 过滤，替换敏感词（例如"尸体"→"失去意识的人影"）。

### DeepSeek 调用

项目自己的封装，非 LangChain。支持：
- `_deepseek_auth_headers(api_key)` → 请求头
- `_loads_json_lenient(text)` → lenient JSON 解析（处理 DeepSeek 偶尔的输出问题）
- `_sanitize_novel_content(text)` → 清理 AI 输出的常见问题

### Image2 图片 API

封装在 `services/image2.py`：
- 支持 `generate_manga_image`, `generate_cover_image`, `edit_existing_image`
- 指数退避重试 + prompt 太长自动截断 + 内容安全策略检测
- 图片存储到 `manga_outputs/`

---

## 常见陷阱

### 1. 后台任务取消不彻底
如果 `request_cancellation` 后任务仍继续运行，检查业务协程中是否**每轮循环都检查** `task_manager.is_cancellation_requested(task_id)`。当前正在调用上游 API 的图片不会被打断。

### 2. 同步函数误 await
`cleanup_stale_tasks` 是**同步函数**，调用时不要加 `await`。`task_manager` 中的 DB 操作都是同步的（直接 `SessionLocal()`）。

### 3. _mark_task_succeeded 覆盖取消状态
`_mark_task_succeeded` 和 `_mark_task_failed` 中都有 `if task.status == "failed": return` 保护，确保取消不被覆盖。

### 4. 种子函数重复写入
种子函数都有 `_ensure_*` 前缀，内部会先检查数据是否存在。写新的种子函数时也要遵循此模式。

### 5. DB 迁移幂等性
`_migrate()` 中的 ALTER TABLE 都检查列是否存在后再执行。迁移函数应始终幂等。

### 6. Vue vs React 在 mobile
`lorevista-mobile/` 使用 Vue 3 + uni-app 而非 React。修改 mobile 时要切换到对应工具链（npm install + manifest.json）。

### 7. 前端 SSO（无 react-router）
添加新页面时需要三步：① 在 `api.ts` 定义 API 函数和类型 ② 创建组件文件 ③ 在 `App.tsx` 添加 `RouteKey` + import + 条件渲染

### 8. Tailwind v4 的特殊性
- 无 `tailwind.config.js`，样式定制直接在 `index.css` 中
- 使用 `@import "tailwindcss"` 而非旧式 `@tailwind` 指令
- 生产构建中 Tailwind 会 tree-shake 未使用的类

---

## Sisyphus Agent 工作文件

`.sisyphus/` 目录包含部署记录和修复报告：
- `deployment-summary.md` — 部署命令历史
- `fix-complete-report.md` — bug 修复记录
- `plans/` — 实施计划
- `evidence/` — 验证证据截图/日志
