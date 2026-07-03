import { describe, expect, it, vi, beforeEach } from 'vitest';

import { coverImageUrl, getAuthorStyleResult, getAuthorStyleStatus, startAuthorStyleAnalysis, toPublicMangaAssetUrl, toPublicVideoAssetUrl, updateAuthorStyleReport, updateDeconstructionReport } from './api';
import { shouldShowAuthorStyleEntry } from './components/DeconstructionWorkPage';

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

describe('author style API', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ task_id: 't1', message: 'ok', status: 'completed', work_id: 7 }), { status: 200 })));
  });

  it('starts author style analysis with the expected endpoint', async () => {
    await startAuthorStyleAnalysis(7);

    expect(fetch).toHaveBeenCalledWith('/api/deconstruct/works/7/author-style/start', expect.objectContaining({ method: 'POST' }));
  });

  it('loads author style status with the expected endpoint', async () => {
    await getAuthorStyleStatus(7);

    expect(fetch).toHaveBeenCalledWith('/api/deconstruct/works/7/author-style/status', expect.any(Object));
  });

  it('loads author style result with the expected endpoint', async () => {
    await getAuthorStyleResult(7);

    expect(fetch).toHaveBeenCalledWith('/api/deconstruct/works/7/author-style/result', expect.any(Object));
  });
});

describe('deconstruction report API', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ok: true, report_markdown: 'edited' }), { status: 200 })));
  });

  it('sends PATCH to report endpoint with correct body', async () => {
    await updateDeconstructionReport(7, { report_markdown: 'hello' });

    expect(fetch).toHaveBeenCalledWith(
      '/api/deconstruct/works/7/report',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ report_markdown: 'hello' }),
      }),
    );
  });

  it('sends PATCH to author-style/report endpoint with correct body', async () => {
    await updateAuthorStyleReport(7, { report_markdown: 'world' });

    expect(fetch).toHaveBeenCalledWith(
      '/api/deconstruct/works/7/author-style/report',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ report_markdown: 'world' }),
      }),
    );
  });
});

describe('author style entry visibility', () => {
  it('在可操作的拆书状态显示作者画像入口', () => {
    expect(shouldShowAuthorStyleEntry('not_started')).toBe(true);
    expect(shouldShowAuthorStyleEntry('paused_after_stage1')).toBe(true);
    expect(shouldShowAuthorStyleEntry('paused_after_partial:50')).toBe(true);
    expect(shouldShowAuthorStyleEntry('completed')).toBe(true);
    expect(shouldShowAuthorStyleEntry('failed')).toBe(true);
  });

  it('在拆书任务运行中隐藏作者画像入口', () => {
    expect(shouldShowAuthorStyleEntry('pending')).toBe(false);
    expect(shouldShowAuthorStyleEntry('running')).toBe(false);
  });
});


