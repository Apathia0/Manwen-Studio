"""画布专用严格导演流程：先验证内容容量，再生成可执行单镜头脚本。"""

from copy import deepcopy
import json
import math
import re

from fastapi import HTTPException

from services.errors import UpstreamServiceError
from services.canvas_creative_guide import DIRECTOR_PLANNING_GUIDE, DIRECTOR_SHOT_GUIDE, craft_warnings
from services.screenplay_meta import strip_meta_beats
from services.video_duration import _duration_options, normalize_video_duration


def resolve_policy(graph, db, model_id=None, user_id=None):
    """导演统一按 4 到 15 秒的任意整数秒拆分镜头，不读取视频模型的时长规格。

    拆分质量取决于内容节奏，而不是某个模型恰好支持的档位（只支持 15 秒的模型会把每个镜头硬凑到 15 秒）。
    之后每个视频节点会按自己的时长自动推荐合适的视频模型（见 canvas_video_model）。参数里的模型与用户仅为兼容旧调用，不再使用。"""
    from services.canvas_video_model import DIRECTOR_MAX_SECONDS, DIRECTOR_MIN_SECONDS

    return {"version": 3, "model_id": None, "duration_options": list(range(DIRECTOR_MIN_SECONDS, DIRECTOR_MAX_SECONDS + 1)), "reference_mode": "clean_single_frame"}


def _legacy_resolve_policy(graph, db, model_id=None, user_id=None):
    """旧版按模型能力取时长档位的实现，保留仅供对照 / 回退。"""
    from models import AiModel
    settings = (graph.get("metadata") or {}).get("production_settings") or {}
    selected = model_id if model_id is not None else settings.get("video_model_id")
    if selected is None and user_id is not None:
        from services.ai.resolver import resolve_model
        selected = resolve_model(db, user_id, modality="video", model_id=None, task_type="video_canvas.video").id
    capabilities = {}
    model_key = ""
    if selected is not None:
        model = db.get(AiModel, selected)
        if not model or not model.enabled or model.modality != "video":
            raise HTTPException(422, "所选视频模型不可用，请先选择可用模型")
        capabilities = (model.capabilities_json or {}).get("video") or {}
        model_key = model.model_key
    options = [n for n in _duration_options(capabilities) if 2 <= n <= 60]
    fallback = [n for n in range(5, 16) if normalize_video_duration(n, model=model_key, capabilities=capabilities) == n]
    if not options and not fallback:
        raise HTTPException(422, "视频模型没有可用时长档位，请检查模型能力配置")
    return {"version": 2, "model_id": selected, "duration_options": options or fallback, "reference_mode": "clean_single_frame"}


def compile_video_prompt(unit):
    """视频正文始终由已校验时间轴编译，不相信客户端遗留提示词。"""
    lead = "连续镜头，画面人物与具名参考一致。"
    if unit.get("continuity_in"):
        lead += f"首帧承接上一镜结尾（{unit['continuity_in']}），人物位置、朝向、道具与光线保持不变，动作与运镜方向延续，不做画面跳变。"
    return lead + "\n" + "\n".join(f"{s['start_second']}-{s['end_second']}秒：起始{s['start_state']}；{s['visual_action']}；机位{s['camera_direction']}；结束{s['end_state']}；对白/旁白：{s.get('dialogue_or_narration') or '无'}" for s in unit["storyboard_json"]["segments"])


_ACTION_SPLIT = r"然后|接着|随后|再将|再把|；|;"
_HEADER_PREFIX = re.compile(r"^\s*(?:场景|场次)\s*\d*\s*[:：][^\n]*\n+\s*(\S.*)$", re.S)


def clean_source_scenes(scenes):
    """导演编排前清洗已保存的场景数据（不改叙事，只修拆分时的误判，旧画布也受益）：
    1. 动作里粘着的“场景N：地点 / 时间”标题行去掉（标题在场景 title 里，不属于画面）；
    2. 冒号前不是人名的“台词”（如“塑料膜上贴着标签：周一、周二”）还原成动作描写，不再当成台词和角色；
    3. 人物表里混进的描述句（如“茶几上压着一张纸”）去掉。
    """
    from services.screenplay_adapt import is_plausible_speaker_name, _real_speaker_matches
    from services.video_canvas_director import _dialogue_lines

    cleaned = []
    for scene in scenes:
        beats = []
        for beat in scene.get("beats") or []:
            if not isinstance(beat, dict):
                beats.append(beat)
                continue
            beat = dict(beat)
            action = str(beat.get("action") or "")
            match = _HEADER_PREFIX.match(action) if beat.get("type") != "dialogue" else None
            if match:
                beat["action"] = match.group(1).strip()
            lines = _dialogue_lines(beat.get("dialogue"))
            if lines and all("：" in line or ":" in line for line in lines) and not any(_real_speaker_matches(line) for line in lines):
                beat["type"] = "action"
                beat["action"] = (str(beat.get("action") or "") + " " + " ".join(lines)).strip()
                beat["dialogue"] = []
            beats.append(beat)
        characters = [c for c in scene.get("characters") or [] if isinstance(c, str) and is_plausible_speaker_name(c, line_start=False)]
        cleaned.append({**scene, "beats": beats, "characters": characters})
    return cleaned

