export const UI_THEME_IDS = ['default', 'ink', 'studio'] as const;

export type UiThemeId = (typeof UI_THEME_IDS)[number];

export const DEFAULT_UI_THEME: UiThemeId = 'default';

export const UI_THEME_OPTIONS: Array<{ id: UiThemeId; name: string; description: string }> = [
  {
    id: 'default',
    name: '清爽蓝白',
    description: '延续当前蓝白界面，适合通用创作平台。',
  },
  {
    id: 'ink',
    name: '纸墨创作',
    description: '深色阅读氛围，适合长时间写作和灵感整理。',
  },
  {
    id: 'studio',
    name: '专业工作台',
    description: '中性灰调和高密度操作感，适合运营与制作流程。',
  },
];

export function normalizeUiTheme(value: unknown): UiThemeId {
  return UI_THEME_IDS.includes(value as UiThemeId) ? (value as UiThemeId) : DEFAULT_UI_THEME;
}
