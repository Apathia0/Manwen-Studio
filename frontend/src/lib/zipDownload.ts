/**
 * ZIP 打包下载公共工具。
 *
 * 从漫画工作流（MangaPanel.handleDownloadAll）抽出的通用下载导出主流程：
 * 接收「文件名 + 直连 URL」清单，并发下载图片、JSZip 打包、saveAs 保存。
 * 漫画导出与资产管理共用此工具，避免重复实现。
 */

/** 单个待下载文件。 */
export interface ZipDownloadItem {
  /** ZIP 内的文件名（含扩展名）。 */
  filename: string;
  /** 图片直连下载地址（OSS URL 或平台静态地址）。 */
  url: string;
}

/** 下载导出选项。 */
export interface ZipDownloadOptions {
  /** 保存的 ZIP 文件名（含 .zip 后缀）。 */
  zipName: string;
  /** 并发下载数，默认 6。 */
  concurrency?: number;
  /** 取消信号：中止后正在进行的下载会立即抛 AbortError。 */
  signal?: AbortSignal;
  /** 进度回调：已完成数量 / 总数。 */
  onProgress?: (completed: number, total: number) => void;
  /** 阶段回调：preparing 准备 / downloading 下载中 / archiving 生成压缩包。 */
  onStage?: (stage: 'preparing' | 'downloading' | 'archiving') => void;
  /** 单个文件下载失败时错误信息中的文件标签，默认「第 N 个文件」。 */
  itemLabel?: (item: ZipDownloadItem, index: number) => string;
}

function errorDetail(cause: unknown): string {
  let detail = '未知错误';
  if (cause instanceof Error && cause.message.trim()) {
    detail = cause.message.trim();
  } else if (typeof cause === 'string' && cause.trim()) {
    detail = cause.trim();
  }
  return detail;
}

function createItemDownloadError(label: string, cause: unknown): Error {
  return new Error(`${label}下载失败：${errorDetail(cause)}`);
}

function createArchiveError(itemCount: number, cause: unknown): Error {
  return new Error(`共 ${itemCount} 个文件的压缩包生成失败：${errorDetail(cause)}`);
}

/** 清洗文件名中的非法字符，避免生成无效的 ZIP 条目名。 */
export function sanitizeFilename(value: string): string {
  return value.replace(/[\\/:*?"<>|]/g, '_');
}

/** 为导出请求附加一次性参数，避免复用普通图片标签留下的无 CORS 缓存。 */
export function createExportDownloadUrl(downloadUrl: string, requestId: string): string {
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

/**
 * 将文件清单打包为 ZIP 下载。
 *
 * 图片内容始终由浏览器直连下载，调用方负责提供校验后的直连 URL 清单。
 * 下载失败时抛出带文件标签的错误；调用方通过 signal.aborted 区分「用户取消」与「真实失败」。
 *
 * @returns 成功下载并打包的文件数量。
 */
export async function downloadImagesAsZip(
  items: ZipDownloadItem[],
  options: ZipDownloadOptions,
): Promise<number> {
  const total = items.length;
  if (total === 0) {
    throw new Error('导出清单中没有可下载的文件');
  }
  const { zipName, signal, onProgress, onStage, itemLabel } = options;
  const concurrency = Math.max(1, Math.floor(options.concurrency ?? 6));

  onStage?.('preparing');
  const [{ default: JSZip }, { saveAs }] = await Promise.all([
    import('jszip'),
    import('file-saver'),
  ]);

  const zip = new JSZip();
  onStage?.('downloading');
  let completedCount = 0;
  const exportRequestId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const downloaded = await mapWithConcurrency(items, concurrency, async (item, index) => {
    try {
      const downloadUrl = createExportDownloadUrl(item.url, `${exportRequestId}-${index}`);
      const response = await fetch(downloadUrl, {
        mode: 'cors',
        credentials: 'omit',
        cache: 'no-store',
        signal,
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const blob = await response.blob();
      completedCount += 1;
      onProgress?.(completedCount, total);
      return { item, blob };
    } catch (error) {
      if (signal?.aborted) throw error;
      throw createItemDownloadError(
        itemLabel ? itemLabel(item, index) : `第 ${index + 1} 个文件`,
        error,
      );
    }
  });

  onStage?.('archiving');
  for (const { item, blob } of downloaded) {
    zip.file(item.filename, blob);
  }

  let blob: Blob;
  try {
    blob = await zip.generateAsync({
      type: 'blob',
      compression: 'STORE',
      compressionOptions: { level: 0 },
    });
  } catch (error) {
    throw createArchiveError(total, error);
  }

  saveAs(blob, zipName);
  return total;
}
