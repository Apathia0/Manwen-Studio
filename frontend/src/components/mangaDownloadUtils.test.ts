import { describe, expect, it } from 'vitest';

import {
  createMangaArchiveError,
  createMangaExportDownloadUrl,
  createMangaPageDownloadError,
  mapWithConcurrency,
} from './mangaDownloadUtils';

describe('漫画导出错误', () => {
  it('在下载错误中保留准确页号和原因', () => {
    const error = createMangaPageDownloadError(4, new Error('HTTP 403'));

    expect(error.message).toBe('漫画第 4 页下载失败：HTTP 403');
  });

  it('无法识别原因时仍返回明确的页号', () => {
    const error = createMangaPageDownloadError(2, null);

    expect(error.message).toBe('漫画第 2 页下载失败：未知错误');
  });

  it('压缩包错误包含参与打包的总页数', () => {
    const error = createMangaArchiveError(6, new Error('内存不足'));

    expect(error.message).toBe('共 6 页漫画的压缩包生成失败：内存不足');
  });

  it('为 OSS 地址增加一次性参数且保留原查询参数', () => {
    const url = createMangaExportDownloadUrl(
      'https://bucket.example/manga_outputs/chapter/1.png?version=2',
      'export-123-1',
    );

    expect(url).toBe(
      'https://bucket.example/manga_outputs/chapter/1.png?version=2&_storycanvas_export=export-123-1',
    );
  });

  it('按指定并发数持续补位并保持结果顺序', async () => {
    let active = 0;
    let maxActive = 0;
    const releaseQueue: Array<() => void> = [];
    const task = mapWithConcurrency([1, 2, 3, 4], 2, async (value) => {
      active += 1;
      maxActive = Math.max(maxActive, active);
      await new Promise<void>((resolve) => releaseQueue.push(resolve));
      active -= 1;
      return value * 10;
    });

    await Promise.resolve();
    expect(active).toBe(2);
    releaseQueue.shift()?.();
    await Promise.resolve();
    await Promise.resolve();
    expect(active).toBe(2);
    while (releaseQueue.length > 0) {
      releaseQueue.shift()?.();
      await Promise.resolve();
      await Promise.resolve();
    }

    await expect(task).resolves.toEqual([10, 20, 30, 40]);
    expect(maxActive).toBe(2);
  });

  it('任一任务失败后不再领取尚未开始的任务', async () => {
    const started: number[] = [];
    let rejectFirst: ((reason?: unknown) => void) | undefined;
    let releaseSecond: (() => void) | undefined;
    const task = mapWithConcurrency([1, 2, 3, 4], 2, async (value) => {
      started.push(value);
      if (value === 1) {
        await new Promise<void>((_resolve, reject) => { rejectFirst = reject; });
      } else if (value === 2) {
        await new Promise<void>((resolve) => { releaseSecond = resolve; });
      }
      return value;
    });

    await Promise.resolve();
    expect(started).toEqual([1, 2]);
    rejectFirst?.(new Error('下载失败'));
    await expect(task).rejects.toThrow('下载失败');
    releaseSecond?.();
    await Promise.resolve();
    await Promise.resolve();
    expect(started).toEqual([1, 2]);
  });
});
