"""画布资产分析：只提取"值得单独生成参考图"的资产，其余交给分镜提示词一句带过。

省成本的设计：
- 一次调用完成风格规范、角色档案、关键场景/道具筛选与它们的绘图提示词（不再逐场景反复调用）；
- 角色提示词只调用一次（此前每个场景都会重复生成同一批角色）；
- 场景/道具必须"反复出现或推动剧情"才入选，数量有上限，其余作为「可选资产」交给用户决定。
"""

from __future__ import annotations

import logging
from typing import Any

from services.errors import UpstreamServiceError
from services.screenplay_meta import is_meta_label, strip_meta_beats

logger = logging.getLogger(__name__)

MAX_SCENE_ASSETS = 4
MAX_PROP_ASSETS = 5
MAX_OPTIONAL = 10
# 道具没有跨场景出现时，正文里至少反复提到这么多次才算"高度出现"
MIN_PROP_MENTIONS = 3

ASSET_TRIAGE_SYSTEM_PROMPT = """你是漫剧美术指导兼角色设计总监。阅读完整剧本与分场信息，一次性输出全片视觉规范、角色档案，以及"值得单独生成参考图"的场景与道具。
输出纯JSON：
{"style":{"art_style":"画风与材质","palette":"主色调与冷暖关系","lighting":"整体光线逻辑","mood":"情绪基调"},
 "characters":[{"name":"剧本原名","profile":"年龄段、身份、性格气质、体型与发型、标志性服装，80字以内"}],
 "scenes":[{"name":"地点（时间/天气，仅光线差异明显时才区分）","scene_ids":["1","3"],"prompt":"场景参考图绘图提示词，空镜无人物，80字以内"}],
 "props":[{"name":"剧本原词","scene_ids":["1","2"],"prompt":"道具参考图绘图提示词，单个物体特写，60字以内"}],
 "optional":[{"role":"scene或prop","name":"剧本原词","scene_ids":["2"],"desc":"一句话说明它是什么、为什么有一定价值"}]}
筛选规则（必须严格执行，目的是节省成本，不要贪多）：
- scenes：同一地点在 2 个及以上分场出现，或是全片视觉核心地标，才放入；最多 4 个。
- props：在 2 个及以上分场反复出现，或直接推动剧情转折（关键证物、信物）才放入；最多 5 个。
- 只出现一次的普通场景与道具不要放进 scenes 或 props；其中有一定价值的最多挑 10 个放进 optional，其余直接忽略，分镜提示词一句带过即可。
- 名称必须是剧本里出现过的原词，不要合并成新造词，不要把动作、表情、屏幕内容当作道具。
- scene_ids 只能使用输入里给出的分场编号。
- 角色外观剧本没写的，按身份合理设定但必须具体；所有风格必须统一协调。"""

CHARACTER_CONTEXT_CHARS = 600


def _scene_brief(scene: dict[str, Any]) -> str:
    beats = [b for b in (scene.get("beats") or []) if isinstance(b, dict)]
    text = " ".join(str(b.get("source_text") or b.get("action") or "") for b in beats).replace("\n", " ").strip()
    purpose = str(scene.get("scene_purpose") or "").strip()
    return (
        f"[{scene.get('scene_id')}] 地点:{scene.get('location') or scene.get('title') or ''} | 时间:{scene.get('time_of_day') or ''} | "
        f"人物:{'、'.join(str(c) for c in (scene.get('characters') or []))} | 概要:{(purpose or text)[:120]}"
    )


def _valid_ids(value: Any, known: set[str]) -> list[str]:
    ids = value if isinstance(value, list) else []
    return list(dict.fromkeys(str(i) for i in ids if str(i) in known))


def _mentions(text: str, name: str) -> int:
    return text.count(name) if name else 0


