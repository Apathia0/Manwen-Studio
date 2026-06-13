import type { VideoAsset } from '../api';

export interface CharacterPromptItem {
  name: string;
  prompt: string;
}

export interface CharacterWorkbenchResource {
  id: number;
  assetId?: number;
  url: string;
  label: string;
  prompt: string;
  characterName: string;
  hasAsset: boolean;
}

export function normalizeCharacterName(name: string | null | undefined): string {
  return (name || '').trim().toLowerCase();
}

export function findCharacterPromptByName(
  prompts: CharacterPromptItem[] | null | undefined,
  targetName: string | null | undefined,
): CharacterPromptItem | null {
  const normalizedTarget = normalizeCharacterName(targetName);
  if (!normalizedTarget || !prompts?.length) return null;
  return prompts.find((item) => normalizeCharacterName(item.name) === normalizedTarget) || null;
}

function assetMatchesCharacter(asset: VideoAsset, normalizedName: string): boolean {
  const haystacks = [asset.name, asset.prompt]
    .filter((value): value is string => Boolean(value && value.trim()))
    .map((value) => normalizeCharacterName(value));
  return haystacks.some((value) => value === normalizedName || value.includes(normalizedName));
}

export function buildCharacterWorkbenchResources(
  characterNames: string[] | null | undefined,
  assets: VideoAsset[],
  prompts: CharacterPromptItem[] | null | undefined,
): CharacterWorkbenchResource[] {
  const resources: CharacterWorkbenchResource[] = [];
  (characterNames || []).forEach((rawName, index) => {
    const characterName = rawName.trim();
    if (!characterName) return;
    const normalizedName = normalizeCharacterName(characterName);
    const asset = assets.find((item) => assetMatchesCharacter(item, normalizedName));
    const prompt = findCharacterPromptByName(prompts, characterName)?.prompt || asset?.prompt || characterName;
    resources.push({
      id: asset?.id ?? -(index + 1),
      assetId: asset?.id,
      url: asset?.file_path || '',
      label: characterName,
      prompt,
      characterName,
      hasAsset: Boolean(asset?.id),
    });
  });
  return resources;
}

type WorkbenchUploadSeed = {
  assetId?: number;
  assetType: string;
  label: string;
  prompt: string;
  characterName?: string;
};

function buildAssetName(resource: WorkbenchUploadSeed): string {
  if (resource.assetType === 'character_reference') {
    return resource.characterName || resource.label || '角色资产';
  }
  if (resource.assetType === 'scene_reference') {
    return resource.label || '场景资产';
  }
  if (resource.assetType === 'prop_reference') {
    return resource.label || '道具资产';
  }
  return resource.label || '资产';
}

export async function uploadWorkbenchAsset(
  resource: WorkbenchUploadSeed,
  chapterId: number,
  file: File,
  createAsset: (
    chapterId: number,
    payload: { asset_type: string; name: string; file_path: string; prompt: string },
  ) => Promise<{ id: number }>,
  replaceAsset: (assetId: number, file: File) => Promise<unknown>,
  refresh?: () => Promise<void> | void,
): Promise<void> {
  let assetId = resource.assetId;
  if (!assetId) {
    const created = await createAsset(chapterId, {
      asset_type: resource.assetType,
      name: buildAssetName(resource),
      file_path: '',
      prompt: resource.prompt || '',
    });
    assetId = created.id;
  }
  await replaceWorkbenchAssetAndRefresh(assetId, file, replaceAsset, refresh);
}

type CharacterUploadSeed = Pick<WorkbenchUploadSeed, 'assetId' | 'label' | 'prompt' | 'characterName'>;

export async function uploadCharacterWorkbenchAsset(
  resource: CharacterUploadSeed,
  chapterId: number,
  file: File,
  createAsset: (
    chapterId: number,
    payload: { asset_type: string; name: string; file_path: string; prompt: string },
  ) => Promise<{ id: number }>,
  replaceAsset: (assetId: number, file: File) => Promise<unknown>,
  refresh?: () => Promise<void> | void,
): Promise<void> {
  await uploadWorkbenchAsset(
    {
      ...resource,
      assetType: 'character_reference',
    },
    chapterId,
    file,
    createAsset,
    replaceAsset,
    refresh,
  );
}

export async function replaceWorkbenchAssetAndRefresh(
  assetId: number | undefined,
  file: File,
  replaceAsset: (assetId: number, file: File) => Promise<unknown>,
  refresh?: () => Promise<void> | void,
): Promise<void> {
  if (!assetId) return;
  await replaceAsset(assetId, file);
  await refresh?.();
}
