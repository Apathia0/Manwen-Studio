const DEFAULT_ERROR_MESSAGE = '操作失败，请稍后重试';

export const AI_MODEL_SELECTION_REQUIRED_EVENT = 'storycanvas:ai-model-selection-required';

export type AiModelSelectionRequiredDetail = {
  code: 'AI_MODEL_SELECTION_REQUIRED';
  message: string;
  modality: 'text' | 'image' | 'video';
  reason?: string;
};

const ERROR_RULES: Array<[RegExp, string]> = [
  [/\b402\b|payment required|insufficient (balance|credits?)|余额不足/i, '上游 AI 服务余额不足，请充值或更换可用渠道后重试'],
  [/\b401\b|unauthorized|invalid api[ _-]?key|authentication failed/i, '身份验证失败，请重新登录或检查 API Key'],
  [/\b403\b|forbidden|permission denied|access denied/i, '当前账号没有执行此操作的权限'],
  [/\b404\b|not found/i, '请求的资源不存在或已被删除'],
  [/\b408\b|request timeout|timed? out|timeout|超时/i, '请求超时，请稍后重试'],
  [/\b409\b|conflict|already (running|exists)|duplicate/i, '任务状态冲突或已有相同任务正在执行，请稍后刷新'],
  [/\b413\b|payload too large|request entity too large/i, '提交内容过大，请缩短内容或减少文件大小'],
  [/\b422\b|validation error|unprocessable entity/i, '提交参数不正确，请检查输入内容'],
  [/\b429\b|too many requests|rate limit/i, '请求过于频繁，请稍后重试'],
  [/\b500\b|internal server error/i, '服务器处理失败，请稍后重试'],
  [/\b502\b|bad gateway/i, '上游 AI 服务暂时不可用，请稍后重试'],
  [/\b503\b|service unavailable|overloaded/i, '服务暂时不可用或繁忙，请稍后重试'],
  [/\b504\b|gateway timeout/i, '上游服务响应超时，请稍后重试'],
  [/failed to fetch|networkerror|network error|load failed|connection (refused|reset|error)/i, '网络连接失败，请检查网络后重试'],
  [/cancelled|canceled|aborted/i, '任务已取消'],
];

function extractPayloadMessage(value: unknown): unknown {
  if (!value || typeof value !== 'object') return value;
  if (Array.isArray(value)) {
    const messages = value
      .map((item) => extractPayloadMessage(item))
      .filter((item): item is string => typeof item === 'string' && item.trim().length > 0);
    return messages.join('；');
  }
  const payload = value as Record<string, unknown>;
  const detail = extractPayloadMessage(payload.detail);
  if (typeof detail === 'string' && detail.trim()) return detail;
  const errors = extractPayloadMessage(payload.errors);
  if (typeof errors === 'string' && errors.trim()) return errors;

  let primary = '';
  for (const key of ['user_message', 'error', 'error_message', 'message']) {
    const message = extractPayloadMessage(payload[key]);
    if (typeof message === 'string' && message.trim()) {
      primary = message.trim();
      break;
    }
  }
  const suggestionValue = extractPayloadMessage(payload.suggestion);
  const suggestion = typeof suggestionValue === 'string' ? suggestionValue.trim() : '';
  if (primary && suggestion && suggestion !== primary) return `${primary}。${suggestion}`;
  if (primary || suggestion) return primary || suggestion;
  if (typeof payload.msg === 'string') return payload.msg;
  return '';
}

function rawErrorText(error: unknown): string {
  if (error instanceof Error) return error.message.trim();
  if (typeof error === 'string') return error.trim();
  const extracted = extractPayloadMessage(error);
  if (typeof extracted === 'string') return extracted.trim();
  return '';
}

function parseErrorText(text: string): string {
  if (!text) return '';
  try {
    const parsed = JSON.parse(text);
    const extracted = extractPayloadMessage(parsed);
    if (typeof extracted === 'string' && extracted.trim()) return extracted.trim();
  } catch {
    // 非 JSON 错误继续按普通文本处理。
  }
  return text.replace(/^Error:\s*/i, '').trim();
}

function notifyModelSelectionRequired(payload: unknown): void {
  if (!payload || typeof payload !== 'object' || typeof window === 'undefined') return;
  const responsePayload = payload as Record<string, unknown>;
  const rawDetail = responsePayload.detail;
  if (!rawDetail || typeof rawDetail !== 'object') return;
  const detail = rawDetail as Record<string, unknown>;
  if (detail.code !== 'AI_MODEL_SELECTION_REQUIRED') return;
  if (!['text', 'image', 'video'].includes(String(detail.modality || ''))) return;
  const message = typeof detail.message === 'string' && detail.message.trim()
    ? detail.message.trim()
    : '默认模型未配置或已失效，请重新选择后再试。';
  window.dispatchEvent(new CustomEvent<AiModelSelectionRequiredDetail>(AI_MODEL_SELECTION_REQUIRED_EVENT, {
    detail: {
      code: 'AI_MODEL_SELECTION_REQUIRED',
      message,
      modality: detail.modality as AiModelSelectionRequiredDetail['modality'],
      reason: typeof detail.reason === 'string' ? detail.reason : undefined,
    },
  }));
}

export function normalizeErrorMessage(error: unknown, fallback = DEFAULT_ERROR_MESSAGE): string {
  const message = parseErrorText(rawErrorText(error));
  if (!message) return fallback;
  for (const [pattern, translated] of ERROR_RULES) {
    if (pattern.test(message)) return translated;
  }
  if (/[一-鿿]/.test(message)) {
    const separatorIndex = message.search(/[：:]/);
    if (separatorIndex > 0) {
      const prefix = message.slice(0, separatorIndex).trim();
      const suffix = message.slice(separatorIndex + 1).trim();
      if (/[一-鿿]/.test(prefix) && suffix && !/[一-鿿]/.test(suffix)) {
        return `${prefix}，请稍后重试`;
      }
    }
    return message.length > 300 ? `${message.slice(0, 300)}...` : message;
  }
  return fallback;
}

export async function readResponseError(response: Response, fallback = DEFAULT_ERROR_MESSAGE): Promise<string> {
  const text = await response.text();
  if (!text) {
    return normalizeErrorMessage(`HTTP ${response.status}`, fallback);
  }
  try {
    notifyModelSelectionRequired(JSON.parse(text));
  } catch {
    // 非 JSON 错误继续按普通文本处理。
  }
  return normalizeErrorMessage(text, fallback);
}
