import { describe, expect, it, vi } from 'vitest';
import { findCharacterPromptByName, replaceWorkbenchAssetAndRefresh, uploadCharacterWorkbenchAsset, uploadWorkbenchAsset } from './videoWorkbenchUtils';

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

describe('replaceWorkbenchAssetAndRefresh', () => {
  it('替换成功后刷新列表', async () => {
    const replaceAsset = vi.fn().mockResolvedValue(undefined);
    const refresh = vi.fn().mockResolvedValue(undefined);

    await replaceWorkbenchAssetAndRefresh(81, {} as File, replaceAsset, refresh);

    expect(replaceAsset).toHaveBeenCalledWith(81, {});
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('没有 assetId 时跳过替换和刷新', async () => {
    const replaceAsset = vi.fn().mockResolvedValue(undefined);
    const refresh = vi.fn().mockResolvedValue(undefined);

    await replaceWorkbenchAssetAndRefresh(undefined, {} as File, replaceAsset, refresh);

    expect(replaceAsset).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
  });
});

describe('uploadCharacterWorkbenchAsset', () => {
  it('没有 assetId 时先创建资产再替换并刷新', async () => {
    const createAsset = vi.fn().mockResolvedValue({ id: 91 });
    const replaceAsset = vi.fn().mockResolvedValue(undefined);
    const refresh = vi.fn().mockResolvedValue(undefined);

    await uploadCharacterWorkbenchAsset(
      {
        assetId: undefined,
        characterName: '林秋',
        label: '林秋',
        prompt: '角色提示词',
      },
      441,
      {} as File,
      createAsset,
      replaceAsset,
      refresh,
    );

    expect(createAsset).toHaveBeenCalledWith(441, {
      asset_type: 'character_reference',
      name: '林秋',
      file_path: '',
      prompt: '角色提示词',
    });
    expect(replaceAsset).toHaveBeenCalledWith(91, {});
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});

describe('uploadWorkbenchAsset', () => {
  it('场景/道具资源没有 assetId 时先创建再替换并刷新', async () => {
    const createAsset = vi.fn().mockResolvedValue({ id: 101 });
    const replaceAsset = vi.fn().mockResolvedValue(undefined);
    const refresh = vi.fn().mockResolvedValue(undefined);

    await uploadWorkbenchAsset(
      {
        assetId: undefined,
        assetType: 'scene_reference',
        label: '场景',
        prompt: '夜晚走廊场景',
      },
      441,
      {} as File,
      createAsset,
      replaceAsset,
      refresh,
    );

    expect(createAsset).toHaveBeenCalledWith(441, {
      asset_type: 'scene_reference',
      name: '场景',
      file_path: '',
      prompt: '夜晚走廊场景',
    });
    expect(replaceAsset).toHaveBeenCalledWith(101, {});
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});
