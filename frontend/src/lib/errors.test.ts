import { describe, expect, it } from 'vitest';

import { normalizeErrorMessage, readResponseError } from './errors';

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
  it('根据空响应状态返回中文提示', async () => {
    const response = new Response('', { status: 503 });
    await expect(readResponseError(response)).resolves.toBe('服务暂时不可用或繁忙，请稍后重试');
  });
});
