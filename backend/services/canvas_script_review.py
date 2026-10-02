"""漫剧剧本提交前的逻辑审稿（以 UTF-8 无 BOM 编码保存）。

篇幅、钩子这类能用规则查的已经在网关里查了；“因果讲不讲得通、打脸有没有铺垫、观众能不能看懂”
只能靠读懂剧情来判断，所以交给文本模型按固定清单审一遍：有硬伤就退回并说明怎么改，没有硬伤才放行。

审稿服务自己出错（欠费、超时、返回乱码）时一律放行：它是质量把关，不能变成创作的阻断点。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 审稿不通过时服务端自动改写重审的最多轮数；用完后取最后一版放行（带警告），不把问题抛给用户
MAX_REVISION_ROUNDS = 2

REVIEW_SYSTEM_PROMPT = """你是严苛的短剧编审，只判断“剧情逻辑能不能让陌生观众看懂并信服”，不评价文笔。
按下面清单逐条检查。硬伤的标准很严：只有“不改它，陌生观众就看不懂主线的胜负是怎么来的 / 会明显出戏”才算。
锦上添花的建议、可有可无的细节补充、个别台词的措辞偏好、可以更好但不影响理解的地方，一律不报。主线已经讲得通时直接 passed。

1. 因果链：每一次转折、胜负逆转，是否都有前文明确交代的原因？观众是否知道“主角凭什么赢 / 凭什么能做到”？只摆出一个物件或一句暗示、却没说清它为什么有效，算硬伤。
2. 人物目标与阻碍：主角想要什么、谁在阻止、代价是什么，是否在剧本里看得出来？
3. 题材契约：
   - 逆袭 / 打脸 / 复仇：必须有 ①被羞辱或被压制的具体场面 ②主角的底牌（真实身份、证据、权力）被明确说出来或亮出来 ③一件可见的证据物或一个无法否认的事实 ④反派付出看得见的具体后果（被撤职、被当众揭穿、被迫低头等）。缺任何一项都是硬伤。
   - 悬疑 / 反转：线索必须在前文出现过，反转后能回头解释前文；凭空冒出的新设定、新人物算硬伤。
4. 可理解性：不依赖任何没写出来的背景就能看懂吗？含糊的意象、没有来源的声音或画面（如“水面上晃过一道光”“一个女声”突然出现）、对白里只有暗号没有含义，算硬伤。
5. 场景衔接：下一场的开头是否承接上一场的结尾（人物、地点、时间、情绪）？人物突然换了立场或身份而没有交代，算硬伤。
6. 结尾：集尾钩子必须由本剧情自己长出来，并且观众能明白它指向什么；与前文无关的新谜团、悬念为悬念而悬念，算硬伤。

输出 JSON：{"passed": true/false, "issues": [{"where": "场景几 / 哪句", "problem": "观众会在哪里看不懂或不信服", "fix": "具体怎么改（补什么信息、换哪句台词），不要写空话"}]}。
issues 最多 4 条，按严重程度排序；没有硬伤时 passed 为 true，issues 为空数组。"""


REVISE_SYSTEM_PROMPT = """你是资深漫剧编剧，负责按编审意见把一份有逻辑漏洞的剧本改成观众能看懂、信服的版本。

做法（必须按顺序）：
第一步，先在 plan 字段里写一张因果表（每项一句话，要具体，不要空话）：
  底牌（主角凭什么赢，含真实身份或权力的来源）/ 证据物（一件看得见的东西，在哪一场、由谁、怎么出示）/ 反派的认知（她事先知不知道主角的底牌，不能自相矛盾）/ 反派的具体后果 / 钩子（指向什么，在哪一场埋下的线索）/ 每一场的结尾画面如何成为下一场的开头。
第二步，严格按因果表写 screenplay。编审指出的每个问题，剧本里都要有一句具体台词或一个可见画面解决它；不能只改措辞。
可以重写场景内容、调整台词和动作，但保留：题材、主要人物名字、地点、开场的冲突，以及“被当众压制 → 亮底牌 → 反派被迫低头 → 钩子”这条主线。

