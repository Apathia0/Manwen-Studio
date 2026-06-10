import { describe, expect, it } from 'vitest';
import { findCharacterPromptByName } from './videoWorkbenchUtils';

describe('findCharacterPromptByName', () => {
  it('按角色名精确匹配并忽略大小写与首尾空格', () => {
    expect(
      findCharacterPromptByName(
        [
          { name: '林秋', prompt: '角色A' },
          { name: ' 陈伯 ', prompt: '角色B' },
        ],
        '  陈伯',
      ),
    ).toEqual({ name: ' 陈伯 ', prompt: '角色B' });
  });

  it('重分析后未识别到当前角色时返回 null', () => {
    expect(findCharacterPromptByName([{ name: '林秋', prompt: '角色A' }], '周临')).toBeNull();
  });
});
