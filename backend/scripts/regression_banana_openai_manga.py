#!/usr/bin/env python3
"""真实验证 OpenAI 兼容协议下 Banana 的漫画多参考图能力。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from PIL import Image, ImageDraw

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from database import SessionLocal
from models import AiChannel, AiModel
from services import image2
from services.ai.channels import load_platform_key, validate_remote_media_url


DEFAULT_REFS = {
    "style": BACKEND_DIR / "manga_outputs/style-presets/style_1_20260718_124651.png",
    "character": BACKEND_DIR / "manga_outputs/story_12/assets/asset_6a95b069e05a41baa3bb3ad508b008fa.png",
    "scene": BACKEND_DIR / "manga_outputs/story_12/assets/asset_5ab666224d83474ba780b86e74070fb1.png",
    "prop": BACKEND_DIR / "manga_outputs/story_12/assets/asset_563d7d843ac84234916ce19be1e60cc1.png",
}

SCENES = [
    "陈玄保持角色参考图中的脸型、发型、身形和灰黑服装，站在出租屋参考场景的木桌旁，双手拿起父亲留下的秘境笔记。笔记必须保持道具参考图中的黄褐色纸张、深蓝墨迹、红色批注和磨损边缘。中景，人物神情警觉，房间布局、材质、光照严格沿用场景参考图。",
    "同一时间连续镜头。陈玄仍穿完全相同的灰黑服装，脸型、发型和体型不变。他走到出租屋窗边，右手握着同一本秘境笔记，翻开的页面仍有深蓝墨迹与红色批注。镜头从侧后方拍摄，出租屋结构、木桌位置和昏黄光线与上一格连续。",
]

CHARACTER_PROFILE = (
    "陈玄，25岁，身高175cm，清瘦但有韧性；短而略乱的黑发，深色眼睛，面容疲惫但目光冷静。"
    "固定服装为黑色旧夹克、深灰T恤、磨旧深蓝牛仔裤和黑色运动鞋。所有漫画格必须保持身份、脸、发型、体型和服装一致。"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="执行真实 API 调用；不传时只检查配置和素材")
    parser.add_argument("--model-id", type=int, help="图片模型 ID；默认自动选择名称包含 gemini 或 banana 的可用模型")
    parser.add_argument("--size", default="1024x1536", help="输出尺寸，默认 1024x1536")
    parser.add_argument("--output-dir", type=Path, help="报告目录；默认写入 manga_outputs/regression")
    parser.add_argument("--style", type=Path, default=DEFAULT_REFS["style"])
    parser.add_argument("--character", type=Path, default=DEFAULT_REFS["character"])
    parser.add_argument("--scene", type=Path, default=DEFAULT_REFS["scene"])
    parser.add_argument("--prop", type=Path, default=DEFAULT_REFS["prop"])
    return parser.parse_args()


def _workspace_path(path: Path, *, output: bool = False) -> Path:
    resolved = path.resolve()
    root = (BACKEND_DIR / "manga_outputs" / "regression").resolve() if output else BACKEND_DIR.resolve()
    if resolved != root and root not in resolved.parents:
        scope = "回归输出目录" if output else "backend 工作区"
        raise RuntimeError(f"路径必须位于 {scope} 内: {resolved}")
    return resolved


def _safe_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.hostname:
        return "<invalid-url>"
    host = parsed.hostname
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, f"{host}{port}", parsed.path.rstrip("/"), "", ""))


def _safe_error(value: object) -> str:
    return re.sub(r"https?://[^\s'\"]+", "<remote-url>", str(value))[:1000]


def resolve_model(model_id: int | None) -> tuple[AiModel, AiChannel, str]:
    with SessionLocal() as db:
        query = db.query(AiModel, AiChannel).join(AiChannel, AiChannel.id == AiModel.channel_id).filter(
            AiModel.modality == "image",
            AiModel.enabled.is_(True),
            AiChannel.enabled.is_(True),
        )
        rows = query.all()
        selected = next(((model, channel) for model, channel in rows if model.id == model_id), None) if model_id else None
        if selected is None and model_id is None:
            selected = next(
                (
                    (model, channel)
                    for model, channel in rows
                    if "gemini" in model.model_key.lower() or "banana" in model.model_key.lower()
                ),
                None,
            )
        if selected is None:
            raise RuntimeError("未找到可用 Banana/Gemini 图片模型，请通过 --model-id 指定")
        model, channel = selected
        model_key = model.model_key.lower()
        if "gemini" not in model_key and "banana" not in model_key:
            raise RuntimeError(f"模型 {model.model_key} 不是 Banana/Gemini 模型，拒绝执行真实回归")
        api_key = load_platform_key(channel) or ""
        if not api_key:
            raise RuntimeError("选中渠道未配置平台 API Key")
        db.expunge(model)
        db.expunge(channel)
        return model, channel, api_key


def inspect_image(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        width, height = image.size
        image_format = image.format
    return {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "width": width,
        "height": height,
        "format": image_format,
    }


def safe_result_url(url: str) -> str:
    """测试进程内将受信任 CDN 的 HTTP 地址升级为同源 HTTPS。"""
    parsed = urlsplit(url.strip())
    if parsed.scheme == "http" and (parsed.hostname or "").lower() == "nana.code2alita.com":
        parsed = parsed._replace(scheme="https", netloc=parsed.hostname or "")
        url = urlunsplit(parsed)
    return validate_remote_media_url(url)


def build_contact_sheet(refs: list[tuple[str, Path]], pages: list[Path], output_path: Path) -> None:
    items = [(f"REF {role}", path) for role, path in refs] + [
        (f"OUTPUT PAGE {index}", path) for index, path in enumerate(pages, start=1)
    ]
    thumb_width, thumb_height, label_height = 360, 420, 36
    sheet = Image.new("RGB", (thumb_width * 3, (thumb_height + label_height) * 2), "#eef2f7")
    draw = ImageDraw.Draw(sheet)
    for index, (label, path) in enumerate(items):
        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail((thumb_width - 16, thumb_height - 16))
            x = (index % 3) * thumb_width + (thumb_width - image.width) // 2
            y = (index // 3) * (thumb_height + label_height) + label_height + (thumb_height - image.height) // 2
            sheet.paste(image, (x, y))
        draw.text(((index % 3) * thumb_width + 10, (index // 3) * (thumb_height + label_height) + 10), label, fill="#111827")
    sheet.save(output_path, format="JPEG", quality=90)


async def execute(args: argparse.Namespace) -> int:
    model, channel, api_key = resolve_model(args.model_id)
    refs = [
        ("style", _workspace_path(args.style)),
        ("character", _workspace_path(args.character)),
        ("scene", _workspace_path(args.scene)),
        ("prop", _workspace_path(args.prop)),
    ]
    try:
        ref_metadata = [(role, path, inspect_image(path)) for role, path in refs]
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise RuntimeError(f"参考图不存在或无法解码: {exc}") from exc

    print(f"模型: {model.display_name or model.model_key} ({model.model_key})")
    print(f"渠道: {channel.name} / adapter={channel.adapter_type}")
    print(f"Base URL: {_safe_endpoint(channel.base_url)}")
    print(f"参考图: {len(refs)} 张，协议预期为 /images/edits + image[]")
    if not args.execute:
        print("配置与素材检查通过。添加 --execute 执行两次真实生图调用。")
        return 0

    run_id = datetime.now().strftime("banana_openai_%Y%m%d_%H%M%S")
    requested_output = args.output_dir or BACKEND_DIR / "manga_outputs/regression" / run_id
    run_dir = _workspace_path(requested_output, output=True)
    run_dir.mkdir(parents=True, exist_ok=False)
    chapter_id = 990001

    image2.configure_runtime(
        base_url=channel.base_url,
        model=model.model_key,
        size=args.size,
        quality="",
        input_fidelity="high",
    )
    image2.OUTPUT_DIR = run_dir
    image2.MAX_RETRIES = 1
    image2._safe_generated_image_url = safe_result_url
    image2._upload_image_url_to_oss = lambda *_args, **_kwargs: None
    image2._upload_to_oss_if_enabled = lambda *_args, **_kwargs: None

    ref_paths = [str(path) for role, path in refs if role != "style"]
    ref_labels = ["陈玄", "出租屋", "秘境笔记（父亲遗物）"]
    ref_roles = ["character", "scene", "prop"]
    pages: list[dict[str, object]] = []
    generated_paths: list[Path] = []

    for page_number, prompt in enumerate(SCENES, start=1):
        started = time.perf_counter()
        page_result: dict[str, object] = {"page": page_number, "prompt": prompt}
        try:
            await image2.generate_manga_image(
                prompt=prompt,
                chapter_id=chapter_id,
                image_number=page_number,
                all_scenes=SCENES,
                character_profiles=CHARACTER_PROFILE,
                ref_image_paths=ref_paths,
                ref_labels=ref_labels,
                ref_roles=ref_roles,
                color_mode="color",
                api_key=api_key,
                size=args.size,
                style_ref_path=str(refs[0][1]),
            )
            candidates = sorted((run_dir / f"chapter_{chapter_id}").glob(f"panel_{page_number:02d}_*.png"))
            if not candidates:
                raise RuntimeError("API 返回成功，但未找到生成文件")
            output_path = candidates[-1]
            generated_paths.append(output_path)
            page_result.update({"status": "passed", "elapsed_seconds": round(time.perf_counter() - started, 2), "output": inspect_image(output_path)})
        except Exception as exc:
            page_result.update({"status": "failed", "elapsed_seconds": round(time.perf_counter() - started, 2), "error_type": type(exc).__name__, "error": _safe_error(exc)})
            pages.append(page_result)
            break
        pages.append(page_result)

    report = {
        "run_id": run_id,
        "protocol": "openai_compatible_images_edits_multipart_image_array",
        "storage_isolation": "OSS disabled; trusted nana HTTP result URLs upgraded to same-host HTTPS inside this script only",
        "model": {"id": model.id, "key": model.model_key, "display_name": model.display_name, "channel": channel.name, "adapter": channel.adapter_type, "base_url": _safe_endpoint(channel.base_url)},
        "references": [{"role": role, **metadata} for role, _, metadata in ref_metadata],
        "pages": pages,
        "protocol_verdict": "passed" if len(pages) == 2 and all(page["status"] == "passed" for page in pages) else "failed",
        "visual_verdict": "manual_review_required" if len(generated_paths) == 2 else "not_available",
        "visual_checklist": ["画风与 style 参考一致", "陈玄脸型发型体型服装一致", "出租屋布局材质光线一致", "秘境笔记外观一致", "两页人物与场景连续"],
    }
    report_path = run_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if len(generated_paths) == 2:
        build_contact_sheet(refs, generated_paths, run_dir / "contact-sheet.jpg")
    markdown = [
        f"# Banana OpenAI 漫画回归 {run_id}",
        "",
        f"- 模型：`{model.model_key}`",
        f"- 协议门禁：`{report['protocol_verdict']}`",
        f"- 视觉结论：`{report['visual_verdict']}`",
        "- 说明：真实请求使用 4 张参考图；OSS 与结果 HTTP 跳转问题在脚本进程内隔离。",
        "",
        "## 人工检查",
        "",
        *[f"- [ ] {item}" for item in report["visual_checklist"]],
    ]
    (run_dir / "report.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    print(f"报告目录: {run_dir}")
    print(f"协议门禁: {report['protocol_verdict']}")
    return 0 if report["protocol_verdict"] == "passed" else 2


def main() -> int:
    try:
        return asyncio.run(execute(parse_args()))
    except Exception as exc:
        print(f"回归脚本失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
