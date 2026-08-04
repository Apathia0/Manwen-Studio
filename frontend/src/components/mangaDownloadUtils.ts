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

/** 为 OSS 导出请求附加一次性参数，避免复用普通图片标签留下的无 CORS 缓存。 */
export function createMangaExportDownloadUrl(downloadUrl: string, requestId: string): string {
  const url = new URL(downloadUrl);
  url.searchParams.set('_storycanvas_export', requestId);
  return url.toString();
}
