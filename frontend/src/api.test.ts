import { describe, expect, it, vi, beforeEach } from 'vitest';

import { adjustChapterContent, analyzeChapterMangaAssets, apiHeaders, coverImageUrl, createAdminAiChannel, createStoryKnowledge, createStoryKnowledgeCategory, deleteAdminAiChannel, deleteStoryKnowledge, deleteStoryKnowledgeCategory, expandChapter, generateMangaAsset, generateMangaAssetsBatch, generateMangaStream, generateNovel, generateScenes, generateStoryCharRefStream, getAiChannels, getAiCredentials, getApiKeySettings, getAuthorStyleResult, getAuthorStyleStatus, getBackgroundTaskStatus, getLocalCredentialMode, getMangaAssetAnalysis, getMangaExportManifest, getStoryKnowledge, login, previewAdminAiChannelPrices, redrawMangaAsset, regenerateStoryChapterContext, regenerateVideoAsset, retryVideoJob, saveAiModalityCredential, saveApiKeySettings, saveMangaAssetAnalysis, setLocalCredentialMode, startAuthorStyleAnalysis, syncAdminAiChannelPrices, syncStoryKnowledgeWithAI, testAiModalityCredential, toPublicMangaAssetUrl, toPublicVideoAssetUrl, updateAdminAiChannel, updateAuthorStyleReport, updateDeconstructionReport, updateStoryBible, updateStoryChapterContext, updateStoryKnowledge, updateStoryKnowledgeCategory } from './api';
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

describe('漫画图片浏览器导出 API', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => 'test-token'),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
  });

  it('通过 GET 获取 OSS 导出清单', async () => {
    const payload = {
      images: [{
        image_number: 1,
        filename: 'panel_01.png',
        download_url: 'https://cdn.example.com/manga_outputs/764/1.png',
      }],
    };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(payload), { status: 200 })));

    await expect(getMangaExportManifest(764)).resolves.toEqual(payload);
    expect(fetch).toHaveBeenCalledWith(
      '/api/chapters/764/manga-images/export-manifest',
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  it('保留 409 状态和后端错误信息', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ detail: '第 2 页图片不是当前平台配置的 OSS 资源' }),
      { status: 409 },
    )));

    await expect(getMangaExportManifest(764)).rejects.toMatchObject({
      status: 409,
      message: '第 2 页图片不是当前平台配置的 OSS 资源',
    });
  });
});

describe('作品知识 API', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
  });

  it('读取作品的四类知识集合', async () => {
    const payload = { story_id: 12, knowledge_revision: 3, resources: [], entities: [], facts: [], plot_threads: [] };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(payload), { status: 200 })));

    await expect(getStoryKnowledge(12)).resolves.toEqual(payload);
    expect(fetch).toHaveBeenCalledWith('/api/stories/12/knowledge', expect.any(Object));
  });

  it('新增、编辑和删除均使用作品与知识类型作用域', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ok: true, item: {}, knowledge_revision: 4 }), { status: 200 })));

    await createStoryKnowledge(12, 'fact', { subject_key: 'character:a', predicate: 'location' });
    await updateStoryKnowledge(12, 'fact', 9, { value_text: '位于灰市' });
    await deleteStoryKnowledge(12, 'fact', 9, 3);

    expect(fetch).toHaveBeenNthCalledWith(1, '/api/stories/12/knowledge/fact', expect.objectContaining({ method: 'POST' }));
    expect(fetch).toHaveBeenNthCalledWith(2, '/api/stories/12/knowledge/fact/9', expect.objectContaining({ method: 'PUT' }));
    expect(fetch).toHaveBeenNthCalledWith(3, '/api/stories/12/knowledge/fact/9?expected_version=3', expect.objectContaining({ method: 'DELETE' }));
  });

  it('保存和重新提取创作包时携带当前版本', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ content: '原文', version: 5 }), { status: 200 })));

    await updateStoryChapterContext(12, 8, '完整创作包原文', 4);
    await regenerateStoryChapterContext(12, 8, 5);

    expect(fetch).toHaveBeenNthCalledWith(1, '/api/stories/12/knowledge/chapter-context?chapter_number=8', expect.objectContaining({
      method: 'PUT',
      body: JSON.stringify({ content: '完整创作包原文', expected_version: 4 }),
    }));
    expect(fetch).toHaveBeenNthCalledWith(2, '/api/stories/12/knowledge/chapter-context/regenerate?chapter_number=8&expected_version=5', expect.objectContaining({ method: 'POST' }));
  });

  it('管理知识分类时使用统一分类端点和版本号', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ok: true, category: { id: 7 }, knowledge_revision: 5 }), { status: 200 })));

    await createStoryKnowledgeCategory(12, { knowledge_kind: 'fact', name: '身份', color: '#2563eb', sort_order: 1 });
    await updateStoryKnowledgeCategory(12, 7, { name: '身份关系', expected_version: 2 });
    await deleteStoryKnowledgeCategory(12, 7, 3);

    expect(fetch).toHaveBeenNthCalledWith(1, '/api/stories/12/knowledge/categories/fact', expect.objectContaining({ method: 'POST' }));
    expect(fetch).toHaveBeenNthCalledWith(2, '/api/stories/12/knowledge/categories/7', expect.objectContaining({ method: 'PUT' }));
    expect(fetch).toHaveBeenNthCalledWith(3, '/api/stories/12/knowledge/categories/7?expected_version=3', expect.objectContaining({ method: 'DELETE' }));
  });

  it('更新作品圣经时携带当前知识版本', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ story_bible: {}, knowledge_revision: 8 }), { status: 200 })));

    await updateStoryBible(12, { creative_brief: { genre: '高武' } as any }, 7);

    expect(fetch).toHaveBeenCalledWith('/api/stories/12/story-bible', expect.objectContaining({
      method: 'PATCH',
      body: JSON.stringify({ story_bible: { creative_brief: { genre: '高武' } }, expected_knowledge_revision: 7 }),
    }));
  });

  it('提交全量和定向知识同步时携带模式与范围', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ task_id: 'knowledge_sync_12_test', status: 'pending', message: '已提交' }), { status: 202 }));
    vi.stubGlobal('fetch', fetchMock);

    await syncStoryKnowledgeWithAI(12, { mode: 'full', scope: 'facts' });

    expect(fetchMock).toHaveBeenCalledWith('/api/stories/12/knowledge/ai-sync', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ mode: 'full', scope: 'facts' }),
    }));
  });
});

