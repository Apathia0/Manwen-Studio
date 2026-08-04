import { describe, expect, it } from 'vitest';

import {
  createMangaArchiveError,
  createMangaExportDownloadUrl,
  createMangaPageDownloadError,
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
});
