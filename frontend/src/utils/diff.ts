// 行差异标记类型
export type DiffType = 'add' | 'remove' | 'same';

export interface DiffLine {
  type: DiffType;
  text: string;
  lineNumber?: number; // 在原文本中的行号（仅 same 和 remove 有）
}

/**
 * 基于 LCS（最长公共子序列）的行级 diff 算法。
 * 返回新旧文本的行差异列表，每行标记为 add / remove / same。
 */
export function lineDiff(oldStr: string, newStr: string): DiffLine[] {
  const oldLines = oldStr.split('\n');
  const newLines = newStr.split('\n');
  const o = oldLines.length;
  const n = newLines.length;

  // 构建 LCS 表
  const dp: number[][] = Array.from({ length: o + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 1; i <= o; i++) {
    for (let j = 1; j <= n; j++) {
      if (oldLines[i - 1] === newLines[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  // 回溯构建差异
  const result: DiffLine[] = [];
  let i = o, j = n;
  const temp: DiffLine[] = [];

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      temp.push({ type: 'same', text: oldLines[i - 1], lineNumber: i });
      i--;
      j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      temp.push({ type: 'add', text: newLines[j - 1], lineNumber: j });
      j--;
    } else if (i > 0) {
      temp.push({ type: 'remove', text: oldLines[i - 1], lineNumber: i });
      i--;
    }
  }

  // 回溯结果是逆序的，需要反转
  for (let k = temp.length - 1; k >= 0; k--) {
    result.push(temp[k]);
  }

  return result;
}

/**
 * 将 DiffLine 数组渲染为 HTML 字符串（带颜色类）。
 */
export function diffToHtml(diff: DiffLine[]): string {
  return diff
    .map((line) => {
      const escaped = line.text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
      if (line.type === 'add') {
        return `<div class="diff-add"><span class="diff-marker">+</span>${escaped}</div>`;
      }
      if (line.type === 'remove') {
        return `<div class="diff-remove"><span class="diff-marker">−</span>${escaped}</div>`;
      }
      return `<div class="diff-same"><span class="diff-marker"> </span>${escaped}</div>`;
    })
    .join('\n');
}
