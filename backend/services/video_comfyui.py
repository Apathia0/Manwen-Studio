"""ComfyUI 本地视频生成供应商。

通过 ComfyUI 的 REST API 提交工作流、查询状态和下载结果。
支持 text-to-video 和 image-to-video 工作流模板。
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from collections.abc import Mapping
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# 默认 ComfyUI 地址（允许运行时重配，故用非全大写命名）
comfyui_base_url: str = os.getenv("COMZYUI_BASE_URL", "http://127.0.0.1:8188")
# 工作流模板目录
WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "workflows"
# 默认工作流模板文件名（text_to_video / image_to_video）
comfyui_t2v_workflow: str = os.getenv("COMZYUI_T2V_WORKFLOW", "comfyui_t2v.json")
comfyui_i2v_workflow: str = os.getenv("COMZYUI_I2V_WORKFLOW", "comfyui_i2v.json")
# 输出目录
VIDEO_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "video_outputs" / "comfyui"


def configure(
    base_url: str | None = None,
    t2v_workflow: str | None = None,
    i2v_workflow: str | None = None,
) -> None:
    """运行时配置 ComfyUI 参数（由 main.py 调用）。"""
    global comfyui_base_url, comfyui_t2v_workflow, comfyui_i2v_workflow
    if base_url:
        comfyui_base_url = base_url.rstrip("/")
    if t2v_workflow:
        comfyui_t2v_workflow = t2v_workflow
    if i2v_workflow:
        comfyui_i2v_workflow = i2v_workflow


def _load_workflow_template(workflow_name: str) -> dict[str, Any]:
    """从 workflows 目录加载 ComfyUI 工作流模板 JSON。"""
    path = WORKFLOWS_DIR / workflow_name
    if not path.exists():
        raise FileNotFoundError(
            f"ComfyUI 工作流模板未找到: {path}。"
            f"请将 ComfyUI 导出的 API 格式工作流放入 {WORKFLOWS_DIR} 目录。"
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _resolve_workflow(
    input_mode: str,
    workflow_name: str | None = None,
) -> str:
    """根据输入模式决定使用哪个工作流模板。"""
    if workflow_name:
        return workflow_name
    if input_mode == "image_to_video":
        return comfyui_i2v_workflow
    return comfyui_t2v_workflow


def _patch_workflow(
    workflow: dict[str, Any],
    *,
    prompt: str,
    model: str | None = None,
    reference_image: str | None = None,
    duration_seconds: int = 5,
) -> dict[str, Any]:
    """修补工作流模板中的节点入参。

    通过节点标题（title）查找需要替换的节点。
    如果工作流中没有对应标题的节点，静默跳过。
    """
    patch_count = 0
    for node_id, node in workflow.items():
        title = node.get("_meta", {}).get("title", "")
        inputs = node.get("inputs", {})

        if title == "Prompt" and "text" in inputs:
            inputs["text"] = prompt
            patch_count += 1

        if title == "正面提示词" and "text" in inputs:
            inputs["text"] = prompt
            patch_count += 1

        if title == "Checkpoint Loader" and "ckpt_name" in inputs and model:
            inputs["ckpt_name"] = model
            patch_count += 1

        if title == "模型" and "ckpt_name" in inputs and model:
            inputs["ckpt_name"] = model
            patch_count += 1

        if title == "加载图片" and "image" in inputs and reference_image:
            inputs["image"] = reference_image
            patch_count += 1

        if title == "参考图片" and "image" in inputs and reference_image:
            inputs["image"] = reference_image
            patch_count += 1

        if title == "帧数" and "int" in inputs:
            inputs["int"] = duration_seconds * 8  # 8fps 估算
            patch_count += 1

        if title == "长度" and "int" in inputs:
            inputs["int"] = duration_seconds * 8
            patch_count += 1

    logger.info(
        "ComfyUI 工作流已修补 %d 个节点 (prompt_len=%d model=%s ref=%s dur=%ds)",
        patch_count, len(prompt), model or "default",
        bool(reference_image), duration_seconds,
    )
    return workflow


def _find_video_from_outputs(outputs: dict[str, Any]) -> str:
    """从 ComfyUI 工作流输出中提取视频文件名。"""
    for node_id, node_output in outputs.items():
        for key, value in node_output.items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        fname = item.get("filename", "")
                        if fname and fname.lower().endswith((".mp4", ".webm", ".gif")):
                            return fname
            elif isinstance(value, dict):
                fname = value.get("filename", "")
                if fname and fname.lower().endswith((".mp4", ".webm", ".gif")):
                    return fname
    return ""


async def submit_job(
    *,
    input_mode: str = "text_to_video",
    prompt: str,
    model: str | None = None,
    reference_images: list[str] | None = None,
    duration_seconds: int = 5,
    workflow_name: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """提交视频生成任务到本地 ComfyUI。

    Returns:
        {provider_job_id, status, progress}
    """
    url = (base_url or comfyui_base_url).rstrip("/") + "/prompt"
    client_id = str(uuid.uuid4())

    wf_name = _resolve_workflow(input_mode, workflow_name)
    template = _load_workflow_template(wf_name)
    ref_img = reference_images[0] if reference_images else None

    workflow = _patch_workflow(
        template,
        prompt=prompt,
        model=model,
        reference_image=ref_img,
        duration_seconds=duration_seconds,
    )

    payload = {
        "prompt": workflow,
        "client_id": client_id,
    }

    logger.info(
        "[comfyui] 提交工作流: url=%s input_mode=%s prompt_len=%d dur=%ds",
        url, input_mode, len(prompt), duration_seconds,
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=300, write=30)) as client:
            response = await client.post(url, json=payload)
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"无法连接到 ComfyUI ({url})，请确认 ComfyUI 已启动。"
        ) from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError("ComfyUI 连接超时") from exc

    if not response.is_success:
        raise RuntimeError(
            f"ComfyUI 提交失败 (HTTP {response.status_code}): {response.text[:300]}"
        )

    result = response.json()
    prompt_id = result.get("prompt_id", "")
    logger.info("[comfyui] 提交成功: prompt_id=%s", prompt_id)

    return {
        "provider_job_id": prompt_id,
        "status": "queued",
        "progress": 0,
    }


async def query_job(
    provider_job_id: str,
    *,
    base_url: str | None = None,
) -> dict[str, Any]:
    """查询 ComfyUI 任务状态。

    Returns:
        {status (queued|running|succeeded|failed), progress, video_url?}
    """
    url = (base_url or comfyui_base_url).rstrip("/") + f"/history/{provider_job_id}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5, read=300, write=5)) as client:
            response = await client.get(url)
    except (httpx.ConnectError, httpx.TimeoutException):
        return {"status": "running", "progress": 50}

    if response.status_code == 404:
        # 队列中尚未开始处理
        return {"status": "queued", "progress": 0}

    if not response.is_success:
        logger.warning("[comfyui] 查询失败 HTTP %s", response.status_code)
        return {"status": "failed", "progress": 0}

    data = response.json()
    prompt_data = data.get(provider_job_id, {})

    status_info = prompt_data.get("status", {})
    completed = status_info.get("completed", False)
    error_msg = prompt_data.get("status_str", "")

    if error_msg and "error" in error_msg.lower():
        return {"status": "failed", "progress": 0, "error": error_msg}

    if completed:
        outputs = prompt_data.get("outputs", {})
        filename = _find_video_from_outputs(outputs)
        video_url = ""
        if filename:
            video_url = (base_url or comfyui_base_url).rstrip("/") + f"/view/{filename}"

        return {
            "status": "succeeded",
            "progress": 100,
            "video_url": video_url,
        }

    # 还在处理中，检查 queue 状态
    queue_remaining = prompt_data.get("queue_remaining", 0)
    if queue_remaining > 0:
        return {"status": "queued", "progress": 0}

    return {"status": "running", "progress": 50}


async def download_video(
    video_url: str,
    *,
    shot_id: int,
    job_id: str,
    output_dir: Path | None = None,
) -> str:
    """从 ComfyUI 下载生成的视频文件到本地。"""
    output_dir = output_dir or VIDEO_OUTPUT_DIR
    shot_dir = output_dir / f"shot_{shot_id}"
    shot_dir.mkdir(parents=True, exist_ok=True)

    ext = ".mp4"
    for known in (".mp4", ".webm", ".gif"):
        if video_url.lower().endswith(known):
            ext = known
            break
    output_path = shot_dir / f"{job_id}{ext}"

    if output_path.exists():
        return str(output_path)

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=600, write=30),
            follow_redirects=True,
        ) as client:
            response = await client.get(video_url)
    except httpx.TransportError as exc:
        raise RuntimeError(f"ComfyUI 视频下载失败: {exc}") from exc

    if not response.is_success:
        raise RuntimeError(f"ComfyUI 视频下载失败 (HTTP {response.status_code})")

    output_path.write_bytes(response.content)
    logger.info("[comfyui] 下载完成: job=%s dest=%s", job_id, output_path)

    # OSS 上传（如已配置，上传成功后删除本地文件）
    try:
        from .oss import upload_and_cleanup as _oss_upload
        oss_url = _oss_upload(str(output_path))
        if oss_url:
            return oss_url
    except Exception:
        pass

    return str(output_path)
