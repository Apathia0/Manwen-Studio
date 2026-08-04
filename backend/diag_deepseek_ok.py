"""诊断脚本：用数据库中的真实 DeepSeek 配置调用一次 newapi，打印完整响应结构。

目的：确认 max_tokens=8192 时 newapi 返回 200 但 content 为空的原因。
仅作诊断用，不改动任何业务代码。
"""
import asyncio
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import httpx
from sqlalchemy.orm import Session

from database import engine
from models import PlatformSetting


def get_settings(db: Session) -> dict:
    rows = db.query(PlatformSetting).all()
    out = {}
    for row in rows:
        out[row.setting_key] = row.value_json
    return out


async def main() -> None:
    db = Session(engine)
    try:
        settings = get_settings(db)
    finally:
        db.close()

    api = settings.get("api", {})
    ds_cfg = api.get("deepseek", {}) if isinstance(api, dict) else {}
    base_url = ds_cfg.get("base_url") or settings.get("DEEPSEEK_BASE_URL")
    api_key = ds_cfg.get("api_key") or settings.get("DEEPSEEK_API_KEY")
    model = ds_cfg.get("model") or settings.get("DEEPSEEK_MODEL")
    if not (base_url and api_key and model):
        print("!! 顶层/嵌套配置缺失，全部 setting_key 如下：")
        for k in sorted(settings.keys()):
            v = settings[k]
            if isinstance(v, dict):
                print(" ", k, "=", json.dumps(v, ensure_ascii=False)[:400])
            else:
                print(" ", k, "=", repr(v)[:200])
        return

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是小说作家。"},
            {"role": "user", "content": "写一段 30 字以内的简短正文。"},
        ],
        "stream": False,
        "max_tokens": 8192,
    }
    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    print("\n== 请求 ==")
    print("url     =", url)
    print("payload =", json.dumps(payload, ensure_ascii=False)[:600])

    try:
        async with httpx.AsyncClient(timeout=600) as client:
            resp = await client.post(url, json=payload, headers=headers)
        print("\n== HTTP 状态 ==")
        print("status_code =", resp.status_code)
        try:
            data = resp.json()
        except Exception as exc:
            print("!! 响应非 JSON:", repr(resp.text[:800]))
            return
        print("\n== 完整响应 (前 2000 字符) ==")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])

        choice = data.get("choices", [{}])[0]
        message = choice.get("message") or {}
        finish_reason = choice.get("finish_reason")
        usage = data.get("usage") or {}
        print("\n== 关键字段 ==")
        print("finish_reason       =", finish_reason)
        print("message.content len =", len(message.get("content") or ""))
        print("message.content[:200] =", repr((message.get("content") or "")[:200]))
        print("message.reasoning_content len =", len(message.get("reasoning_content") or ""))
        print("message keys =", list(message.keys()))
        print("usage =", json.dumps(usage, ensure_ascii=False))
        details = usage.get("completion_tokens_details") or {}
        print("completion_tokens_details =", json.dumps(details, ensure_ascii=False))
    except Exception as exc:
        print("\n!! 调用失败:", type(exc).__name__, str(exc)[:800])


if __name__ == "__main__":
    asyncio.run(main())