describe('章节正文后台任务 API', () => {
  beforeEach(() => {
    const store = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: vi.fn((key: string) => store.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => { store.set(key, value); }),
      removeItem: vi.fn((key: string) => { store.delete(key); }),
    });
  });

  it('生成正文时提交任务、查询状态并读取最终章节', async () => {
    const chapter = { id: 23, story_id: 12, chapter_number: 5, title: '灰市追查' };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ task_id: 'chapter_gen_23_test', status: 'pending', chapter_id: 23, message: '已提交' }), { status: 202 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ task_id: 'chapter_gen_23_test', task_type: 'chapter_generation', status: 'succeeded', result_json: { chapter_id: 23 } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(chapter), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(generateNovel(23)).resolves.toEqual(chapter);
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/chapters/23/generation-task', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ action: 'generate_novel' }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/tasks/chapter_gen_23_test', expect.any(Object));
    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/chapters/23', expect.any(Object));
    expect(localStorage.setItem).toHaveBeenCalledWith(
      'storycanvas.chapterGenerationTasks',
      expect.stringContaining('chapter_gen_23_test'),
    );
  });

  it('刷新后再次生成优先恢复本地记录的活动任务', async () => {
    localStorage.setItem('storycanvas.chapterGenerationTasks', JSON.stringify({
      23: { task_id: 'chapter_gen_23_saved', chapter_id: 23, action: 'generate_novel', updated_at: Date.now() },
    }));
    const chapter = { id: 23, story_id: 12, chapter_number: 5, title: '灰市追查' };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ task_id: 'chapter_gen_23_saved', task_type: 'chapter_generation', status: 'succeeded', result_json: { chapter_id: 23 } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(chapter), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(generateNovel(23)).resolves.toEqual(chapter);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).not.toHaveBeenCalledWith('/api/chapters/23/generation-task', expect.any(Object));
    expect(localStorage.removeItem).not.toHaveBeenCalled();
    expect(localStorage.setItem).toHaveBeenLastCalledWith('storycanvas.chapterGenerationTasks', '{}');
  });

  it('轮询遇到临时网络错误后继续等待后台任务', async () => {
    vi.useFakeTimers();
    const chapter = { id: 23, story_id: 12, chapter_number: 5, title: '灰市追查' };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ task_id: 'chapter_gen_23_retry', status: 'pending', chapter_id: 23, message: '已提交' }), { status: 202 }))
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(new Response(JSON.stringify({ task_id: 'chapter_gen_23_retry', task_type: 'chapter_generation', status: 'succeeded', result_json: { chapter_id: 23 } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(chapter), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    const promise = generateNovel(23);
    await vi.advanceTimersByTimeAsync(2000);
    await expect(promise).resolves.toEqual(chapter);
    vi.useRealTimers();
  });

  it('框架扩写和整章调整提交对应的后台任务动作', async () => {
    const chapter = { id: 23, story_id: 12, chapter_number: 5, title: '灰市追查' };
    const responses = [
      { task_id: 'expand', status: 'pending', chapter_id: 23, message: '已提交' },
      { task_id: 'expand', task_type: 'chapter_generation', status: 'succeeded', result_json: { chapter_id: 23 } },
      chapter,
      { task_id: 'adjust', status: 'pending', chapter_id: 23, message: '已提交' },
      { task_id: 'adjust', task_type: 'chapter_generation', status: 'succeeded', result_json: { chapter_id: 23 } },
      chapter,
    ];
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(responses.shift()), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await expandChapter(12, { act: '第一幕', chapter_number: 5, chapter_title: '灰市追查' });
    await adjustChapterContent(23, '加强冲突');

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/stories/12/expand-chapter/task', expect.objectContaining({ method: 'POST' }));
    expect(fetchMock).toHaveBeenNthCalledWith(4, '/api/chapters/23/generation-task', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ action: 'adjust_content', instruction: '加强冲突' }),
    }));
  });
});

