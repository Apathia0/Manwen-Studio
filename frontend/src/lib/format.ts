/**
 * 用户功能特性元数据与格式化工具函数
 */

export const USER_FEATURE_META: Record<string, { label: string; description: string; unit: string; kind?: 'boolean' | 'number' }> = {
  'framework.generate.monthly_limit': {
    label: '小说框架生成',
    description: '用于生成世界观、角色设定和故事大纲。',
    unit: '次/月',
  },
  'chapter.expand.monthly_limit': {
    label: '章节扩写',
    description: '将章节规划一键扩写为完整正文。',
    unit: '次/月',
  },
  'scene.generate.monthly_limit': {
    label: '漫画分镜生成',
    description: '将小说正文转换成分镜脚本。',
    unit: '次/月',
  },
  'manga.image.monthly_limit': {
    label: '漫画图片生成',
    description: '每月可生成的漫画图片总张数。',
    unit: '张/月',
  },
  'manga.regenerate.monthly_limit': {
    label: '漫画重绘',
    description: '对单张漫画图重新生成和修正。',
    unit: '次/月',
  },
  'ai.text.advanced_calls.monthly_limit': {
    label: '高级文本 AI',
    description: '用于框架调整、继续扩展、文本改写、正文调整、质量评估与单项重生成。',
    unit: '次/月',
  },
  'manga.max_image_count_per_chapter': {
    label: '单章节最大出图',
    description: '单个章节允许生成的最大图片数量。',
    unit: '张/章',
  },
  'manga.allow_color_mode': {
    label: '彩漫模式',
    description: '是否支持彩色漫画生成。',
    unit: '',
    kind: 'boolean',
  },
  'video.generate.seconds.monthly_limit': {
    label: '视频生成时长',
    description: '每月可生成的视频总时长。',
    unit: '秒/月',
  },
  'screenplay.generate.monthly_limit': {
    label: '剧本生成',
    description: '每月可生成影视剧本的次数。',
    unit: '次/月',
  },
  'shot.generate.monthly_limit': {
    label: '分镜任务生成',
    description: '每月可生成分镜任务卡的次数。',
    unit: '次/月',
  },
};

export function featureLabel(key: string): string {
  return USER_FEATURE_META[key]?.label || key;
}

export function featureDescription(key: string): string {
  return USER_FEATURE_META[key]?.description || '';
}

export function featureUnit(key: string): string {
  return USER_FEATURE_META[key]?.unit || '';
}

export function formatFeatureValue(key: string, value: any): string {
  const meta = USER_FEATURE_META[key];
  if (meta?.kind === 'boolean') {
    return value ? '已开启' : '未开启';
  }
  const unit = featureUnit(key);
  return unit ? `${value}${unit}` : String(value ?? '-');
}

export function getPlanFeatureEntries(features: Record<string, any> | null | undefined) {
  const source = features || {};
  const knownKeys = Object.keys(USER_FEATURE_META).filter((key) => key in source);
  const extraKeys = Object.keys(source).filter((key) => !(key in USER_FEATURE_META)).sort();
  return [...knownKeys, ...extraKeys].map((key) => ({ key, value: source[key] }));
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN');
}

export function formatSubscriptionPeriod(start: string | null | undefined, end: string | null | undefined): string {
  if (!start || !end) return '-';
  const startDate = new Date(start);
  const endDate = new Date(end);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) {
    return `${start || '-'} ~ ${end || '-'}`;
  }
  return `${startDate.toLocaleDateString('zh-CN')} ~ ${endDate.toLocaleDateString('zh-CN')}`;
}

export function formatMoney(value: number | string | null | undefined): string {
  const amount = Number(value ?? 0);
  if (!Number.isFinite(amount)) return '-';
  return amount.toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1');
}

export function paymentMethodLabel(method: string | null | undefined): string {
  if (!method) return '-';
  if (method === 'mock_qr') return '模拟支付';
  if (method === 'wechat_qr') return '微信扫码';
  if (method === 'alipay_qr') return '支付宝扫码';
  if (method === 'epay_qr') return '易支付';
  if (method.startsWith('epay_')) {
    const labels: Record<string, string> = { alipay: '支付宝', wxpay: '微信支付', qqpay: 'QQ钱包', tenpay: '财付通' };
    const type = method.slice(5);
    return `易支付(${labels[type] || type})`;
  }
  if (method === 'mapay_qr') return '码支付';
  if (method.startsWith('mapay_')) {
    const labels: Record<string, string> = { alipay: '支付宝', wxpay: '微信支付', qqpay: 'QQ钱包', usdt: 'USDT' };
    const type = method.slice(6);
    return `码支付(${labels[type] || type})`;
  }
  if (method === 'manual_adjustment') return '后台人工调整';
  return method;
}

export function orderSourceLabel(source: string | null | undefined): string {
  if (!source) return '-';
  if (source === 'admin_adjustment') return '后台套餐调整';
  if (source === 'quota_grant') return '额度补发';
  if (source === 'mock_checkout') return '模拟支付下单';
  return source;
}

export const SUBSCRIPTION_STATUS_LABELS: Record<string, string> = {
  active: '生效中',
  pending: '待支付',
  paid: '已支付',
  admin_adjusted: '后台调整',
  inactive: '未生效',
  cancelled: '已取消',
  expired: '已过期',
};

export function statusLabel(status: string | null | undefined): string {
  if (!status) return '-';
  return SUBSCRIPTION_STATUS_LABELS[status] || status;
}
