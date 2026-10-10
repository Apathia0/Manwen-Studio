"""画布资产分析：只提取"值得单独生成参考图"的资产，其余交给分镜提示词一句带过。

省成本的设计：
- 一次调用完成风格规范、角色档案、关键场景/道具筛选与它们的绘图提示词（不再逐场景反复调用）；
- 角色提示词只调用一次（此前每个场景都会重复生成同一批角色）；
- 场景/道具必须"反复出现或推动剧情"才入选，数量有上限，其余作为「可选资产」交给用户决定。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from services.canvas_style import strip_style_text
from services.errors import UpstreamServiceError
from services.screenplay_meta import is_meta_label, strip_meta_beats

logger = logging.getLogger(__name__)

MAX_SCENE_ASSETS = 8
MAX_PROP_ASSETS = 5
MAX_OPTIONAL = 10
# 道具没有跨场景出现时，正文里至少反复提到这么多次才算"高度出现"
MIN_PROP_MENTIONS = 3

ASSET_TRIAGE_SYSTEM_PROMPT = """你是漫剧美术指导兼角色设计总监。阅读完整剧本与分场信息，一次性输出全片视觉规范、角色档案，以及"值得单独生成参考图"的场景与道具。
输出纯JSON：
{"characters":[{"name":"剧本原名","profile":"年龄段、身份、性格气质、体型与发型、标志性服装，80字以内"}],
 "scenes":[{"name":"地点（时间/天气，仅光线差异明显时才区分）","scene_ids":["1","3"],"prompt":"场景参考图绘图提示词，空镜无人物，80字以内"}],
 "props":[{"name":"剧本原词","scene_ids":["1","2"],"prompt":"道具参考图绘图提示词，单个物体特写，60字以内"}],
 "optional":[{"role":"scene或prop","name":"剧本原词","scene_ids":["2"],"desc":"一句话说明它是什么、为什么有一定价值"}],
 "roster":{"characters":[{"name":"规范名","aliases":["候选名单里指同一个人的其他写法"],"importance":"main或minor"}],"not_person":["候选名单里不是人物的条目"]}}
筛选规则（必须严格执行，目的是节省成本，不要贪多）：
- scenes：分场信息里出现的每一个不同地点都要放入（同一地点出现在多个分场只写一条；名称相近的如“周府东院”和“东院”合并为一条，用更完整的名字）；最多 8 个。
- props：在 2 个及以上分场反复出现，或直接推动剧情转折（关键证物、信物）才放入；最多 5 个。
- 只出现一次的普通道具不要放进 props；其中有一定价值的最多挑 10 个放进 optional，其余直接忽略，分镜提示词一句带过即可。
- 名称必须是剧本里出现过的原词，不要合并成新造词，不要把动作、表情、屏幕内容当作道具。
- scene_ids 只能使用输入里给出的分场编号。
- roster 是人物名册：候选名单由程序从分场里抽出，可能夹杂错误写法，请通读剧本后校正。
  · 人物 = 在剧情里行动或说话的个体：有名字的人，以及有固定称呼的人（车夫、掌柜、账房先生），有台词的一定算。
  · 候选里“人名 + 动作/神态”（如 车夫勒马、苏砚沉默片刻、周氏赶来）是同一个人的写法变体：name 填简洁的规范名（车夫、苏砚、周氏），把变体写进 aliases，不要当成新人物。
  · 候选里的群体、场景或事件描述（如 院外议论、围观众人、路人甲）不是人物，放进 not_person。
  · importance：main = 戏份多、推动剧情或有多句台词的主要人物；minor = 只露面几次或台词很少，但有名字或固定称呼。
  · name 必须是候选名单里的写法或剧本原文里的原词，不得虚构；拿不准的条目不要放进 aliases 或 not_person（保持原样）。
  · characters 里的档案只为 roster 中确实是人物的角色写，name 与 roster 的规范名一致。
