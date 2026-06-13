# StoryCanvas — AI 小说创作 + 漫画/视频生成平台

## 项目概览

StoryCanvas 是一个 AI 驱动的创作平台，支持小说创作、自动分镜、漫画图片生成和视频制作。基于 LoreVista 深度二次开发，融入更多创作工具和优化体验。

- **后端**：Python 3.10+ / FastAPI / SQLAlchemy 2.0 / PostgreSQL
- **前端**：React 19 / TypeScript 6 / Vite 8 / Tailwind CSS v4
- **移动端**：Vue 3 / uni-app（`storycanvas-mobile/`）
- **AI 服务**：DeepSeek API（文本）+ Image2 API（图片）+ ComfyUI（视频）
- **部署**：Docker Compose（ghcr.io 镜像 + sidecar 热更新），宿主机 Nginx（TLS 终止 + BT-Panel）
- **生产服务器**：103.149.26.199（CentOS Stream 9），已从 PM2 直接部署迁移至 Docker
- **Docker 部署目录**：`/opt/lorevista/`

---

## 目录结构

```
StoryCanvas/
├── backend/                          # FastAPI 后端
│   ├── main.py                       # 主入口（9407 行）— 所有 API 路由 + 种子函数 + cron + updater 代理
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
│   │   ├── install.py                # 首次安装向导（数据库/Redis 测试、.env 写入、PM2 重启）
│   │   ├── video_*.py                # 视频相关服务（qa/compiler/generation/api/comfyui）
│   │   ├── alipay_f2f.py             # 支付宝当面付
│   │   └── errors.py                 # 错误类型定义
│   ├── tests/                        # pytest 测试
│   ├── workflows/                    # ComfyUI JSON 工作流模板
│   ├── manual_migrate.py             # 手动数据库迁移脚本
│   ├── manga_outputs/                # ⚠️ 用户生成的漫画图片（部署时绝对不可删除）
│   └── video_outputs/                # ⚠️ 用户生成的视频文件（部署时绝对不可删除）
│
├── .github/                          # GitHub CI/CD
│   └── workflows/
│       └── docker-images.yml         # Docker 镜像构建与推送（main/master/v* 标签触发）
│
├── *.Dockerfile                      # Docker 镜像定义
│   ├── Dockerfile.backend            # FastAPI 后端镜像（python:3.11-slim）
│   ├── Dockerfile.web                # 前端 Nginx 镜像（node:22-alpine 构建 → nginx:1.27-alpine）
│   └── Dockerfile.updater            # 热更新 sidecar 镜像（python:3.11-alpine + docker-cli）
│
├── docker-compose.yml                # Docker Compose 编排（backend/web/updater/postgres/redis）
│
├── deploy/
│   └── docker/                       # Docker 部署资源
│       ├── README.md                 # Docker 部署完整文档
│       ├── .env.example              # Docker Compose 环境变量模板
│       ├── update-lorevista.sh       # 热更新 shell 脚本（flock 锁 + 镜像拉取 + 迁移 + 健康检查 + 回滚）
│       ├── nginx/
│       │   └── default.conf          # Nginx 配置（反向代理 /api/ → backend:8000）
│       ├── runtime/
│       │   └── backend.env.example   # backend 容器环境变量模板
│       ├── systemd/
│       │   ├── lorevista-update.service  # systemd 热更新服务（可选无人值守）
│       │   └── lorevista-update.timer    # systemd 定时器（默认每 5 分钟检测）
│       └── updater/
│           └── app.py               # 热更新 sidecar HTTP 服务（FastAPI, 240 行）
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
├── storycanvas-mobile/               # Vue 3 + uni-app 移动端
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

### 生命周期管理

FastAPI 已从废弃的 `@app.on_event("startup")` 迁移为 **`lifespan` 异步上下文管理器**：

```python
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：DB 初始化 + 默认故事重命名 + 后台清理循环
    yield
    # 关闭：取消清理任务
