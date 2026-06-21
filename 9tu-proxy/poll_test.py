#!/usr/bin/env python3
import urllib.request, json, time

# 创建任务
data = json.dumps({"prompt": "test", "duration": 5}).encode()
req = urllib.request.Request("http://127.0.0.1:8001/v1/videos", data=data, headers={"Content-Type": "application/json"})
resp = urllib.request.urlopen(req)
result = json.loads(resp.read().decode())
task_id = result["id"]
print(f"任务创建: {task_id}")

# 轮询
for i in range(40):
    time.sleep(3)
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:8001/v1/videos/{task_id}")
        data = json.loads(resp.read().decode())
        status = data.get("status", "?")
        result_url = data.get("result_url", "")
        print(f"[{i*3+3:3d}s] status={status:12s} url={'有' if result_url else '无'}")
        if status in ("completed", "success", "failed"):
            print(f"  完整响应: {json.dumps(data, indent=2)}")
            break
    except Exception as e:
        print(f"[{i*3+3:3d}s] ERROR: {e}")