#!/usr/bin/env python3
"""生成风格预设预览图脚本

使用项目的 Image2 API 生成 8 个内置风格的预览图，
保存到 frontend/src/assets/style-presets/ 目录（永久保存，提交到 git）。

使用方法：
    cd backend
    python scripts/generate_style_preset_images.py

前置条件：
    1. 后端服务已启动（或 .env 中配置了 IMAGE_API_KEY）
    2. 数据库已初始化（video_style_presets 表存在）
"""

import asyncio
import os
import sys
from pathlib import Path

# 添加 backend 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.image2 import generate_reference_image, configure_runtime
from database import SessionLocal
from models import VideoStylePreset, PlatformSetting

# 风格预设配置
STYLE_PRESETS = [
    {
        "name": "写实电影感",
        "prompt": "一位年轻女性站在城市街头，身穿米白色风衣，微微抬头望向远方。电影级真实光影，自然色彩，高细节，胶片质感。柔和的黄金时刻光线，浅景深，背景虚化。16:9 宽银幕构图，好莱坞电影截图风格。",
        "size": "1920x1080",
    },
    {
        "name": "日式动漫风",
        "prompt": "一位少女站在樱花树下，身穿水手服，齐刘海长发，大眼睛，表情温柔。日式赛璐璐动画风格，鲜艳色彩，清晰线条，角色大眼睛表现力强。Studio Ghibli 风格背景，柔和的粉色樱花飘落。16:9 动画截图风格。",
        "size": "1920x1080",
    },
    {
        "name": "3A游戏渲染",
        "prompt": "一位战士站在城堡废墟中，身穿盔甲，手持长剑，表情坚毅。虚幻引擎5级画质，写实纹理，光线追踪光照，高多边形细节。电影级光照，体积光，粒子效果。16:9 游戏过场动画风格。",
        "size": "1920x1080",
    },
    {
        "name": "水墨国风",
        "prompt": "一位古代文人站在竹林小径上，身穿青色长袍，手持折扇，表情淡然。中国水墨画风格，笔触纹理，极简构图，黑白为主淡彩点缀，诗意氛围。留白构图，意境深远。16:9 水墨画风格。",
        "size": "1920x1080",
    },
    {
        "name": "水彩手绘风",
        "prompt": "一位女孩坐在咖啡厅窗边，身穿碎花连衣裙，手捧咖啡杯，表情慵懒。水彩插画风格，柔边，纸张纹理，轻盈透气，手绘感。柔和的暖色调，水彩晕染效果。16:9 水彩插画风格。",
        "size": "1920x1080",
    },
    {
        "name": "暗黑哥特风",
        "prompt": "一位神秘人物站在古堡走廊中，身穿黑色长袍，表情冷峻。暗黑哥特风格，戏剧性阴影，低饱和度，高对比，神秘氛围。烛光照明，哥特式建筑细节。16:9 哥特电影风格。",
        "size": "1920x1080",
    },
    {
        "name": "复古胶片感",
        "prompt": "一位青年坐在老式理发店中，身穿复古衬衫，表情怀旧。70年代电影美学，暖色调，胶片颗粒，柔焦，复古镜头光晕。橙黄色调，复古家具。16:9 复古电影风格。",
        "size": "1920x1080",
    },
    {
        "name": "科技赛博风",
        "prompt": "一位黑客站在霓虹灯闪烁的雨夜街道上，身穿科技外套，表情专注。赛博朋克科幻风格，霓虹灯，暗黑都市环境，全息投影，雨夜街道。蓝紫色霓虹灯光，潮湿反射。16:9 赛博朋克电影风格。",
        "size": "1920x1080",
    },
]

# 输出目录 1: frontend/src/assets/style-presets/ (git 管理，永久保存)
FRONTEND_OUTPUT_DIR = Path(__file__).parent.parent.parent / "frontend" / "src" / "assets" / "style-presets"

# 输出目录 2: backend/manga_outputs/style-presets/ (后端服务，用于 API 访问)
BACKEND_OUTPUT_DIR = Path(__file__).parent.parent / "manga_outputs" / "style-presets"


