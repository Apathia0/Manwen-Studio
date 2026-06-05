# LoreVista Docker 常见问题

本文记录 Docker 首次安装和更新过程中最常见的问题。所有命令默认在服务器宿主机执行：

```bash
cd /opt/lorevista
```

## 1. 安装成功了，但 `/api/install/status` 仍显示未安装

典型现象：

```json
{
  "installed": false,
  "database_reachable": false,
  "database_error": "password authentication failed for user \"postgres\""
}
```

先确认数据库里是否已有安装数据：

```bash
docker compose --env-file .env exec postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) from users;"'
```

如果返回 `1` 或更大，说明安装数据已经在数据库里，不要清库。继续检查 backend 当前环境：

```bash
docker compose --env-file .env exec backend sh -lc 'env | grep -E "^(SYSTEM_INSTALLED|DATABASE_URL|REDIS_URL|APP_VERSION)="'
```

再检查宿主机 `.env`：

```bash
grep -E '^(SYSTEM_INSTALLED|DATABASE_URL|REDIS_URL|POSTGRES_PASSWORD)=' .env
```

如果宿主机 `.env` 和 backend 容器环境不一致，重建服务：

```bash
docker compose --env-file .env up -d --force-recreate backend web updater
```

## 2. 安装返回 `env_path=/app/backend/.env`

这表示旧版本把安装后的配置写到了 backend 容器内部，而不是宿主机 `/opt/lorevista/.env`。容器重建后，Compose 仍读取宿主机 `.env`，所以会出现“安装成功但重启后仍未安装”。

处理方式：

```bash
grep -E '^(SYSTEM_INSTALLED|DATABASE_URL|REDIS_URL)=' .env
```

如果 `.env` 没有安装后的配置，手动修正 `.env`，然后重建容器：

```bash
docker compose --env-file .env up -d --force-recreate backend web updater
```

`v1.0.4` 及之后版本已修复：Docker 安装会通过内部 `updater` 写宿主机 `/opt/lorevista/.env`。

## 3. PostgreSQL 报 `password authentication failed`

这表示 backend 使用的 `DATABASE_URL` 密码和数据库里 `postgres` 用户真实密码不一致。

注意：`POSTGRES_PASSWORD` 只在 PostgreSQL volume 第一次初始化时生效。已有 volume 后，修改 `.env` 不会自动修改数据库用户密码。

把数据库用户密码改成 `.env` 中的密码，例如 `90909090090`：

```bash
docker compose --env-file .env exec -T postgres sh -lc "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -c \"ALTER USER postgres WITH PASSWORD '90909090090';\""
```

同时确保 `.env` 使用同一个密码：

```bash
python3 - <<'PY'
from pathlib import Path
p = Path(".env")
updates = {
    "POSTGRES_PASSWORD": "90909090090",
    "DATABASE_URL": "postgresql://postgres:90909090090@postgres:5432/manga_novel?sslmode=prefer",
    "SYSTEM_INSTALLED": "true",
}
lines = p.read_text().splitlines()
out = []
seen = set()
for line in lines:
    key = line.split("=", 1)[0].strip() if "=" in line else ""
    if key in updates:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")
p.write_text("\n".join(out).rstrip() + "\n")
PY
```

重建服务：

```bash
docker compose --env-file .env up -d --force-recreate backend web updater
```

## 4. `users` 表不存在

命令：

```bash
docker compose --env-file .env exec postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) from users;"'
```

如果返回：

```text
ERROR: relation "users" does not exist
```

说明当前 Compose PostgreSQL 连接的是空库。常见原因：

- 安装向导里数据库 host 填了 `localhost` 或公网 IP，安装到了另一套数据库。
- `.env` 中 `DATABASE_URL` 指向的数据库和安装向导填写的数据库不是同一套。
- PostgreSQL volume 被删除或换了部署目录。

如果确定这是空库且需要重新安装：

```bash
sed -i 's/^SYSTEM_INSTALLED=.*/SYSTEM_INSTALLED=false/' .env
docker compose --env-file .env up -d --force-recreate backend web updater
```

浏览器打开站点重新进入安装向导。Compose 自带 PostgreSQL 时数据库字段必须填写：

```text
host: postgres
port: 5432
database: manga_novel
username: postgres
password: /opt/lorevista/.env 中的 POSTGRES_PASSWORD
sslmode: disable 或 prefer
```

## 5. Redis 和 PostgreSQL host 应该填什么

使用 Compose 内置服务时：

```text
PostgreSQL host: postgres
Redis host: redis
```

不要填：

```text
localhost
127.0.0.1
服务器公网 IP
```

原因：安装向导运行在 backend 容器内，`localhost` 指的是 backend 容器自己，不是 postgres 或 redis 容器。

如果使用宿主机或外部数据库，安装向导填写的地址必须和 `/opt/lorevista/.env` 中 `DATABASE_URL`、`REDIS_URL` 指向同一套服务。

## 6. 自动重启失败，提示需要 `INSTALL_RESTART_COMMAND`

旧版本在 Linux 上不知道如何重启 backend，会提示：

```text
Linux 部署请配置 INSTALL_RESTART_COMMAND 或 INSTALL_PM2_PROCESS_NAME
```

Docker 部署在 `v1.0.3` 后已支持默认自动重启：backend 会退出当前容器，由 `restart: unless-stopped` 自动拉起。

临时手动重启命令：

```bash
docker compose --env-file .env restart backend web updater
```

如果仍失败，确认 compose 中 backend 有：

```yaml
restart: unless-stopped
```

## 7. Shell 命令里的 `\` 为什么报 `sh: -c requires an argument`

不要在反斜杠 `\` 后面敲空行。反斜杠只用于“下一行紧接着继续命令”。

错误示例：

```bash
docker compose --env-file .env exec postgres sh -lc \

'psql ...'
```

推荐直接复制单行命令：

```bash
docker compose --env-file .env exec postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) from users;"'
```

## 8. 如何判断是否已经安装成功

依次执行：

```bash
curl -fsS http://127.0.0.1:8080/api/install/status
curl -fsS http://127.0.0.1:8080/api/health
docker compose --env-file .env exec postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) from users;"'
```

期望结果：

```text
/api/install/status: installed=true
/api/health: ready=true, database_reachable=true
users count: >= 1
```

如果 `users >= 1` 但接口仍显示未安装，优先排查 `.env`、backend 环境变量、数据库密码，不要清库。

## 9. 哪些命令不要在生产执行

不要执行：

```bash
docker compose down -v
```

除非你明确要删除 PostgreSQL 和 Redis volume。

不要随意删除：

```text
/opt/lorevista/data/manga_outputs
/opt/lorevista/data/video_outputs
Docker volume: lorevista_postgres_data
Docker volume: lorevista_redis_data
```

不要用 `rsync --delete`、`git clean -fdx` 或整目录替换方式部署用户已有实例。

## 10. 线上更新到指定版本

等 GHCR 镜像构建完成后：

```bash
sed -i 's/^APP_VERSION=.*/APP_VERSION=v1.0.4/' .env
docker compose --env-file .env pull backend web updater
docker compose --env-file .env up -d backend web updater
```

验证：

```bash
curl -fsS http://127.0.0.1:8080/api/health
docker compose --env-file .env ps
```
