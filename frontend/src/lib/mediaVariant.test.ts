import { describe, expect, it } from 'vitest';
import { buildImageSources, mediaVariantUrl, pickMediaWidth } from './mediaVariant';

describe('mediaVariantUrl', () => {
  it('为本站静态图片追加宽度参数', () => {
    expect(mediaVariantUrl('/static/manga/a/b.png', 480)).toBe('/static/manga/a/b.png?w=480');
    expect(mediaVariantUrl('/static/video/x.JPG', 240)).toBe('/static/video/x.JPG?w=240');
  });

  it('不处理视频、外链、data/blob 与已带查询参数的地址', () => {
    expect(mediaVariantUrl('/static/video/a.mp4', 480)).toBe('/static/video/a.mp4');
    expect(mediaVariantUrl('https://oss.example.com/a.png', 480)).toBe('https://oss.example.com/a.png');
    expect(mediaVariantUrl('/static/manga/a.png?v=1', 480)).toBe('/static/manga/a.png?v=1');
    expect(mediaVariantUrl('data:image/png;base64,AAA', 480)).toBe('data:image/png;base64,AAA');
    expect(mediaVariantUrl('blob:http://x/1', 480)).toBe('blob:http://x/1');
    expect(mediaVariantUrl('', 480)).toBe('');
  });
});

describe('pickMediaWidth', () => {
  it('取不小于需求的最小档位，并设上限', () => {
    expect(pickMediaWidth(10)).toBe(96);
    expect(pickMediaWidth(100)).toBe(240);
    expect(pickMediaWidth(2000)).toBe(1920);
  });
});

describe('buildImageSources', () => {
  it('缩略图失败依次退回原图和带随机参数的原图', () => {
    const sources = buildImageSources('/static/manga/a.png', 480);
    expect(sources[0]).toBe('/static/manga/a.png?w=480');
    expect(sources[1]).toBe('/static/manga/a.png');
    expect(sources[2]).toMatch(/^\/static\/manga\/a\.png\?_r=\d+$/);
  });

  it('无法生成衍生版本时只尝试原图与重试', () => {
    const sources = buildImageSources('https://oss.example.com/a.png', 480);
    expect(sources).toHaveLength(2);
    expect(sources[0]).toBe('https://oss.example.com/a.png');
  });

  it('空地址返回空列表', () => {
    expect(buildImageSources('', 480)).toEqual([]);
  });
});
