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

type CharacterBusyResource = Pick<CharacterWorkbenchResource, 'id' | 'characterName'>;
type WorkbenchBusyResource = { id: number; label?: string; characterName?: string };

export type WorkbenchBusyType = 'character' | 'storyboard' | 'video' | 'scene' | 'prop';

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

function assetNameMatchesCharacter(asset: VideoAsset, normalizedName: string): boolean {
  const normalizedAssetName = normalizeCharacterName(asset.name);
  const exactNames = [
    normalizedAssetName,
    normalizeCharacterName((asset.name || '').replace(/^Character\s*-\s*/i, '')),
  ].filter(Boolean);
  return exactNames.some((value) => value === normalizedName);
}

function assetPromptMatchesCharacter(asset: VideoAsset, normalizedName: string): boolean {
  const normalizedPrompt = normalizeCharacterName(asset.prompt);
  return Boolean(normalizedPrompt) && normalizedPrompt.includes(normalizedName);
}

export function findCharacterAssetByName(
  assets: VideoAsset[],
  targetName: string | null | undefined,
): VideoAsset | undefined {
  const normalizedName = normalizeCharacterName(targetName);
  if (!normalizedName) return undefined;
  return assets.find((item) => assetNameMatchesCharacter(item, normalizedName))
    || assets.find((item) => assetPromptMatchesCharacter(item, normalizedName));
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
    const asset = findCharacterAssetByName(assets, characterName);
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

export function buildCharacterWorkbenchBusyKey(shotId: number, characterName: string | null | undefined): string {
  return `${shotId}:${(characterName || '').trim()}`;
}

export function buildWorkbenchBusyKey(
  type: WorkbenchBusyType,
  shotId: number,
  resource: WorkbenchBusyResource,
): string {
  if (type === 'storyboard') return `storyboard:${shotId}`;
  if (type === 'video') return `video:${shotId}`;
  if (type === 'scene') return `scene:${shotId}`;
  const rawName = resource.characterName || resource.label || String(resource.id);
  const normalizedName = rawName.trim();
  return `${type}:${shotId}:${normalizedName}`;
}

export function isCharacterWorkbenchResourceBusy(
  shotId: number,
  resource: CharacterBusyResource,
  busyKeys: Set<string>,
): boolean {
  return busyKeys.has(buildCharacterWorkbenchBusyKey(shotId, resource.characterName));
}

export function findBusyCharacterWorkbenchResourceId(
  shotId: number,
  resources: CharacterBusyResource[],
  busyKeys: Set<string>,
): number | undefined {
  return resources.find((resource) => isCharacterWorkbenchResourceBusy(shotId, resource, busyKeys))?.id;
}

export function isWorkbenchResourceBusy(
  type: WorkbenchBusyType,
  shotId: number,
  resource: WorkbenchBusyResource,
  busyKeys: Set<string>,
): boolean {
  return busyKeys.has(buildWorkbenchBusyKey(type, shotId, resource));
}

export function findBusyWorkbenchResourceId(
  type: WorkbenchBusyType,
  shotId: number,
  resources: WorkbenchBusyResource[],
  busyKeys: Set<string>,
): number | undefined {
  return resources.find((resource) => isWorkbenchResourceBusy(type, shotId, resource, busyKeys))?.id;
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
