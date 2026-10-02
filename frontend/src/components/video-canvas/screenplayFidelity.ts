/**
 * 改写剧本与小说原文的忠实度比对（纯前端、不调用模型）。
 *
 * 目的：让用户在审核节点里一眼看出“改写有没有失真”——哪些台词在原文里找不到、哪些只是改写、有没有凭空多出来的人物。
 * 做法：把文本切成相邻两字的片段（二元组），看剧本这一句的片段有多大比例出现在原文里。
 * 它是辅助提示，不是裁决：改写本来就会换说法，所以只把“明显对不上”的句子标出来，由用户判断。
 */

export type FidelityStatus = 'ok' | 'changed' | 'new';
export type FidelityKind = 'header' | 'dialogue' | 'action';

export interface FidelityLine {
  text: string;
  kind: FidelityKind;
  /** 台词的说话人（去掉括号提示），非台词为空 */
  speaker: string;
  /** 与原文的重合度 0~1；标题行为 null */
  coverage: number | null;
  /** 标题行没有状态 */
  status: FidelityStatus | null;
}

export interface FidelityReport {
  lines: FidelityLine[];
  dialogueTotal: number;
  dialogueOk: number;
  dialogueChanged: number;
  dialogueNew: number;
  actionNew: number;
  /** 剧本里出现、但原文里一次都没出现过的说话人 */
  newSpeakers: string[];
}

const DIALOGUE_RE = /^\s*([^\s：:，。！？]{1,16})[：:]\s*(.+)$/;
const HEADER_RE = /^\s*(?:场景|场次)\s*\d*\s*[:：]/;
const PAREN_RE = /[（(][^）)]*[）)]/g;
const STRIP_RE = /[\s，。！？、；：:,.!?;"'“”‘’（）()《》…—\-·]/g;

export function normalizeForCompare(text: string): string {
  return String(text || '').replace(STRIP_RE, '');
}

function bigrams(text: string): string[] {
  const normalized = normalizeForCompare(text);
  if (normalized.length < 2) return normalized ? [normalized] : [];
  const result: string[] = [];
  for (let i = 0; i < normalized.length - 1; i += 1) result.push(normalized.slice(i, i + 2));
  return result;
}

/** 这段文字的二元组里，有多大比例出现在原文的二元组集合中。 */
export function coverageAgainst(text: string, sourceGrams: Set<string>): number {
  const grams = bigrams(text);
  if (grams.length === 0) return 1;
  let hit = 0;
  for (const gram of grams) if (sourceGrams.has(gram)) hit += 1;
  return hit / grams.length;
}

export function sourceGramSet(source: string): Set<string> {
  return new Set(bigrams(source));
}

/** 台词：重合度 ≥ 0.75 基本忠实；0.45~0.75 改写；< 0.45 原文里找不到。 */
function dialogueStatus(coverage: number): FidelityStatus {
  if (coverage >= 0.75) return 'ok';
  if (coverage >= 0.45) return 'changed';
  return 'new';
}

/** 动作：改写会把叙述转成画面，说法差异大，只把几乎完全对不上的标出来。 */
function actionStatus(coverage: number): FidelityStatus {
  if (coverage >= 0.5) return 'ok';
  if (coverage >= 0.3) return 'changed';
  return 'new';
}

export function analyzeFidelity(screenplay: string, source: string): FidelityReport {
  const grams = sourceGramSet(source);
  const normalizedSource = normalizeForCompare(source);
  const lines: FidelityLine[] = [];
  const speakers = new Set<string>();
  const report: FidelityReport = { lines, dialogueTotal: 0, dialogueOk: 0, dialogueChanged: 0, dialogueNew: 0, actionNew: 0, newSpeakers: [] };

  for (const raw of String(screenplay || '').split(/\r?\n/)) {
    const text = raw.trim();
    if (!text) continue;
    if (HEADER_RE.test(text)) {
      lines.push({ text, kind: 'header', speaker: '', coverage: null, status: null });
      continue;
    }
    const match = DIALOGUE_RE.exec(text);
    if (match && match[1] !== '旁白') {
      const speaker = match[1].replace(PAREN_RE, '').trim() || match[1];
      const coverage = coverageAgainst(match[2], grams);
      const status = dialogueStatus(coverage);
      speakers.add(speaker);
      report.dialogueTotal += 1;
      if (status === 'ok') report.dialogueOk += 1;
      else if (status === 'changed') report.dialogueChanged += 1;
      else report.dialogueNew += 1;
      lines.push({ text, kind: 'dialogue', speaker, coverage, status });
      continue;
    }
    const coverage = coverageAgainst(text, grams);
    const status = actionStatus(coverage);
    if (status === 'new') report.actionNew += 1;
    lines.push({ text, kind: 'action', speaker: '', coverage, status });
  }
  report.newSpeakers = [...speakers].filter((name) => name.length >= 2 && !normalizedSource.includes(normalizeForCompare(name)));
  return report;
}

/** 把原文切成段落（空行或换行分段），用于点击剧本句子后在原文里定位。 */
export function splitParagraphs(source: string): string[] {
  return String(source || '').split(/\r?\n+/).map((part) => part.trim()).filter(Boolean);
}

/** 剧本里的这一句，对应原文里的哪一段：取二元组重合最多的段落；都对不上返回 -1。 */
export function findSourceParagraph(text: string, paragraphs: string[]): number {
  const body = DIALOGUE_RE.exec(text)?.[2] ?? text;
  const grams = bigrams(body);
  if (grams.length === 0) return -1;
  let best = -1;
  let bestScore = 0;
  paragraphs.forEach((paragraph, index) => {
    const set = sourceGramSet(paragraph);
    let hit = 0;
    for (const gram of grams) if (set.has(gram)) hit += 1;
    const score = hit / grams.length;
    if (score > bestScore) { bestScore = score; best = index; }
  });
  return bestScore >= 0.25 ? best : -1;
}
