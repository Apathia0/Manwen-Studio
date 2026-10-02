/** 漫剧题材模板：预置题材、画风和节奏约束，一键交给助手创作。 */

export interface CanvasTemplate {
  id: string;
  title: string;
  desc: string;
  prompt: string;
}

const COMMON = '时长约60秒，16:9横屏；开场3秒内出现冲突或悬念，每10到15秒一次反转或信息点，结尾留集尾钩子，至少一句可传播的台词。';

export const CANVAS_TEMPLATES: CanvasTemplate[] = [
  { id: 'sweet', title: '甜宠反转', desc: '误会、心动、结尾撒糖', prompt: `请创作一个甜宠题材漫剧：男女主因误会相遇，逐步心动，结尾反转撒糖。画风明亮柔和，暖色调。${COMMON}` },
  { id: 'revenge', title: '逆袭复仇', desc: '被轻视后当众打脸', prompt: `请创作一个逆袭复仇题材漫剧：主角被当众羞辱，亮出真实身份完成打脸。画风冷峻写实，高对比光线。${COMMON}` },
  { id: 'suspense', title: '悬疑反转', desc: '日常异常，真相反转', prompt: `请创作一个悬疑题材漫剧：一个日常细节暴露出异常，层层揭开后真相反转。画风偏冷，低饱和，强调光影。${COMMON}` },
  { id: 'office', title: '职场爽文', desc: '被压制后凭实力翻盘', prompt: `请创作一个职场题材漫剧：主角被同事甩锅，凭一个关键证据当场翻盘。都市写实画风，干净利落。${COMMON}` },
  { id: 'ancient', title: '古风情缘', desc: '身份错位的虐恋', prompt: `请创作一个古风题材漫剧：身份错位的两人在一场变故中重逢，情绪克制而张力十足。画风国风水墨质感，暖冷对比。${COMMON}` },
];

export function ideaPrompt(idea: string): string {
  return `请根据这个想法创作漫剧并完成画布编排：${idea.trim()}。${COMMON}`;
}
