import { describe, expect, it, vi } from 'vitest';
import {
  notifyMangaAssetAnalysisChanges,
  resolveMangaAssetWorkbenchPrompt,
  subscribeMangaAssetAnalysisChanged,
} from './mangaAssetAnalysisSync';

describe('漫画资产分析同步', () => {
  it('只通知发生资产提示词变化的章节并自动去重', () => {
    const listener = vi.fn();
    const unsubscribe = subscribeMangaAssetAnalysisChanged(listener);

    notifyMangaAssetAnalysisChanges([
      { record_id: 12, field: 'manga_asset_analysis_json' },
      { record_id: 12, field: 'manga_asset_analysis_json' },
      { record_id: 13, field: 'novel_content' },
    ]);
    unsubscribe();
    notifyMangaAssetAnalysisChanges([{ record_id: 14, field: 'manga_asset_analysis_json' }]);

    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith(12);
  });

  it('工作台优先采用当前章节分析建议而不是历史 metadata 提示词', () => {
    const prompt = resolveMangaAssetWorkbenchPrompt(
      {
        asset_type: 'character_reference',
        name: '角色候选图 01',
        analysis_name: '陈 玄',
        metadata: { prompt: '旧生成提示词' },
      },
      [{ asset_type: 'character_reference', name: '陈玄', prompt: 'Agent 更新后的角色提示词' }],
    );

    expect(prompt).toBe('Agent 更新后的角色提示词');
  });

  it('没有匹配建议时保留资产 metadata 提示词作为回退', () => {
    const prompt = resolveMangaAssetWorkbenchPrompt(
      {
        asset_type: 'prop_reference',
        name: '铜钥匙',
        metadata: { prompt: '最近一次重绘提示词' },
      },
      [{ asset_type: 'scene_reference', name: '雨巷', prompt: '场景提示词' }],
    );

    expect(prompt).toBe('最近一次重绘提示词');
  });
});
