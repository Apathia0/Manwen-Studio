export type VideoAdapterType = 'openai_video' | 'lingdong_video';

export interface VideoAdapterPreset {
  id: VideoAdapterType;
  label: string;
  adapterType: VideoAdapterType;
  baseUrl: string;
  modelKey: string;
  capabilities: Record<string, unknown>;
}

export interface VideoAdapterDraft {
  adapterType: VideoAdapterType;
  baseUrl: string;
  modelKey: string;
  capabilities: Record<string, unknown>;
}

export interface VideoAdapterDraftState {
  adapterType: string;
  canSave: boolean;
}

export interface VideoModelCapabilitiesDraft {
  channelId: number;
  channelBaseUrl: string;
  modelKey: string;
  capabilities: Record<string, unknown>;
}

export const VIDEO_ADAPTER_PRESETS: readonly VideoAdapterPreset[] = [
  {
    id: 'openai_video',
    label: 'OpenAI 原生视频',
    adapterType: 'openai_video',
    baseUrl: 'https://api.openai.com/v1',
    modelKey: 'sora-2',
    capabilities: {
      schema_version: 1,
      video: {
        defaults: {
          aspect_ratio: '16:9',
          resolution: '720P',
          duration_seconds: 8,
        },
        input_modes: ['text_to_video', 'image_to_video'],
        limits: {
          aspect_ratios: ['16:9', '9:16'],
          resolutions: ['720P'],
          duration_seconds: { allowed: [4, 8, 12] },
          max_reference_images: 1,
        },
        wire: {
          size_by_resolution_aspect: {
            '720P|16:9': '1280x720',
            '720P|9:16': '720x1280',
          },
        },
      },
    },
  },
  {
    id: 'lingdong_video',
    label: 'Lingdong 兼容中转',
    adapterType: 'lingdong_video',
    baseUrl: '',
    modelKey: 'sd-2-vip-720',
    capabilities: {
      schema_version: 1,
      video: {
        payload_profile: 'legacy_lingdong',
        defaults: {
          aspect_ratio: '16:9',
          resolution: '720P',
          duration_seconds: 15,
        },
        input_modes: ['text_to_video', 'image_to_video'],
        limits: {
          aspect_ratios: ['16:9', '9:16'],
          resolutions: ['720P'],
          duration_seconds: { allowed: [15] },
          max_reference_images: 9,
        },
        wire: {
          duration_field: 'duration',
          reference_field: 'input_reference',
        },
      },
    },
  },
];

export function isVideoAdapterType(value: unknown): value is VideoAdapterType {
  return value === 'openai_video' || value === 'lingdong_video';
}

export function getVideoModelCapabilitiesAdapter(
  modality: string,
  adapterType: unknown,
): VideoAdapterType | null {
  return modality === 'video' && isVideoAdapterType(adapterType) ? adapterType : null;
}

export function getVideoAdapterLabel(adapterType: string): string {
  if (adapterType === 'openai_video') return 'OpenAI 原生';
  if (adapterType === 'lingdong_video') return 'Lingdong 兼容中转';
  return `无效适配器：${adapterType}`;
}

export function createVideoAdapterDraftState(adapterType: string): VideoAdapterDraftState {
  return { adapterType, canSave: isVideoAdapterType(adapterType) };
}

export function getVideoAdapterPreset(adapterType: VideoAdapterType): VideoAdapterPreset {
  const preset = VIDEO_ADAPTER_PRESETS.find((item) => item.id === adapterType);
  if (!preset) throw new Error(`不支持的视频适配器：${adapterType}`);
  return preset;
}

export function applyVideoAdapterPreset(
  draft: VideoAdapterDraft,
  adapterType: VideoAdapterType,
): VideoAdapterDraft {
  const preset = getVideoAdapterPreset(adapterType);
  return {
    adapterType: preset.adapterType,
    baseUrl: preset.baseUrl || draft.baseUrl,
    modelKey: preset.modelKey,
    capabilities: structuredClone(preset.capabilities),
  };
}

export function applyVideoModelCapabilitiesPreset(
  draft: VideoModelCapabilitiesDraft,
  adapterType: VideoAdapterType,
): VideoModelCapabilitiesDraft {
  return {
    ...draft,
    capabilities: structuredClone(getVideoAdapterPreset(adapterType).capabilities),
  };
}