describe('分类 AI 凭据 API', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
  });

  it('读取三类凭据聚合状态', async () => {
    const payload = { credentials: { text: { configured: true }, image: { configured: false }, video: { configured: false } }, configured_count: 1 };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(payload), { status: 200 })));

    await expect(getAiCredentials()).resolves.toEqual(payload);
    expect(fetch).toHaveBeenCalledWith('/api/ai/credentials', expect.any(Object));
  });

  it('保存图片 Key 时只发送到图片槽位', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ modality: 'image', configured: true }), { status: 200 })));

    await saveAiModalityCredential('image', 'image-secret');

    expect(fetch).toHaveBeenCalledWith('/api/ai/credentials/image', expect.objectContaining({
      method: 'PUT',
      body: JSON.stringify({ api_key: 'image-secret' }),
    }));
  });

  it('视频 Key 测试返回明确模态且不调用生成端点', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ok: true, verified: false, modality: 'video' }), { status: 200 })));

    await expect(testAiModalityCredential('video')).resolves.toMatchObject({ modality: 'video' });
    expect(fetch).toHaveBeenCalledWith('/api/ai/credentials/video/test', expect.objectContaining({ method: 'POST' }));
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

describe('regenerateVideoAsset', () => {
  it('重生成请求会携带当前风格预设', async () => {
    vi.stubGlobal('localStorage', {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ asset: {} }), { status: 200 })));

    await regenerateVideoAsset(42, '角色提示词', undefined, '日式动漫风');

    expect(fetch).toHaveBeenCalledWith(
      '/api/video-assets/42/regen',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ prompt: '角色提示词', style_preset: '日式动漫风' }),
      }),
    );
  });
});

