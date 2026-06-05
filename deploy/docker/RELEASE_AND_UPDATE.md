# LoreVista Docker 发布与用户更新说明

本文档说明 Docker 发行模式下的两个流程：

- 我们发布新版本：由研发/运维侧构建并推送私有镜像。
- 用户更新系统：由用户在系统管理后台手动点击更新，服务器只拉取镜像并重启容器。

核心原则：生产服务器不保存源码、不配置 Git 凭据、不执行源码构建，只运行 Docker Compose、私有镜像和 updater 服务。

## 私有仓库定义

本文档中的“私有仓库”特指私有 Docker 镜像仓库，也就是 Docker Registry，不是 Git 源码仓库。

推荐默认使用 GHCR：

```text
Registry: ghcr.io
Image prefix: ghcr.io/<github-owner>/<github-repo>
```

如果 GitHub 仓库是 `your-org/lorevista`，则三类镜像地址为：

```text
ghcr.io/your-org/lorevista/backend:v1.2.3
ghcr.io/your-org/lorevista/web:v1.2.3
ghcr.io/your-org/lorevista/updater:v1.2.3
```

对应服务器 `.env` 配置：

```env
REGISTRY_IMAGE_PREFIX=ghcr.io/your-org/lorevista
APP_VERSION=v1.2.3
```

权限边界：

- CI 侧需要 push 权限，用于构建并推送镜像。
- 用户服务器只配置只读 pull token，用于拉取镜像。
- 用户服务器不配置 GitHub/GitLab 源码仓库访问权限。
- 不向用户提供 CI token、源码仓库 token、可写 registry token。

GHCR 场景下，CI 可使用 GitHub Actions 的 `GITHUB_TOKEN` 推送 packages；用户服务器建议使用单独的机器账号或细粒度 token，只授予当前镜像包的读取权限。镜像包本身必须设置为 private。

当前仓库已经配置 GitHub Actions：推送 `v*` tag 后会自动构建并推送到 GHCR。正式发布不需要人工执行 `docker build` 或 `docker push`。

## 一、我们发布版本的流程

### 1. 发布前准备

发布前确认以下条件已经满足：

- 私有 Docker 镜像仓库已配置，例如 GHCR、GitLab Registry、阿里云 ACR 或 Harbor。
- CI 具备镜像推送权限，服务器侧只配置只读 pull token。
- 版本号已确定，推荐使用 `v1.2.3` 这类固定版本标签。
- 数据库迁移保持向后兼容。破坏性迁移必须走人工维护窗口，不应作为普通自动更新发布。
- 用户生成资源不进入镜像，必须继续使用持久化挂载保存 `manga_outputs` 和 `video_outputs`。

### 2. 触发发布

推荐通过 Git tag 发布正式版本：

```bash
git tag v1.2.3
git push origin v1.2.3
```

推送 tag 后，`.github/workflows/docker-images.yml` 会自动执行测试、构建镜像并推送到 GHCR。

发布 `v1.2.3` 时会生成：

```text
ghcr.io/<github-owner>/<github-repo>/backend:v1.2.3
ghcr.io/<github-owner>/<github-repo>/web:v1.2.3
ghcr.io/<github-owner>/<github-repo>/updater:v1.2.3
```

同时还会生成提交追踪标签：

```text
ghcr.io/<github-owner>/<github-repo>/backend:sha-<commit>
ghcr.io/<github-owner>/<github-repo>/web:sha-<commit>
ghcr.io/<github-owner>/<github-repo>/updater:sha-<commit>
```

也可以推送到 `main` 或 `master` 触发 CI 构建预发布镜像。当前工作流会为每次分支构建生成 `sha-<commit>` 标签，并更新 `stable` 标签。

### 3. CI 执行内容

CI 会按以下顺序执行：

1. 安装后端依赖。
2. 执行后端语法检查和测试。
3. 安装前端依赖。
4. 执行 `npm run build`。
5. 构建并推送三个镜像：
   - `${REGISTRY_IMAGE_PREFIX}/backend:<version>`
   - `${REGISTRY_IMAGE_PREFIX}/web:<version>`
   - `${REGISTRY_IMAGE_PREFIX}/updater:<version>`

当前仓库的 GitHub Actions 工作流位于 `.github/workflows/docker-images.yml`，镜像包括：

- `backend`：FastAPI 后端，运行 `uvicorn main:app --host 0.0.0.0 --port 8000`。
- `web`：Nginx 托管前端 `dist`，并反代 `/api`、`/static` 到后端。
- `updater`：内部更新服务，负责调用 Docker Compose 拉镜像、迁移、重启和回滚。

### 4. 镜像标签规则

推荐同时保留两类标签：

- 固定版本标签：`v1.2.3`，用于用户手动选择升级目标。
- 提交标签：`sha-abcdef123456`，用于精确追踪构建来源。

`stable` 可以作为“最新稳定版”指针，但不建议默认让生产用户使用 `APP_VERSION=stable`。用户手动更新时如果仍使用 `stable`，每次点击更新都可能拉到最新 stable，版本可控性较弱。

### 5. 发布完成后的交付信息

给用户或交付人员提供以下信息即可：

