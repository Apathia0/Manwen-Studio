"""测试脚本：从视频文件读取内容，转为 base64 data URL，通过 /chat/completions 发送到视觉 API。

用法：
    python scripts/test_video_base64.py
    python scripts/test_video_base64.py --video "path/to/video.mp4"
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import sys
import time
from pathlib import Path

import httpx

# 确保 backend 目录在 Python 路径中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_video_base64")


# 代理上支持视频理解的模型列表（通过 /chat/completions）
# Gemini 系列需要原生格式不支持，Qwen-VL 系列原生兼容 OpenAI 格式
VIDEO_CAPABLE_MODELS = [
    "qwen2.5-vl-32b-instruct",    # 已验证支持视频
    "qwen3-vl-flash",             # 最快
    "qwen3-vl-plus",              # 均衡
    "qwen3-vl-32b-instruct",      # 最新
    "qwen3-vl-32b-thinking",      # 带推理
    "qwen3-omni-flash",           # 全模态
    "qwen3.5-omni-flash",         # 最新全模态
    "qwen-vl-max",                # 旧版但稳定
    "gemini-2.5-flash",           # 需要原生格式（当前配置）
]


def load_visual_config() -> dict:
    """从数据库 PlatformSetting 读取视觉 API 配置。"""
    from database import SessionLocal
    from models import PlatformSetting

    db = SessionLocal()
    try:
        def get_val(key: str) -> str:
            row = db.query(PlatformSetting).filter(
                PlatformSetting.setting_key == key
            ).first()
            if not row or not row.value_json:
                return ""
            return str(row.value_json.get("value", ""))

        base_url = get_val("visual_api.base_url")
        model = get_val("visual_api.model")
        api_key = get_val("visual_api.api_key")

        if not base_url:
            raise SystemExit("错误：数据库未配置 visual_api.base_url")
        if not model:
            raise SystemExit("错误：数据库未配置 visual_api.model")
        if not api_key:
            raise SystemExit("错误：数据库未配置 visual_api.api_key")

        logger.info("从数据库读取配置:")
        logger.info("  base_url = %s", base_url)
        logger.info("  model    = %s", model)
        logger.info("  api_key  = %s...%s", api_key[:8], api_key[-4:])

        return {"base_url": base_url.rstrip("/"), "model": model, "api_key": api_key}
    finally:
        db.close()


def find_video(video_path: str | None = None) -> str:
    """找测试视频文件。"""
    if video_path:
        p = Path(video_path)
        if not p.exists():
            raise SystemExit(f"错误：视频文件不存在: {p}")
        return str(p.resolve())

    analysis_dir = Path(__file__).resolve().parent.parent / "video_outputs" / "analysis_inputs"
    if not analysis_dir.exists():
        raise SystemExit(f"错误：analysis_inputs 目录不存在: {analysis_dir}")

    mp4_files = sorted(analysis_dir.glob("*.mp4"))
    if not mp4_files:
        raise SystemExit(f"错误：analysis_inputs 目录下没有 mp4 文件: {analysis_dir}")

    video = str(mp4_files[0].resolve())
    logger.info("自动选择视频: %s", video)
    return video


def video_to_base64_data_url(video_path: str) -> tuple[str, int]:
    """读取视频文件，返回 (data_url, 原始字节数)。"""
    path_obj = Path(video_path)
    video_bytes = path_obj.read_bytes()
    raw_size = len(video_bytes)

    ext = video_path.lower().rsplit(".", 1)[-1] if "." in video_path else "mp4"
    mime_map = {
        "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
        "avi": "video/x-msvideo", "mkv": "video/x-matroska",
    }
    mime = mime_map.get(ext, "video/mp4")

    b64 = base64.b64encode(video_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    logger.info("视频: %.1f MB → base64 data URL (%.1f MB)",
                raw_size / 1024 / 1024, len(data_url) / 1024 / 1024)
    return data_url, raw_size


async def send_to_api(
    config: dict,
    data_url: str,
    prompt: str,
    max_tokens: int = 65536,
) -> dict:
    """发送请求到 /chat/completions，返回完整响应信息。"""
    url = f"{config['base_url']}/chat/completions"
    payload = {
        "model": config["model"],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "max_tokens": max_tokens,
    }

    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }

    logger.info("发送请求...")
    logger.info("  POST %s", url)
    logger.info("  model: %s", config["model"])
    payload_size = len(json.dumps(payload))
    logger.info("  payload: %.1f MB", payload_size / 1024 / 1024)

    start = time.time()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=60, read=600, write=300, pool=60)
        ) as client:
            response = await client.post(url, json=payload, headers=headers)
        elapsed = time.time() - start
        logger.info("响应耗时: %.1f 秒", elapsed)
        logger.info("HTTP 状态码: %d", response.status_code)

        result = {
            "elapsed": elapsed,
            "status_code": response.status_code,
            "success": response.is_success,
        }

        if response.is_success:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            result["response_length"] = len(content)
            result["content_preview"] = content[:500]
            # 尝试解析 JSON
            try:
                parsed = json.loads(content)
                result["parsed_json"] = parsed
            except json.JSONDecodeError:
                result["parsed_json"] = None
                result["parse_error"] = "非 JSON 响应"
        else:
            result["response_body"] = response.text[:1000]
            # 检查是否是 API 不支持视频格式
            if response.status_code in (400, 415):
                result["error_type"] = "format_not_supported"
            elif response.status_code == 504:
                result["error_type"] = "gateway_timeout"
            elif response.status_code >= 500:
                result["error_type"] = "server_error"
            else:
                result["error_type"] = "other"

        return result

    except httpx.TimeoutException as e:
        elapsed = time.time() - start
        logger.error("超时: %.1f 秒 - %s", elapsed, e)
        return {"elapsed": elapsed, "success": False, "error_type": "timeout", "error": str(e)}
    except Exception as e:
        elapsed = time.time() - start
        logger.error("请求异常: %s", e)
        return {"elapsed": elapsed, "success": False, "error_type": "exception", "error": str(e)}


async def main():
    parser = argparse.ArgumentParser(description="测试视频 base64 data URL 发送到视觉 API")
    parser.add_argument("--video", "-v", help="视频文件路径（不指定则自动选择）")
    parser.add_argument("--model", "-m", help="模型名称（覆盖数据库配置）")
    parser.add_argument("--batch", "-b", action="store_true",
                        help="批量测试所有支持视频的模型")
    parser.add_argument("--prompt", "-p", default="请详细描述这个视频的内容，包括场景、角色、动作和镜头运动。",
                        help="发送的提示词")
    parser.add_argument("--max-tokens", type=int, default=65536, help="max_tokens")
    args = parser.parse_args()

    print("=" * 60)
    print("  视频 base64 data URL 测试")
    print("=" * 60)

    # 1. 读配置
    config = load_visual_config()

    if args.model:
        config["model"] = args.model
        logger.info("覆盖模型: %s", args.model)

    # 2. 找视频
    video_path = find_video(args.video)

    # 3. 转 base64
    data_url, raw_size = video_to_base64_data_url(video_path)
    print()

    models_to_test = []
    if args.batch:
        models_to_test = VIDEO_CAPABLE_MODELS
        if args.model:
            models_to_test = [args.model] + [m for m in models_to_test if m != args.model]
    else:
        models_to_test = [config["model"]]

    results = []
    for model in models_to_test:
        config["model"] = model
        print("=" * 60)
        print(f"  测试模型: {model}")
        print("=" * 60)
        result = await send_to_api(config, data_url, args.prompt, args.max_tokens)

        results.append({"model": model, "result": result})

        if result["success"]:
            print(f"  ✅ 成功 ({result['elapsed']:.1f}s, {result['response_length']} chars)")
            print()
            print("--- 响应预览 ---")
            print(result["content_preview"])
            print("---")

            if result.get("parsed_json"):
                print()
                pj = result["parsed_json"]
                if isinstance(pj, dict):
                    for k, v in pj.items():
                        if isinstance(v, list):
                            print(f"  {k}: [{len(v)} 项]")
                            if len(v) > 0:
                                print(f"    首项: {json.dumps(v[0], ensure_ascii=False)[:200]}")
                        elif isinstance(v, dict):
                            short = json.dumps(v, ensure_ascii=False)[:200]
                            print(f"  {k}: {{{short}}}")
                        else:
                            print(f"  {k}: {json.dumps(v, ensure_ascii=False)[:200]}")
        else:
            print(f"  ❌ 失败 ({result['elapsed']:.1f}s)")
            print(f"     错误: {result.get('error_type', 'unknown')}")
            if result.get("response_body"):
                print(f"     响应: {result['response_body'][:200]}")
            if result.get("error"):
                print(f"     异常: {result['error']}")
        print()

    if len(results) > 1:
        print("=" * 60)
        print("  批量测试汇总")
        print("=" * 60)
        for r in results:
            status = "✅" if r["result"]["success"] else "❌"
            detail = f"{r['result']['elapsed']:.1f}s" if r["result"]["success"] else r["result"].get("error_type", "?")
            print(f"  {status} {r['model']:40s} {detail}")
        print()

    success_count = sum(1 for r in results if r["result"]["success"])
    return 0 if success_count > 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
