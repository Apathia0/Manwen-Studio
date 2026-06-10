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
