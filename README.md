# StoryCanvas

AI 驱动的创作平台，支持小说创作、自动分镜、漫画图片生成和视频制作。通过对话引导 AI 创作小说，自动拆分分镜脚本，生成漫画图片并支持视频创作工作流。



## 功能

- **AI 小说创作**：基于 DeepSeek API，通过对话交互引导创作。
- **自动分镜**：AI 将小说内容拆分为漫画分镜脚本，支持手动编辑。
- **漫画生成**：基于 Image2 API 生成漫画图片，支持逐张重新生成。
- **视频制作**：剧本生成、分镜任务、ComfyUI 视频工作流。
- **角色卡系统**：固定角色外貌描述，帮助保持人物形象一致。
- **多张垫图**：支持上传多张参考图，让生成结果更稳定。
- **实时进度**：对话、分镜、漫画生成、视频制作都有进度反馈。
- **AI Agent 助手**：智能对话辅助创作全流程。

## 技术栈

- **后端**：Python / FastAPI / SQLAlchemy / PostgreSQL
- **前端**：React / TypeScript / Vite / TailwindCSS
- **移动端**：Vue 3 / uni-app
- **AI**：DeepSeek API + Image2 API + ComfyUI
- **部署**：Docker Compose（ghcr.io 镜像 + CI/CD 自动构建 + BT-Panel Nginx TLS 终止）

---
## Docker 部署（生产环境）

本项目使用 Docker Compose 部署生产环境，所有镜像由 GitHub Actions CI/CD 自动构建并推送到 GitHub Container Registry（ghcr.io）。

### 镜像来源

```text
ghcr.io/dream619/manwen-studio/backend:<tag>   # FastAPI 后端
ghcr.io/dream619/manwen-studio/web:<tag>       # Nginx 静态服务
ghcr.io/dream619/manwen-studio/updater:<tag>   # 热更新 sidecar
```

推送 `main` 分支或 `v*` 标签即可触发 CI 自动构建。

### 全新服务器部署流程

#### 1. 前置条件

- 服务器已安装 Docker 和 Docker Compose
- 拥有 GitHub Personal Access Token（**只需 `read:packages` 权限**，无需 repo 权限）

#### 2. 创建 GitHub PAT（仅首次）

GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)

创建 Token：
- 权限只勾 `read:packages`
- 复制 Token 值备用

> 若你** fork 了仓库**，镜像地址会变成 `ghcr.io/<你的用户名>/Manwen-Studio/*`，需要先在 fork 仓库手动触发一次 Actions 构建，镜像就绪后才能拉取。

#### 3. 登录 ghcr.io 并部署

```bash
# 设置变量（按需修改）
SERVER_IP="你的服务器IP"
PAT="你的GitHubPAT"

# SSH 登录服务器
ssh root@$SERVER_IP

# 创建项目目录
mkdir -p /opt/lorevista/deploy/docker/runtime /opt/lorevista/data

# 登录 ghcr.io（只需一次，凭证会保存在 ~/.docker/config.json）
echo "$PAT" | docker login ghcr.io -u dream619 --password-stdin

# 从仓库获取部署文件（二选一）
# 方式 A：git clone
git clone https://github.com/dream619/Manwen-Studio.git /tmp/lorevista
cp /tmp/lorevista/docker-compose.yml /opt/lorevista/
cp -r /tmp/lorevista/deploy/docker /opt/lorevista/deploy/
rm -rf /tmp/lorevista

# 方式 B：本地打包上传（本地执行）
tar czf lorevista-deploy.tar.gz docker-compose.yml deploy/docker/
scp lorevista-deploy.tar.gz root@$SERVER_IP:/opt/lorevista/
# 服务器上解压
cd /opt/lorevista && tar xzf lorevista-deploy.tar.gz
```

#### 4. 配置环境变量

```bash
cd /opt/lorevista

# 复制环境变量模板
cp deploy/docker/.env.example .env
cp deploy/docker/runtime/backend.env.example deploy/docker/runtime/backend.env

# 编辑 .env，修改以下关键项：
#   REGISTRY_IMAGE_PREFIX=ghcr.io/dream619/manwen-studio
#   APP_VERSION=v1.0.4（或你想要的版本）
#   POSTGRES_PASSWORD=设置一个强密码
#   DATABASE_URL=postgresql://postgres:密码@postgres:5432/manga_novel
#   SYSTEM_INSTALLED=false（新服务器首次部署为 false）
#   UPDATER_TOKEN=$(openssl rand -hex 32)（生成随机 Token）
```

#### 5. 启动服务

```bash
cd /opt/lorevista
docker compose --env-file .env up -d
```

Docker 会自动从 ghcr.io 拉取 3 个业务镜像 + 从 Docker Hub 拉取 PostgreSQL 和 Redis。

#### 6. 验证

```bash
docker compose ps
# 应看到 5 个容器全部 healthy

curl http://localhost:8080/api/health
# 应返回 {"status":"ok"}
```

#### 7. 配置宿主 Nginx（TLS 终止）

宿主机 Nginx 反向代理到 Docker web 容器的端口（默认 `127.0.0.1:8080`）：

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### 8. 首次访问

浏览器打开 `https://your-domain.com` → 自动进入安装向导，创建管理员账号后即可使用。

### 更新线上服务

推送代码后，GitHub Actions 会自动构建镜像，然后在服务器上执行更新：

