# 版本号更新前置验证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在用户输入不存在的版本号时，更新流程在修改任何状态之前拒绝并返回明确错误，防止服务宕机。

**Architecture:** Updater 侧利用 Docker socket 和 ghcr.io 凭证，在 `POST /update` 的 handler 中同步执行 `docker buildx imagetools inspect` 验证三个镜像（backend/web/updater）的 tag 是否存在。脚本回退路径也加一道验证。

**Tech Stack:** Python (FastAPI), Bash, Docker CLI

---

### Task 1: Updater 新增版本验证函数

**Files:**
- Modify: `deploy/docker/updater/app.py`

- [ ] **Step 1.1: 添加 COMPOSE_FILE 常量和日志函数引用**

在 `APP_DIR` 和 `ENV_FILE` 定义下方添加 `COMPOSE_FILE` 常量（约第 21 行）：

```python
COMPOSE_FILE = Path(os.getenv("COMPOSE_FILE", str(APP_DIR / "docker-compose.yml")))
```

- [ ] **Step 1.2: 新增 `_get_image_ref()` 函数**

在 `_parse_semver()` 函数之前（约第 192 行），添加：

```python
def _get_image_ref(service: str, target_version: str) -> str:
    """从 docker compose config 获取服务镜像名，替换 tag 为目标版本。"""
    try:
        result = subprocess.run(
            ["docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE),
             "config", "--images", service],
            capture_output=True, text=True, timeout=15, cwd=str(APP_DIR),
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(503, f"无法获取 {service} 的镜像配置：命令超时")
    except Exception as exc:
        raise HTTPException(502, f"无法获取 {service} 的镜像配置：{exc}")
    if result.returncode != 0:
        raise HTTPException(502, f"无法获取 {service} 的镜像配置：{result.stderr.strip()}")
    lines = result.stdout.strip().splitlines()
    if not lines:
        raise HTTPException(502, f"无法确定服务 {service} 的镜像名")
    current_ref = lines[0]
    if ":" in current_ref:
        repo = current_ref.rsplit(":", 1)[0]
        return f"{repo}:{target_version}"
    return f"{current_ref}:{target_version}"
```

- [ ] **Step 1.3: 新增 `_validate_version_tags()` 函数**

在 `_get_image_ref()` 下方添加：

```python
def _validate_version_tags(target_version: str) -> None:
    """验证目标版本的所有镜像标签在仓库中存在。"""
    services = ["backend", "web", "updater"]
    missing: list[str] = []
    for service in services:
        image = _get_image_ref(service, target_version)
        try:
            result = subprocess.run(
                ["docker", "buildx", "imagetools", "inspect", image],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(503, f"验证镜像 {image} 超时，仓库可能不可达")
        except FileNotFoundError:
            # docker buildx 插件可能未安装，跳过验证（防御降级）
            return
        if result.returncode != 0:
            missing.append(image)
    if missing:
        detail = "以下镜像在仓库中不存在:\n" + "\n".join(f"  - {img}" for img in missing)
        raise HTTPException(400, detail)
```

- [ ] **Step 1.4: 在 `start_update()` 中调用验证**

修改 `start_update()`（约第 448–449 行），在格式验证之后、状态写入之前插入：

原代码：
```python
        if payload.target_version and not VERSION_RE.match(payload.target_version):
            raise HTTPException(400, "Invalid target version")
        _write_state({...})
```

改为：
```python
        if payload.target_version and not VERSION_RE.match(payload.target_version):
            raise HTTPException(400, "Invalid target version")
        # 验证目标版本的镜像标签在仓库中存在
        if payload.target_version:
            _validate_version_tags(payload.target_version)
        _write_state({...})
```

- [ ] **Step 1.5: 修复 `_fetch_update_manifest()` 的 404 崩溃**

私有仓库的 `DEFAULT_MANIFEST_URL`（raw.githubusercontent.com）返回 404，导致 `/check` 端点抛 502。改为 HTTP 错误时返回空 dict，由调用方决定如何处理。

修改 `_fetch_update_manifest()`（第 153–154 行）：

原代码：
```python
    except urllib.error.HTTPError as exc:
        raise HTTPException(502, f"Update manifest request failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(502, f"Update manifest is unavailable: {exc.reason}") from exc
    except TimeoutError as exc:
        raise HTTPException(502, "Update manifest request timed out") from exc
```

改为：
```python
    except urllib.error.HTTPError:
        return {}
    except urllib.error.URLError:
        return {}
    except TimeoutError:
        return {}
```

然后修改 `/check` 端点（第 409–416 行），处理空 manifest 时不抛 502：

原代码：
```python
    manifest = _fetch_update_manifest()
    latest_version = _string_field(manifest, "latest_version") or _string_field(manifest, "version")
    if not latest_version:
        raise HTTPException(502, "Update manifest is missing latest_version")
    if not VERSION_RE.match(latest_version):
        raise HTTPException(502, "Update manifest contains an invalid latest_version")
```

