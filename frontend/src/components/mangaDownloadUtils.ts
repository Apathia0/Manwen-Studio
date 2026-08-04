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

/** 使用固定数量的常驻 worker 并发处理任务，并保持结果顺序不变。 */
export async function mapWithConcurrency<T, R>(
  items: T[],
  concurrency: number,
  mapper: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  if (items.length === 0) return [];
  const workerCount = Math.min(items.length, Math.max(1, Math.floor(concurrency)));
  const results = new Array<R>(items.length);
  let nextIndex = 0;
  let stopped = false;

  const worker = async () => {
    while (!stopped && nextIndex < items.length) {
      const index = nextIndex;
      nextIndex += 1;
      try {
        results[index] = await mapper(items[index], index);
      } catch (error) {
        stopped = true;
        throw error;
      }
    }
  };

  await Promise.all(Array.from({ length: workerCount }, () => worker()));
  return results;
}