describe('自定义视频上游配置', () => {
  it('登录后将旧版全局上游配置迁移到当前用户', async () => {
    const storage = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: vi.fn((key: string) => storage.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => storage.set(key, value)),
      removeItem: vi.fn((key: string) => storage.delete(key)),
    });
    storage.set('storycanvas.deepseekBaseUrl', 'https://legacy.example.com/v1');
    storage.set('storycanvas.imageBaseUrl', 'https://legacy.example.com/v1');
    storage.set('storycanvas.videoBaseUrl', 'https://legacy.example.com/v1');
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      token: 'token',
      user: { id: 7, name: '用户', email: 'u@example.com', role: 'user', can_override_api_key: true, can_override_api_url: true },
    }), { status: 200 })));

    await login({ email: 'u@example.com', password: 'password' });

    expect(storage.get('storycanvas.deepseekBaseUrl')).toBeUndefined();
    expect(getApiKeySettings().upstreamBaseUrl).toBe('https://legacy.example.com/v1');
  });

  it('保存视频 URL 和模型并注入通用请求头', () => {
    const storage = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: vi.fn((key: string) => storage.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => storage.set(key, value)),
      removeItem: vi.fn((key: string) => storage.delete(key)),
    });
    storage.set('storycanvas.authUserId', '7');
    storage.set('storycanvas_credential_mode.user.7', 'user_key');

    saveApiKeySettings({
      deepseekApiKey: '',
      upstreamBaseUrl: ' https://api.example.com/v1/ ',
      deepseekBaseUrl: '',
      deepseekModel: '',
      imageApiKey: '',
      imageBaseUrl: '',
      imageModel: '',
      videoBaseUrl: '',
      videoModel: ' seedance-custom ',
    });

    expect(getApiKeySettings()).toMatchObject({
      upstreamBaseUrl: 'https://api.example.com/v1/',
      videoModel: 'seedance-custom',
    });
    expect(apiHeaders()).toMatchObject({
      'X-DeepSeek-Base-URL': 'https://api.example.com/v1/',
      'X-Image-Base-URL': 'https://api.example.com/v1/',
      'X-Video-Base-URL': 'https://api.example.com/v1/',
      'X-Video-Model': 'seedance-custom',
    });
  });

  it('按用户隔离同一浏览器中的自定义上游配置', () => {
    const storage = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: vi.fn((key: string) => storage.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => storage.set(key, value)),
      removeItem: vi.fn((key: string) => storage.delete(key)),
    });
    const emptySettings = {
      deepseekApiKey: '',
      upstreamBaseUrl: '',
      deepseekBaseUrl: '',
      deepseekModel: '',
      imageApiKey: '',
      imageBaseUrl: '',
      imageModel: '',
      videoBaseUrl: '',
      videoModel: '',
    };

    storage.set('storycanvas.authUserId', '1');
    saveApiKeySettings({ ...emptySettings, videoBaseUrl: 'https://video-a.example.com/v1' });
    storage.set('storycanvas.authUserId', '2');
    expect(getApiKeySettings().videoBaseUrl).toBe('');
    saveApiKeySettings({ ...emptySettings, videoBaseUrl: 'https://video-b.example.com/v1' });

    storage.set('storycanvas.authUserId', '1');
    expect(getApiKeySettings().videoBaseUrl).toBe('https://video-a.example.com/v1');
    storage.set('storycanvas.authUserId', '2');
    expect(getApiKeySettings().videoBaseUrl).toBe('https://video-b.example.com/v1');
  });

  it('按用户隔离凭据模式', () => {
    const storage = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: vi.fn((key: string) => storage.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => storage.set(key, value)),
      removeItem: vi.fn((key: string) => storage.delete(key)),
    });

    storage.set('storycanvas.authUserId', '1');
    setLocalCredentialMode('user_key');
    storage.set('storycanvas.authUserId', '2');
    expect(getLocalCredentialMode()).toBe('platform');
    setLocalCredentialMode('platform');

    storage.set('storycanvas.authUserId', '1');
    expect(getLocalCredentialMode()).toBe('user_key');
    storage.set('storycanvas.authUserId', '2');
    expect(getLocalCredentialMode()).toBe('platform');
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

describe('video job API', () => {
  it('使用当前视频重试路由并解包 job', async () => {
    const job = { id: 9, shot_id: 3, status: 'pending' };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ job }), { status: 200 })));

    await expect(retryVideoJob(9)).resolves.toEqual(job);
    expect(fetch).toHaveBeenCalledWith(
      '/api/video-jobs/9/retry',
      expect.objectContaining({ method: 'POST' }),
    );
  });
});

