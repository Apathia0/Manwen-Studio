/**
 * 漫画下载导出兼容层。
 *
 * 通用下载打包逻辑已迁移至 lib/zipDownload.ts，此处保留漫画专属错误文案，
 * 并 re-export 通用函数，避免破坏既有调用方与测试。
 */
export { createExportDownloadUrl as createMangaExportDownloadUrl, mapWithConcurrency } from '../lib/zipDownload';

function errorDetail(cause: unknown): string {
  let detail = '未知错误';
  if (cause instanceof Error && cause.message.trim()) {
    detail = cause.message.trim();
  } else if (typeof cause === 'string' && cause.trim()) {
    detail = cause.trim();
  }
  return detail;
}

/** 生成包含准确页号的漫画下载错误。 */
export function createMangaPageDownloadError(imageNumber: number, cause: unknown): Error {
  return new Error(`漫画第 ${imageNumber} 页下载失败：${errorDetail(cause)}`);
}

/** 生成包含总页数的漫画压缩包错误。 */
export function createMangaArchiveError(pageCount: number, cause: unknown): Error {
  return new Error(`共 ${pageCount} 页漫画的压缩包生成失败：${errorDetail(cause)}`);
}