def select_assets(triage: dict[str, Any], scenes: list[dict[str, Any]], screenplay_text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按硬规则二次筛选模型返回的场景/道具，返回 (入选资产, 可选候选)。不信任模型的数量与判断。"""
    known = {str(s.get("scene_id")) for s in scenes}
    selected: list[dict[str, Any]] = []
    optional: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def push_optional(role: str, name: str, scene_ids: list[str], desc: str) -> None:
        if len(optional) < MAX_OPTIONAL and (role, name) not in seen:
            seen.add((role, name))
            optional.append({"role": role, "name": name, "scene_ids": scene_ids, "desc": desc})

    for role, key, limit in (("scene", "scenes", MAX_SCENE_ASSETS), ("prop", "props", MAX_PROP_ASSETS)):
        count = 0
        for item in triage.get(key) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            prompt = str(item.get("prompt") or "").strip()
            ids = _valid_ids(item.get("scene_ids"), known)
            if not name or (role, name) in seen:
                continue
            base_name = name.split("（", 1)[0].strip()
            # 场景需跨分场复用；道具需跨分场出现，或正文里被反复提及，且名称必须真实出现在剧本里。
            recurring = len(ids) >= 2 or (role == "prop" and _mentions(screenplay_text, name) >= MIN_PROP_MENTIONS)
            grounded = _mentions(screenplay_text, base_name) >= 1
            if recurring and grounded and prompt and count < limit:
                seen.add((role, name))
                selected.append({"role": role, "name": name, "prompt": prompt, "scene_ids": ids, "unit_count": max(1, len(ids))})
                count += 1
            elif grounded:
                push_optional(role, name, ids, str(item.get("reason") or item.get("desc") or "").strip() or f"{'场景' if role == 'scene' else '道具'}「{name}」")
    for item in triage.get("optional") or []:
        if not isinstance(item, dict):
            continue
        role = "scene" if str(item.get("role")) == "scene" else "prop"
        name = str(item.get("name") or "").strip()
        if name and _mentions(screenplay_text, name.split("（", 1)[0].strip()) >= 1:
            push_optional(role, name, _valid_ids(item.get("scene_ids"), known), str(item.get("desc") or "").strip() or name)
    return selected, optional


async def analyze_scene_assets(
    *,
    scenes: list[dict[str, Any]],
    screenplay_text: str,
    api_key: str | None = None,
    style_hint: str | None = None,
) -> dict[str, Any]:
    """资产分析：角色（全部）+ 关键场景/道具（按重要性筛选），其余作为可选候选返回。"""
    from services import deepseek as deepseek_service
    from services import video_canvas_director as director

    warnings: list[str] = []
    failed_calls = 0
    scenes = strip_meta_beats(scenes)
    names = list(dict.fromkeys(
        str(c).strip() for scene in scenes for c in (scene.get("characters") or []) if str(c or "").strip() and not is_meta_label(str(c))
    ))

    # ① 一次调用：风格 + 角色档案 + 关键场景/道具（含提示词）+ 可选候选
    triage: dict[str, Any] = {}
    try:
        data = await director._call_deepseek_json(
            system=ASSET_TRIAGE_SYSTEM_PROMPT,
            user=(f"用户已选定画风（所有提示词必须遵循，不要另起风格；style 字段直接沿用它）：{style_hint}\n\n" if style_hint else "") + f"角色：{'、'.join(names) or '无'}\n\n## 分场\n" + "\n".join(_scene_brief(s) for s in scenes) + f"\n\n## 完整剧本\n{screenplay_text}",
            api_key=api_key,
            max_tokens=8192,
        )
        triage = data if isinstance(data, dict) else {}
    except Exception as exc:
        warnings.append(f"资产筛选失败（{type(exc).__name__}），本次只提取角色，场景与道具由分镜提示词直接描述")

    style = triage.get("style") if isinstance(triage.get("style"), dict) else {}
    style_line = style_hint or "；".join(str(style.get(k) or "").strip() for k in ("art_style", "palette", "lighting", "mood") if str(style.get(k) or "").strip())
    profiles = {
        str(item.get("name") or "").strip(): str(item.get("profile") or "").strip()
        for item in triage.get("characters") or []
        if isinstance(item, dict) and str(item.get("name") or "").strip() and str(item.get("profile") or "").strip()
    }

    assets: list[dict[str, Any]] = []

    # ② 角色提示词：整部剧只调用一次
    if names:
        scene_ids_by_name = {n: [str(s.get("scene_id")) for s in scenes if n in [str(c).strip() for c in (s.get("characters") or [])]] for n in names}
        shot_data = {
            "scene_location": "",
            "time_of_day": "",
            "story_summary": screenplay_text[:CHARACTER_CONTEXT_CHARS],
            "dialogue_or_narration": "",
            "characters": names,
            "chapter_text": screenplay_text,
            "source_text_span": "全片角色",
            "camera_plan": "", "motion_plan": "", "emotion_plan": "", "key_props": [], "scene_asset_candidates": [],
        }
        profile_text = "\n".join(f"- {n}：{profiles[n]}" for n in names if n in profiles)
        try:
            char_prompts = await deepseek_service.generate_shot_character_prompts_ai(shot_data, profile_text, api_key)
        except Exception as exc:
            failed_calls += 1
            warnings.append(f"角色分析失败（{type(exc).__name__}），已跳过")
            char_prompts = []
        for entry in char_prompts or []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            prompt = str(entry.get("prompt") or "").strip()
            if name and prompt:
                asset = {"role": "character", "name": name, "prompt": director._with_style(prompt, style_line), "scene_ids": scene_ids_by_name.get(name, []), "unit_count": max(1, len(scene_ids_by_name.get(name, [])))}
                if name in profiles:
                    asset["profile"] = profiles[name]
                assets.append(asset)

    # ③ 关键场景/道具：硬规则二次筛选，提示词已在第一步生成
    selected, optional = select_assets(triage, scenes, screenplay_text)
    for item in selected:
        item["prompt"] = director._with_style(item["prompt"], style_line)
        assets.append(item)

    order = {"character": 0, "scene": 1, "prop": 2}
    assets.sort(key=lambda item: (order.get(item["role"], 9), item["name"]))
    if not assets:
        raise UpstreamServiceError(
            "资产分析未得到任何角色/场景/道具提示词，请重试或检查文本模型配置",
            retryable=True,
            provider="DeepSeek",
            status_code=502,
            code="asset_analysis_empty",
            diagnostics={"failed_calls": failed_calls},
        )
    return {"assets": assets, "candidates": optional, "warnings": warnings, "failed_calls": failed_calls}