_META_LINE = re.compile(r"^\s*(一句话梗概|梗概|简介|标题|剧名|logline|Logline)\s*[：:]")


def _action_steps(text):
    """按动作步骤切分并保留原文（分隔词归入后一步，分号归入前一步）。"""
    return [p for p in re.split(rf"(?<=[；;])|(?=然后|接着|随后|再将|再把)", str(text or "")) if p.strip("；; \n")]


def _split_long_line(line, budget_chars):
    """单句对白超过容量时按句末标点拆开，后续片段补回说话人前缀。"""
    speaker, sep, body = line.partition("：")
    if not sep:
        speaker, body = "", line
    parts = [p for p in re.split(r"(?<=[。！？!?；;])", body) if p.strip()]
    prefix = f"{speaker}：" if speaker else ""
    # 整句没有句末标点（一整句长话只有逗号）时，退而按分句（逗号、顿号）切开，再把相邻分句合并到不超过容量。
    # 只切分不改写：把所有片段按顺序拼回去就是原句。
    spoken = lambda text: len(re.sub(r"[\s，。！？、；：,.!?;:…]", "", text))
    if len(parts) <= 1 and spoken(body) > budget_chars:
        clauses = [p for p in re.split(r"(?<=[，,、…])", body) if p.strip()]
        packed, current = [], ""
        for clause in clauses:
            if current and spoken(current + clause) > budget_chars * 0.9:
                packed.append(current)
                current = clause
            else:
                current += clause
        if current:
            packed.append(current)
        parts = packed
    return [prefix + p for p in parts] if len(parts) > 1 else [line]


