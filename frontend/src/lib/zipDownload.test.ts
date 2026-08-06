import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  saveAs: vi.fn(),
  generateAsync: vi.fn(),
  file: vi.fn(),
}));

vi.mock('jszip', () => ({
  default: class {
    file = mocks.file;
    generateAsync = mocks.generateAsync;
  },
}));

vi.mock('file-saver', () => ({
  saveAs: mocks.saveAs,
}));

import { createExportDownloadUrl, downloadImagesAsZip } from './zipDownload';

describe('downloadImagesAsZip', () => {
  it('本地相对媒体地址会拼接当前站点域名后再导出', () => {
    const url = createExportDownloadUrl('/static/manga/story_12/asset.png', 'request-1');
    expect(url).toBe('http://localhost/static/manga/story_12/asset.png?_storycanvas_export=request-1');
  });

  it('并发下载全部图片并打包为 ZIP 后触发保存', async () => {
    mocks.generateAsync.mockResolvedValueOnce(new Blob(['zip-content']));
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, blob: async () => new Blob(['a']) })
      .mockResolvedValueOnce({ ok: true, blob: async () => new Blob(['b']) });
    vi.stubGlobal('fetch', fetchMock);

    const stages: string[] = [];
    const result = await downloadImagesAsZip(
      [
        { filename: 'panel_01.png', url: 'https://oss.example/a.png' },
        { filename: 'panel_02.png', url: 'https://oss.example/b.png' },
      ],
      {
        zipName: '导出.zip',
        concurrency: 2,
        onStage: (stage) => stages.push(stage),
      },
    );

    expect(result).toBe(2);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(mocks.file).toHaveBeenCalledTimes(2);
    expect(mocks.file).toHaveBeenCalledWith('panel_01.png', expect.any(Blob));
    expect(mocks.generateAsync).toHaveBeenCalledTimes(1);
    expect(mocks.saveAs).toHaveBeenCalledTimes(1);
    expect(mocks.saveAs).toHaveBeenCalledWith(expect.any(Blob), '导出.zip');
    expect(stages).toEqual(['preparing', 'downloading', 'archiving']);
  });

  it('同名文件按大小写不敏感规则追加序号，且每个下载都生成 ZIP 条目', async () => {
    mocks.file.mockClear();
    mocks.generateAsync.mockClear();
    mocks.saveAs.mockClear();
    mocks.generateAsync.mockResolvedValueOnce(new Blob(['zip-content']));
    const fetchMock = vi.fn()
      .mockResolvedValue({ ok: true, blob: async () => new Blob(['image']) });
    vi.stubGlobal('fetch', fetchMock);

    const result = await downloadImagesAsZip(
      [
        { filename: 'panel.png', url: 'https://oss.example/a.png' },
        { filename: 'PANEL.PNG', url: 'https://oss.example/b.png' },
        { filename: 'panel (2).png', url: 'https://oss.example/c.png' },
        { filename: 'panel.png', url: 'https://oss.example/d.png' },
      ],
      { zipName: 'export.zip' },
    );

    expect(result).toBe(4);
    expect(mocks.file).toHaveBeenCalledTimes(4);
    expect(mocks.file.mock.calls.map(([filename]) => filename)).toEqual([
      'panel.png',
      'PANEL (2).PNG',
      'panel (2) (2).png',
      'panel (3).png',
    ]);
  });

  it('图片下载失败时抛出带文件标签的错误', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: false, status: 403 });
    vi.stubGlobal('fetch', fetchMock);

    await expect(downloadImagesAsZip(
      [{ filename: 'panel_01.png', url: 'https://oss.example/a.png' }],
      { zipName: '导出.zip' },
    )).rejects.toThrow('第 1 个文件下载失败：HTTP 403');
  });

  it('清单为空时直接报错', async () => {
    await expect(downloadImagesAsZip([], { zipName: '导出.zip' }))
      .rejects.toThrow('导出清单中没有可下载的文件');
  });
});
