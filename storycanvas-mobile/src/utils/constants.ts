// utils/constants.ts
// 全局常量定义

// API 基础地址
let apiBaseUrl = ''
// #ifndef H5
// 小程序/App 使用完整后端地址
const buildEnv = (import.meta as ImportMeta & {
  env?: Record<string, string | undefined>
}).env
apiBaseUrl = (buildEnv?.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '')
// #endif
// H5 使用相对路径（同源），由 nginx 代理 /api → 后端
export const BASE_URL = apiBaseUrl

// 存储键名
let KEYS: Record<string, string>
// #ifdef H5
KEYS = {
  AUTH_TOKEN: 'storycanvas.authToken',
  ACTIVE_STORY: 'storycanvas.activeStory',
  WORKSPACE_TAB: 'storycanvas.workspaceTab',
  USER_INFO: 'storycanvas.userInfo',
  DEEPSEEK_API_KEY: 'storycanvas.deepseekApiKey',
  DEEPSEEK_BASE_URL: 'storycanvas.deepseekBaseUrl',
  DEEPSEEK_MODEL: 'storycanvas.deepseekModel',
  IMAGE_API_KEY: 'storycanvas.imageApiKey',
  IMAGE_BASE_URL: 'storycanvas.imageBaseUrl',
  IMAGE_MODEL: 'storycanvas.imageModel'
}
// #endif
// #ifndef H5
KEYS = {
  AUTH_TOKEN: 'lv_auth_token',
  ACTIVE_STORY: 'lv_active_story',
  WORKSPACE_TAB: 'lv_workspace_tab',
  USER_INFO: 'lv_user_info',
  DEEPSEEK_API_KEY: 'lv_deepseek_api_key',
  DEEPSEEK_BASE_URL: 'lv_deepseek_base_url',
  DEEPSEEK_MODEL: 'lv_deepseek_model',
  IMAGE_API_KEY: 'lv_image_api_key',
  IMAGE_BASE_URL: 'lv_image_base_url',
  IMAGE_MODEL: 'lv_image_model'
}
// #endif
export const STORAGE_KEYS: Record<string, string> = KEYS

// SSE 事件类型
export const SSE_EVENTS = {
  TOKEN: 'token',
  DONE: 'done',
  ERROR: 'error',
  PROGRESS: 'progress',
  IMAGE: 'image',
  SCENES: 'scenes',
  TOOL_CALL: 'tool_call',
  TOOL_RESULT: 'tool_result'
} as const

// 标签页类型
export const WORKSPACE_TABS = {
  FRAMEWORK: 'framework',
  EDITOR: 'editor',
  MANGA: 'manga',
  AGENT: 'agent'
} as const

// 支付方式
export const PAYMENT_METHODS = {
  WECHAT_JSAPI: 'wechat_jsapi',
  WECHAT_APP: 'wechat_app',
  ALIPAY_APP: 'alipay_app',
  QRCODE: 'qrcode'
} as const

// 套餐功能中文标签
// 对齐后端 FEATURE_CATALOG（backend/main.py），用于普通用户页面展示用量
// 管理后台页面优先使用 getAdminFeatureCatalog() 返回的 catalog 数据，本字典仅作为 fallback
export interface FeatureMeta {
  label: string
  description: string
  unit: string
  kind?: 'boolean' | 'number'
}

export const FEATURE_LABELS: Record<string, FeatureMeta> = {
  // ── 小说创作 ──
  'framework.generate.monthly_limit': {
    label: '小说框架生成',
    description: '用户每月可生成世界观、角色与大纲的次数。',
    unit: '次/月',
  },
  'chapter.expand.monthly_limit': {
    label: '章节扩写',
    description: '用户每月可将章节计划扩写成正文的次数。',
    unit: '次/月',
  },
  // ── 漫画生成 ──
  'scene.generate.monthly_limit': {
    label: '漫画分镜生成',
    description: '用户每月可将文本拆分为漫画分镜的次数。',
    unit: '次/月',
  },
  // 注意: 后端实际 key 是 manga.image.generate.monthly_limit（含 .generate）
  'manga.image.generate.monthly_limit': {
    label: '生图配额',
    description: '用户每月可生成的图片总张数（含新生成和重绘）。',
    unit: '张/月',
  },
  'manga.regenerate.monthly_limit': {
    label: '漫画重绘',
    description: '对单张漫画图重新生成和修正。',
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
  // ── 高级文本能力 ──
  'ai.text.advanced_calls.monthly_limit': {
    label: '高级文本 AI',
    description: '用于框架调整、继续扩展、文本改写、正文调整、质量评估与单项重生成。',
    unit: '次/月',
  },
  // ── 视频创作 ──
  'video.shot.split.monthly_limit': {
    label: '拆镜次数',
    description: '用户每月可拆镜次数，每次点击顶部拆镜按钮消耗 1 次。',
    unit: '次/月',
  },
  'video.generate.count.monthly_limit': {
    label: '视频生成次数',
    description: '用户每月可生成视频次数，每次生成一个分镜视频消耗 1 次。',
    unit: '次/月',
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
}

// 计费周期
export const BILLING_CYCLES = {
  MONTHLY: 'monthly',
  YEARLY: 'yearly'
} as const

// 角色类型
export const USER_ROLES = {
  USER: 'user',
  ADMIN: 'admin'
} as const