```bash
# 方式一：管理后台在线更新（推荐）
# 管理员登录 → 管理导航「系统更新」→ 输入版本号 → 确认

# 方式二：SSH 命令行更新
sudo APP_DIR=/opt/lorevista /usr/bin/env bash /opt/lorevista/deploy/docker/update-lorevista.sh
```

> 只需 `git push` 打 tag，不需要手动执行构建。构建由 GitHub Actions 自动完成。

### 架构示意

```
宿主 Nginx (TLS 443)
    ↓ proxy_pass :8080
Docker Compose (5 容器)
├── web (Nginx :80)          ← 静态文件 + 反向代理 /api/ → backend
├── backend (FastAPI :8000)  ← 业务 API
├── updater (FastAPI :8090)  ← 热更新 sidecar（挂载 docker.sock）
├── postgres (PostgreSQL 16) ← 数据库（持久化 volume）
└── redis (Redis 7)          ← 缓存（AOF 持久化 volume）
```

### ⚠️ 部署红线

| 规则 | 说明 |
|------|------|
| 禁止 `docker compose down -v` | 会删除 PostgreSQL 和 Redis 数据卷 |
| 禁止 `rsync --delete` | 会删除用户已生成的漫画/视频文件 |
| 禁止 `git clean -fdx` | 会删除 manga_outputs/ 和 video_outputs/ |
| 禁止整个目录替换 | 只做增量覆盖代码文件 |
| `manga_outputs/` 和 `video_outputs/` | 在 `.gitignore` 中，本地仓库不含用户资源 |

---

## 使用教程（PostgreSQL 版）

### 1. 拉取项目代码

```bash
git clone https://github.com/dream619/Manwen-Studio.git
cd -LoreVista
```

### 2. 准备 PostgreSQL 数据库

请先安装并启动 PostgreSQL，然后创建数据库：

```sql
CREATE DATABASE manga_novel;
```

默认连接地址是：

```text
postgresql://postgres:postgres@localhost:5432/manga_novel
```

如果你的 PostgreSQL 用户名、密码、端口或数据库名不同，需要在后面的 `.env` 中修改 `DATABASE_URL`。

### 3. 配置后端环境变量

进入后端目录：

```bash
cd backend
```

复制环境变量示例文件：

```bash
copy .env.example .env
```

然后打开 `backend/.env`，确认或修改数据库配置：

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/manga_novel
    IMAGE_API_BASE_URL=https://newapi.aifusion6.cn/v1
HOST=127.0.0.1
PORT=8000
```

DeepSeek 和 Image2 的 API Key 可以不写在 `.env` 里，后面可以直接在网页里填写。

### 4. 安装依赖

你可以选择下面任意一种方式安装前后端依赖。

#### 方式一（推荐，小白友好）：双击 `install.bat`

进入项目根目录，双击：

```text
install.bat
```

脚本会自动检查 Python / Node.js，并依次安装后端 (`pip install`) 和前端 (`npm install`) 依赖。看到 `Install completed successfully!` 即成功。

> 前置条件：已安装 Python 3.10+ 和 Node.js 18+。如果脚本提示找不到 Python 或 Node，请先去官网安装：
> Python: https://www.python.org/downloads/（安装时勾选 *Add Python to PATH*）
> Node.js: https://nodejs.org/

#### 方式二：手动安装

先安装后端依赖：

```bash
cd backend
pip install -r requirements.txt
cd ..
```

再安装前端依赖：

```bash
cd frontend
npm install
cd ..
```

### 5. 启动项目

你可以选择下面任意一种启动方式。

#### 方式一：分别启动后端和前端

先打开一个终端，启动后端：

```bash
cd backend
python main.py
```

再打开另一个终端，启动前端：

```bash
cd frontend
npm run dev
```

然后在浏览器访问：

```text
http://localhost:5173
```

#### 方式二：双击 start.bat 启动

进入项目所在的桌面文件夹，双击项目根目录里的：

```text
start.bat
```

它会自动启动后端、前端，并打开浏览器页面。

如果浏览器没有自动打开，可以手动访问：

```text
http://localhost:5173
```

### 6. 配置 API Key

打开网页后，点击页面上的 **API Key** 按钮。

你需要配置两个 Key：

#### DeepSeek API Key

用于 AI 对话、生成小说、生成分镜。

购买 / 查看用量：

```text
https://platform.deepseek.com/usage
```

#### Image2 API Key

用于生成漫画图片。

充值入口：

```text
https://api.xbyjs.top/console/token
```

购买后，把两个 API Key 分别填入网页里的 API Key 设置窗口，然后点击保存。

### 7. 开始测试

配置完成后，就可以开始测试：

1. 点击"新建小说"
2. 进入小说
3. 和 AI 对话，生成小说内容
4. 生成分镜
5. 生成漫画图片

## 效果

<img width="1437" height="1325" alt="image" src="https://github.com/user-attachments/assets/292cd965-1bbe-4ac2-be2c-e577d1c1b545" />
<img width="2477" height="1474" alt="8225c4cd8b1ac53ee97418cc6646db8c" src="https://github.com/user-attachments/assets/2e394e4c-f0c0-4af6-ae8d-63713d111cde" />
<img width="2478" height="1479" alt="image" src="https://github.com/user-attachments/assets/5e4a6aa5-9f7f-49a2-8e47-65a5c2ad9dec" />

## License

MIT
