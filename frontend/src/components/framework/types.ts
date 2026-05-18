export interface FrameworkChapter {
  id?: number;
  act: string;
  chapter_number: number;
  title: string;
  summary?: string;
  status?: string;
  key_events?: string[];
  goal?: string;
  conflict?: string;
  hook?: string;
  payoff?: string;
  highlight?: string;
}

export const BIG_FIVE_LABELS: Record<string, string> = {
  O: '开放性',
  C: '尽责性',
  E: '外向性',
  A: '宜人性',
  N: '情绪性',
};

export const BIG_FIVE_COLORS: Record<string, string> = {
  O: 'bg-violet-400',
  C: 'bg-blue-400',
  E: 'bg-amber-400',
  A: 'bg-emerald-400',
  N: 'bg-rose-400',
};

export const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-slate-100 text-slate-600',
  draft: 'bg-amber-100 text-amber-700',
  completed: 'bg-emerald-100 text-emerald-700',
  reviewed: 'bg-blue-100 text-blue-700',
};

export const STATUS_LABELS: Record<string, string> = {
  pending: '待处理',
  draft: '草稿',
  completed: '已完成',
  reviewed: '已校对',
};

export function actPercentage(act: string): string {
  const pct: Record<string, string> = {
    '1': '25%',
    '2': '50%',
    '3': '25%',
  };
  return pct[act] || '';
}
