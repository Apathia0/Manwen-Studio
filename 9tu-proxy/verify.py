#!/usr/bin/env python3
import urllib.request, json

# Test admin login
data = json.dumps({"password": "admin123"}).encode()
req = urllib.request.Request("http://127.0.0.1:8001/admin/api/login", data=data, headers={"Content-Type": "application/json"})
try:
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read().decode())
    print("Login OK, token:", result.get("token", "")[:30] + "...")
except Exception as e:
    print("Login FAILED:", e)

# Test health
resp = urllib.request.urlopen("http://127.0.0.1:8001/health")
print("Health:", resp.read().decode())