- 新版本号，例如 `v1.2.3`。
- 本次更新内容和是否涉及数据库迁移。
- 是否需要维护窗口。
- 如果更新失败，应保留现场日志并联系支持，不要执行 `docker compose down -v`。

不要向用户提供源码仓库、CI token、构建缓存或可写 registry token。

## 二、用户站内手动更新流程

### 1. 用户服务器前提

用户服务器需要按 Docker Compose 方式部署，并满足：

- `/opt/lorevista/docker-compose.yml` 存在。
- `/opt/lorevista/deploy/docker/update-lorevista.sh` 存在。
- `/opt/lorevista/.env` 已配置 `REGISTRY_IMAGE_PREFIX`、`APP_VERSION`、`UPDATER_TOKEN` 等参数。
- `backend`、`web`、`updater`、`postgres`、`redis` 容器正常运行。
- 服务器已经使用只读 token 登录私有镜像仓库。
- 宿主机 Nginx 只反代到 `web` 容器端口，PostgreSQL 和 Redis 不对公网开放。

只读登录示例：

```bash
echo "$READ_ONLY_REGISTRY_TOKEN" | docker login ghcr.io -u "$REGISTRY_USER" --password-stdin
```

生产服务器只需要 Compose 文件、部署脚本、运行时配置和数据目录，不需要保存完整源码仓库。

### 2. 用户在系统内执行更新

管理员操作步骤：

1. 登录系统管理员账号。
2. 进入管理后台。
3. 打开 `系统更新`。
4. 输入目标版本号，例如 `v1.2.3`。如果留空，则使用服务器 `/opt/lorevista/.env` 中已有的 `APP_VERSION`。
5. 点击确认更新。
6. 等待页面显示更新状态和日志。

系统内更新接口由后端管理员 API 触发：

- `GET /api/admin/system/update/status`
- `POST /api/admin/system/update`

业务后端只负责管理员鉴权和调用内部 updater，不挂载 Docker socket。真正的 Docker 操作由 `updater` 容器完成。

### 3. updater 实际执行顺序

用户点击更新后，updater 会执行：

1. 如果用户填写了目标版本，先更新 `/opt/lorevista/.env` 中的 `APP_VERSION`，并创建备份。
2. 执行 `docker compose pull backend web` 拉取新镜像。
3. 对比当前运行镜像和拉取后的镜像，未变化则结束。
4. 使用新后端镜像执行数据库迁移命令。
5. 重启 `backend` 服务。
6. 请求 `backend` 的 `/api/health` 做健康检查。
7. 重启 `web` 服务。
8. 请求 `web` 的 `/api/health` 做健康检查。
9. 更新成功后记录日志。

默认迁移命令为：

```bash
python -c "from database import init_db; init_db(run_migrations=True, raise_errors=True)"
```

### 4. 失败和回滚

如果迁移或健康检查失败，updater 会尝试：

- 恢复 `.env` 中更新前的 `APP_VERSION`。
- 将 `backend` 和 `web` 镜像切回更新前的镜像 ID。
- 重新执行 `docker compose up -d` 恢复旧版本容器。

管理员应在 `系统更新` 页面查看日志。日志会做基础脱敏，不应输出 `.env` 密钥、数据库密码、registry token。

如果系统后台无法访问，可以在宿主机执行兜底命令：

```bash
sudo APP_DIR=/opt/lorevista /usr/bin/env bash /opt/lorevista/deploy/docker/update-lorevista.sh
```

### 5. 用户侧配置建议

固定版本更新推荐：

```env
REGISTRY_IMAGE_PREFIX=ghcr.io/your-org/lorevista
APP_VERSION=v1.2.3
UPDATER_URL=http://updater:8090
UPDATER_TOKEN=<long-random-token>
```

如果希望管理员每次在页面输入目标版本，`APP_VERSION` 可保留为当前已安装版本；点击更新时填写新版本号即可。

不建议普通生产环境默认使用：

```env
APP_VERSION=stable
```

原因是 `stable` 是浮动标签，用户点击更新时实际拉取到哪个版本取决于当时 registry 中的 stable 指向。

### 6. 数据和安全红线

用户侧更新时禁止执行：

```bash
docker compose down -v
git clean -fdx
rm -rf backend
```

这些操作可能删除数据库 volume 或用户生成资源。

必须持久化保存：

- `/opt/lorevista/data/manga_outputs`
- `/opt/lorevista/data/video_outputs`
- Docker volume `lorevista_postgres_data`
- Docker volume `lorevista_redis_data`

安全边界要求：

- `backend` 不挂载 `/var/run/docker.sock`。
- `updater` 不暴露公网端口，只在 Docker 内部网络可访问。
- `UPDATER_TOKEN` 必须是长随机值，并同时配置给 `backend` 和 `updater`。
- 服务器 registry token 只允许 pull 当前项目镜像。
- 生产服务器不保存 `.git`、源码、CI token、构建缓存或可写 registry token。

### 7. 推荐交付话术

给用户的简化说明可以是：

```text
新版本已发布：v1.2.3。
请使用管理员账号进入后台 -> 系统更新，输入 v1.2.3 后确认更新。
更新过程会自动拉取镜像、执行数据库迁移、重启服务并做健康检查。
如果页面显示失败，请保留更新日志并联系技术支持，不要执行 docker compose down -v。
```
