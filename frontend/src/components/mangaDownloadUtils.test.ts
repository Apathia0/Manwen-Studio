import { describe, expect, it } from 'vitest';

import { isRemoteMangaImagePath, shouldUseBrowserMangaZip } from './mangaDownloadUtils';

describe('漫画导出路径选择', () => {
  it('识别 HTTP 和 HTTPS 图片为远程资源', () => {
    expect(isRemoteMangaImagePath('https://cdn.example.com/panel.png')).toBe(true);
    expect(isRemoteMangaImagePath('http://oss.example.com/panel.jpg')).toBe(true);
  });

  it('将本地静态路径和存储路径识别为本地资源', () => {
    expect(isRemoteMangaImagePath('/static/manga/chapter/panel.png')).toBe(false);
    expect(isRemoteMangaImagePath('manga_outputs/chapter/panel.png')).toBe(false);
    expect(isRemoteMangaImagePath('')).toBe(false);
  });

  it('只有全部图片都在远程时才使用浏览器打包', () => {
    expect(shouldUseBrowserMangaZip([
      { image_path: 'https://oss.example.com/1.png' },
      { image_path: 'https://oss.example.com/2.png' },
    ])).toBe(true);
    expect(shouldUseBrowserMangaZip([
      { image_path: 'https://oss.example.com/1.png' },
      { image_path: 'manga_outputs/2.png' },
    ])).toBe(false);
    expect(shouldUseBrowserMangaZip([])).toBe(false);
  });
});
