import { describe, expect, it, beforeEach, vi } from 'vitest';
import {
  buildCharacterWorkbenchResources,
  buildCharacterWorkbenchBusyKey,
  buildWorkbenchBusyKey,
  findCharacterAssetByName,
  findBusyCharacterWorkbenchResourceId,
  findBusyWorkbenchResourceId,
  isCharacterWorkbenchResourceBusy,
  isWorkbenchResourceBusy,
} from './videoWorkbenchUtils';

// 为 videoGenStore 提供 localStorage mock
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => { store[key] = value; }),
    removeItem: vi.fn((key: string) => { delete store[key]; }),
    clear: vi.fn(() => { store = {}; }),
    get length() { return Object.keys(store).length; },
    key: vi.fn((index: number) => Object.keys(store)[index] ?? null),
  };
})();
Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock, writable: true });

import { videoGenStore } from '../videoGenStore';

describe('videoWorkbenchUtils character asset matching', () => {
  it('同镜头两个角色时分别绑定各自角色资产，不被其他角色 prompt 串位', () => {
    const resources = buildCharacterWorkbenchResources(
      ['林晚晚', '顾深'],
      [
        {
          id: 11,
          asset_type: 'character_reference',
          name: 'Character - 林晚晚',
          file_path: '/assets/lin.png',
          prompt: '林晚晚站在办公室里，顾深只是背景里被提及。',
        } as any,
        {
          id: 22,
          asset_type: 'character_reference',
          name: 'Character - 顾深',
          file_path: '/assets/gu.png',
          prompt: '顾深角色设定卡',
        } as any,
      ],
      [
        { name: '林晚晚', prompt: '林晚晚角色提示词' },
        { name: '顾深', prompt: '顾深角色提示词' },
      ],
    );

    expect(resources).toHaveLength(2);
    expect(resources[0].assetId).toBe(11);
    expect(resources[0].url).toBe('/assets/lin.png');
    expect(resources[1].assetId).toBe(22);
    expect(resources[1].url).toBe('/assets/gu.png');
  });

  it('缩略图与工作台都应优先按角色名精确绑定资产', () => {
    const asset = findCharacterAssetByName(
      [
        {
          id: 11,
          asset_type: 'character_reference',
          name: 'Character - 林晚晚',
          file_path: '/assets/lin.png',
          prompt: '林晚晚站在办公室里，顾深只是背景里被提及。',
        } as any,
        {
          id: 22,
          asset_type: 'character_reference',
          name: 'Character - 顾深',
          file_path: '/assets/gu.png',
          prompt: '顾深角色设定卡',
        } as any,
      ],
      '顾深',
    );

    expect(asset?.id).toBe(22);
    expect(asset?.file_path).toBe('/assets/gu.png');
  });
});

describe('videoWorkbenchUtils character busy helpers', () => {
  it('normalizes shot id and character name into a stable busy key', () => {
    expect(buildCharacterWorkbenchBusyKey(12, '  艾琳  ')).toBe('12:艾琳');
    expect(buildCharacterWorkbenchBusyKey(12, 'alice')).toBe('12:alice');
  });

  it('detects a busy character resource by shot id and character name', () => {
    const busyKeys = new Set(['8:艾琳']);
    const resource = {
      id: -1,
      label: '艾琳',
      prompt: '银发少女',
      characterName: ' 艾琳 ',
      url: '',
      hasAsset: false,
    };

    expect(isCharacterWorkbenchResourceBusy(8, resource, busyKeys)).toBe(true);
    expect(isCharacterWorkbenchResourceBusy(9, resource, busyKeys)).toBe(false);
  });

  it('finds the first busy character resource id for reopening workbench', () => {
    const resources = [
      {
        id: -1,
        label: '艾琳',
        prompt: '银发少女',
        characterName: '艾琳',
        url: '',
        hasAsset: false,
      },
      {
        id: -2,
        label: '诺亚',
        prompt: '黑发少年',
        characterName: '诺亚',
        url: '',
        hasAsset: false,
      },
    ];

    expect(findBusyCharacterWorkbenchResourceId(3, resources, new Set(['3:诺亚']))).toBe(-2);
    expect(findBusyCharacterWorkbenchResourceId(3, resources, new Set())).toBeUndefined();
  });

  it('builds stable busy keys for storyboard, video, scene and prop resources', () => {
    expect(buildWorkbenchBusyKey('storyboard', 5, { id: 10 })).toBe('storyboard:5');
    expect(buildWorkbenchBusyKey('video', 5, { id: 10 })).toBe('video:5');
    expect(buildWorkbenchBusyKey('scene', 5, { id: 10, label: '场景' })).toBe('scene:5');
    expect(buildWorkbenchBusyKey('prop', 5, { id: 10, label: '  宝剑  ' })).toBe('prop:5:宝剑');
  });

  it('detects and restores busy resource across all workbench types', () => {
    const storyboardResource = { id: 21 };
    const propResources = [
      { id: 31, label: '宝剑', characterName: '宝剑' },
      { id: 32, label: '王冠', characterName: '王冠' },
    ];

    expect(isWorkbenchResourceBusy('storyboard', 7, storyboardResource, new Set(['storyboard:7']))).toBe(true);
    expect(findBusyWorkbenchResourceId('prop', 7, propResources, new Set(['prop:7:王冠']))).toBe(32);
    expect(findBusyWorkbenchResourceId('video', 7, [{ id: 99 }], new Set())).toBeUndefined();
  });
});