def expand_scenes(scenes, max_seconds):
    """把单个超过模型最大时长的节拍按动作步骤/对白无损拆成子节拍（不改写原文，仅切分）。"""
    from services.video_canvas_director import _dialogue_lines
    result = []
    for scene in scenes:
        new_beats = []
        for beat in scene.get("beats", []):
            if isinstance(beat, dict) and beat.get("dialogue"):
                kept = [l for l in _dialogue_lines(beat.get("dialogue")) if not _META_LINE.match(l)]
                if len(kept) != len(_dialogue_lines(beat.get("dialogue"))):
                    beat = {**beat, "dialogue": kept}
            if not isinstance(beat, dict) or not beat.get("beat_id") or minimum_seconds([beat]) <= max_seconds:
                new_beats.append(beat)
                continue
            actions = _action_steps(beat.get("action"))
            lines = []
            for line in _dialogue_lines(beat.get("dialogue")):
                lines.extend(_split_long_line(line, max_seconds * 3.5) if speech_seconds([{"dialogue": line}]) > max_seconds else [line])
            groups = None
            for k in range(2, len(actions) + len(lines) + 1):
                cut = lambda items, i: items[i * len(items) // k:(i + 1) * len(items) // k]
                cand = [(cut(actions, i), cut(lines, i)) for i in range(k)]
                if any(not a and not d for a, d in cand):
                    continue
                if all(minimum_seconds([{"action": "".join(a), "dialogue": d}]) <= max_seconds for a, d in cand):
                    groups = cand
                    break
            if not groups:
                new_beats.append(beat)
                continue
            for n, (a, d) in enumerate(groups, 1):
                sub = deepcopy(beat)
                sub["beat_id"] = f"{beat['beat_id']}-{n}"
                sub["action"] = "".join(a)
                sub["dialogue"] = d
                new_beats.append(sub)
        result.append({**scene, "beats": new_beats})
    return result


def repair_units(plan, scenes, options):
    """确定性修复：按原文顺序重排节拍归属，补齐遗漏/去重，跨场景或超容量时拆开，时长不足则上调档位（不改动叙事内容）。"""
    index = source_index(scenes, max(options))
    if not isinstance(plan, dict) or not isinstance(plan.get("units"), list):
        return plan
    units = plan["units"]
    owner = {}
    for i, unit in enumerate(units):
        for key in (unit.get("beat_ids") if isinstance(unit, dict) and isinstance(unit.get("beat_ids"), list) else []):
            if isinstance(key, str) and key in index:
                owner.setdefault(key, i)
    if not owner:
        return plan
    order = list(index)
    for key in order:
        if key not in owner:
            prev = [owner[k] for k in order[:order.index(key)] if k in owner]
            nxt = [owner[k] for k in order[order.index(key):] if k in owner]
            owner[key] = prev[-1] if prev else nxt[0]
    runs = []
    for key in order:
        if runs and runs[-1][0] == owner[key] and str(index[runs[-1][1][-1]][0]["scene_id"]) == str(index[key][0]["scene_id"])                 and minimum_seconds([index[k][1] for k in runs[-1][1] + [key]]) <= max(options):
            runs[-1][1].append(key)
        else:
            runs.append((owner[key], [key]))
    per_owner = {}
    for i, _ in runs:
        per_owner[i] = per_owner.get(i, 0) + 1
    used, fixed = {}, []
    for i, run in runs:
        part = deepcopy(units[i])
        used[i] = used.get(i, 0) + 1
        if per_owner[i] > 1 and used[i] > 1:
            part["unit_id"] = f"{units[i].get('unit_id')}_{used[i]}"
        part["beat_ids"] = run
        need = minimum_seconds([index[k][1] for k in run])
        seconds = part.get("duration_seconds")
        valid = isinstance(seconds, int) and not isinstance(seconds, bool) and seconds in options and seconds >= need
        bigger = [o for o in sorted(options) if o >= need]
        if (per_owner[i] > 1 or not valid) and bigger:
            part["duration_seconds"] = bigger[0]
        fixed.append(part)
    for position, unit in enumerate(fixed, 1):
        unit["sequence"] = position
    plan["units"] = fixed
    return plan


def repair_shot_timelines(plan, scenes, options):
    """确定性修复镜头时间轴：补回遗漏的原对白，并按对白所需时长重新分配各时间段（总时长不变）。"""
    from services.video_canvas_director import _dialogue_lines
    if not isinstance(plan, dict):
        return plan
    index = source_index(scenes, max(options))
    for unit in plan.get("units") or []:
        segs = (unit.get("storyboard_json") or {}).get("segments") if isinstance(unit, dict) and isinstance(unit.get("storyboard_json"), dict) else None
        total = unit.get("duration_seconds") if isinstance(unit, dict) else None
        refs = unit.get("beat_ids") if isinstance(unit, dict) else None
        if not isinstance(segs, list) or not segs or not isinstance(total, (int, float)) or isinstance(total, bool) \
                or not all(isinstance(g, dict) for g in segs) or not isinstance(refs, list) or any(k not in index for k in refs if isinstance(k, str)):
            continue
        rendered = "\n".join(str(g.get("dialogue_or_narration") or "") for g in segs)
        for key in refs:
            for line in _dialogue_lines(index[key][1].get("dialogue")):
                if line not in rendered:
                    last = segs[-1]
                    last["dialogue_or_narration"] = (str(last.get("dialogue_or_narration") or "").strip() + "\n" + line).strip()
                    rendered += "\n" + line
        need = [speech_seconds([{"dialogue": str(g.get("dialogue_or_narration") or "")}]) for g in segs]
        try:
            span = [float(g["end_second"]) - float(g["start_second"]) for g in segs]
        except (KeyError, TypeError, ValueError):
            span = [total / len(segs)] * len(segs)
        if any(not math.isfinite(v) or v <= 0 for v in span):
            span = [total / len(segs)] * len(segs)
        if all(span[i] + .01 >= need[i] for i in range(len(segs))) and abs(sum(span) - total) < .01:
            continue
        span = [max(v, math.ceil(n * 100) / 100) for v, n in zip(span, need)]
        excess = sum(span) - total
        if excess > 0:
            slack = [max(0.0, v - max(n, 1.0)) for v, n in zip(span, need)]
            if sum(slack) > 0:
                ratio = min(1.0, excess / sum(slack))
                span = [v - sl * ratio for v, sl in zip(span, slack)]
        elif excess < 0:
            span[-1] += -excess
        cursor = 0.0
        for g, v in zip(segs, span):
            g["start_second"] = round(cursor, 2)
            cursor += v
            g["end_second"] = round(cursor, 2)
        segs[-1]["end_second"] = total if abs(cursor - total) < .05 else round(cursor, 2)
    return plan


def source_index(scenes, max_seconds=None):
    if max_seconds:
        scenes = expand_scenes(scenes, max_seconds)
    index = {}
    for scene in scenes:
        for beat in scene.get("beats", []):
            if not scene.get("scene_id") or not isinstance(beat, dict) or not beat.get("beat_id"):
                raise HTTPException(422, "来源场景或节拍缺少有效ID，请重新拆分")
            key = f"{scene['scene_id']}.{beat['beat_id']}"
            if key in index:
                raise HTTPException(422, "来源节拍ID重复，请重新拆分")
            index[key] = (scene, beat)
    return index


def speech_seconds(beats):
    from services.video_canvas_director import _dialogue_lines
    count = sum(len(re.sub(r"[\s，。！？、；：,.!?;:]", "", line.split("：", 1)[-1])) for b in beats for line in _dialogue_lines(b.get("dialogue")))
    return count / 3.5


def minimum_seconds(beats):
    """动作可与发声重叠；明确动作步骤与对白各自必须有足够时间。"""
    actions = sum(max(1, len([p for p in re.split(_ACTION_SPLIT, str(b.get("action") or "")) if p.strip()])) for b in beats if b.get("action"))
    return max(3 * actions, speech_seconds(beats))


def validate_plan(raw, scenes, policy, *, require_shots=False):
    """返回错误而不改写、追加或删除任何叙事内容。"""
    from services.video_canvas_director import _dialogue_lines
    errors = []
    if not isinstance(raw, dict) or not isinstance(raw.get("units"), list) or not raw["units"]:
        return ["缺少视频单元"]
    options = policy["duration_options"]
    index = source_index(scenes, max(options))
    seen, unit_ids, ordered = [], set(), list(index)
    for position, unit in enumerate(raw["units"], 1):
        if not isinstance(unit, dict):
            errors.append("单元必须是对象")
            continue
        uid = str(unit.get("unit_id") or "")
        if not uid or uid in unit_ids:
            errors.append("单元ID缺失或重复")
        unit_ids.add(uid)
        if unit.get("sequence") != position:
            errors.append(f"{uid}镜头顺序必须连续且与原文一致")
        refs = unit.get("beat_ids")
        if not isinstance(refs, list) or not refs or any(not isinstance(k, str) or k not in index for k in refs):
            errors.append(f"{uid}缺少有效的完整节拍引用")
            continue
        seen.extend(refs)
        if len({str(index[k][0]["scene_id"]) for k in refs}) != 1:
            errors.append(f"{uid}连续镜头不能跨越不同场景，请拆成独立片段")
        beats = [index[k][1] for k in refs]
        seconds = unit.get("duration_seconds")
        minimum = minimum_seconds(beats)
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds not in options:
            errors.append(f"{uid}时长必须选择模型档位{options}")
        elif seconds < minimum:
            errors.append(f"{uid}动作/对白至少需要{minimum:.1f}秒，不能塞进{seconds}秒；请重新分配或在拆分阶段细分节拍")
        if minimum > max(options):
            errors.append(f"{uid}超过模型最大{max(options)}秒，请保留原文细分节拍后重新编排")
        if not str(unit.get("narrative_purpose") or "").strip():
            errors.append(f"{uid}必须说明镜头推动什么信息或人物变化")
        if not require_shots:
            continue
        frame = str(unit.get("storyboard_prompt") or "")
        if len(frame) < 20 or re.search(r"分镜展示|多格|格线|信息栏|时间标注|漫画格", frame):
            errors.append(f"{uid}必须提供干净单帧构图，不能用多格展示板或信息图")
        segments = (unit.get("storyboard_json") or {}).get("segments") if isinstance(unit.get("storyboard_json"), dict) else None
        if not isinstance(segments, list) or not segments:
            errors.append(f"{uid}缺少可执行时间轴")
            continue
        cursor = 0.0
        for seg in segments:
            if not isinstance(seg, dict):
                errors.append(f"{uid}时间段格式错误")
                continue
            start, end = seg.get("start_second"), seg.get("end_second")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, end)) or abs(start-cursor) > .01 or end <= start:
                errors.append(f"{uid}时间轴必须有限、连续、无重叠且正时长")
                continue
            cursor = end
            for key in ("visual_action", "camera_direction", "start_state", "end_state"):
                if not str(seg.get(key) or "").strip():
                    errors.append(f"{uid}时间段缺少{key}")
            if re.search(r"蒙太奇|转场到|跳转到", str(seg.get("camera_direction") or "")):
                errors.append(f"{uid}单元内只能停留在同一空间，跨空间的转场请拆为独立片段")
            speech = str(seg.get("dialogue_or_narration") or "")
            if speech_seconds([{"dialogue": speech}]) > end-start:
                errors.append(f"{uid}时间段对白无法在分配时间内完成")
        if not isinstance(seconds, (int, float)) or abs(cursor-seconds) > .01:
            errors.append(f"{uid}时间轴必须完整覆盖单元时长")
        rendered = "\n".join(str(s.get("dialogue_or_narration") or "") for s in segments if isinstance(s, dict))
        for beat in beats:
            for line in _dialogue_lines(beat.get("dialogue")):
                if line not in rendered:
                    errors.append(f"{uid}时间轴缺少原对白：{line}")
    if seen != ordered:
        errors.append("节拍必须按原文顺序完整覆盖一次，禁止遗漏、重复或将补漏节拍追加末尾")
    return list(dict.fromkeys(errors))


