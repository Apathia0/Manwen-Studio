from services.agent_service import _is_multimodal_unsupported_response


def test_detects_upstream_multimodal_unsupported_error():
    assert _is_multimodal_unsupported_response(
        400,
        '{"error":{"message":"当前模型最多支持 1 张图片参考","type":"invalid_request_error"}}',
    )
    assert _is_multimodal_unsupported_response(
        422,
        '{"error":{"message":"model does not support image_url inputs"}}',
    )


def test_does_not_misclassify_unrelated_bad_request():
    assert not _is_multimodal_unsupported_response(400, '{"error":{"message":"prompt 不能为空"}}')
    assert not _is_multimodal_unsupported_response(429, '{"error":{"message":"图片数量超限"}}')
    assert not _is_multimodal_unsupported_response(400, '{"error":{"message":"image_url 请求的 max_tokens 不能为空"}}')