硬性要求：
1. 谁知道什么要一致：观众看到的信息，和人物此刻应当知道的信息不能矛盾（例如不能让反派替主角说出他的底牌，除非她已经查证过）。
2. 证据物必须在画面里出现并被看清（念出内容或特写），不能只说“她脸色骤变”。
3. 反派的后果必须落在画面上（被撤职、被当众揭穿、被迫当面道歉等），不能只是“被镇住了”。
4. 钩子必须由前文埋下的线索长出来，并且观众能明白它指向什么。
5. 格式严格保持：每场以“场景N：地点 / 时间 / 内外”开头，随后是动作行和“人物：台词”行；不写标题、梗概、说明和括号里的创作备注。
6. 篇幅不超过给定字数（去空白），要删就删次要对白和重复动作，不删因果交代。场景数按故事需要定，一般4到6场。
输出 JSON：{"plan": "因果表", "screenplay": "修改后的完整剧本正文"}"""


async def revise_screenplay(content: str, issues: list[dict[str, Any]], user_constraints: str | None, max_chars: int, api_key: str | None) -> str | None:
    """按审稿意见改写剧本；失败或结果不合格（空、过长、丢了场景格式）返回 None。"""
    import re

    from services.video_canvas_director import _call_deepseek_json

    user = json.dumps(
        {"创作要求": user_constraints or "漫剧短篇", "字数上限": max_chars, "编审意见": issues, "当前剧本": content},
        ensure_ascii=False,
    )
    try:
        result = await _call_deepseek_json(system=REVISE_SYSTEM_PROMPT, user=user, api_key=api_key, max_tokens=8192)
    except Exception:  # noqa: BLE001 - 改写失败就沿用当前版本
        logger.warning("剧本自动改写调用失败，沿用当前版本", exc_info=True)
        return None
    revised = str(result.get("screenplay") or "").strip() if isinstance(result, dict) else ""
    if not revised or len(re.sub(r"\s", "", revised)) > max_chars or not re.search(r"(?:^|\n)\s*场景\s*\d*\s*[:：]", revised):
        logger.warning("剧本自动改写结果不合格已丢弃：空=%s 字数=%s/%s", not revised, len(re.sub(r"\s", "", revised)), max_chars)
        return None
    return revised


async def improve_screenplay(content: str, user_constraints: str | None, max_chars: int, api_key: str | None) -> tuple[str, list[dict[str, Any]], int]:
    """审稿 → 不通过就自动改写 → 再审，最多 MAX_REVISION_ROUNDS 轮。

    返回 (最终剧本, 仍未解决的问题, 实际改写轮数)。全程不抛错、不要求用户介入：
    每一轮改写后的版本只要比上一版更好（审稿问题更少）就采用，否则保留上一版。
    """
    issues = await review_screenplay(content, user_constraints, api_key)
    rounds = 0
    while issues and rounds < MAX_REVISION_ROUNDS:
        revised = await revise_screenplay(content, issues, user_constraints, max_chars, api_key)
        rounds += 1
        if not revised:
            continue
        revised_issues = await review_screenplay(revised, user_constraints, api_key)
        if len(revised_issues) <= len(issues):
            content, issues = revised, revised_issues
    return content, issues, rounds


def format_issues(issues: list[dict[str, Any]]) -> str:
    lines = []
    for index, item in enumerate(issues[:4], 1):
        where = str(item.get("where") or "").strip()
        problem = str(item.get("problem") or "").strip()
        fix = str(item.get("fix") or "").strip()
        lines.append(f"{index}. {where}：{problem}" + (f"（建议：{fix}）" if fix else ""))
    return "\n".join(lines)


async def review_screenplay(content: str, user_constraints: str | None, api_key: str | None) -> list[dict[str, Any]]:
    """返回硬伤列表；通过或审稿服务不可用时返回空列表。"""
    from services.video_canvas_director import _call_deepseek_json

    user = json.dumps({"创作要求": user_constraints or "漫剧短篇", "剧本": content}, ensure_ascii=False)
    try:
        result = await _call_deepseek_json(system=REVIEW_SYSTEM_PROMPT, user=user, api_key=api_key, max_tokens=2048)
    except Exception:  # noqa: BLE001 - 审稿失败不能阻断创作
        logger.warning("剧本逻辑审稿调用失败，已跳过", exc_info=True)
        return []
    if not isinstance(result, dict) or result.get("passed") is True:
        return []
    issues = [i for i in result.get("issues") or [] if isinstance(i, dict) and str(i.get("problem") or "").strip()]
    return issues[:4]