describe('AI 渠道 API', () => {
  it('读取用户可见渠道列表', async () => {
    const result = { channels: [{ id: 1, code: 'text', name: '文本', base_url: 'https://example.com/v1', modality: 'text' }] };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(result), { status: 200 })));

    await expect(getAiChannels()).resolves.toEqual(result);
    expect(fetch).toHaveBeenCalledWith('/api/ai/channels', expect.any(Object));
  });

  it('创建视频渠道时发送显式 adapter_type', async () => {
    const channel = { id: 3, code: 'openai-video', name: 'OpenAI 视频', adapter_type: 'openai_video' };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(channel), { status: 200 })));
    const payload = {
      code: 'openai-video',
      name: 'OpenAI 视频',
      adapter_type: 'openai_video' as const,
      base_url: 'https://api.openai.com/v1',
      modality: 'video',
      extra_config_json: {},
    };

    await expect(createAdminAiChannel(payload)).resolves.toEqual(channel);
    expect(fetch).toHaveBeenCalledWith(
      '/api/admin/ai/channels',
      expect.objectContaining({ method: 'POST', body: JSON.stringify(payload) }),
    );
  });

  it('更新视频渠道时发送管理员主动选择的 adapter_type', async () => {
    const channel = { id: 3, code: 'relay-video', name: '兼容视频', adapter_type: 'lingdong_video' };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(channel), { status: 200 })));
    const payload = {
      name: '兼容视频',
      adapter_type: 'lingdong_video' as const,
      base_url: 'https://relay.example.com/v1',
      modality: 'video',
      extra_config_json: {},
    };

    await expect(updateAdminAiChannel(3, payload)).resolves.toEqual(channel);
    expect(fetch).toHaveBeenCalledWith(
      '/api/admin/ai/channels/3',
      expect.objectContaining({ method: 'PUT', body: JSON.stringify(payload) }),
    );
  });

  it('删除渠道时调用渠道删除接口', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ok: true, channel_id: 3 }), { status: 200 })));

    await expect(deleteAdminAiChannel(3)).resolves.toEqual({ ok: true, channel_id: 3 });
    expect(fetch).toHaveBeenCalledWith(
      '/api/admin/ai/channels/3',
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('读取渠道模型定价同步预览', async () => {
    const result = {
      channel: { id: 3, code: 'text', name: '文本', modality: 'text' },
      yuan_to_points: 10,
      yuan_per_point: 0.1,
      upstream: { currency: 'CNY', quota_per_unit: 500000, group: 'default', group_ratio: 1, pricing_version: 'v1' },
      summary: { total: 1, ready: 1, unchanged: 0, skipped: 0 },
      items: [],
    };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(result), { status: 200 })));

    await expect(previewAdminAiChannelPrices(3)).resolves.toEqual(result);
    expect(fetch).toHaveBeenCalledWith(
      '/api/admin/ai/channels/3/prices/preview',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('提交选中的已有模型定价', async () => {
    const payload = {
      model_ids: [5, 8],
      expected_price_ids: { 5: null, 8: 12 },
      expected_pricing_version: 'v1',
      expected_yuan_to_points: 10,
    };
    const result = { updated: [5], unchanged: [8], skipped: [] };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(result), { status: 200 })));

    await expect(syncAdminAiChannelPrices(3, payload)).resolves.toEqual(result);
    expect(fetch).toHaveBeenCalledWith(
      '/api/admin/ai/channels/3/prices/sync',
      expect.objectContaining({ method: 'POST', body: JSON.stringify(payload) }),
    );
  });
});