_CAMERA_SCALES = ("中景", "近景", "中景", "特写", "全景")
_BANNED_FRAME = re.compile(r"分镜展示|多格|格线|信息栏|时间标注|漫画格")


def _smallest_option(options, seconds):
    bigger = [o for o in sorted(options) if o >= seconds]
    return bigger[0] if bigger else max(options)


def _row_end_state(action, speech):
    """时间段结束时的画面状态：有对白就是说话人说完这句的样子，否则取动作最后一个分句（如“手指发抖”）。"""
    if speech:
        last = speech.split("\n")[-1]
        who = last.split("：", 1)[0].strip() if "：" in last else ""
        tail = last.split("：", 1)[-1].strip().rstrip("。！？…")[-10:]
        return f"{who}说完“{tail}”" if who else f"说完“{tail}”"
    clauses = [c for c in re.split(r"[，。；！？]", action) if c.strip()]
    return (clauses[-1] if clauses else action)[:30]


def _merge_short_rows(rows, total, floor=2.0):
    """相邻的短节拍并成一个时间段：一个动作配一句话至少给 2 秒，免得切成一秒一格什么都看不清。"""
    rows = [list(r) for r in rows]
    while len(rows) > 1:
        need = [speech_seconds([{"dialogue": sp}]) if sp else 0.0 for _, sp in rows]
        free = max(0.0, total - sum(need))
        weight = [0.4 if sp else 1.0 for _, sp in rows]
        span = [n + free * w / sum(weight) for n, w in zip(need, weight)]
        short = next((i for i, v in enumerate(span) if v < floor), None)
        if short is None:
            break
        other = short + 1 if short + 1 < len(rows) else short - 1
        a, b = sorted((short, other))
        rows[a] = ["；".join(x for x in (rows[a][0].rstrip("；"), rows[b][0]) if x), "\n".join(x for x in (rows[a][1], rows[b][1]) if x)]
        del rows[b]
    return [tuple(r) for r in rows]


