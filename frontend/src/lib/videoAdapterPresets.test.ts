import { describe, expect, it } from 'vitest';

import { applyVideoAdapterPreset, applyVideoModelCapabilitiesPreset, createVideoAdapterDraftState, getVideoAdapterLabel, getVideoModelCapabilitiesAdapter, isVideoAdapterType } from './videoAdapterPresets';

describe('applyVideoAdapterPreset', () => {
  it('仅识别两个受支持的视频适配器，并保留未知草稿值以等待管理员处理', () => {
    const unknownAdapter = 'legacy_video_relay';

    expect(isVideoAdapterType('openai_video')).toBe(true);
    expect(isVideoAdapterType('lingdong_video')).toBe(true);
    expect(isVideoAdapterType(unknownAdapter)).toBe(false);
    expect(getVideoAdapterLabel(unknownAdapter)).toBe(`无效适配器：${unknownAdapter}`);
    expect(createVideoAdapterDraftState(unknownAdapter)).toEqual({
      adapterType: unknownAdapter,
      canSave: false,
    });
  });

  it('应用 OpenAI 原生预设时填入官方 Base URL、模型标识和推荐能力', () => {
    const draft = applyVideoAdapterPreset(
      {
        adapterType: 'lingdong_video',
        baseUrl: 'https://relay.example.com/v1',
        modelKey: 'custom-video',
        capabilities: { video: { input_modes: ['text_to_video'] } },
      },
      'openai_video',
    );

    expect(draft.adapterType).toBe('openai_video');
    expect(draft.baseUrl).toBe('https://api.openai.com/v1');
    expect(draft.modelKey).toBe('sora-2');
    expect(draft.capabilities).toMatchObject({
      video: {
        input_modes: ['text_to_video', 'image_to_video'],
        limits: { max_reference_images: 1 },
      },
    });
  });

  it('应用 Lingdong 预设时保留已有手动 Base URL，同时填入模型标识和能力', () => {
    const draft = applyVideoAdapterPreset(
      {
        adapterType: 'openai_video',
        baseUrl: 'https://relay.example.com/v1',
        modelKey: 'sora-2',
        capabilities: {},
      },
      'lingdong_video',
    );

    expect(draft).toMatchObject({
      adapterType: 'lingdong_video',
      baseUrl: 'https://relay.example.com/v1',
      modelKey: 'sd-2-vip-720',
      capabilities: {
        video: {
          payload_profile: 'legacy_lingdong',
          input_modes: ['text_to_video', 'image_to_video'],
        },
      },
    });
  });

  it('连续选择预设后保留其后的手动修改，且函数不产生保存副作用', () => {
    const afterPreset = applyVideoAdapterPreset(
      { adapterType: 'lingdong_video', baseUrl: '', modelKey: '', capabilities: {} },
      'openai_video',
    );
    const manuallyEdited = { ...afterPreset, modelKey: 'sora-2-pro' };

    expect(manuallyEdited.modelKey).toBe('sora-2-pro');
    expect(afterPreset.modelKey).toBe('sora-2');
  });

  it('为上游同步的既有视频模型按频道适配器填充能力，不改模型或频道草稿字段', () => {
    const upstreamModelDraft = {
      channelId: 42,
      channelBaseUrl: 'https://relay.example.com/v1',
      modelKey: 'upstream-video-model',
      capabilities: {},
    };

    const presetDraft = applyVideoModelCapabilitiesPreset(upstreamModelDraft, 'lingdong_video');

    expect(presetDraft).toMatchObject({
      channelId: 42,
      channelBaseUrl: 'https://relay.example.com/v1',
      modelKey: 'upstream-video-model',
      capabilities: {
        video: {
          payload_profile: 'legacy_lingdong',
          input_modes: ['text_to_video', 'image_to_video'],
        },
      },
    });
    expect(upstreamModelDraft.capabilities).toEqual({});
  });

  it('为已配置视频模型重新应用频道预设时仅替换能力草稿，不产生保存副作用', () => {
    const configuredModelDraft = {
      channelId: 9,
      channelBaseUrl: 'https://api.openai.com/v1',
      modelKey: 'custom-sora-model',
      capabilities: { video: { input_modes: ['text_to_video'] } },
    };

    const presetDraft = applyVideoModelCapabilitiesPreset(configuredModelDraft, 'openai_video');

    expect(presetDraft.channelId).toBe(9);
    expect(presetDraft.channelBaseUrl).toBe('https://api.openai.com/v1');
    expect(presetDraft.modelKey).toBe('custom-sora-model');
    expect(presetDraft.capabilities).toMatchObject({
      video: {
        input_modes: ['text_to_video', 'image_to_video'],
        limits: { max_reference_images: 1 },
      },
    });
    expect(configuredModelDraft.capabilities).toEqual({ video: { input_modes: ['text_to_video'] } });
  });

  it('仅为使用受支持频道适配器的视频模型显示能力预设', () => {
    expect(getVideoModelCapabilitiesAdapter('video', 'openai_video')).toBe('openai_video');
    expect(getVideoModelCapabilitiesAdapter('text', 'openai_video')).toBeNull();
    expect(getVideoModelCapabilitiesAdapter('video', 'legacy_video_relay')).toBeNull();
  });
});
