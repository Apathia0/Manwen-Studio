import { describe, expect, it } from 'vitest';

import { coverImageUrl, toPublicMangaAssetUrl, toPublicVideoAssetUrl } from './api';

describe('coverImageUrl', () => {
  it('保留完整 OSS URL', () => {
    const ossUrl = 'https://oss.aifusion6.cn/manga_outputs/covers/cover_114_test.png';

    expect(coverImageUrl(ossUrl)).toBe(ossUrl);
  });

  it('将本地相对路径转换为静态资源路径', () => {
    expect(coverImageUrl('manga_outputs/covers/cover_114_test.png')).toBe('/static/manga/covers/cover_114_test.png');
  });
});

describe('toPublicMangaAssetUrl', () => {
  it('保留静态图片路径', () => {
    expect(toPublicMangaAssetUrl('/static/manga/covers/cover_114_test.png')).toBe('/static/manga/covers/cover_114_test.png');
  });
});

describe('toPublicVideoAssetUrl', () => {
  it('保留完整视频 URL', () => {
    const videoUrl = 'https://oss.aifusion6.cn/video_outputs/test.mp4';

    expect(toPublicVideoAssetUrl(videoUrl)).toBe(videoUrl);
  });

  it('将本地视频相对路径转换为静态资源路径', () => {
    expect(toPublicVideoAssetUrl('shot_12/test.mp4')).toBe('/static/video/shot_12/test.mp4');
  });

  it('保留静态视频路径', () => {
    expect(toPublicVideoAssetUrl('/static/video/shot_12/test.mp4')).toBe('/static/video/shot_12/test.mp4');
  });
});