async def generate_style_image(preset: dict, api_key: str) -> str | None:
    """生成单个风格预设的预览图，同时保存到前端和后端目录"""
    name = preset["name"]
    prompt = preset["prompt"]
    size = preset["size"]

    # 文件名：风格名称
    filename = f"{name}.png"
    frontend_path = FRONTEND_OUTPUT_DIR / filename
    backend_path = BACKEND_OUTPUT_DIR / filename

    # 如果前端目录文件已存在，跳过生成
    if frontend_path.exists():
        print(f"  [跳过] {name} - 文件已存在: {frontend_path}")
        # 确保后端目录也有副本
        if not backend_path.exists():
            import shutil
            shutil.copy2(frontend_path, backend_path)
            print(f"  [复制] {name} - 已复制到后端目录: {backend_path}")
        return str(frontend_path)

    print(f"  [生成] {name} - 开始生成...")
    try:
        # 先生成到后端目录
        result = await generate_reference_image(
            prompt=prompt,
            output_path=backend_path,
            api_key=api_key,
            size=size,
        )

        # 复制到前端目录（git 管理）
        import shutil
        shutil.copy2(backend_path, frontend_path)

        print(f"  [完成] {name} - 已保存到:")
        print(f"         前端: {frontend_path}")
        print(f"         后端: {backend_path}")
        return str(frontend_path)
    except Exception as e:
        print(f"  [错误] {name} - 生成失败: {e}")
        return None


async def update_database(image_paths: dict[str, str]):
    """更新数据库中的 image_url 字段"""
    db = SessionLocal()
    try:
        for name, path in image_paths.items():
            preset = db.query(VideoStylePreset).filter(VideoStylePreset.name == name).first()
            if preset:
                # 使用相对路径，前端通过 /static/style-presets/ 访问
                relative_path = f"style-presets/{Path(path).name}"
                preset.image_url = relative_path
                print(f"  [更新] {name} - image_url: {relative_path}")
        db.commit()
        print("\n数据库更新完成！")
    except Exception as e:
        db.rollback()
        print(f"\n数据库更新失败: {e}")
    finally:
        db.close()


async def main():
    """主函数"""
    print("=" * 60)
    print("风格预设预览图生成脚本")
    print("=" * 60)

    # 从数据库读取 API 配置
    db = SessionLocal()
    try:
        def get_setting(key, default=""):
            setting = db.query(PlatformSetting).filter(PlatformSetting.setting_key == key).first()
            if setting and setting.value_json:
                return setting.value_json.get("value", default)
            return default

        api_key = get_setting("api.image.api_key")
        base_url = get_setting("api.image.base_url", "https://newapi.aifusion6.cn/v1")
        model = get_setting("api.image.model", "default")

        if not api_key:
            print("\n错误: 数据库中未配置 Image API Key")
            print("请在管理后台 → 系统设置 → API 配置中填写 Image API Key")
            sys.exit(1)

        # 配置 image2 服务
        configure_runtime(base_url=base_url, model=model)

        print(f"\nAPI 配置:")
        print(f"  Base URL: {base_url}")
        print(f"  Model: {model}")
        print(f"  API Key: {api_key[:8]}...{api_key[-4:] if len(api_key) > 12 else '***'}")

    finally:
        db.close()

    # 创建输出目录
    FRONTEND_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    BACKEND_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n前端目录: {FRONTEND_OUTPUT_DIR}")
    print(f"后端目录: {BACKEND_OUTPUT_DIR}")

    # 生成图片
    print("\n开始生成风格预设图片...\n")
    image_paths = {}

    for preset in STYLE_PRESETS:
        path = await generate_style_image(preset, api_key)
        if path:
            image_paths[preset["name"]] = path

    # 更新数据库
    if image_paths:
        print("\n更新数据库...")
        await update_database(image_paths)

    # 统计
    print("\n" + "=" * 60)
    print(f"生成完成！成功: {len(image_paths)}/{len(STYLE_PRESETS)}")
    print("=" * 60)

    if image_paths:
        print("\n生成的文件:")
        for name, path in image_paths.items():
            print(f"  - {name}: {path}")

        print("\n下一步:")
        print("1. 将生成的图片提交到 git:")
        print("   git add frontend/src/assets/style-presets/")
        print("   git commit -m 'feat: add style preset preview images'")
        print("2. 重启后端服务使数据库更新生效")


if __name__ == "__main__":
    asyncio.run(main())
