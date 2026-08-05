import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  AI_MODEL_SELECTION_REQUIRED_EVENT,
  normalizeErrorMessage,
  readResponseError,
  type AiModelSelectionRequiredDetail,
} from './errors';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('normalizeErrorMessage', () => {
  it('提取 FastAPI detail 而不是显示原始 JSON', () => {
    expect(normalizeErrorMessage('{"detail":"当前章节没有可分析的正文"}')).toBe('当前章节没有可分析的正文');
  });

  it('将常见上游英文状态转换为中文操作提示', () => {
    expect(normalizeErrorMessage("Client error '402 Payment Required' for url https://example.com/v1"))
      .toBe('上游 AI 服务余额不足，请充值或更换可用渠道后重试');
    expect(normalizeErrorMessage('Failed to fetch')).toBe('网络连接失败，请检查网络后重试');
  });

  it('未知英文错误不直接暴露给用户', () => {
    expect(normalizeErrorMessage('opaque provider stack trace', '图片生成失败，请重试'))
      .toBe('图片生成失败，请重试');
    expect(normalizeErrorMessage('视频生成失败: opaque provider stack'))
      .toBe('视频生成失败，请稍后重试');
  });

  it('解析 Pydantic 校验错误数组', () => {
    const payload = JSON.stringify({ detail: [{ msg: 'Field required' }] });
    expect(normalizeErrorMessage(payload, '提交失败')).toBe('提交失败');
  });

  it('保留结构化错误中的中文补救建议', () => {
    const payload = JSON.stringify({ detail: { error: '图片生成失败', suggestion: '请切换模型后重试' } });
    expect(normalizeErrorMessage(payload)).toBe('图片生成失败。请切换模型后重试');
  });

  it('提取分镜导入冲突的 errors 数组', () => {
    const payload = JSON.stringify({ errors: ['分镜已被其他操作更新，请重新预览后再提交'] });
    expect(normalizeErrorMessage(payload)).toBe('分镜已被其他操作更新，请重新预览后再提交');
  });
});

describe('readResponseError', () => {
  it('网关空响应返回后端服务提示（而非上游 AI 不可用）', async () => {
    const response = new Response('', { status: 502 });
    await expect(readResponseError(response)).resolves.toBe(
      '后端服务暂不可用或正在重启，请稍后重试，必要时联系管理员检查服务状态',
    );
  });

  it('网关 HTML 错误页同样判定为后端服务错误（含 502 字样不误判 AI 上游）', async () => {
    const response = new Response(
      '<html><body>502 Bad Gateway</body></html>',
      { status: 502, headers: { 'content-type': 'text/html' } },
    );
    await expect(readResponseError(response)).resolves.toBe(
      '后端服务暂不可用或正在重启，请稍后重试，必要时联系管理员检查服务状态',
    );
  });

  it('后端返回的 JSON AI 上游错误保持原语义（真 AI 上游不可用）', async () => {
    const response = new Response(
      JSON.stringify({ detail: 'Bad Gateway from upstream AI' }),
      { status: 502, headers: { 'content-type': 'application/json' } },
    );
    await expect(readResponseError(response)).resolves.toBe('上游 AI 服务暂时不可用，请稍后重试');
  });

  it('503 空响应属于网关/服务繁忙提示', async () => {
    const response = new Response('', { status: 503 });
    await expect(readResponseError(response)).resolves.toBe('后端服务繁忙或正在初始化，请稍后重试');
  });

  it('模型选择失效时派发全局配置事件', async () => {
    vi.stubGlobal('window', new EventTarget());
    const listener = vi.fn();
    window.addEventListener(AI_MODEL_SELECTION_REQUIRED_EVENT, listener as EventListener);
    const response = new Response(JSON.stringify({
      detail: {
        code: 'AI_MODEL_SELECTION_REQUIRED',
        message: '已选择的图片模型已下架，请重新选择',
        modality: 'image',
        reason: 'hidden',
      },
    }), { status: 409 });

    const message = await readResponseError(response, '请求失败');

    expect(message).toBe('已选择的图片模型已下架，请重新选择');
    expect(listener).toHaveBeenCalledTimes(1);
    const event = listener.mock.calls[0][0] as CustomEvent<AiModelSelectionRequiredDetail>;
    expect(event.detail).toEqual({
      code: 'AI_MODEL_SELECTION_REQUIRED',
      message: '已选择的图片模型已下架，请重新选择',
      modality: 'image',
      reason: 'hidden',
    });
  });

  it('普通冲突错误不会派发模型配置事件', async () => {
    vi.stubGlobal('window', new EventTarget());
    const listener = vi.fn();
    window.addEventListener(AI_MODEL_SELECTION_REQUIRED_EVENT, listener as EventListener);
    const response = new Response(JSON.stringify({ detail: '任务正在运行中' }), { status: 409 });

    await readResponseError(response, '请求失败');

    expect(listener).not.toHaveBeenCalled();
  });
});