describe('manga asset analysis API', () => {
  it('分镜生成在绑定模板时携带预设 ID，未绑定时保持无请求体', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ scenes: [] }), { status: 200 })));

    await generateScenes(12, undefined, 7);
    await generateScenes(12);

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      '/api/chapters/12/generate-scenes',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ preset_id: 7 }),
      }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      '/api/chapters/12/generate-scenes',
      expect.objectContaining({
        method: 'POST',
        body: undefined,
      }),
    );
  });

  it('漫画 SSE 空响应体会返回中文错误终态', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 200 })));
    const onEvent = vi.fn();

    generateMangaStream(12, onEvent);

    await vi.waitFor(() => expect(onEvent).toHaveBeenCalledWith({
      type: 'error',
      data: { error: '漫画生成连接未返回数据，请稍后重试' },
    }));
  });

  it('角色参考图 SSE 无终态断流会返回中文错误', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      'event: snapshot\ndata: {"images":[],"max":4,"generated":[],"skipped":[]}\n\n',
      { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
    )));
    const onEvent = vi.fn();

    generateStoryCharRefStream(12, {}, onEvent);

    await vi.waitFor(() => expect(onEvent).toHaveBeenCalledWith({
      type: 'error',
      data: { error: '角色参考图连接意外中断，请稍后重试' },
    }));
  });

  it('将漫画自动资产选择作为生成任务快照提交', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 200 })));

    generateMangaStream(12, () => {}, '1024x1536', '真人风格', '/static/manga/style.png', {
      enabled: true,
      types: ['character', 'prop'],
    });

    await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(fetch).toHaveBeenCalledWith(
      '/api/chapters/12/generate-manga-stream',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          size: '1024x1536',
          style_preset_name: '真人风格',
          style_ref_url: '/static/manga/style.png',
          auto_asset_extraction: { enabled: true, types: ['character', 'prop'] },
        }),
      }),
    );
  });

  it.each([
    {
      name: '默认三类',
      config: { enabled: true, types: ['character', 'scene', 'prop'] as Array<'character' | 'scene' | 'prop'> },
    },
    {
      name: '关闭自动提取',
      config: { enabled: false, types: ['character', 'scene', 'prop'] as Array<'character' | 'scene' | 'prop'> },
    },
    {
      name: '空选择',
      config: { enabled: true, types: [] as Array<'character' | 'scene' | 'prop'> },
    },
    {
      name: '仅场景',
      config: { enabled: true, types: ['scene'] as Array<'character' | 'scene' | 'prop'> },
    },
  ])('完整保留$name配置到漫画生成请求体', async ({ config }) => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 200 })));

    generateMangaStream(12, () => {}, undefined, undefined, undefined, config);

    await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(fetch).toHaveBeenCalledWith(
      '/api/chapters/12/generate-manga-stream',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ auto_asset_extraction: config }),
      }),
    );
  });

  it('analyzes assets from the current chapter endpoint', async () => {
    const response = { chapter_id: 12, suggestions: [] };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(response), { status: 200 })));

    await expect(analyzeChapterMangaAssets(12)).resolves.toEqual(response);
    expect(fetch).toHaveBeenCalledWith(
      '/api/chapters/12/manga-assets/analyze',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({}) }),
    );
  });

  it('读取当前章节已保存的资产分析', async () => {
    const response = { chapter_id: 12, suggestions: [] };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(response), { status: 200 })));

    await expect(getMangaAssetAnalysis(12)).resolves.toEqual(response);
    expect(fetch).toHaveBeenCalledWith(
      '/api/chapters/12/manga-assets/analysis',
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  it('显式保存用户编辑后的资产提示词', async () => {
    const suggestions = [{
      asset_type: 'character_reference' as const,
      name: '陈玄',
      description: '角色描述',
      evidence: '正文依据',
      prompt: '编辑后的提示词',
      candidates: [],
    }];
    const response = { chapter_id: 12, suggestions };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(response), { status: 200 })));

    await expect(saveMangaAssetAnalysis(12, suggestions)).resolves.toEqual(response);
    expect(fetch).toHaveBeenCalledWith(
      '/api/chapters/12/manga-assets/analysis',
      expect.objectContaining({ method: 'PUT', body: JSON.stringify({ suggestions }) }),
    );
  });

  it('使用编辑后的提示词生成当前章节漫画资产', async () => {
    const asset = { id: 21, story_id: 3, chapter_id: 12, asset_type: 'character_reference', name: '陈玄' };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(asset), { status: 201 })));

    await expect(generateMangaAsset(12, {
      asset_type: 'character_reference',
      name: '陈玄',
      prompt: '完整角色设定图提示词',
    })).resolves.toEqual(asset);
    expect(fetch).toHaveBeenCalledWith(
      '/api/chapters/12/manga-assets/generate',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          asset_type: 'character_reference',
          name: '陈玄',
          prompt: '完整角色设定图提示词',
        }),
      }),
    );
  });

  it('一次提交多个选中资产到后台生成接口', async () => {
    const response = { task_id: 'manga_asset_batch_12_abcd', status: 'pending', total: 2, message: '已提交' };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(response), { status: 202 })));
    const items = [
      { asset_type: 'character_reference' as const, name: '陈玄', prompt: '角色设定' },
      { asset_type: 'prop_reference' as const, name: '青锋剑', prompt: '道具设定' },
    ];

    await expect(generateMangaAssetsBatch(12, items)).resolves.toEqual(response);
    expect(fetch).toHaveBeenCalledWith(
      '/api/chapters/12/manga-assets/generate-batch',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ items }) }),
    );
  });

  it('向漫画资产二级工作台提交局部重绘', async () => {
    const asset = { id: 21, story_id: 3, chapter_id: 12, asset_type: 'character_reference', name: '陈玄' };
    const payload = { prompt: '调整服装纹样', mode: 'partial' as const, mask: 'data:image/png;base64,mask' };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(asset), { status: 200 })));

    await expect(redrawMangaAsset(21, payload)).resolves.toEqual(asset);
    expect(fetch).toHaveBeenCalledWith(
      '/api/manga-assets/21/redraw',
      expect.objectContaining({ method: 'POST', body: JSON.stringify(payload) }),
    );
  });

  it('查询持久化后台任务状态', async () => {
    const response = { task_id: 'manga asset/1', task_type: 'manga_asset_batch_generation', status: 'running' };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(response), { status: 200 })));

    await expect(getBackgroundTaskStatus('manga asset/1')).resolves.toEqual(response);
    expect(fetch).toHaveBeenCalledWith(
      '/api/tasks/manga%20asset%2F1',
      expect.objectContaining({ headers: expect.any(Object) }),
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