```

启动时序：
1. 检查系统安装状态（`INSTALL_STATUS`）
2. 如已安装 → `init_db()` 初始化数据库 + 执行增量迁移
3. 默认故事重命名（"我的第一个故事" → "转生成为暗恋公主的女仆故事"）
4. 启动后台任务清理循环（每小时清理 24 小时前的过期任务）
5. 标记 `SYSTEM_READY = True`

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

所有 API 路由集中在 `main.py`（9407 行），按功能分区：
- `/api/stories/*`, `/api/chapters/*` — 作品、章节 CRUD
- `/api/framework/*` — 小说框架生成、调整
- `/api/manga/*` — 漫画生成、重绘
- `/api/screenplay/*`, `/api/shots/*` — 视频剧本、分镜
- `/api/admin/*` — 管理后台
- `/api/auth/*` — 认证
- `/api/prompt-templates/*` — 提示词模板
- `/api/billing/*` — 计费
- `/api/video/*` — 视频生成（路由在 `routers/video.py`）
- `/api/install/*` — 首次安装向导（数据库/Redis 测试、管理员创建、环境变量写入）
- `/api/admin/system/update*` — 系统热更新代理（管理员触发 → 转发到 updater sidecar）

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

## 移动端（`storycanvas-mobile/`）

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
- **部署方式**：Docker Compose（5 容器），已从 PM2 迁移
- **Docker 项目目录**：`/opt/lorevista/`
- **Compose 配置**：`/opt/lorevista/docker-compose.yml`
- **Docker 环境变量**：`/opt/lorevista/.env`
- **后端密钥配置**：`/opt/lorevista/deploy/docker/runtime/backend.env`
- **数据持久化**：`/opt/lorevista/data/manga_outputs/` + `data/video_outputs/` + Docker volumes
- **宿主机 Nginx**：BT-Panel 管理，位于 `/www/server/panel/vhost/nginx/canvas.aifusion6.cn.conf`
- **旧 PM2 项目路径**（已停用）：`/www/wwwroot/canvas.aifusion6.cn/`

### Docker 服务一览

```bash
# 生产服务器当前运行的 5 个容器
lorevista-backend-1    ghcr.io/dream619/manwen-studio/backend:v1.0.4   healthy
lorevista-web-1        ghcr.io/dream619/manwen-studio/web:v1.0.4       healthy
lorevista-updater-1    ghcr.io/dream619/manwen-studio/updater:v1.0.4   healthy
lorevista-postgres-1   postgres:16-alpine                              healthy
lorevista-redis-1      redis:7-alpine                                  healthy
```

### 镜像来源

镜像由 GitHub Actions CI/CD 自动构建并推送到 `ghcr.io/dream619/manwen-studio/`：
- `ghcr.io/dream619/manwen-studio/backend:<tag>`
- `ghcr.io/dream619/manwen-studio/web:<tag>`
- `ghcr.io/dream619/manwen-studio/updater:<tag>`

### ⚠️ 部署红线：用户生成资源绝对保护

部署时**最容易犯的致命错误**是删除或覆盖用户已生成的漫画/视频资源。

| 资源目录 | 对应路由 | 说明 |
|---------|---------|------|
| `backend/manga_outputs/` | `/static/manga` | 所有已生成的漫画图片 |
| `backend/video_outputs/` | `/static/video` | 所有已生成的视频文件 |

**硬性规则（任何部署工具/脚本都必须遵守）：**

1. **禁止 `rsync --delete`** — 绝对不能在部署时使用 `--delete` 标志，它会删掉目标机已有的用户图片和视频，但 `manga_outputs/` 不在本地仓库中，部署脚本本地没有这些文件，一旦 `--delete` 会被全部清空。
2. **禁止 `git clean -fdx`** — 会删除 `manga_outputs/` 和 `video_outputs/` 中所有未跟踪的用户资源。
3. **禁止整个目录替换** — 不要 `rm -rf backend && cp -r`；只能增量覆盖代码文件。
4. **这些目录已在 `.gitignore` 中**，本地仓库不含用户资源，无需担心误提交。

**安全做法：**
- Docker 部署下用户数据通过卷挂载保护，`manga_outputs/` 和 `video_outputs/` 映射到 `/opt/lorevista/data/`
- 禁止 `docker compose down -v`（会删除 PostgreSQL 和 Redis 数据卷）
- 更新镜像使用管理后台在线更新，或 CLI 回退方案

### Docker 更新方式

详见 [deploy/docker/DOCKER-DEPLOY-FROM-ZERO.md](deploy/docker/DOCKER-DEPLOY-FROM-ZERO.md) 第 8 章。

#### 方式一：管理后台在线更新（推荐）
1. 管理员登录 → 管理导航「系统更新」
2. 输入目标版本（如 `v1.2.3`）或留空（使用 `.env` 中的 `APP_VERSION`）
3. 确认 → 系统自动拉取镜像 → 执行迁移 → 滚动更新 backend + web

#### 方式二：SSH 命令行更新
```bash
sudo APP_DIR=/opt/lorevista /usr/bin/env bash /opt/lorevista/deploy/docker/update-lorevista.sh
```

#### 方式三：无人值守自动更新（可选）
```bash
sudo cp /opt/lorevista/deploy/docker/systemd/lorevista-update.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lorevista-update.timer
```

### 数据库迁移

```bash
# 通过 docker compose exec 执行数据库操作
cd /opt/lorevista
docker compose exec -T postgres psql -U postgres -d manga_novel -c "SQL 语句"

# 手动执行 _ensure_framework_prompt_synced
docker compose run --rm backend python -c "
from database import SessionLocal
from main import _ensure_framework_prompt_synced
_ensure_framework_prompt_synced(next(SessionLocal()))
"
```

### 全新服务器部署

在全新的服务器上从零部署 StoryCanvas。

#### 前置条件

- 服务器已安装 Docker 和 Docker Compose
- 拥有 GitHub Personal Access Token（只需 `read:packages` 权限）

#### 1. 创建 GitHub PAT

GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)

- 权限只勾 `read:packages`
- 不需要任何 repo 权限

> 若你 **fork 了仓库**，镜像地址会变更为 `ghcr.io/<你的用户名>/Manwen-Studio/*`。
> 首次部署前需要在 fork 仓库手动触发一次 Actions 构建（`Actions` → `Docker Images` → `Run workflow`），
> 等镜像就绪后才能拉取。`.env` 中的 `REGISTRY_IMAGE_PREFIX` 也要对应更改。

#### 2. 部署步骤

```bash
# SSH 登录新服务器
ssh root@新服务器IP

# 创建目录
mkdir -p /opt/lorevista/deploy/docker/runtime /opt/lorevista/data

# 登录 ghcr.io（凭证保存在 ~/.docker/config.json，updater 容器也会读取）
echo "$你的PAT" | docker login ghcr.io -u dream619 --password-stdin

# 复制部署文件（二选一）
# 方式 A：git clone
git clone https://github.com/dream619/Manwen-Studio.git /tmp/lv
cp /tmp/lv/docker-compose.yml /opt/lorevista/
cp -r /tmp/lv/deploy/docker /opt/lorevista/deploy/
rm -rf /tmp/lv

# 方式 B：本地打包上传
# 本地执行：tar czf deploy.tar.gz docker-compose.yml deploy/docker/
# scp deploy.tar.gz root@新服务器IP:/opt/lorevista/
# 服务器执行：cd /opt/lorevista && tar xzf deploy.tar.gz
```

#### 3. 配置环境变量

```bash
cd /opt/lorevista
cp deploy/docker/.env.example .env
cp deploy/docker/runtime/backend.env.example deploy/docker/runtime/backend.env
```

修改 `.env` 关键项：

```ini
REGISTRY_IMAGE_PREFIX=ghcr.io/dream619/manwen-studio
APP_VERSION=v1.0.4
POSTGRES_PASSWORD=设置强密码
DATABASE_URL=postgresql://postgres:密码@postgres:5432/manga_novel
SYSTEM_INSTALLED=false           # 新服务器首次 = false
UPDATER_TOKEN=openssl rand -hex 32 的值
```

#### 4. 启动

```bash
cd /opt/lorevista
docker compose --env-file .env up -d
```

Docker 自动拉取 5 个镜像（3 个 ghcr.io + postgres + redis from Docker Hub）。

#### 5. 验证

```bash
docker compose ps               # 5 个容器全部 healthy
curl http://localhost:8080/api/health  # {"status":"ok"}
```

#### 6. 配置宿主 Nginx（TLS 终止）

参考 `deploy/docker/nginx/default.conf`，反向代理到 `127.0.0.1:8080`。

#### 7. 首次访问

浏览器打开域名 → 安装向导 → 创建管理员账号即可使用。

#### ghcr.io 凭证过期处理

ghcr.io 的 token 可能过期，导致 `docker compose pull` 失败：

```bash
# 重新登录
echo "$新PAT" | docker login ghcr.io -u dream619 --password-stdin

# 验证
docker compose pull
```

建议在 CI/CD 中定期刷新凭证，或使用机器人账户的只读 token。

---

## Docker 部署

### 架构概览

```
┌──────────────────────────────┐
│       Host Nginx (TLS)       │
│  proxy_pass :8080            │
└──────────┬───────────────────┘
           │
┌──────────▼───────────────────┐
│    docker-compose.yml        │
│  ┌────────┐ ┌──────┐ ┌────┐ │
│  │  web   │ │be-  │ │up- │ │
│  │(Nginx  │ │ckend│ │datr│ │
│  │ :80)   │ │:8000│ │:809│ │
│  └───┬────┘ └──┬───┘ └─┬──┘ │
│      │/api/*───┘       │    │
│      │/static/*────────┘     │
│      │       ┌──────┐       │
│  ┌───▼───┐ ┌─▼────┐ │       │
│  │postgres│ │redis │ │       │
│  └───────┘ └──────┘ │       │
│  updater mounts:     │       │
│  /var/run/docker.sock │       │
│  /opt/lorevista      │       │
└──────────────────────────────┘
```

### Dockerfile 定义

| 文件 | 基础镜像 | 作用 |
|------|---------|------|
| `Dockerfile.backend` | `python:3.11-slim` | FastAPI 后端，暴露 8000，HEALTHCHECK `/api/health` |
| `Dockerfile.web` | 两阶段：`node:22-alpine` 构建 → `nginx:1.27-alpine` 运行 | React 静态文件，Nginx 反向代理 `/api/` |
| `Dockerfile.updater` | `python:3.11-alpine` | 热更新 sidecar，暴露 8090，挂载 Docker socket |

### 服务器初始设置

```bash
# 创建运行目录
sudo mkdir -p /opt/lorevista/deploy/docker/runtime /opt/lorevista/data
sudo cp docker-compose.yml /opt/lorevista/
sudo cp -r deploy/docker /opt/lorevista/deploy/
sudo cp deploy/docker/.env.example /opt/lorevista/.env
sudo cp deploy/docker/runtime/backend.env.example /opt/lorevista/deploy/docker/runtime/backend.env

# 登录 ghcr.io（只读 token）
echo "$READ_ONLY_REGISTRY_TOKEN" | docker login ghcr.io -u "$REGISTRY_USER" --password-stdin

# 启动
cd /opt/lorevista
docker compose --env-file .env up -d
```

### 服务网络

- **web**: 暴露端口到宿主机（默认 `127.0.0.1:8080`），由宿主 Nginx 做 TLS 终止
- **backend**: 仅 Docker 内部网络可达，web 通过 `http://backend:8000` 访问
- **updater**: 仅 Docker 内部网络可达，backend 通过 `http://updater:8090` 调用
- **postgres/redis**: 不对外暴露端口

### Docker Compose 编排（5 个服务）

| 服务 | 镜像来源 | 说明 |
|------|---------|------|
| `backend` | `ghcr.io/dream619/manwen-studio/backend:<tag>` | 后端应用，挂载 manga_outputs/video_outputs volume |
| `web` | `ghcr.io/dream619/manwen-studio/web:<tag>` | Nginx 静态服务 |
| `updater` | `ghcr.io/dream619/manwen-studio/updater:<tag>` | 热更新 sidecar，挂载 docker.sock |
| `postgres` | `postgres:16-alpine` | 数据库，持久化 volume |
| `redis` | `redis:7-alpine` | 缓存，AOF 持久化 volume |

---

## 热更新流程

### 设计原则

**"业务后端不接触 Docker socket"** — 用一个专门的 `updater` sidecar 容器执行所有 Docker/Compose 操作。

### 触发链路

```
管理员登录 → 管理后台 "系统更新" 页面
         ↓
POST /api/admin/system/update { target_version? }
         ↓
backend 验证管理员身份（_require_admin）
         ↓
POST http://updater:8090/update { target_version }
    Headers: X-Updater-Token = UPDATER_TOKEN
```

### Updater Sidecar（`deploy/docker/updater/app.py`）

| 端点 | 方法 | 作用 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/status` | GET | 查询当前更新状态（含日志尾部） |
| `/update` | POST | 触发更新（指定版本或按 .env 中的 APP_VERSION） |

状态管理：`update-state.json` 持久化，支持防抖（stale 检测）、并发锁。

### 热更新执行流程

```
┌─ 1. 更新 APP_VERSION（如指定目标版本）
│   → 修改 /opt/lorevista/.env 中的 APP_VERSION=
│   → 创建 .env.bak.<timestamp> 备份
│
├─ 2. 异步启动 update-lorevista.sh
│   → flock 文件锁（/var/lock/lorevista-update.lock）
│   → 防止并发更新
│
├─ 3. 记录当前运行镜像 ID（backend / web）
│
├─ 4. docker compose pull（拉取最新镜像）
│
├─ 5. 检查镜像 ID 是否变化
│   └─ 无变化 → 退出（跳过不必要的更新）
│
├─ 6. 运行数据库迁移
│   → docker compose run --rm -e RUN_STARTUP_MIGRATIONS=true backend \
│       python -c "from database import init_db; init_db()"
│   → timeout 180 秒
│
├─ 7. 启动 backend 新容器
│   → docker compose up -d --no-deps backend
│   → 等待 /api/health 响应（timeout 90 秒，每 3 秒轮询）
│   └─ 失败 → 回滚
│
├─ 8. 启动 web 新容器
│   → docker compose up -d --no-deps web
│   → 再次等待健康检查
│   └─ 失败 → 回滚
│
├─ 9. docker image prune -f（清理 7 天前的旧镜像）
│
└─ ✅ 完成
```

### 回滚机制

任何健康检查失败或脚本执行错误时：

```bash
# 将之前记录的镜像 ID 重新 tag 回原来的引用
docker tag $BACKEND_PREVIOUS_IMAGE_ID $BACKEND_IMAGE_REF
docker tag $WEB_PREVIOUS_IMAGE_ID $WEB_IMAGE_REF
# 重新启动旧版本
docker compose up -d backend web
```

### 管理后台实时日志

```
前端每隔 3 秒轮询 GET /api/admin/system/update/status
  → backend 代理到 GET http://updater:8090/status
  → 返回 sanitized 更新状态 + 最近 120 行日志
  → 日志在传输过程中做脱敏（密码/TOKEN/KEY → ***）
  → 前端渲染在黑色 <pre> 终端风格区域
```

### CLI 回退方案

```bash
sudo APP_DIR=/opt/lorevista /usr/bin/env bash /opt/lorevista/deploy/docker/update-lorevista.sh
```

### 无人值守自动更新（可选）

```bash
sudo cp /opt/lorevista/deploy/docker/systemd/lorevista-update.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lorevista-update.timer
```

- `lorevista-update.timer`：开机 2 分钟后启动，之后每 5 分钟检测一次
- `lorevista-update.service`：oneshot 类型，调用 `update-lorevista.sh`

---

## CI/CD 流水线

定义在 `.github/workflows/docker-images.yml`，在 push 到 `main`/`master` 分支或 `v*` 标签时触发。

| 阶段 | 操作 |
|------|------|
| **代码检查** | `py_compile` 语法检查 + `pytest` 运行测试 |
| **前端构建** | `npm ci` + `npm run build` |
| **Docker 构建** | Buildx 构建 3 个镜像（backend/web/updater） |
| **镜像推送** | 推送到 `ghcr.io/<repo>/` |

镜像标签策略：
- 普通分支推送：`sha-<commit12位>` + `stable`
- 标签推送（`v*`）：`sha-<commit12位>` + `<标签名>`

---

## 首次安装向导

`backend/services/install.py` 提供了完整的首次部署安装流程：

| API 端点 | 作用 |
|---------|------|
| `GET /api/install/status` | 检测系统是否已安装 |
| `POST /api/install/test-database` | 测试 PostgreSQL 连接（支持 SSL 模式配置） |
| `POST /api/install/test-redis` | 测试 Redis 连接（支持 TLS/密码认证） |
| `POST /api/install/complete` | 写入 .env（数据库/Redis URL + 管理员账号），初始化数据库种子 |
| `POST /api/install/restart` | 重启后端进程（PM2 / 自定义命令 / 开发模式自重启） |

重启策略优先级：
1. `INSTALL_RESTART_COMMAND` 环境变量 → 执行自定义命令
2. `INSTALL_PM2_PROCESS_NAME` 或 PM2 检测 → `pm2 reload --update-env`
3. 开发模式（Windows 或 `INSTALL_ALLOW_DEV_RESTART=true`）→ 分离进程自重启

前端页面：`frontend/src/components/InstallWizardPage.tsx`，三步引导配置。

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
`storycanvas-mobile/` 使用 Vue 3 + uni-app 而非 React。修改 mobile 时要切换到对应工具链（npm install + manifest.json）。

### 7. 前端 SSO（无 react-router）
添加新页面时需要三步：① 在 `api.ts` 定义 API 函数和类型 ② 创建组件文件 ③ 在 `App.tsx` 添加 `RouteKey` + import + 条件渲染

### 8. Tailwind v4 的特殊性
- 无 `tailwind.config.js`，样式定制直接在 `index.css` 中
- 使用 `@import "tailwindcss"` 而非旧式 `@tailwind` 指令
- 生产构建中 Tailwind 会 tree-shake 未使用的类

### 9. ⚠️ 部署时误删用户图片/视频（致命）
`manga_outputs/` 和 `video_outputs/` 在 `.gitignore` 中，本地仓库没有这些文件。如果部署时使用 `rsync --delete`、`git clean -fdx`、或用 `rm -rf backend` 再替换，会永久删除所有用户的漫画图片和视频。**永远只做增量更新，不做全量替换。**

### 10. Docker 卷挂载路径一致性
`docker-compose.yml` 中用 `${LOREVISTA_DATA_DIR:-./deploy/docker/data}` 作为默认数据目录。确保宿主机上该路径存在，否则 Docker 会自动创建目录但权限可能不正确。生产部署建议使用绝对路径。

### 11. Updater 端口冲突
updater 监听 8090 端口，仅在 Docker 内部网络可达。如果宿主机有服务占用 8090，不会冲突（Docker 网络隔离），但如果宿主机有 iptables 规则拦截内部网络通信，updater 会无法被 backend 访问。

### 12. ghcr.io 镜像拉取凭证
updater 容器挂载了 `/root/.docker:ro` 用于拉取私有镜像。如果镜像仓库凭证过期，更新操作会在 `docker compose pull` 阶段静默失败。建议在 CI/CD 中定期刷新凭证，或使用机器人账户的只读 token。

### 13. PM2 → Docker 迁移时数据库密码不一致
Docker PostgreSQL 容器首次启动时通过环境变量 `POSTGRES_PASSWORD` 设置密码。后期修改 `.env` 中的密码**不会自动同步到运行中的 PostgreSQL**。迁移时需通过 `docker compose exec -T postgres psql -U postgres -c "ALTER USER postgres WITH PASSWORD '新密码';"` 手动修改，或删除 Docker volume 重建。

### 14. 宿主机与 Docker 的 PostgreSQL 端口冲突
宿主机本身可能运行 PostgreSQL（监听 `127.0.0.1:5432`）。Docker compose 的 postgres 容器默认不暴露端口到宿主机，但通过 `docker compose exec` 访问时不受影响。从宿主机执行 `psql -h 127.0.0.1` 时连接的是**宿主机数据库**而非 Docker 数据库，注意区分。

### 15. ⚠️ AI 模型配置必须从数据库注入（关键）
项目使用三个 AI 服务，每个都有全局变量。**必须在调用任何 AI 函数前通过配置函数注入数据库配置。**

| 服务 | 全局变量 | 配置函数 | 错误症状 |
|------|---------|---------|---------|
| **DeepSeek** | `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL` | `deepseek_service.configure_runtime()` | `DeepSeek API 地址未配置` |
| **Image2** | `IMAGE_API_BASE_URL`, `IMAGE_API_KEY`, `IMAGE_MODEL` | `image2_service.configure_runtime()` | `图片 API 地址未配置` |
| **Video API** | `_runtime_base_url`, `_runtime_api_key`, `_runtime_model` | `video_api_service.configure()` | `视频 API 地址未配置` |

**Router 层配置函数**（必须在调用对应服务前调用）：
```python
# DeepSeek - 已集成到 _user_deepseek_api_key() 中，无需额外调用
deepseek_api_key = _user_deepseek_api_key(request, db)

# Image2 - 必须在调用图片生成函数前调用
_configure_image_service_from_db(request, db)

# Video API - 必须在调用视频生成函数前调用
_configure_video_service_from_db(request, db)
```

**⚠️ 绝对不能只调用 `_user_xxx_api_key()` 就直接调用 AI 生成函数！必须同时调用对应的 `_configure_xxx_service_from_db()`。**

**已知受影响的端点**：
- `api_regenerate_shot_storyboard`（已修复）
- 所有调用 `image2_service.generate_*` 的端点
- 所有调用 `video_api_service.*` 的端点

**如果新增调用 AI 生成的端点，必须在调用前配置对应的服务。**

### 16. ⚠️ 工作台按钮绑定规范（反复出问题，必须遵守）

工作台（VideoCardWorkbench）的按钮绑定涉及三层数据流，任何一层断裂都会导致按钮点击无反应。

**三层数据流**：
```
VideoCardWorkbench（按钮 onClick）
  → ChapterVideoWorkflowPanel（handler 变量赋值）
    → VideoStoryboardLayout（handler 实现 + API 调用）
      → 后端 API 端点
```

**修改工作台按钮时必须检查的清单**：

| 检查项 | 说明 |
|--------|------|
| ✅ `VideoCardWorkbench.tsx` 按钮有 `onClick` | 每个按钮必须绑定到 handler 函数 |
| ✅ handler 函数有正确的保护逻辑 | 检查 `currentResource`、`state.busy` 等 |
| ✅ `ChapterVideoWorkflowPanel.tsx` 每种 type 都有 handler 赋值 | character/storyboard/video 三种类型分别处理 |
| ✅ handler 不是空 `async () => {}` 空壳 | 空壳函数需要实现或明确标注为 TODO |
| ✅ `VideoStoryboardLayout.tsx` handler 实现正确 | 有正确的 API 调用和错误处理 |
| ✅ 后端 API 端点存在且可访问 | 检查路由注册和权限验证 |
| ✅ 所有渲染分支都有必要的 DOM 元素 | 如 `<input type="file">` 在所有 modal 类型中都必须存在 |

**已知空壳 handler（尚未实现）**：
- 无（所有 handler 已实现）

**已实现的 handler**：
- `onRegenerate`：character 类型调用 `regenerateVideoAsset`，storyboard/video 类型调用对应的 regenerate 端点
- `onUploadReplace`：character 类型调用 `replaceVideoAsset`，storyboard 类型调用 `uploadShotStoryboard`，video 类型调用 `uploadShotVideo`
- `onRedraw`：character 类型调用 `regenerateVideoAsset`（支持 mask），storyboard/video 类型调用对应的 regenerate 端点

**已知陷阱**：
- 视频类型 modal（`type === 'video'`）在 line 366 提前 `return`，后续添加的 DOM 元素不会被渲染
- `workflowRunning` 为 `true` 时会禁用大部分按钮，但重置按钮不应受此限制
- `fileInputRef.current?.click()` 需要 `<input ref={fileInputRef}>` 在同一渲染分支中存在

### 17. ⚠️ DeepSeek JSON 截断修复陷阱（反复出问题）

DeepSeek 返回的 JSON 可能被 `max_tokens` 截断，触发 `_repair_truncated_json`（`backend/services/deepseek.py:2792`）。该函数有两个容易出错的点：

**陷阱 1：括号闭合顺序必须是 LIFO**
- 不要用 `brace_depth`/`bracket_depth` 两个独立计数器
- 必须用 **栈（list）** 追踪打开顺序，`reversed(stack)` 按 LIFO 闭合
- 反例：`{[{...` 用计数器会输出 `}}]`，正确应为 `}]}`

**陷阱 2：键名截断需要补 `:null`**
- 值字符串截断（`"value_`）：补 `"` 即修复
- 键名截断（`"key_`）：补 `"` 后得到孤儿键 `"key_"`，缺少 `: value`
- 修复后必须额外做：从右向左找 `"` 紧接 `}])` 的位置，插入 `:null`

**修改任何修复逻辑时必须检查清单**：
| 检查项 | 说明 |
|--------|------|
| ✅ 栈追踪代替计数器 | 所有括号追踪必须 LIFO，禁止计数器 |
| ✅ `json.loads()` 最终验证 | 任何修复路径最后都要通过 `json.loads()` 验证 |
| ✅ 同时覆盖两条链路 | `_parse_lite_chunk`（轻量拆镜）和 `_parse_full_chunk`（完整拆镜）共用 `_repair_truncated_json` |
| ✅ 新增修复后自测 | 至少覆盖 8 个场景：值截断、键名截断、嵌套键名截断、数组内截断、多字段截断、有效JSON不变、空内容、仅空白 |

---



## ⚠️ 已修复 Bug 记录（2026-06-12 批次）

### Bug 1: 故事版重生成路由漏传 reference_asset_ids

- **症状**：选择引用角色资产图生成故事版时，日志显示 `ref_asset_ids=None effective=[]`，走的纯文本 generations 而非图生图模式
- **根因**：`api_regenerate_shot_storyboard` 未把请求体中的 `reference_asset_ids` 传给 `regenerate_shot_storyboard()` 函数
- **修复**：在 `backend/routers/video.py:6221` 加上 `ref_asset_ids = body.reference_asset_ids or None` 并透传给服务层
- **测试**：`test_regenerate_shot_storyboard_passes_reference_asset_ids`
- **文件**：`backend/routers/video.py`

### Bug 2: `_resolve_ref_image_paths` 不认 HTTP/OSS URL

- **症状**：`ref_asset_ids` 已传到服务层，但日志显示 `resolved paths=None`，走 generations
- **根因**：`_resolve_ref_image_paths()` 只检查本地文件路径（`/static/video/`、绝对路径等），如果 `VideoAsset.file_path` 是 OSS URL 则跳过
- **修复**：在 `backend/services/video_chapter_pipeline.py:907` 复用 `resolve_reference_input(fp, "video")` 优先解析，支持 HTTP URL 透传
- **测试**：`test_resolve_ref_image_paths_accepts_http_urls`
- **文件**：`backend/services/video_chapter_pipeline.py`

### Bug 3: 视频链路错误地把角色资产 ID 当成故事版镜头 ID

- **症状**：`reference_asset_ids=[86, 194]` 中角色资产 `86` 被误当作 `ChapterVideoShot.id` 去查故事版
- **根因**：`regenerate_shot_video()` 中 `shot_ids_in_refs = [rid for rid in effective_ref_ids if rid > 0]` 把 **所有** 正数 ID 都拿去查故事版表，角色参考图被混乱
- **修复**：改成了只有 `shot.id in effective_ref_ids` 或 `-1` sentinel 时才使用当前镜头故事版；其余 ID 保留给角色图解析
- **测试**：`test_regenerate_shot_video_keeps_character_refs_separate_from_storyboard_refs`
- **文件**：`backend/services/video_chapter_pipeline.py`

### Bug 4: 视频链路参考图路径不一致（本地 vs 远程）

- **症状**：日志中 storyboard `[local] .media_cache`、character `[remote] OSS`、style `[local]`，三种路径格式混用
- **根因**：故事版/风格参考图使用 `ensure_local_media_path()`（主动下载到 `.media_cache`），角色参考图使用 `resolve_reference_input()`（保持远程 URL）
- **修复**：视频链路全部改为优先 `resolve_reference_input()` 保持远程 URL，只有拿不到远程时才回退本地路径
- **测试**：`test_regenerate_shot_video_prefers_remote_urls_for_all_reference_images`
- **文件**：`backend/services/video_chapter_pipeline.py`

### Bug 5: 视频提交日志未标明参考图用途

- **症状**：`[video_submit] 参考图列表` 只输出编号和路径，看不出每张图是 storyboard/character/style
- **修复**：日志改为 `[video_submit]   参考图 1 [storyboard][remote]: ...` 格式，包含用途和来源类型
- **测试**：`test_regenerate_shot_storyboard_logs_reference_inputs`、`test_regenerate_shot_video_logs_reference_roles`
- **文件**：`backend/services/video_chapter_pipeline.py`

### Bug 6: 后台风格预设配置页入口丢失

- **症状**：管理后台没有"风格预设"菜单项，页面不可访问
- **根因**：`StylePresetManager` 组件存在，但 `App.tsx` 的 `RouteKey`、`ADMIN_NAV` 和渲染分支都没有接上
- **修复**：新增 `style-presets` 路由 key、菜单项和页面渲染分支
- **文件**：`frontend/src/App.tsx`

### Bug 7 (15秒迁移): 故事版导演提示词仍输出10秒分镜

- **症状**：镜头拆分已改为15秒，但故事版提示词仍输出 `8.5-10s` 等10秒固定分段内容，不符合15秒要求
- **根因**：`STORYBOARD_DIRECTOR_SYSTEM_PROMPT` 中硬编码了"10秒镜头约束"、固定6格分镜（0-1.5s/1.5-3s/3-5s/5-7s/7-8.5s/8.5-10s），AI 直接套用旧模板
- **修复**：
  - 将"10秒镜头约束"改为"15秒镜头容量建模约束"，要求 AI 动态决定分镜段落数量，不再固定6段
  - 核心故事板区从硬编码6格改为动态段落（示例0-4.2s/4.2-9.5s/9.5-15s，允许变化）
  - 项目栏改为 `{duration_seconds}` 参数化
  - `build_storyboard_director_messages` 增加 `duration_seconds` 参数，统一传入15
  - 所有调用方传递 `duration_seconds=15` 或从 `shot_data` 读取
  - 清理残留的旧 `VIDEO_PROMPT_TEMPLATE`（0-3/3-7/7-10 模板）改为15秒动态描述
  - `concat_chapter_videos` 中 `duration_seconds=10` 改为15
- **测试**：`test_storyboard_director_prompt_no_longer_uses_10s_segments`
- **文件**：`backend/services/video_chapter_prompts.py`、`backend/services/deepseek.py`、`backend/services/video_chapter_pipeline.py`

### Bug 8: 分析提示词后 storyboard prompt 与 video prompt 场景不一致

- **症状**：点击"分析提示词"后，storyboard prompt 描述的是完整场景（如少年少女在天台望月），但 video prompt 变成只有月亮移动的空镜
- **根因**：`reanalyze_shot_prompts` 中两次独立 AI 调用互不感知。`generate_shot_video_prompt_ai` 只基于镜头结构化字段生成，不知道同一镜头的 storyboard prompt 写了什么内容，导致 AI 自行编造不同的场景描述
- **修复**：在 `SHOT_VIDEO_USER_TEMPLATE` 增加 `storyboard_prompt` 字段，`generate_shot_video_prompt_ai` 增加 `storyboard_prompt` 参数，`reanalyze_shot_prompts` 和 `regenerate_shot_video` 在生成 video prompt 时把同一镜头的 storyboard prompt 传入作为上下文
- **测试**：`test_shot_video_user_prompt_includes_storyboard_prompt`
- **文件**：`backend/services/video_chapter_prompts.py`、`backend/services/deepseek.py`、`backend/services/video_chapter_pipeline.py`

### Bug 8: 风格预设图片上传不走 OSS

- **症状**：日志显示 `风格预设图片未上传到 OSS（未配置或上传失败）`
- **根因**：`upload_style_preset_image` 未调用 `_configure_oss_from_db(db)` 读取数据库配置注入运行时，`oss_service.is_enabled()` 返回 False
- **修复**：在 OSS 上传前调用 `_configure_oss_from_db(db)` 注入配置
- **文件**：`backend/routers/video.py`

### Bug 9: DeepSeek JSON 被截断导致"JSON 解析错误"

- **症状**：轻量拆镜/完整拆镜时出现 `ValueError: 轻量拆镜失败：JSON 解析错误`，日志中原始响应以 `"key_` 等不完整的字段名结尾
- **根因**：`_repair_truncated_json` 有两个问题：
  1. 使用计数器追踪括号深度（`brace_depth`/`bracket_depth`），嵌套结构闭合顺序错误（如 `}}]` 而非 `}]}`）
  2. 只处理了**值字符串**被截断（补 `"`），未处理**键名**被截断（补 `"` 后得到孤儿键 `"key_"` 缺少 `: value`）
- **修复**：
  1. 计数器 → 栈追踪（LIFO），修复嵌套结构的正确闭合顺序
  2. 基础修复后若 `json.loads` 失败，从右向左查找 `"` 紧接 `}])` 的位置，插入 `:null`
- **测试**：8 个独立验证用例全部通过，28 个 pipeline 测试无回归
- **文件**：`backend/services/deepseek.py` — `_repair_truncated_json` 函数
- **⚠️ 修改此函数时必须检查**：
  - 新加的闭合逻辑必须用栈追踪，不能用计数器
  - 任何修复路径最后都必须通过 `json.loads()` 验证
  - 同时覆盖 `_parse_lite_chunk` 和 `_parse_full_chunk` 两条链路（共用同一修复函数）

---

## Sisyphus Agent 工作文件

`.sisyphus/` 目录包含部署记录和修复报告：
- `deployment-summary.md` — 部署命令历史
- `fix-complete-report.md` — bug 修复记录
- `plans/` — 实施计划
- `evidence/` — 验证证据截图/日志
