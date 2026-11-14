"""断言章节补全 max_tokens 常量足够大，避免 deepseek-v4-flash 思考耗尽 token 导致正文截断。"""

from services import deepseek


def test_chapter_completion_max_tokens_sufficient():
    """章节补全 max_tokens 必须 >= 8192，为思考 + 输出留足缓冲。"""
    assert deepseek.CHAPTER_COMPLETION_MAX_TOKENS >= 8192