def synthesize_shots(unit, index, options):
    """确定性生成保守的镜头时间轴与起始画面：逐节拍成段，对白段至少取对白所需时长，余量按权重分配。

    所有文字都来自原文节拍（动作、对白），不编造剧情；时长不够时只上调到模型档位。
    """
    from services.video_canvas_director import _dialogue_lines
    beats = [index[k][1] for k in unit["beat_ids"]]
    scene = index[unit["beat_ids"][0]][0]
    rows = []
    for beat in beats:
        speech = "\n".join(_dialogue_lines(beat.get("dialogue")))
        action = str(beat.get("action") or "").strip()
        header = _HEADER_PREFIX.match(action)
        rows.append((header.group(1).strip() if header else action, speech))
    need = [speech_seconds([{"dialogue": speech}]) if speech else 0.0 for _, speech in rows]
    # 每个纯动作节拍至少留 1.5 秒：导演给的总时长偏短时，兜底宁可上调到够用的档位，也不把几个动作挤进一个时间段
    action_rows = sum(1 for _, speech in rows if not speech)
    total = _smallest_option(options, max(float(unit.get("duration_seconds") or 0), sum(need) + 1.5 * action_rows + 0.05))
    rows = _merge_short_rows(rows, total)
    need = [speech_seconds([{"dialogue": speech}]) if speech else 0.0 for _, speech in rows]
    weight = [0.4 if speech else 1.0 for _, speech in rows]
    free = max(0.0, total - sum(need))
    span = [n + free * w / sum(weight) for n, w in zip(need, weight)]
    cursor, segments, previous_end = 0.0, [], str(unit.get("transition_in") or "").strip()[:40] or "开场"
    for i, ((action, speech), length) in enumerate(zip(rows, span)):
        end = total if i == len(rows) - 1 else round(cursor + length, 2)
        speaker = speech.split("：", 1)[0].strip() if "：" in speech else ""
        first_line = speech.split("\n", 1)[0]
        said = first_line.split("：", 1)[-1].strip()[:20]
        visual = action or (f"{speaker}说话：{said}" if speaker else "人物对话")
        if action and speaker:
            visual = f"{action}；{speaker}说话：{said}"
        segments.append({
            "start_second": round(cursor, 2), "end_second": end,
            "visual_action": visual,
            "camera_direction": _CAMERA_SCALES[i % len(_CAMERA_SCALES)] + ("，固定机位" if speech else "，缓慢跟随动作"),
            "start_state": previous_end,
            "end_state": _row_end_state(action, speech),
            "dialogue_or_narration": speech,
        })
        previous_end = segments[-1]["end_state"]
        cursor = end
    unit["duration_seconds"] = total
    unit["storyboard_json"] = {"segments": segments}
    frame = str(unit.get("storyboard_prompt") or "")
    if len(frame) < 20 or _BANNED_FRAME.search(frame):
        place = str(scene.get("location") or scene.get("title") or "场景").strip()
        lead = rows[0][0] or rows[0][1].split("：", 1)[-1] or "人物对话"
        unit["storyboard_prompt"] = f"{place}，{str(scene.get('time_of_day') or '').strip()}。{lead[:40]}，人物站位与朝向清晰，光线符合场景氛围，动作即将开始"
    return unit


