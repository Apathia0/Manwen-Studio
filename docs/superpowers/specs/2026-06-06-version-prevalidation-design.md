# 版本号更新前置验证设计

## 问题

管理员在「指定版本更新」中输入不存在的版本号（如 CI 尚未构建完成时），系统会直接执行更新流程：修改 `.env` → 拉取镜像 → 拉取失败 → 回滚。回滚机制不可靠（曾导致 `postgres:16-alpine` 镜像标签被覆盖为 nginx 镜像），造成服务 502 宕机。

## 目标

在更新流程**修改任何状态之前**，验证目标版本号对应的 Docker 镜像是否存在于容器仓库中。不存在时立即返回错误，不触发任何副作用。

## 当前验证现状

| 层面 | 验证 | 不足 |
|------|------|------|
| Backend `main.py:4897` | 格式正则 `UPDATER_VERSION_RE` | 只检查字符格式 |
| Updater `app.py:448` | 格式正则 `VERSION_RE` | 只检查字符格式 |
| `update-lorevista.sh` | 无验证 | 直接 `compose pull` |

## 方案：Updater 端预验证

### 架构

```
用户输入 v1.2.4
    ↓
POST /api/admin/system/update {"target_version": "v1.2.4"}
    ↓
Backend 格式验证 → 转发给 updater
    ↓
Updater POST /update
    ↓
验证镜像存在  ←── 新增
    ├── 全部存在 → 写入 queued 状态 → 后台执行更新
    └── 任一缺失 → 返回 400 + 缺失镜像列表（不修改任何状态）
```

### 新增函数：`_validate_version_tags(target_version)`

**位置**：`deploy/docker/updater/app.py`

**逻辑**：

1. 取服务列表 `["backend", "web", "updater"]`
2. 对每个服务，运行 `docker compose config --images <service>` 获取当前镜像全名
3. 从镜像名中解析 tag 部分，替换为目标版本
4. 运行 `docker buildx imagetools inspect <image>` 检查标签是否存在
5. 全部存在 → 返回；任一失败 → 抛出 HTTPException(400)

**调用时机**：`start_update()` handler 中，`_write_state("queued")` **之前**，`VERSION_RE` 格式验证**之后**。同步阻塞调用，不启动后台线程。

```python
# start_update 中的调用位置
if payload.target_version and not VERSION_RE.match(payload.target_version):
    raise HTTPException(400, "Invalid target version")

# NEW: 验证镜像存在
if payload.target_version:
    _validate_version_tags(payload.target_version)

# 然后继续写入状态、启动后台线程
_write_state({...})
thread.start()
```

### 辅助函数：`_get_image_ref(service, target_version)`

解析 compose 配置中的镜像名并替换 tag：

```python
def _get_image_ref(service: str, target_version: str, compose_file: Path, env_file: Path, app_dir: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "--env-file", str(env_file), "-f", str(compose_file),
         "config", "--images", service],
        capture_output=True, text=True, timeout=10, cwd=app_dir
    )
    lines = result.stdout.strip().splitlines()
    if not lines:
        raise HTTPException(502, f"Cannot determine image name for service {service}")
    current_ref = lines[0]
    if ":" in current_ref:
        repo = current_ref.rsplit(":", 1)[0]
        return f"{repo}:{target_version}"
    return f"{current_ref}:{target_version}"
```

### 错误信息

```json
HTTP 400
{
    "detail": "以下镜像在仓库中不存在:\n  - ghcr.io/dream619/manwen-studio/backend:v9.9.9\n  - ghcr.io/dream619/manwen-studio/web:v9.9.9\n  - ghcr.io/dream619/manwen-studio/updater:v9.9.9"
}
```

### 防御性验证（CLI 回退）

在 `update-lorevista.sh` 的 `compose pull` 前也添加相同验证。这样通过 SSH 直接执行脚本的用户也能得到保护。

### 边界情况

| 场景 | 行为 |
|------|------|
| `target_version` 为空（使用 .env 的 APP_VERSION） | 跳过验证，`compose pull` 检查是否变化 |
| Registry 不可达（网络问题） | `subprocess.run` 超时 → HTTP 503 |
| `docker compose config --images` 失败 | HTTP 502 |
| 本地已有该版本的镜像 | `imagetools inspect` 仍然能查到，通过 |

## 变更文件

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `deploy/docker/updater/app.py` | 修改 | 新增 `_validate_version_tags()` + `_get_image_ref()`，修改 `start_update()` |
| `deploy/docker/update-lorevista.sh` | 修改 | 在 `compose pull` 前新增验证步骤 |
| `Dockerfile.updater` | 无变更 | 已有 `docker-cli` 和 `docker-cli-compose` |
| `backend/main.py` | 无变更 | 错误信息通过 `_call_updater` 的 400 响应自动传递 |
| `frontend/` | 无变更 | 错误信息由后端直接返回 |

## 验证方法

1. 构建新版本镜像（v1.2.5）
2. 在管理后台输入 `v9.9.9` → 应立即返回错误，不触发更新
3. 输入 `v1.2.5` → 应正常执行更新
4. 留空 → 应正常执行更新（使用 .env 的 APP_VERSION）
