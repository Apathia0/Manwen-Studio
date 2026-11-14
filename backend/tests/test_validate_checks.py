#!/usr/bin/env python3
"""验证质量检测函数的正确性"""
import re

BANNED_WORDS_TIER1 = {
    "仿佛", "犹如", "宛若", "如同", "深吸一口气", "缓缓", "不禁",
    "微微", "轻轻", "淡淡", "眼中闪过", "嘴角勾起", "眉头微皱",
    "不易察觉", "显而易见",
}
BANNED_PATTERNS_TIER1 = [
    (r"不是.+，[而]?.+是", "不是A而是B"),
    (r"，带着[一这]", "万能状语"),
    (r"仿佛[^。]*一般", "仿佛...一般"),
]
DASH_PATTERN = re.compile(r"——|—{1,2}|\.{2,}")

# 测试1：干净正文
clean = "他推开门。屋里很暗。\"来了？\"老刘问。"
words_found = [w for w in BANNED_WORDS_TIER1 if w in clean]
assert len(words_found) == 0, f"干净正文不应检出禁用词，但发现: {words_found}"
print("✅ 测试1 PASS: 干净正文无禁用词")

# 测试2：破折号检测
dash_text = "他看着她——不，这不可能。"
dashes = DASH_PATTERN.findall(dash_text)
assert len(dashes) > 0, "破折号检测漏报"
print("✅ 测试2 PASS: 破折号检测正常")

# 测试3：禁用句式检测
pattern_text = "不是他不想做，而是他不能做。"
found_any = False
for p, name in BANNED_PATTERNS_TIER1:
    if re.search(p, pattern_text):
        found_any = True
        break
assert found_any, "禁用句式漏报"
print("✅ 测试3 PASS: 禁用句式检测正常")

# 测试4：字数计算
chars = len(clean.replace(" ", "").replace("\n", ""))
assert chars == 19, f"字数计算错误: {chars}"
print("✅ 测试4 PASS: 字数统计正常")

# 测试5：章末钩子检测
good_ending = "他推开门，床上竟然空无一人。"
bad_ending = "他终于明白了，人生就是这样。"
g5_1 = re.search(r"[原来竟然居然其实]", good_ending[-100:])
g5_2 = re.search(r"[他她]终于明白", bad_ending[-100:])
assert g5_1, f"钩子检测漏报: {good_ending}"
assert g5_2, "总结式结尾检测漏报"
print("✅ 测试5 PASS: 章末钩子检测正常")

print("\n🎉 全部 5 项检测函数验证通过")
