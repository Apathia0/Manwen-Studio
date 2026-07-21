#!/usr/bin/env python3
"""验证生产 Docker 服务并重启后端，凭据仅从环境变量或 SSH Agent 读取。"""

import os
import time

import paramiko


HOST = os.getenv("LOREVISTA_SSH_HOST", "").strip()
USERNAME = os.getenv("LOREVISTA_SSH_USER", "root").strip() or "root"
PASSWORD = os.getenv("LOREVISTA_SSH_PASSWORD", "").strip() or None
KEY_FILENAME = os.getenv("LOREVISTA_SSH_KEY", "").strip() or None

if not HOST:
    raise SystemExit("请设置 LOREVISTA_SSH_HOST；禁止在脚本中硬编码生产服务器地址")

client = paramiko.SSHClient()
client.load_system_host_keys()
client.set_missing_host_key_policy(paramiko.RejectPolicy())
client.connect(
    HOST,
    username=USERNAME,
    password=PASSWORD,
    key_filename=KEY_FILENAME,
    allow_agent=True,
    look_for_keys=True,
    timeout=10,
)


def run(command: str, timeout: int = 30) -> tuple[str, str, int]:
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    stdin.close()
    output = stdout.read().decode("utf-8", errors="replace")
    error = stderr.read().decode("utf-8", errors="replace")
    return_code = stdout.channel.recv_exit_status()
    return output.strip(), error.strip(), return_code


try:
    print("=== Docker PostgreSQL 数据 ===")
    output, _, _ = run(
        'cd /opt/lorevista && docker compose exec -T postgres psql -U postgres -d manga_novel '
        '-c "SELECT count(*) FROM users;" -c "SELECT count(*) FROM stories;"',
        15,
    )
    print(output[:300])

    print("\n=== 验证 PostgreSQL 密码认证 ===")
    output, error, _ = run(
        'cd /opt/lorevista && docker compose exec -T postgres psql -U postgres -h localhost '
        '-p 5432 -d manga_novel -c "SELECT 1 AS auth_works;"',
        15,
    )
    print(output[:300])
    if error:
        print("错误:", error[:200])

    print("\n=== 重启后端容器 ===")
    output, _, return_code = run("cd /opt/lorevista && docker compose restart backend", 30)
    if return_code != 0:
        raise RuntimeError("后端容器重启失败")
    print(output[:200] if output else "已发起重启")

    print("等待后端健康检查...")
    time.sleep(20)

    output, _, return_code = run("curl --fail --silent http://127.0.0.1:8080/api/health", 15)
    print("\n=== 健康检查 ===")
    print(output[:500] if output else "未就绪")
    if return_code != 0:
        raise RuntimeError("后端健康检查失败")

    output, _, _ = run("cd /opt/lorevista && docker compose ps", 15)
    print("\n=== 容器状态 ===")
    print(output)

    output, _, _ = run("cd /opt/lorevista && docker compose logs --tail 20 backend", 15)
    print("\n=== 后端最近日志 ===")
    print(output[-1000:] if output else "无日志")
finally:
    client.close()
