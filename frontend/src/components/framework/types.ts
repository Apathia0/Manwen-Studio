export interface FrameworkChapter {
  id?: number;
  act: string;
  chapter_number: number;
  title: string;
  status?: string;
  key_events?: string[];
}

export const BIG_FIVE_LABELS: Record<string, string> = {
  O: '开放性',
  C: '尽责性',
  E: '外向性',
  A: '宜人性',
  N: '神经质',
};

export const BIG_FIVE_COLORS: Record<string, string> = {
  O: 'bg-violet-400',
  C: 'bg-blue-400',
  E: 'bg-amber-400',
  A: 'bg-emerald-400',
  N: 'bg-rose-400',
};

export const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-gray-600 text-gray-200',
  draft: 'bg-yellow-600/80 text-yellow-100',
  completed: 'bg-emerald-600/80 text-emerald-100',
  reviewed: 'bg-blue-600/80 text-blue-100',
};

export const STATUS_LABELS: Record<string, string> = {
  pending: '待处理',
  draft: '草稿',
  completed: '已完成',
  reviewed: '已审核',
};

export function actPercentage(act: string): string {
  const pct: Record<string, string> = {
    '1': '25%',
    '2': '50%',
    '3': '25%',
  };
  return pct[act] || '';
}
