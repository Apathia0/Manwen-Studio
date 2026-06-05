#!/usr/bin/env python3
"""Verify Docker postgres data and restart backend"""
import paramiko, time

HOST = "103.149.26.199"; PASSWORD = "lxh100400"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", password=PASSWORD, timeout=10)

def run(cmd, timeout=30):
    stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    stdin.close()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return out.strip(), err.strip(), rc

# 1. Verify Docker postgres data via exec (bypasses password)
print("=== Docker postgres data ===")
out, _, _ = run(
    'cd /opt/lorevista && docker compose exec -T postgres psql -U postgres -d manga_novel -c "SELECT count(*) FROM users;" -c "SELECT count(*) FROM stories;" 2>/dev/null || true',
    15)
print(out[:300])

# 2. Check Docker postgres is accessible via its internal network
print("\n=== Testing password auth on Docker postgres ===")
out, err, rc = run(
    'cd /opt/lorevista && docker compose exec -T postgres psql -U postgres -h localhost -p 5432 -d manga_novel -c "SELECT 1 as auth_works;" 2>/dev/null || true',
    15)
print(out[:300])
if err: print("ERR:", err[:200])

# 3. Restart backend to pick up new password
print("\n=== Restarting backend container ===")
out, _, _ = run("cd /opt/lorevista && docker compose restart backend", 30)
print(out[:200] if out else "restart issued")

# Wait for health
print("Waiting for backend to become healthy...")
time.sleep(20)

# 4. Health check
out, _, _ = run("curl -s http://127.0.0.1:8080/api/health 2>/dev/null || true", 15)
print(f"\n=== Health Check ===")
print(out[:500] if out else "NOT READY")

# 5. Container status
out, _, _ = run("cd /opt/lorevista && docker compose ps 2>/dev/null || true", 15)
print(f"\n=== Container Status ===")
print(out)

# 6. Backend logs
out, _, _ = run("cd /opt/lorevista && docker compose logs --tail 20 backend 2>/dev/null || true", 15)
print(f"\n=== Backend Logs (last 20) ===")
print(out[-1000:] if out else "NO LOGS")

c.close()