def synthesize_plan(scenes, policy):
    """确定性的保守分组：同场景相邻节拍按容量贪心成组，每组取能容纳的最小时长档位。"""
    options = policy["duration_options"]
    limit = max(options)
    units = []
    for scene in scenes:
        beats = [b for b in scene.get("beats", []) if isinstance(b, dict) and b.get("beat_id")]
        groups, group = [], []
        for beat in beats:
            trial = group + [beat]
            if group and (len(trial) > 5 or minimum_seconds(trial) > limit):
                groups.append(group)
                group = []
            group.append(beat)
        if group:
            groups.append(group)
        for group in groups:
            number = len(units) + 1
            place = str(scene.get("location") or scene.get("title") or "场景").strip()
            text = " ".join(str(b.get("source_text") or b.get("action") or "") for b in group).replace("\n", " ").strip()
            units.append({
                "unit_id": f"u-{number:03d}", "sequence": number,
                "scene_ids": [scene["scene_id"]],
                "beat_ids": [f"{scene['scene_id']}.{b['beat_id']}" for b in group],
                "title": (text[:12] or place),
                "narrative_purpose": str(scene.get("scene_purpose") or "").strip() or f"推进「{place}」的情节",
                "story_summary": text[:60] or place,
                "duration_seconds": _smallest_option(options, minimum_seconds(group)),
                "duration_reason": "按节拍内容量保守分组，取能容纳对白与动作的最小时长档位",
                "transition_in": "开场" if number == 1 else "承接上一单元结尾的画面与情绪",
                "transition_out": "交给下一单元",
                "opening_shot_scale": "中景", "closing_shot_scale": "中景",
                "continuity": {"from_previous": "", "to_next": "", "anchor": place},
            })
    if units:
        units[-1]["transition_out"] = "收束"
    return {"pacing_strategy": "保守自动分组（模型编排多次未通过校验）", "units": units}


_SCALES = ("远景", "全景", "中景", "近景", "特写")


def _scale_of(text):
    """返回文本中最先出现的景别词及其位置，没有则为 (None, -1)。"""
    found = [(str(text).find(w), w) for w in _SCALES if w in str(text)]
    return (min(found)[1], min(found)[0]) if found else (None, -1)


def _set_scale(segment, scale):
    text = str(segment.get("camera_direction") or "")
    old, pos = _scale_of(text)
    segment["camera_direction"] = text[:pos] + scale + text[pos + len(old):] if old else f"{scale}，{text}".strip("，")


def _step_toward(previous, step):
    i = _SCALES.index(previous)
    return _SCALES[max(0, min(len(_SCALES) - 1, i + step))]


def polish_continuity(plan):
    """确定性衔接修整（只调整景别/转场/状态承接，不改叙事）：
    相邻镜头景别不重复（匹配剪辑/正反打除外）、景别跨度不超过两级、上一镜结束状态作为下一镜起始状态，并补全转场手法。返回调整说明。"""
    units = [u for u in plan.get("units") or [] if isinstance(u, dict) and isinstance((u.get("storyboard_json") or {}).get("segments"), list) and u["storyboard_json"]["segments"]]
    changed = 0
    for i, unit in enumerate(units):
        segs = unit["storyboard_json"]["segments"]
        first, last = segs[0], segs[-1]
        technique = str(unit.get("transition_technique") or "").strip()
        if i > 0:
            prev = units[i - 1]
            prev_last = prev["storyboard_json"]["segments"][-1]
            same_scene = list(prev.get("scene_ids") or []) == list(unit.get("scene_ids") or [])
            p_scale, _ = _scale_of(prev_last.get("camera_direction") or "")
            c_scale, _ = _scale_of(first.get("camera_direction") or "")
            if p_scale in _SCALES:
                target = c_scale
                if not same_scene:
                    # 换场景：以更开阔的景别建立新空间
                    if c_scale is None or c_scale == p_scale:
                        target = "全景" if p_scale != "全景" else "远景"
                elif c_scale == p_scale and technique not in ("匹配剪辑", "正反打"):
                    target = _step_toward(p_scale, 1 if _SCALES.index(p_scale) <= 2 else -1)
                    technique = "景别递进"
                elif c_scale in _SCALES and abs(_SCALES.index(c_scale) - _SCALES.index(p_scale)) > 2:
                    target = _step_toward(p_scale, 2 if _SCALES.index(c_scale) > _SCALES.index(p_scale) else -2)
                    technique = technique or "景别递进"
                if target and target != c_scale:
                    _set_scale(first, target)
                    changed += 1
            if not technique:
                technique = "动作剪辑" if same_scene else "时空跳转"
            handoff = str(prev_last.get("end_state") or "").strip()
            if handoff:
                first["start_state"] = handoff
                unit["continuity_in"] = handoff
            unit["transition_technique"] = technique
            if not str(unit.get("transition_in") or "").strip() or unit.get("transition_in") in ("承接上一单元结尾的画面与情绪", "开场"):
                unit["transition_in"] = f"{technique}：承接上一镜结束状态" + (f"「{handoff[:30]}」" if handoff else "")
        unit["opening_shot_scale"] = _scale_of(first.get("camera_direction") or "")[0] or unit.get("opening_shot_scale") or "中景"
        unit["closing_shot_scale"] = _scale_of(last.get("camera_direction") or "")[0] or unit.get("closing_shot_scale") or "中景"
    return f"已自动调整 {changed} 处镜头衔接（景别递进、起止状态承接）" if changed else ""