改为：
```python
    manifest = _fetch_update_manifest()
    latest_version = _string_field(manifest, "latest_version") or _string_field(manifest, "version")
    if not latest_version or not VERSION_RE.match(latest_version):
        return {
            "configured": False,
            "source": None,
            "current_version": current_version,
            "latest_version": latest_version or None,
            "update_available": False,
            "release_notes": "",
            "published_at": None,
            "min_supported_version": None,
            "channel": None,
            "manifest_url": _redact_manifest_url(UPDATE_MANIFEST_URL),
            "message": "更新清单不可用。如果仓库是私有的，需要在 .env 中配置 UPDATE_MANIFEST_URL。",
        }
```

- [ ] **Step 1.6: LSP 检查**

```bash
cd C:\Users\Administrator\Desktop\Desktop\Manwen-Studio
pylint deploy/docker/updater/app.py 2>&1 | Select-String -Pattern "error|warning" -NotMatch
```
期望：无新增错误

---

### Task 2: Update 脚本添加前置验证

**Files:**
- Modify: `deploy/docker/update-lorevista.sh`

- [ ] **Step 2.1: 新增 `check_image_exists()` 函数**

在 `wait_for_health()` 函数之后（约第 79 行前），添加：

```bash
check_image_exists() {
  local image="$1"
  local version="$2"
  # 从镜像引用中提取 registry/repo 部分
  local repo="${image%:*}"
  local full_image="${repo}:${version}"
  if docker buildx imagetools inspect "$full_image" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

validate_version_images() {
  local version="$1"
  local all_exist=true
  for svc in backend web updater; do
    local img
    img="$(image_ref_for "$svc")"
    if ! check_image_exists "$img" "$version"; then
      local repo="${img%:*}"
      log "ERROR: 镜像 ${repo}:${version} 在仓库中不存在"
      all_exist=false
    fi
  done
  if ! $all_exist; then
    log "版本 ${version} 存在缺失的镜像，终止更新"
    exit 1
  fi
  log "版本 ${version} 的所有镜像已验证通过"
}
```

- [ ] **Step 2.2: 在 `main()` 开头调用验证**

在 `main()` 中，`cd "$APP_DIR"` 和清理占位符逻辑之后、`compose pull` 之前，添加：

查找 `backend_before="$(running_image_id_for "$BACKEND_SERVICE")"` 这一行之前，加入：

```bash
  # 如果指定了目标版本（通过 .env 的 APP_VERSION），验证镜像存在
  local current_target
  current_target="$(grep -oP '^APP_VERSION=\K.*' "$ENV_FILE" 2>/dev/null || true)"
  if [[ -n "$current_target" ]]; then
    validate_version_images "$current_target"
  fi
```

注意：脚本中 APP_VERSION 已经在 `_run_update()` 中通过 `_update_env_version()` 写入 `.env` 了，所以脚本读取到的 APP_VERSION 就是目标版本。

- [ ] **Step 2.3: ShellCheck**

```bash
bash -n deploy/docker/update-lorevista.sh
```
期望：无语法错误

---

### Task 3: 提交并打 tag

- [ ] **Step 3.1: Commit**

```bash
cd C:\Users\Administrator\Desktop\Desktop\Manwen-Studio
git add deploy/docker/updater/app.py deploy/docker/update-lorevista.sh docs/superpowers/specs/2026-06-06-version-prevalidation-design.md
git commit -m "feat: 指定版本更新前验证镜像标签是否存在

- updater 新增 _validate_version_tags()，在修改状态前检查镜像存在性
- update-lorevista.sh 新增 validate_version_images() 作为 CLI 回退防御
- 设计文档：docs/superpowers/specs/2026-06-06-version-prevalidation-design.md"
```

- [ ] **Step 3.2: 打 tag 触发 CI**

```bash
git tag v1.2.5
git push origin v1.2.5
```

---

### Task 4: 生产更新验证

- [ ] **Step 4.1: 等待 CI 构建完成**

```bash
# 通过 GitHub Actions 页面确认镜像构建成功
```

- [ ] **Step 4.2: 登录服务器验证错误版本号被拒绝**

```bash
# 构造一个不存在的版本号请求，应该返回 400
curl -s -H "X-Updater-Token: change-this-updater-token" \
  -X POST -H "Content-Type: application/json" \
  -d '{"target_version":"v9.9.9"}' \
  http://127.0.0.1:8090/update | python3 -m json.tool
```
期望输出：
```json
{
  "detail": "以下镜像在仓库中不存在:\n  - ghcr.io/dream619/manwen-studio/backend:v9.9.9\n  - ghcr.io/dream619/manwen-studio/web:v9.9.9\n  - ghcr.io/dream619/manwen-studio/updater:v9.9.9"
}
```

- [ ] **Step 4.3: 验证正确版本号正常更新**

```bash
curl -s -H "X-Updater-Token: change-this-updater-token" \
  -X POST -H "Content-Type: application/json" \
  -d '{"target_version":"v1.2.5"}' \
  http://127.0.0.1:8090/update | python3 -m json.tool
```
期望：返回状态 "queued"

- [ ] **Step 4.4: 在管理后台手动测试**
  1. 打开管理后台 → 系统更新
  2. 输入不存在的版本号（如 v9.9.9）→ 应直接报错，不触发更新
  3. 输入 v1.2.5 → 应正常更新
