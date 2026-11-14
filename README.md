# StoryCanvas（曼文工坊）

> AI 驱动的**小说创作 → 分镜拆解 → 漫画插画 → 短视频**一站式创作平台。
>
> 从一句话灵感开始，AI 陪你写完整本小说，自动拆分镜、生成分镜图，再串成视频镜头。

<p align="left">
  <img alt="license" src="https://img.shields.io/badge/license-Apache%202.0-blue" />
  <img alt="python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB" />
  <img alt="react" src="https://img.shields.io/badge/React-19-61DAFB" />
  <img alt="fastapi" src="https://img.shields.io/badge/FastAPI-0.115%2B-009688" />
</p>

---

## 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [配置 API Key](#配置-api-key)
- [项目结构](#项目结构)
- [安全说明](#安全说明)
- [常见问题](#常见问题)
- [贡献](#贡献)
- [License](#license)

---

## 功能特性

### 文字创作
- **对话式小说创作** —— 基于 DeepSeek，通过自然语言对话推进剧情、扩写、润色、续写
- **框架与大纲管理** —— 世界观、人物卡、章节大纲、标签体系统一管理
- **风格参考** —— 上传参考文本，让 AI 对齐文风
- **连续性保障** —— 自动摘要前文，避免章节之间设定冲突

### 视觉化
- **自动分镜** —— AI 将小说正文拆解为镜头脚本（景别、构图、情绪、台词）
- **分镜可编辑** —— 逐条修改镜头描述，支持单张重新生成
- **角色卡固化** —— 锁定人物外貌描述，保证多张图形象一致
- **多张垫图** —— 支持多参考图输入，提升生成稳定性

### 视频（进阶）
- **剧本 → 分镜 → 镜头 → 视频** 全链路
- 支持云端视频 API，也支持**本地 ComfyUI** 工作流（`VIDEO_PROVIDER=comfyui`）
- 镜头级资产管理与重生成

### 平台能力
- **Agent 面板** —— 内置工具调用式 AI 助手，可直接读写创作内容
- **故事库** —— 多作品管理、封面与元信息
- **授权与配额** —— 可选的授权码服务（`auth/`）与用量点数体系
- **实时进度** —— 长任务流式反馈，可中断

---

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 19 · TypeScript · Vite 8 · TailwindCSS 4 |
| 后端 | Python 3.10+ · FastAPI · SQLAlchemy · Alembic |
| 数据库 | PostgreSQL 16（也可用 SQLite） |
| AI | DeepSeek（文本） · Image2（图像） · 可插拔视频 Provider |
| 授权服务 | PHP 8 · MySQL（可选，独立部署） |

---

## 快速开始

### 前置要求

- **Python 3.10+**
- **Node.js 18+**
- **PostgreSQL 16**（或使用 SQLite，见下文）

### 1. 克隆仓库

```bash
git clone https://github.com/dream619/Manwen-Studio.git
cd Manwen-Studio
```

### 2. 准备数据库

```sql
CREATE DATABASE manga_novel;
```

默认连接串：

```text
postgresql://postgres:postgres@localhost:5432/manga_novel
```

> 若使用 SQLite，把 `.env` 中的 `DATABASE_URL` 改为
> `sqlite:///./storycanvas.db` 即可，无需安装 PostgreSQL。

### 3. 配置环境变量

```bash
cd backend
cp .env.example .env      # Windows: copy .env.example .env
```

编辑 `backend/.env`：

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/manga_novel
HOST=127.0.0.1
PORT=8000
```

> ⚠️ **API Key 不要写进 `.env` 提交到仓库。** 推荐在网页端「API Key」设置里填写，
> 密钥只保存在浏览器本地存储中。详见 [安全说明](#安全说明)。

### 4. 安装依赖

**方式一（推荐，Windows 用户）**：双击根目录 `install.bat`，自动检查环境并安装前后端依赖。

**方式二（手动）**：

```bash
# 后端
cd backend && pip install -r requirements.txt && cd ..

# 前端
cd frontend && npm install && cd ..
```

### 5. 启动

**方式一**：双击根目录 `start.bat`（自动启动前后端并打开浏览器）。

**方式二**：两个终端分别启动：

```bash
# 终端 1
cd backend && python main.py

# 终端 2
cd frontend && npm run dev
```

访问 <http://localhost:5173>

---

## 配置 API Key

打开网页后点击右上角 **API Key**，分别配置：

| Key | 用途 | 获取地址 |
|---|---|---|
| **DeepSeek API Key** | 小说生成、分镜拆解、Agent 对话 | <https://platform.deepseek.com/> |
| **Image2 API Key** | 漫画 / 插画生成 | <https://api.xbyjs.top/console/token> |

填入后保存即可，无需重启服务。

---

## 项目结构

```text
Manwen-Studio/
├── backend/                 # FastAPI 后端
│   ├── main.py              # 应用入口与主路由
│   ├── models.py            # SQLAlchemy 数据模型
│   ├── database.py          # 数据库连接与会话
│   ├── routers/             # 路由模块（agent / video）
│   ├── services/            # 业务服务（AI、分镜、图像、视频）
│   ├── workflows/           # ComfyUI 工作流模板
│   ├── tests/               # pytest 测试套件
│   └── .env.example         # 环境变量模板
├── frontend/                # React + TypeScript 前端
│   └── src/
│       ├── components/      # UI 组件
│       ├── prompts/         # 提示词工程模块
│       ├── api.ts           # 后端接口封装
│       └── genStore.ts      # 生成任务状态管理
├── auth/                    # 独立授权码服务（PHP，可选，独立仓库）
├── docs/                    # 设计文档与规格说明
├── install.bat / start.bat  # Windows 一键安装 / 启动
└── LICENSE
```

---

## 安全说明

本项目在开源前已完成密钥扫描，仓库中**不含任何真实凭据**。部署时请注意：

- **不要提交 `.env`** —— 已在 `.gitignore` 中屏蔽，包含 `*.env.bak*` 等备份文件变体
- **API Key 优先走前端输入** —— 后端 `.env` 中的 Key 仅作为兜底
- **修改默认配置** —— PostgreSQL 默认 `postgres/postgres` 仅用于本地开发，生产环境务必更改
- **授权服务** —— `auth/` 下默认管理员为 `admin / admin123`，**首次登录必须修改**
- **公网部署** —— 建议置于 Nginx 之后并启用 HTTPS，同时设置 `API_TOKEN` 与严格的 `CORS_ORIGINS`

发现安全问题请参阅 [SECURITY.md](SECURITY.md)，请勿直接开公开 Issue。

---

## 常见问题

<details>
<summary><b>生成图片失败 / 超时？</b></summary>

确认 Image2 Key 有效且余额充足；单张生成通常需要 20–60 秒，超时时间可在 `.env` 中调大 `MAX_UPLOAD_BYTES` 之外的请求超时配置。
</details>

<details>
<summary><b>不想装 PostgreSQL？</b></summary>

使用 SQLite：把 `DATABASE_URL` 设为 `sqlite:///./storycanvas.db`，首次启动会自动建表。
</details>

<details>
<summary><b>视频生成怎么配置？</b></summary>

默认走云端视频 API（复用 Image2 的 Key）。如需本地生成，安装 ComfyUI 后设置：

```env
VIDEO_PROVIDER=comfyui
COMFYUI_BASE_URL=http://127.0.0.1:8188
```
</details>

<details>
<summary><b>端口被占用？</b></summary>

改 `backend/.env` 的 `PORT`；前端端口改 `frontend/vite.config.ts` 中的 `server.port`。
</details>

---

## 贡献

欢迎 Issue 与 PR。提交前请确保：

1. 不包含任何密钥、令牌、真实域名或服务器信息
2. 新增代码附带相应测试（`cd backend && pytest`）
3. 遵循现有代码风格

---

## 效果

<img width="1437" alt="创作工作台" src="https://github.com/user-attachments/assets/292cd965-1bbe-4ac2-be2c-e577d1c1b545" />
<img width="2477" alt="分镜与漫画" src="https://github.com/user-attachments/assets/2e394e4c-f0c0-4af6-ae8d-63713d111cde" />
<img width="2478" alt="视频工作流" src="https://github.com/user-attachments/assets/5e4a6aa5-9f7f-49a2-8e47-65a5c2ad9dec" />

---

## License

本项目采用 [Apache License 2.0](LICENSE) 授权，Copyright 2026 libohan-ha。

你可以自由地使用、修改、分发本项目（包括商业用途），但需遵守以下条件：

- 保留版权声明、许可声明与 [`NOTICE`](NOTICE) 文件
- 修改过的文件需标注「已修改」
- 若发起专利诉讼指控本项目侵权，你获得的相关专利授权将自动终止

> Apache-2.0 相比 MIT 额外提供了**明确的专利授权**与**商标保护**条款，
> 更适合可能被企业采用的项目。详见 [LICENSE](LICENSE) 全文。
