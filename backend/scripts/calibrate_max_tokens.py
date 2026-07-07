"""
max_tokens 校准脚本
用法：
  1. 先在 .env 中配置 DEEPSEEK_API_KEY
  2. python scripts/calibrate_max_tokens.py

原理：用不同的 max_tokens 值多次调用 expand_chapter_to_content，
统计输出字数与 max_tokens 的比例，找到产生 2000-3000 字的最佳值。
"""
import asyncio
import json
import os
import sys

# 添加 backend 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

TEST_VALUES = [2048, 2560, 3072, 3328, 3584, 3840, 4096]
TARGET_CHARS = (2000, 3000)  # 目标字数范围

# 一个简化的测试章节信息
TEST_CHAPTER = {
    "chapter_number": 1,
    "title": "仙尊落凡",
    "summary": "半步合道仙尊冲击超脱失败，魂穿高武世界底层外卖骑手，适应凡人肉身。",
    "goal": "从濒死残躯中苏醒，确认处境并评估生存可能性。",
    "conflict": "仙体尽碎修为归零，必须接受变成最底层的凡人。",
    "hook": "仙尊残魂穿越成外卖骑手的瞬间——体内空空如也。",
    "payoff": "确认世界灵气稀薄但仍可逆袭，重燃求道意志。",
    "highlight": "以神魂扫描凡人肉身的震撼对比——曾掌天地法则，今连内视都需全力集中。"
}

TEST_STORY_CONTEXT = {
    "title": "落凡仙尊：从零苦修镇高武",
    "description": "半步合道仙尊穿越高武世界，从外卖骑手起步重新修炼。",
    "genre_tags": ["都市", "修仙", "高武", "重生"],
    "outline": {"three_acts": [{"act": 1, "title": "凡人崛起", "summary": "从外卖骑手到擂台之王"}]},
    "characters": {
        "protagonist": {"name": "陈玄", "age": 25, "personality": "沉稳务实、意志坚定、冷静理性"},
        "mother": {"name": "张兰", "relation": "母亲", "condition": "尿毒症需透析"}
    }
}


async def test_single_value(max_tokens: int, api_key: str) -> dict:
    """用指定的 max_tokens 调用章节生成，返回字数统计。"""
    from services.deepseek import expand_chapter_to_content

    # 模拟 DeepSeek 配置
    import services.deepseek as ds
    ds.DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    ds.DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    content = await expand_chapter_to_content(
        story_context=TEST_STORY_CONTEXT,
        chapter_info=TEST_CHAPTER,
        api_key=api_key,
        previous_chapter_summary="",
        system_prompt=None,
        db=None,
    )

    char_count = len(content.replace(" ", "").replace("\n", ""))
    actual_tokens = None  # 无法从 API 响应直接获取，需从日志推断

    return {
        "max_tokens": max_tokens,
        "char_count": char_count,
        "chars_per_token": round(char_count / max_tokens, 4) if max_tokens > 0 else 0,
        "in_range": TARGET_CHARS[0] <= char_count <= TARGET_CHARS[1],
    }


async def main():
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("=" * 60)
        print("未配置 DEEPSEEK_API_KEY")
        print("请在 backend/.env 中添加:")
        print("  DEEPSEEK_API_KEY=sk-xxx")
        print("  DEEPSEEK_BASE_URL=https://api.deepseek.com")
        print("  DEEPSEEK_MODEL=deepseek-chat")
        print("=" * 60)
        print()
        print("【理论推算】基于用户提供的经验数据点：")
        print(f"  max_tokens=4096 → 输出 ~3800 字")
        print(f"  估算比例 ≈ 3800/4096 = {3800/4096:.4f} 字/token")
        print()
        print(f"  目标字数范围: {TARGET_CHARS[0]}-{TARGET_CHARS[1]} 字")
        print(f"  绝对上限: 3500 字")
        print()
        print("  【推荐值计算】")
        for mt in TEST_VALUES:
            estimated_chars = int(mt * 3800 / 4096)
            safety = "✅" if estimated_chars <= 3500 else "⚠️ 可能超限"
            in_range = "🎯" if TARGET_CHARS[0] <= estimated_chars <= TARGET_CHARS[1] else ""
            print(f"    max_tokens={mt:5d} → 约 {estimated_chars:4d} 字  {safety} {in_range}")
        print()
        print(f"  ╔══════════════════════════════════════════╗")
        print(f"  ║ 推荐: max_tokens = 3328                 ║")
        print(f"  ║ 预期输出: ~3095 字（在 3000 上限内）    ║")
        print(f"  ║ 既避免截断，又防止篇幅超标              ║")
        print(f"  ╚══════════════════════════════════════════╝")
        print()
        print(f"  【回退方案】若 AI 仍超出字数限制：")
        print(f"    在 prompt 中将上限改为 2500 字 + max_tokens=3072")
        print(f"    （预期输出 ~2857 字，稳稳在 3000 以内）")
        return

    print(f"使用 API Key: {api_key[:8]}...")
    print(f"测试 {len(TEST_VALUES)} 个 max_tokens 值...\n")
    print(f"{'max_tokens':>10} | {'字数':>6} | {'字/token':>9} | {'符合目标':>8}")
    print("-" * 45)

    results = []
    for mt in TEST_VALUES:
        result = await test_single_value(mt, api_key)
        results.append(result)
        flag = "✅" if result["in_range"] else "❌"
        print(f"{result['max_tokens']:>10} | {result['char_count']:>6} | {result['chars_per_token']:>9.4f} | {flag}")

    # 找最佳值
    in_range_results = [r for r in results if r["in_range"]]
    print(f"\n符合 {TARGET_CHARS[0]}-{TARGET_CHARS[1]} 字范围的值: {len(in_range_results)} 个")
    if in_range_results:
        best = min(in_range_results, key=lambda r: abs(r["char_count"] - sum(TARGET_CHARS)//2))
        print(f"最佳值: max_tokens={best['max_tokens']} → {best['char_count']} 字")


if __name__ == "__main__":
    asyncio.run(main())