describe('videoGenStore', () => {
  beforeEach(() => {
    // 清除 localStorage 和内存中缓存的状态
    localStorage.clear();
    [123, 124, 125].forEach((id) => videoGenStore.clear(id));
  });

  it('应能开始任务并获取初始状态', () => {
    const shotId = 123;
    const jobId = 456;

    videoGenStore.startJob(shotId, jobId);

    const state = videoGenStore.get(shotId);
    expect(state).toBeDefined();
    expect(state?.active).toBe(true);
    expect(state?.jobId).toBe(jobId);
    expect(state?.status).toBe('pending');
    expect(state?.progress).toBe(0);
  });

  it('应能更新进度', () => {
    const shotId = 124;
    const jobId = 456;

    videoGenStore.startJob(shotId, jobId);
    videoGenStore.updateProgress(shotId, 'running', 50, '正在生成...');

    const state = videoGenStore.get(shotId);
    expect(state?.status).toBe('running');
    expect(state?.progress).toBe(50);
    expect(state?.statusMsg).toBe('正在生成...');
  });

  it('应能标记为成功', () => {
    const shotId = 125;
    const jobId = 456;

    videoGenStore.startJob(shotId, jobId);
    videoGenStore.markSucceeded(shotId);

    const state = videoGenStore.get(shotId);
    expect(state?.active).toBe(false);
    expect(state?.status).toBe('succeeded');
    expect(state?.progress).toBe(100);
    expect(state?.statusMsg).toBe('视频生成完成');
  });

  it('应能标记为失败', () => {
    const shotId = 123;
    const jobId = 456;

    videoGenStore.startJob(shotId, jobId);
    videoGenStore.markFailed(shotId, '生成失败');

    const state = videoGenStore.get(shotId);
    expect(state?.active).toBe(false);
    expect(state?.status).toBe('failed');
    expect(state?.errorMsg).toBe('生成失败');
    expect(state?.statusMsg).toBe('视频生成失败');
  });

  it('应能持久化到 localStorage', () => {
    const shotId = 124;
    const jobId = 456;

    videoGenStore.startJob(shotId, jobId);

    const stored = localStorage.getItem('video_gen_states');
    expect(stored).toBeDefined();

    const parsed = JSON.parse(stored!);
    expect(parsed[shotId]).toBeDefined();
    expect(parsed[shotId].active).toBe(true);
    expect(parsed[shotId].jobId).toBe(jobId);
  });

  it('应能取消订阅', () => {
    const shotId = 125;
    let callCount = 0;
    const unsubscribe = videoGenStore.subscribe(() => { callCount++; });

    videoGenStore.startJob(shotId, 789);
    expect(callCount).toBe(1);

    unsubscribe();

    videoGenStore.markSucceeded(shotId);
    // 取消订阅后不应再触发回调
    expect(callCount).toBe(1);
  });
});