async def direct(scenes, policy, *, api_key=None, user_constraints=None, **source_meta):
    # 标题、一句话梗概等不是对白也不是画面，不参与编排；否则会被要求塞进镜头而永远校验不过。
    scenes = clean_source_scenes(strip_meta_beats(scenes))
    from services.video_canvas_director import _call_deepseek_json, _dialogue_lines
    planning = f"""你是剧情导演与剪辑师。依据人物目标、阻碍、选择及后果设计镜头目的。
每个视频单元只承担清晰可拍的动作/信息变化。原节拍按顺序完整覆盖一次。
严格遵守提供的模型时长档位及动作对白容量；长节拍无法容纳时明确指出需重拆，禁止缩时塞对白。
{DIRECTOR_PLANNING_GUIDE}
输出JSON：pacing_strategy、units，每项含unit_id、sequence、beat_ids（场景ID.节拍ID）、scene_ids、title、narrative_purpose、story_summary、duration_seconds、duration_reason、transition_in、transition_out、transition_technique（首个单元可为空）、opening_shot_scale、closing_shot_scale（远景/全景/中景/近景/特写之一）、continuity（from_previous/to_next/anchor）。"""
    scenes = expand_scenes(scenes, max(policy["duration_options"]))
    annotated = [{**s, "beats": [{**b, "最少秒数": round(minimum_seconds([b]), 1)} if isinstance(b, dict) else b for b in s.get("beats", [])]} for s in scenes]
    planning += "\n硬性规则：同一单元的beat_ids必须来自同一个scene_id，禁止跨场景合并；单元duration_seconds必须不小于其所含节拍“最少秒数”之和的需求，并取模型档位。"
    from services.video_duration import parse_target_duration_seconds

    target_seconds = parse_target_duration_seconds(user_constraints)
    payload = {"创作约束": user_constraints or "漫剧，开场即钩子，重人物选择与因果，运镜有动机、不炫技", "模型能力": policy, "完整源场景": annotated}
    if target_seconds:
        payload["目标总时长秒数"] = target_seconds
        from services.video_duration import target_duration_ceiling

        planning += f"\n总时长：用户给的参考时长约{target_seconds}秒，只是参考，故事讲完整优先；所有单元duration_seconds之和可在{target_seconds}到{target_duration_ceiling(target_seconds)}秒之间按剧情需要浮动，不要为了贴近参考值而删减剧情，也不要注水凑时长。在不低于节拍“最少秒数”的前提下，把同一场景内相邻的短节拍合并成更少的单元，不要为每个动作单独设镜头。"
    notes = []

    async def request_valid(system, data, check, fallback=None):
        errors, result = [], None
        for _ in range(3):
            result = await _call_deepseek_json(system=system, user=json.dumps({**data, "需修复问题": errors}, ensure_ascii=False), api_key=api_key)
            errors = check(result)
            if not errors:
                return result
        # 模型多次没能通过校验：自动采用基于原文的保守方案，而不是失败后让用户自己选择。
        recovered = fallback(result, errors) if fallback else None
        if recovered is not None:
            return recovered
        raise UpstreamServiceError("前置创作校验未通过：" + "；".join(errors[:6]), retryable=False, provider="DeepSeek", code="canvas_director_quality_failed", diagnostics={"issues": errors})
    def plan_fallback(last, errors):
        candidate = synthesize_plan(scenes, policy)
        if not candidate["units"] or validate_plan(candidate, scenes, policy):
            return None
        notes.append("导演编排多次未通过校验，已按原文自动分组（保守方案），可在节点中调整。校验问题：" + "；".join((errors or [])[:3]))
        return candidate

    plan = await request_valid(planning, payload, lambda p: validate_plan(repair_units(p, scenes, policy["duration_options"]), scenes, policy), plan_fallback)
    index = source_index(scenes)
    for unit in plan["units"]:
        unit["scene_ids"] = list(dict.fromkeys(index[k][0]["scene_id"] for k in unit["beat_ids"]))
        unit["source_beats"] = [{"source_id": k, "scene": {key: value for key, value in index[k][0].items() if key != "beats"}, "beat": deepcopy(index[k][1])} for k in unit["beat_ids"]]
        unit["characters"] = list(dict.fromkeys(c for k in unit["beat_ids"] for c in index[k][0].get("characters", [])))
        unit["dialogue_or_narration"] = "\n".join(line for k in unit["beat_ids"] for line in _dialogue_lines(index[k][1].get("dialogue")))
    shots = f"""你是镜头导演。不得修改输入单元ID、顺序、时长或剧情。输出JSON units按unit_id对应。
每项含storyboard_prompt和storyboard_json.segments。storyboard_prompt是用于图生视频的干净单帧起始画面：准确描绘人物站位、朝向、景别构图、道具归属、光线和动作即将开始的状态；人物外观遵循具名参考图。不要画文字或展示板。
segments各项含start_second/end_second、visual_action、camera_direction（写明景别与运镜）、start_state、end_state、dialogue_or_narration。时间连续覆盖全长；同一空间内动作有因果且可完成。对白逐句保留说话人和原文并分配足够时间。使用完整源动作和视觉锚点，不凭摘要发明细节。
{DIRECTOR_SHOT_GUIDE}"""
    def merge_details(result):
        details = result.get("units") if isinstance(result, dict) else None
        if not isinstance(details, list) or len(details) != len(plan["units"]):
            return None
        mapping = {u.get("unit_id"): u for u in details if isinstance(u, dict)}
        if set(mapping) != {u["unit_id"] for u in plan["units"]} or len(mapping) != len(details):
            return None
        merged = deepcopy(plan)
        for unit in merged["units"]:
            detail = mapping[unit["unit_id"]]
            unit.update({k: detail.get(k) for k in ("storyboard_prompt", "storyboard_json")})
        return merged
    def shots_fallback(last, errors):
        options = policy["duration_options"]
        merged = repair_shot_timelines(merge_details(last), scenes, options) if last is not None and merge_details(last) else None
        base = merged or deepcopy(plan)
        failing = validate_plan(base, scenes, policy, require_shots=True) if merged else []
        full_index = source_index(scenes)
        fixed = []
        for position, unit in enumerate(base["units"]):
            uid = str(unit["unit_id"])
            if merged is None or any(re.match(rf"{re.escape(uid)}(?![A-Za-z0-9_])", e) for e in failing):
                synthesize_shots(unit, full_index, options)
                plan["units"][position]["duration_seconds"] = unit["duration_seconds"]
                fixed.append(uid)
        if validate_plan(base, scenes, policy, require_shots=True):
            return None
        if fixed:
            reason = "；".join((errors or failing or [])[:3])
            notes.append(f"镜头 {'、'.join(fixed)} 的时间轴多次未通过校验，已按原文自动生成（保守分镜），可在节点中微调" + (f"。校验问题：{reason}" if reason else ""))
        return {"units": base["units"]}

    detail = await request_valid(shots, {"完整导演交接": plan, "模型能力": policy}, lambda r: validate_plan(repair_shot_timelines(merge_details(r), scenes, policy["duration_options"]), scenes, policy, require_shots=True), shots_fallback)
    plan = repair_shot_timelines(merge_details(detail), scenes, policy["duration_options"])
    polish_note = polish_continuity(plan)
    if polish_note:
        notes.append(polish_note)
    for unit in plan["units"]:
        unit["video_prompt"] = compile_video_prompt(unit)
        unit["reference_mode"] = "clean_single_frame"
    total_seconds = sum(int(unit.get("duration_seconds") or 0) for unit in plan["units"])
    if target_seconds:
        from services.video_duration import target_duration_ceiling

        ceiling = target_duration_ceiling(target_seconds)
        if total_seconds > ceiling:
            notes.append(
                f"导演编排总时长 {total_seconds} 秒，超过短视频的合理上限 {ceiling} 秒（参考时长 {target_seconds} 秒）。镜头时长已是容纳原文对白与动作的最小档位，"
                f"如需缩短，请精简剧本（约 {int(ceiling * 5.6)} 字以内）后重新拆分。"
            )
    plan.update(plan_version=2, production_policy=policy, creative_constraints=user_constraints or "", warnings=[*notes, *craft_warnings(plan)], meta=source_meta, total_duration_seconds=total_seconds, target_duration_seconds=target_seconds)
    return plan