- 角色外观剧本没写的，按身份合理设定但必须具体。\n- 提示词只描述内容（人物外貌与服装、场景布局与陈设、物体形态与材质细节），绝对不要出现任何画风、渲染、画质或镜头滤镜类词语（如 写实、赛璐璐、水彩、电影感、cinematic、film grain、8k）：画风由用户选定的画风参考图统一控制，不由提示词控制。"""

CHARACTER_CONTEXT_CHARS = 600

LEAN_CHARACTER_SYSTEM_PROMPT = """你是影视角色造型师。为每个角色写一段给图片模型用的外貌描述，中文，每个角色 100 到 200 字。
只写客观可见、能画出来的外貌：性别与年龄段、身高体型、脸型五官、肤色、发型发色、服装（内外层分别写颜色、材质、款式）、鞋、随身配饰和标志性特征；剧本明确写了的伤痕、污渍、病态也要写。
绝对不要写：性格、背景故事、MBTI、人生弧光、画风、渲染、画质、摄影或镜头词汇（如 写实、电影感、赛璐璐、8k、masterpiece）、设定板、三视图、版式、背景、文字标注。画风、版式由系统统一控制，不在你这里。
外貌必须具体且与剧本一致（剧本没写的按身份合理设定），不同角色之间要有清楚的区分（体型、发型、服装颜色）。同一个角色的描述要像一个真实存在的人，不要用“美丽”“帅气”这类空话。
输出 JSON：{"character_prompts": [{"name": "角色原名", "prompt": "外貌描述"}]}，每个给定角色都要有一条，name 与给定名字完全一致。"""


async def generate_character_prompts(shot_data: dict[str, Any], character_profiles: str, api_key: str | None) -> list[dict[str, Any]]:
    """角色外貌提示词（精简版）：只写可见外貌，不带设定板黑话 / 画风词 / 版式描述，输出短，一批 3 个也不会被截断。"""
    from services import video_canvas_director as director

    user = json.dumps(
        {"角色": list(shot_data.get("characters") or []), "角色档案": character_profiles, "剧本": str(shot_data.get("chapter_text") or "")[:6000]},
        ensure_ascii=False,
    )
    data = await director._call_deepseek_json(system=LEAN_CHARACTER_SYSTEM_PROMPT, user=user, api_key=api_key, max_tokens=3072)
    entries = data.get("character_prompts") if isinstance(data, dict) else None
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
# 主要角色名额；角色提示词每批生成的人数和并发数。
# 每个角色的三视图提示词很长，一次让模型写完全部角色会撞上输出上限被截断，只剩前几个（路人甲乙反而挤掉了女主）。
MAX_MAIN_CHARACTERS = 12
# 次要角色（台词少、出场少）放进“可选资产”的上限；不丢弃，需要时一键补建
MAX_MINOR_CANDIDATES = 12
CHARACTER_BATCH_SIZE = 3
CHARACTER_BATCH_CONCURRENCY = 3

# 群演 / 路人：少年甲、少女乙、中年族人、路人丙…不单独生成资产（分镜里按画面描述）
_EXTRA_RE = re.compile(
    r"^(?:[少青中老]年|少女|老者|妇人|路人|村民|族人|众人|人群|侍卫|护卫|士兵|仆人|下人|弟子|宾客|客人|围观者|旁观者)?[甲乙丙丁戊己庚辛壬癸]$"
    r"|(?:路人|村民|族人|众人|人群|围观者|旁观者|看客|群众|议论|围观|群像|低语|喧哗|嘈杂)$"
)


def is_extra_character(name: str) -> bool:
    """群演类角色名（少年甲、中年族人、路人…）：这类泛称不单独生成资产，质检也不要求它们有角色资产。"""
    return bool(_EXTRA_RE.search(str(name or "").strip()))


def find_variant_aliases(names: list[str], text: str) -> dict[str, str]:
    """找出“真实角色名 + 一段动作描述”被误当成角色名的变体：{变体: 真实角色名}。

    剧本里常有“苏砚侧身让开：……”“苏砚沉默片刻：……”这类行，解析时整句被当成说话人，于是多出
    “苏砚侧身让开”“苏砚沉默片刻”这样的假角色，每个都要单独生图，还会和真正的“苏砚”长得不一样。
    判定：变体以另一个已知角色名开头（至少 2 个字），后面还多出 2 个字及以上的描述，且它自己台词不超过 1 句、
    台词也不比真角色多。名字后面只多 1 个字的（苏砚秋、老张头）更像另一个真人，不合并。"""
    from services.screenplay_adapt import speaker_label_stats

    dialogue, _ = speaker_label_stats(text)
    aliases: dict[str, str] = {}
    for variant in names:
        candidates = [
            base for base in names
            if base != variant and len(base) >= 2 and variant.startswith(base) and len(variant) - len(base) >= 2
            and dialogue.get(variant, 0) <= 1
        ]
        if candidates:
            aliases[variant] = max(candidates, key=len)  # 多个前缀时取最长的（最具体的真名）
    return aliases


def apply_name_aliases(text: str, aliases: dict[str, str]) -> str:
    """把文本里的变体名替换成真实角色名（长的先换），让“车夫勒马：”的台词算到“车夫”头上。"""
    for variant in sorted(aliases, key=len, reverse=True):
        text = text.replace(variant, aliases[variant])
    return text


def parse_character_roster(triage: Any, candidates: list[str], text: str) -> dict[str, Any]:
    """校验并提取模型梳理的人物名册：{aliases: {变体: 规范名}, not_person: set, main: set, added: [规范名]}。

    模型的结论只在能被原文/候选名单印证时才采纳：规范名必须出自候选或原文；变体必须在候选里、且与规范名有包含关系
    （防止把两个不同的人并到一起）；“不是人物”只对台词不超过 1 句的条目生效（有多句台词的真人物不会被误删；群体类标签另由群演规则兜底）。"""
    from services.screenplay_adapt import speaker_label_stats

    result: dict[str, Any] = {"aliases": {}, "not_person": set(), "main": set(), "added": []}
    roster = triage.get("roster") if isinstance(triage, dict) else None
    if not isinstance(roster, dict):
        return result
    cand = set(candidates)
    dialogue, _ = speaker_label_stats(text)

    def clean(value: Any) -> str:
        return " ".join(str(value or "").split())

    for item in roster.get("characters") or []:
        if not isinstance(item, dict):
            continue
        name = clean(item.get("name"))
        if len(name) < 2 or (name not in cand and text.count(name) == 0):
            continue
        if str(item.get("importance") or "").strip().lower() == "main":
            result["main"].add(name)
        for raw_alias in item.get("aliases") or []:
            alias = clean(raw_alias)
            if alias in cand and alias != name and (name in alias or alias in name):
                result["aliases"][alias] = name
                if name not in cand and name not in result["added"]:
                    result["added"].append(name)
    for raw in roster.get("not_person") or []:
        name = clean(raw)
        if name in cand and name not in result["aliases"] and dialogue.get(name, 0) <= 1:
            result["not_person"].add(name)
    # 规范名本身不能又被当成别名，避免链式/循环合并
    for canonical in set(result["aliases"].values()):
        result["aliases"].pop(canonical, None)
    result["main"] -= set(result["aliases"])
    return result


def split_characters(names: list[str], text: str, appearances: dict[str, int] | None = None, force_main: set[str] | None = None) -> tuple[list[str], list[str], list[str]]:
    """把清洗后的角色分成（主要角色, 次要角色, 群演）。

    判断依据是“有没有名有姓、有没有台词”，而不是本集出场次数：短剧单集里一个角色可能只露一两次脸，
    但他有名字、有台词，后面的集数还会再出现，必须有资产才能前后一致。
    - 群演：只有泛称（少年甲、路人、族人…），不建资产，分镜里按画面描述；
    - 主要角色：有名字且（有至少 1 句台词，或在剧本里出现 2 次及以上，或出现在 2 个及以上分场的出场名单里），按重要性排序，最多 MAX_MAIN_CHARACTERS 个；
    - 次要角色：有名字但既没台词又几乎没出现，或超出名额的部分，进“可选资产”由用户决定，不直接丢弃。
    全是群演时退回按重要性取前几个，保证至少有角色资产。"""
    from services.screenplay_adapt import speaker_label_stats

    dialogue, _ = speaker_label_stats(text)

    def score(name: str) -> int:
        return dialogue.get(name, 0) * 3 + text.count(name)

    ordered = sorted(names, key=lambda n: (-score(n), names.index(n)))
    named = [n for n in ordered if not is_extra_character(n)]
    seen_in = appearances or {}
    forced = force_main or set()
    primary = [n for n in named if n in forced or dialogue.get(n, 0) >= 1 or text.count(n) >= 2 or seen_in.get(n, 0) >= 2]
    if not primary:
        primary = named[:MAX_MAIN_CHARACTERS] or ordered[:MAX_MAIN_CHARACTERS]
    main = primary[:MAX_MAIN_CHARACTERS]
    minor = [n for n in named if n not in main]
    extras = [n for n in names if n not in main and n not in minor]
    return main, minor, extras


def rank_main_characters(names: list[str], text: str) -> tuple[list[str], list[str]]:
    """兼容旧调用：返回（主要角色, 其余）。其余 = 次要角色 + 群演。"""
    main, minor, extras = split_characters(names, text)
    return main, [n for n in names if n in minor or n in extras]


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


_GENERIC_LOCATIONS = frozenset({"未知", "场景", "地点", "内景", "外景", "无", "空", "同上"})
_PAREN_LOC_RE = re.compile(r"[（(][^）)]*[）)]")


def _clean_location(scene: dict[str, Any]) -> str:
    """分场的地点名：优先 location；没有时从标题“场景1: 古道 / 暮色 / 外景”里取冒号后、第一个斜杠前的部分。"""
    raw = str(scene.get("location") or "").strip()
    if not raw:
        title = str(scene.get("title") or "")
        raw = re.split(r"[:：]", title, maxsplit=1)[-1] if re.search(r"[:：]", title) else ""
    raw = _PAREN_LOC_RE.sub("", raw.split("/", 1)[0]).strip()
    return "" if raw in _GENERIC_LOCATIONS or len(raw) < 2 else raw


def location_groups(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把剧本拆分出的分场按地点归并：同名、或一个名字包含另一个（东院 / 周府东院）算同一个地点，取更完整的名字。"""
    groups: list[dict[str, Any]] = []
    for scene in scenes:
        name = _clean_location(scene)
        if not name:
            continue
        scene_id = str(scene.get("scene_id"))
        beats = [b for b in (scene.get("beats") or []) if isinstance(b, dict)]
        text = " ".join(str(b.get("source_text") or b.get("action") or "") for b in beats).replace("\n", " ").strip()
        brief = (str(scene.get("scene_purpose") or "").strip() or text)[:80]
        group = next((g for g in groups if g["name"] == name or name in g["name"] or g["name"] in name), None)
        if group is None:
            groups.append({"name": name, "scene_ids": [scene_id], "brief": brief, "time": str(scene.get("time_of_day") or "").strip()})
            continue
        if len(name) > len(group["name"]):
            group["name"] = name
        if scene_id not in group["scene_ids"]:
            group["scene_ids"].append(scene_id)
        if not group["brief"]:
            group["brief"] = brief
    return groups


