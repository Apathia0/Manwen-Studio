export interface MangaAssetAnalysisChange {
  record_id: number;
  field: string;
}

export interface MangaAssetPromptSource {
  asset_type: string;
  name: string;
  analysis_name?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface MangaAssetPromptSuggestion {
  asset_type: string;
  name: string;
  prompt: string;
}

type AnalysisListener = (chapterId: number) => void;

const analysisListeners = new Set<AnalysisListener>();

function normalizeAssetIdentity(value: string): string {
  return String(value || '').trim().toLowerCase().replace(/[^0-9a-z\u4e00-\u9fff]+/g, '');
}

export function findMangaAssetPromptSuggestion<T extends MangaAssetPromptSuggestion>(
  asset: MangaAssetPromptSource,
  suggestions: readonly T[],
): T | undefined {
  const assetName = normalizeAssetIdentity(asset.analysis_name || asset.name);
  return suggestions.find((suggestion) => (
    suggestion.asset_type === asset.asset_type
    && normalizeAssetIdentity(suggestion.name) === assetName
  ));
}

export function resolveMangaAssetWorkbenchPrompt(
  asset: MangaAssetPromptSource,
  suggestions: readonly MangaAssetPromptSuggestion[],
): string {
  const suggestionPrompt = findMangaAssetPromptSuggestion(asset, suggestions)?.prompt?.trim();
  if (suggestionPrompt) return suggestionPrompt;
  const metadataPrompt = asset.metadata?.prompt;
  if (typeof metadataPrompt === 'string' && metadataPrompt.trim()) return metadataPrompt.trim();
  return `保持“${asset.name}”的核心造型、材质、配色和画面风格一致，按我的要求重新绘制。`;
}

export function notifyMangaAssetAnalysisChanged(chapterId: number): void {
  if (!Number.isInteger(chapterId) || chapterId <= 0) return;
  for (const listener of Array.from(analysisListeners)) listener(chapterId);
}

export function notifyMangaAssetAnalysisChanges(changes: readonly MangaAssetAnalysisChange[]): void {
  const chapterIds = new Set(
    changes
      .filter((change) => change.field === 'manga_asset_analysis_json')
      .map((change) => change.record_id)
      .filter((chapterId) => Number.isInteger(chapterId) && chapterId > 0),
  );
  for (const chapterId of chapterIds) notifyMangaAssetAnalysisChanged(chapterId);
}

export function subscribeMangaAssetAnalysisChanged(listener: AnalysisListener): () => void {
  analysisListeners.add(listener);
  return () => analysisListeners.delete(listener);
}
