from routers import deconstruct_library


def test_only_qidian_supports_remote_auto_crawl():
    assert deconstruct_library.is_remote_crawl_supported("qidian") is True
    assert deconstruct_library.is_remote_crawl_supported("fanqie") is False
    assert deconstruct_library.is_remote_crawl_supported("qimao") is False
    assert deconstruct_library.is_remote_crawl_supported("zongheng") is False


def test_upload_required_message_mentions_manual_original_text():
    message = deconstruct_library.get_upload_required_message("fanqie")

    assert "番茄小说" in message
    assert "上传原文" in message
    assert "粘贴原文" in message


def test_split_imported_novel_text_by_chapter_heading():
    text = "第1章 开端\n第一章正文。\n\n第2章 转折\n第二章正文。"

    chapters = deconstruct_library.split_imported_novel_text(text)

    assert chapters == [
        {"chapter_number": 1, "title": "第1章 开端", "content": "第一章正文。"},
        {"chapter_number": 2, "title": "第2章 转折", "content": "第二章正文。"},
    ]


def test_split_imported_novel_text_falls_back_to_single_chapter():
    chapters = deconstruct_library.split_imported_novel_text("没有章节标题，但有正文。")

    assert chapters == [
        {"chapter_number": 1, "title": "第1章", "content": "没有章节标题，但有正文。"},
    ]


def test_all_unsupported_platforms_have_upload_message():
    for platform in ("fanqie", "qimao", "zongheng"):
        assert not deconstruct_library.is_remote_crawl_supported(platform), f"{platform} 不应支持远程爬取"
        message = deconstruct_library.get_upload_required_message(platform)
        assert "上传原文" in message, f"{platform} 的提示消息应包含「上传原文」"
        assert "粘贴原文" in message, f"{platform} 的提示消息应包含「粘贴原文」"


def test_upload_required_message_platform_label():
    cases = [
        ("fanqie", "番茄小说"),
        ("qimao", "七猫"),
        ("zongheng", "纵横"),
        ("", "该平台"),
        ("unknown", "该平台"),
    ]
    for platform, expected_label in cases:
        message = deconstruct_library.get_upload_required_message(platform)
        assert expected_label in message, f"平台 {platform!r} 的提示应包含 {expected_label!r}"


def test_split_imported_novel_text_various_chapter_formats():
    text = "第1章 第一章\n正文1。\n\n第一回 初遇\n正文2。\n\n第一节 开始\n正文3。"
    chapters = deconstruct_library.split_imported_novel_text(text)
    assert len(chapters) == 3
    assert chapters[0]["title"] == "第1章 第一章"
    assert chapters[1]["title"] == "第一回 初遇"
    assert chapters[2]["title"] == "第一节 开始"


def test_split_imported_novel_text_ignores_empty_chapters():
    text = "第1章 端\n正文1。\n\n第2章 空\n\n第3章 续\n正文3。"
    chapters = deconstruct_library.split_imported_novel_text(text)
    assert len(chapters) == 2, "中间空章节应被跳过"
    assert chapters[0]["title"] == "第1章 端"
    assert chapters[1]["title"] == "第3章 续"


def test_split_imported_novel_text_empty_input():
    assert deconstruct_library.split_imported_novel_text("") == []
    assert deconstruct_library.split_imported_novel_text("   ") == []
    assert deconstruct_library.split_imported_novel_text(None) == []


def test_split_imported_novel_text_carriage_return_normalization():
    text = "第1章\r\n正文1。\r\n\r\n第2章\r\n正文2。"
    chapters = deconstruct_library.split_imported_novel_text(text)
    assert len(chapters) == 2
    assert chapters[0]["content"] == "正文1。"
    assert chapters[1]["content"] == "正文2。"


def test_remote_crawl_supported_platforms_explicit_mapping():
    assert deconstruct_library.REMOTE_CRAWL_SUPPORTED_PLATFORMS == {"qidian"}
    assert deconstruct_library.PLATFORM_LABELS.keys() == deconstruct_library.REMOTE_CRAWL_SUPPORTED_PLATFORMS | {"fanqie", "qimao", "zongheng"}