def _same_place(a: str, b: str) -> bool:
    a, b = a.split("（", 1)[0].strip(), b.split("（", 1)[0].strip()
    return bool(a and b and (a == b or a in b or b in a))


def select_assets(triage: dict[str, Any], scenes: list[dict[str, Any]], screenplay_text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按硬规则二次筛选模型返回的场景/道具，返回 (入选资产, 可选候选)。不信任模型的数量与判断。

    场景以剧本拆分出的地点为准：拆分里出现的每个不同地点都建场景资产（上限 MAX_SCENE_ASSETS），
    不要求“出现 2 次”——短剧一集里的地点大多只出现一次，却同样需要前后一致的空镜参考；
    道具仍要求跨分场出现或被反复提及。"""
    known = {str(s.get("scene_id")) for s in scenes}
    groups = location_groups(scenes)
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
            group = next((g for g in groups if _same_place(g["name"], base_name)), None) if role == "scene" else None
            if group is not None:
                ids = list(dict.fromkeys([*ids, *group["scene_ids"]]))
            # 场景：是拆分出的地点、或跨分场复用即入选；道具需跨分场出现，或正文里被反复提及，且名称必须真实出现在剧本里。
            recurring = len(ids) >= 2 or group is not None or (role == "prop" and _mentions(screenplay_text, name) >= MIN_PROP_MENTIONS)
            grounded = group is not None or _mentions(screenplay_text, base_name) >= 1
            if recurring and grounded and prompt and count < limit:
                seen.add((role, name))
                selected.append({"role": role, "name": name, "prompt": prompt, "scene_ids": ids, "unit_count": max(1, len(ids))})
                count += 1
            elif grounded:
                push_optional(role, name, ids, str(item.get("reason") or item.get("desc") or "").strip() or f"{'场景' if role == 'scene' else '道具'}「{name}」")
    # 兜底：模型漏掉、或没给提示词的地点，用拆分里的信息补齐，保证拆分出的每个地点都有场景资产
    scene_count = sum(1 for item in selected if item["role"] == "scene")
    for group in groups:
        if scene_count >= MAX_SCENE_ASSETS:
            break
        if any(item["role"] == "scene" and _same_place(item["name"], group["name"]) for item in selected):
            continue
        time_hint = f"，{group['time']}的光线" if group["time"] else ""
        prompt = f"空镜场景参考图：{group['name']}{time_hint}。{group['brief']}。无人物，画面统一。" if group["brief"] else f"空镜场景参考图：{group['name']}{time_hint}。无人物，画面统一。"
        selected.append({"role": "scene", "name": group["name"], "prompt": prompt, "scene_ids": list(group["scene_ids"]), "unit_count": max(1, len(group["scene_ids"]))})
        scene_count += 1
    # 已经入选的场景不再作为“可选资产”重复出现
    optional = [o for o in optional if not (o["role"] == "scene" and any(i["role"] == "scene" and _same_place(i["name"], o["name"]) for i in selected))]
    for item in triage.get("optional") or []:
        if not isinstance(item, dict):
            continue
        role = "scene" if str(item.get("role")) == "scene" else "prop"
        name = str(item.get("name") or "").strip()
        if role == "scene" and any(i["role"] == "scene" and _same_place(i["name"], name) for i in selected):
            continue
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
    from services.screenplay_adapt import clean_character_names

    # 角色名先清洗（去括号提示、去“级别”这类标签词），再把“人名 + 动作”的明显变体并回真名；
    # 之后由模型通读剧本梳理人物名册，校正程序抽取不准的地方（迁移自列表模式“模型通读正文认人物”的做法）
    all_names = clean_character_names([c for scene in scenes for c in (scene.get("characters") or [])], screenplay_text)
    aliases = find_variant_aliases(all_names, screenplay_text)
    all_names = [n for n in all_names if n not in aliases]
    from services.screenplay_adapt import base_character_name as _base_name

    def _scene_names(scene: dict[str, Any]) -> set[str]:
        # 把变体名折回真实角色名，让“苏砚侧身让开”出现的分场算作“苏砚”出现
        return {aliases.get(_base_name(str(c)), _base_name(str(c))) for c in (scene.get("characters") or [])}

    def tier(pool: list[str], force_main: set[str] | None = None) -> tuple[list[str], list[str], list[str]]:
        # 每个角色出现在几个分场的出场名单里：跨分场出现的有名角色是常驻人物，即使台词少也要有资产
        appearances = {n: sum(1 for sc in scenes if n in _scene_names(sc)) for n in pool}
        return split_characters(pool, apply_name_aliases(screenplay_text, aliases), appearances, force_main)

    names, minor_names, extras = tier(all_names)

    # ① 一次调用：风格 + 人物名册校正 + 角色档案 + 关键场景/道具（含提示词）+ 可选候选
    triage: dict[str, Any] = {}
    candidates = [*names, *minor_names]
    try:
        data = await director._call_deepseek_json(
            system=ASSET_TRIAGE_SYSTEM_PROMPT,
            user=f"角色候选名单（程序从分场里抽出，可能夹杂错误写法）：{'、'.join(candidates) or '无'}\n\n## 分场\n" + "\n".join(_scene_brief(s) for s in scenes) + f"\n\n## 完整剧本\n{screenplay_text}",
            api_key=api_key,
            max_tokens=8192,
        )
        triage = data if isinstance(data, dict) else {}
    except Exception as exc:
        warnings.append(f"资产筛选失败（{type(exc).__name__}），本次提取角色和剧本拆分出的场景，道具由分镜提示词直接描述")

    roster = parse_character_roster(triage, candidates, screenplay_text)
    if roster["aliases"] or roster["not_person"]:
        aliases.update(roster["aliases"])
        all_names = [n for n in all_names if n not in roster["aliases"] and n not in roster["not_person"]]
        all_names.extend(n for n in roster["added"] if n not in all_names)
        names, minor_names, extras = tier(all_names, set(roster["main"]))
    elif roster["main"]:
        names, minor_names, extras = tier(all_names, set(roster["main"]))
    if aliases:
        warnings.append(f"已把角色表里“人名 + 动作”的写法并入对应角色，不再单独生成资产：{'、'.join(f'{v}→{b}' for v, b in list(aliases.items())[:6])}{'…' if len(aliases) > 6 else ''}")
    if roster["not_person"]:
        warnings.append(f"已排除不是人物的条目：{'、'.join(sorted(roster['not_person'])[:6])}")
    if extras:
        warnings.append(f"群演类角色（{'、'.join(extras[:6])}{'…' if len(extras) > 6 else ''}）只有泛称，不单独生成角色资产，分镜里按画面描述")
    if minor_names:
        warnings.append(f"次要角色（{'、'.join(minor_names[:6])}{'…' if len(minor_names) > 6 else ''}）台词和出场都很少，已放进“可选资产”，后续集数会再出现时可一键添加")

    profiles = {
        str(item.get("name") or "").strip(): str(item.get("profile") or "").strip()
        for item in triage.get("characters") or []
        if isinstance(item, dict) and str(item.get("name") or "").strip() and str(item.get("profile") or "").strip()
    }

    assets: list[dict[str, Any]] = []

    # ② 角色提示词：分批并发生成，逐批核对是否每个角色都有，缺的单独补一次
    if names:
        from services.screenplay_adapt import base_character_name

        scene_ids_by_name = {n: [str(sc.get("scene_id")) for sc in scenes if n in {aliases.get(base_character_name(str(c)), base_character_name(str(c))) for c in (sc.get("characters") or [])}] for n in names}

        def shot_data_for(batch: list[str]) -> dict[str, Any]:
            return {
                "scene_location": "",
                "time_of_day": "",
                "story_summary": screenplay_text[:CHARACTER_CONTEXT_CHARS],
                "dialogue_or_narration": "",
                "characters": batch,
                "chapter_text": screenplay_text,
                "source_text_span": "全片角色",
                "camera_plan": "", "motion_plan": "", "emotion_plan": "", "key_props": [], "scene_asset_candidates": [],
            }

        def profile_text_for(batch: list[str]) -> str:
            return "\n".join(f"- {n}：{profiles[n]}" for n in batch if n in profiles)

        semaphore = asyncio.Semaphore(CHARACTER_BATCH_CONCURRENCY)

        async def generate(batch: list[str]) -> list[dict[str, Any]] | BaseException:
            async with semaphore:
                try:
                    return await generate_character_prompts(shot_data_for(batch), profile_text_for(batch), api_key)
                except Exception as exc:  # noqa: BLE001 - 单批失败不影响其他批，统一在下面核对补漏
                    return exc

        def collect(into: dict[str, str], batch: list[str], entries: Any) -> None:
            for entry in entries if isinstance(entries, list) else []:
                if not isinstance(entry, dict):
                    continue
                returned = base_character_name(str(entry.get("name") or ""))
                prompt = str(entry.get("prompt") or "").strip()
                owner = next((n for n in batch if n == returned or (returned and (n in returned or returned in n))), None)
                if owner and prompt and owner not in into:
                    into[owner] = prompt

        prompts_by_name: dict[str, str] = {}
        batches = [names[i:i + CHARACTER_BATCH_SIZE] for i in range(0, len(names), CHARACTER_BATCH_SIZE)]
        for batch, outcome in zip(batches, await asyncio.gather(*(generate(b) for b in batches))):
            if isinstance(outcome, BaseException):
                failed_calls += 1
                continue
            collect(prompts_by_name, batch, outcome)
        # 补漏：整批失败或模型少写了某几个角色时，逐个单独再要一次（不计入失败调用数，只看最终有没有）
        for name in [n for n in names if n not in prompts_by_name]:
            outcome = await generate([name])
            if not isinstance(outcome, BaseException):
                collect(prompts_by_name, [name], outcome)
        still_missing = [n for n in names if n not in prompts_by_name]
        if still_missing:
            warnings.append(f"角色 {'、'.join(still_missing)} 的提示词没有生成成功，可点「重做资产分析」再试一次")
        if failed_calls and not prompts_by_name:
            warnings.append("角色分析失败，已跳过")
        for name in names:
            if name not in prompts_by_name:
                continue
            asset = {"role": "character", "name": name, "prompt": strip_style_text(prompts_by_name[name]), "scene_ids": scene_ids_by_name.get(name, []), "unit_count": max(1, len(scene_ids_by_name.get(name, [])))}
            if name in profiles:
                asset["profile"] = profiles[name]
            assets.append(asset)

    # ③ 关键场景/道具：硬规则二次筛选，提示词已在第一步生成
    from services.screenplay_adapt import base_character_name
    selected, optional = select_assets(triage, scenes, screenplay_text)
    # 次要角色也列进候选（带出场分场与一句话说明），不因“本集露脸少”就从资产体系里消失
    for name in minor_names[:MAX_MINOR_CANDIDATES]:
        scene_ids = [str(sc.get("scene_id")) for sc in scenes if name in [base_character_name(str(c)) for c in (sc.get("characters") or [])]]
        profile = profiles.get(name, "")
        optional.append({"role": "character", "name": name, "scene_ids": scene_ids, "desc": profile or f"次要角色「{name}」，台词和出场较少；后续集数会再出现时建议补建，保证形象一致"})
    for item in selected:
        item["prompt"] = strip_style_text(item["prompt"])
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
