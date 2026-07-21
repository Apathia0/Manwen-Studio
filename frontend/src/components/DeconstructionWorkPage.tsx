import { useState, useEffect, useRef } from 'react';
import {
  BookOpen, Search, Loader2, CheckCircle2, XCircle, ArrowLeft, ExternalLink,
  FileText, Palette, Globe, Upload, Edit3,
} from 'lucide-react';
import type {
  DeconstructionWorkItem, NovelSearchResult, CrawlStatus,
  AuthorStyleResult, AuthorStyleStatus,
} from '../api';
import { normalizeErrorMessage } from '../lib/errors';
import {
  listDeconstructionWorks,
  searchDeconstructNovels,
  createDeconstructionWork,
  importDeconstructionText,
  importDeconstructionFile,
  getDeconstructWorkCrawlStatus,
  startAuthorStyleAnalysis,
  getAuthorStyleStatus,
  getAuthorStyleResult,
  updateAuthorStyleReport,
} from '../api';

interface Props {
  workId: number;
  onBack: () => void;
}

type PageState = 'loading' | 'search' | 'crawling' | 'deconstructing' | 'completed' | 'failed' | 'not_found';

export function shouldShowAuthorStyleEntry(status?: string | null): boolean {
  if (!status) return false;
  return status !== 'pending' && status !== 'running';
}

export default function DeconstructionWorkPage({ workId, onBack }: Props) {
  const [pageState, setPageState] = useState<PageState>('loading');
  const [work, setWork] = useState<DeconstructionWorkItem | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 搜书状态
  const [keyword, setKeyword] = useState('');
  const [searchResults, setSearchResults] = useState<NovelSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [creating, setCreating] = useState(false);
  const [searchPlatform, setSearchPlatform] = useState('all');
  const [showUploadForm, setShowUploadForm] = useState(false);
  const [uploadTitle, setUploadTitle] = useState('');
  const [uploadAuthor, setUploadAuthor] = useState('');
  const [uploadText, setUploadText] = useState('');
  const [importing, setImporting] = useState(false);
  const [uploadFileName, setUploadFileName] = useState<string | null>(null);
  const [uploadMode, setUploadMode] = useState<'file' | 'paste'>('file');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const selectedFileRef = useRef<File | null>(null);

  // 仅 qidian 支持稳定远程爬取
  const REMOTE_CRAWL_SUPPORTED = ['qidian'];
  const CRAWL_UNSUPPORTED_MESSAGE: Record<string, string> = {
    fanqie: '番茄小说爬取不稳定，建议上传原文',
    qimao: '七猫暂不支持自动爬取，请上传原文',
    zongheng: '纵横暂不支持自动爬取，请上传原文',
  };

  const PLATFORM_OPTIONS = [
    { value: 'all', label: '全网', icon: Globe },
    { value: 'qidian', label: '起点' },
    { value: 'fanqie', label: '番茄小说' },
    { value: 'qimao', label: '七猫' },
    { value: 'zongheng', label: '纵横' },
  ] as const;

  const PLATFORM_BADGES: Record<string, { label: string; className: string }> = {
    qidian: { label: '起点', className: 'bg-blue-100 text-blue-700' },
    fanqie: { label: '番茄小说', className: 'bg-orange-100 text-orange-700' },
    qimao: { label: '七猫', className: 'bg-green-100 text-green-700' },
    zongheng: { label: '纵横', className: 'bg-purple-100 text-purple-700' },
  };

  // 爬取状态
  const [crawlStatus, setCrawlStatus] = useState<CrawlStatus | null>(null);

  // 作者风格/套路提取
  const [authorStyleStatus, setAuthorStyleStatus] = useState<AuthorStyleStatus | null>(null);
  const [authorStyleResult, setAuthorStyleResult] = useState<AuthorStyleResult | null>(null);
  const [authorStyleLoading, setAuthorStyleLoading] = useState(false);

  // 作者画像报告编辑
  const [isEditingAuthorStyle, setIsEditingAuthorStyle] = useState(false);
  const [draftAuthorStyleContent, setDraftAuthorStyleContent] = useState('');
  const [savingAuthorStyle, setSavingAuthorStyle] = useState(false);

  // 初始加载：根据 workId 判断是新创建还是已有
  useEffect(() => {
    if (workId <= 0) {
      setPageState('search');
      return;
    }
    loadWorkData();
  }, [workId]);

  const loadWorkData = async () => {
    try {
      setError(null);
      const works = await listDeconstructionWorks();
      const found = works.find((w) => w.id === workId);
      if (!found) {
        setPageState('not_found');
        return;
      }
      setWork(found);

      // 根据状态决定初始页面状态
      if (found.decon_status === 'completed') {
        setPageState('completed');
      } else if (found.crawl_status === 'crawling') {
        try {
          const cs = await getDeconstructWorkCrawlStatus(found.id);
          setCrawlStatus(cs);
        } catch {
          setCrawlStatus({ status: 'crawling', platform: found.platform, total_chapters: found.total_chapters, crawled_chapters: found.crawled_chapters, word_count: null, source_url: null });
        }
        setPageState('crawling');
      } else if (found.crawl_status === 'completed') {
        setPageState('deconstructing');
      } else {
        setPageState('search');
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '加载失败';
      setError(msg);
      setPageState('not_found');
    }
  };

  const fetchAuthorStyle = async () => {
    try {
      const s = await getAuthorStyleStatus(work?.id || workId);
      setAuthorStyleStatus(s);
      if (s.status === 'completed') {
        const r = await getAuthorStyleResult(work?.id || workId);
        setAuthorStyleResult(r);
      }
    } catch (error) {
      setError(normalizeErrorMessage(error, '无法获取作者画像任务状态，请稍后重试'));
    }
  };

  const handleEditAuthorStyle = () => {
    setDraftAuthorStyleContent(authorStyleResult?.report_markdown || '');
    setIsEditingAuthorStyle(true);
  };

  const handleSaveAuthorStyle = async () => {
    setSavingAuthorStyle(true);
    try {
      await updateAuthorStyleReport(
        work?.id || workId,
        { report_markdown: draftAuthorStyleContent }
      );
    setIsEditingAuthorStyle(false);
    fetchAuthorStyle();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '保存失败';
      setError(msg);
    } finally {
      setSavingAuthorStyle(false);
    }
  };

  const handleCancelEditAuthorStyle = () => {
    setIsEditingAuthorStyle(false);
  };

  const handleStartAuthorStyle = async () => {
    setAuthorStyleLoading(true);
    setError(null);
    // 清空旧结果，避免重复提取时残留旧报告
    setAuthorStyleResult(null);
    try {
      await startAuthorStyleAnalysis(work?.id || workId);
      setAuthorStyleStatus({ status: 'running', progress: '- 作者画像分析已启动', work_id: work?.id || workId });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '作者画像启动失败';
      setError(msg);
    } finally {
      setAuthorStyleLoading(false);
    }
  };

  const renderAuthorStyleEntry = (compact = false) => {
    const running = authorStyleLoading || authorStyleStatus?.status === 'running' || authorStyleStatus?.status === 'pending';
    return (
      <button
        onClick={handleStartAuthorStyle}
        disabled={running}
        className={`flex items-center gap-2 rounded-lg border border-violet-300 bg-violet-50 text-sm font-medium text-violet-700 transition hover:bg-violet-100 disabled:cursor-not-allowed disabled:opacity-50 ${compact ? 'px-3 py-1.5' : 'px-4 py-2'}`}
      >
        {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Palette className="h-4 w-4" />}
        {running ? '作者画像分析中' : '提取作者风格/套路'}
      </button>
    );
  };

  const renderAuthorStyleProgress = () => {
    if (authorStyleStatus?.status !== 'running' && authorStyleStatus?.status !== 'pending') return null;
    return (
      <div className="w-full max-w-2xl rounded-lg border border-violet-100 bg-violet-50 p-3 text-xs text-violet-700">
        <div className="flex items-center gap-2 font-medium">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          作者画像分析中
        </div>
        {authorStyleStatus.progress && (
          <pre className="mt-2 max-h-28 overflow-auto whitespace-pre-wrap text-violet-600">
            {authorStyleStatus.progress.split('\n').slice(-8).join('\n')}
          </pre>
        )}
      </div>
    );
  };

  const renderAuthorStyleResult = () => {
    if (!authorStyleResult) return null;
    return (
      <div className="flex flex-1 flex-col space-y-3 rounded-lg border border-violet-200 bg-white p-4 text-left shadow-sm">
        <div className="flex items-start justify-between rounded-lg bg-violet-50 p-3">
          <div>
            <h4 className="font-semibold text-violet-800">作者风格画像</h4>
            <p className="mt-1 text-xs text-violet-600">基于抽样章节生成，适合提取写法和套路。</p>
          </div>
          <button
            onClick={handleEditAuthorStyle}
            className="inline-flex items-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100"
          >
            <Edit3 className="h-3.5 w-3.5" />
            编辑报告
          </button>
        </div>
        {authorStyleResult.report_markdown ? (
          <pre className="flex-1 overflow-auto whitespace-pre-wrap text-sm leading-6 text-slate-700">
            {authorStyleResult.report_markdown}
          </pre>
        ) : (
          <pre className="flex-1 overflow-auto whitespace-pre-wrap text-xs text-slate-600">
            {JSON.stringify(authorStyleResult.profile, null, 2)}
          </pre>
        )}
      </div>
    );
  };

  // 轮询爬取状态
  useEffect(() => {
    if (pageState !== 'crawling' || !work?.id) return;
    let autoStarted = false;
    const timer = setInterval(async () => {
      try {
        const s = await getDeconstructWorkCrawlStatus(work.id);
        setCrawlStatus(s);
        if (s.status === 'completed' && !autoStarted) {
          autoStarted = true;
          setPageState('deconstructing');
          // 爬取完成 → 自动启动作者画像分析
          await startAuthorStyleAnalysis(work.id);
          setAuthorStyleStatus({ status: 'running', progress: '- 作者画像分析已启动', work_id: work.id });
        } else if (s.status === 'failed') {
          setPageState('failed');
          setError('爬取失败，请重试');
        }
      } catch (error) {
        setError(normalizeErrorMessage(error, '无法获取爬取任务状态，系统将继续重试'));
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [pageState, work?.id]);

  useEffect(() => {
    if (pageState !== 'deconstructing') return;
    if (authorStyleStatus?.status === 'completed') {
      setPageState('completed');
    } else if (authorStyleStatus?.status === 'failed') {
      setPageState('failed');
      setError('作者画像分析失败');
    }
  }, [authorStyleStatus?.status, pageState]);

  // 初始加载作者画像状态
  useEffect(() => {
    if (!work?.id) return;
    fetchAuthorStyle();
  }, [work?.id]);

  // 轮询作者画像状态
  useEffect(() => {
    if (!work?.id || authorStyleStatus?.status !== 'running') return;
    const timer = setInterval(fetchAuthorStyle, 3000);
    return () => clearInterval(timer);
  }, [work?.id, authorStyleStatus?.status]);

  // 搜书
  const handleSearch = async () => {
    if (!keyword.trim()) return;
    setSearching(true);
    setError(null);
    try {
      const data = await searchDeconstructNovels(keyword.trim(), searchPlatform);
      setSearchResults(data.results);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '搜索失败';
      setError(msg);
    } finally {
      setSearching(false);
    }
  };

  // 文件选择（直接上传，不回显到 textarea）
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.txt')) {
      setError('仅支持 .txt 文件');
      if (fileInputRef.current) fileInputRef.current.value = '';
      selectedFileRef.current = null;
      setUploadFileName(null);
      return;
    }
    setError(null);
    selectedFileRef.current = file;
    setUploadFileName(file.name);
    // 自动从文件名提取书名
    if (!uploadTitle.trim()) {
      const name = file.name.replace(/\.[^.]+$/, '');
      setUploadTitle(name);
    }
  };

  const handleClearFile = () => {
    setUploadFileName(null);
    selectedFileRef.current = null;
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  // 上传原文创建拆书工作
  const handleImportText = async () => {
    if (!uploadTitle.trim() || !uploadText.trim()) {
      setError('请输入书名和原文');
      return;
    }
    setImporting(true);
    setError(null);
    try {
      const { work_id } = await importDeconstructionText({
        title: uploadTitle.trim(),
        text: uploadText,
        author: uploadAuthor.trim() || undefined,
      });
      setWork({ id: work_id, title: uploadTitle.trim(), author: uploadAuthor.trim() || null, platform: 'manual', genre: null, status_label: '手动导入', crawl_status: 'completed', decon_status: 'not_started', total_chapters: null, crawled_chapters: 0, word_count: null, task_id: null, created_at: null, updated_at: null, progress_markdown: null });
      setPageState('deconstructing');
      await startAuthorStyleAnalysis(work_id);
      setAuthorStyleStatus({ status: 'running', progress: '- 作者画像分析已启动', work_id });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '导入失败';
      setError(msg);
    } finally {
      setImporting(false);
    }
  };

  const handleDirectFileUpload = async () => {
    const file = selectedFileRef.current;
    if (!file) {
      setError('请先选择文件');
      return;
    }
    const title = uploadTitle.trim() || (uploadFileName ? uploadFileName.replace(/\.[^.]+$/, '') : '');
    if (!title) {
      setError('请输入书名');
      return;
    }
    setImporting(true);
    setError(null);
    try {
      const result = await importDeconstructionFile(file, title, uploadAuthor.trim() || undefined);
      setWork({
        id: result.work_id,
        title,
        author: uploadAuthor.trim() || null,
        platform: 'manual',
        genre: null,
        status_label: '手动导入',
        crawl_status: 'completed',
        decon_status: 'not_started',
        total_chapters: null, crawled_chapters: 0, word_count: null,
        task_id: result.task_id || null,
        created_at: null, updated_at: null, progress_markdown: null,
      });
      setPageState('deconstructing');
      await startAuthorStyleAnalysis(result.work_id);
      setAuthorStyleStatus({ status: 'running', progress: '- 作者画像分析已启动', work_id: result.work_id });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '上传失败';
      setError(msg);
    } finally {
      setImporting(false);
    }
  };

  // 创建并开始爬取
  const handleCreate = async (book: NovelSearchResult) => {
    setCreating(true);
    setError(null);
    try {
      const { work_id } = await createDeconstructionWork({
        title: book.title,
        book_id: book.book_id,
        platform: book.platform,
        author: book.author,
        genre: book.genre,
        status_label: book.status,
      });
      setPageState('crawling');
      setCrawlStatus({ status: 'crawling', platform: book.platform, total_chapters: null, crawled_chapters: 0, word_count: null, source_url: null });
      // 刷新 workId 引用
      setWork({ id: work_id, title: book.title, author: book.author, platform: book.platform, genre: book.genre, status_label: book.status, crawl_status: 'crawling', decon_status: 'not_started', total_chapters: null, crawled_chapters: 0, word_count: null, task_id: null, created_at: null, updated_at: null, progress_markdown: null });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '创建失败';
      setError(msg);
    } finally {
      setCreating(false);
    }
  };

  // 顶部标题栏
  const header = (
    <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="flex items-center gap-1 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
        >
          <ArrowLeft className="h-4 w-4" />
          <span className="text-sm">返回库</span>
        </button>
        {work && (
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-slate-700">
              {work.title}
            </span>
            {work.author && (
              <span className="text-xs text-slate-400">{work.author}</span>
            )}
          </div>
        )}
      </div>
    </div>
  );

  // 作者画像报告全窗口编辑
  if (isEditingAuthorStyle) {
    const hasChanges = draftAuthorStyleContent !== (authorStyleResult?.report_markdown || '');
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <button
            onClick={handleCancelEditAuthorStyle}
            className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-4 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50"
          >
            <ArrowLeft className="h-4 w-4" />
            取消
          </button>
          <h3 className="text-sm font-semibold text-slate-700">编辑作者画像报告</h3>
          <button
            onClick={handleSaveAuthorStyle}
            disabled={savingAuthorStyle || !hasChanges}
            className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {savingAuthorStyle ? '保存中...' : '保存更改'}
          </button>
        </div>
        <div className="flex-1 p-4">
          <textarea
            value={draftAuthorStyleContent}
            onChange={(e) => setDraftAuthorStyleContent(e.target.value)}
            className="h-full w-full resize-none rounded-lg border border-slate-200 bg-white px-6 py-4 text-sm leading-relaxed whitespace-pre-wrap focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
        </div>
      </div>
    );
  }

  // 加载中
  if (pageState === 'loading') {
    return (
      <div className="flex h-full flex-col">
        {header}
        <div className="flex flex-1 flex-col items-center justify-center gap-3">
          <Loader2 className="h-10 w-10 animate-spin text-blue-500" />
          <p className="text-sm text-slate-500">正在加载...</p>
        </div>
      </div>
    );
  }

  // 未找到
  if (pageState === 'not_found') {
    return (
      <div className="flex h-full flex-col">
        {header}
        <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
          <XCircle className="h-16 w-16 text-slate-300" />
          <div className="text-center">
            <h3 className="text-lg font-semibold text-slate-700">未找到作品</h3>
            <p className="mt-1 text-sm text-slate-500">{error || '该作品可能已被删除'}</p>
          </div>
          <button
            onClick={onBack}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            <ArrowLeft className="h-4 w-4" />
            返回库
          </button>
        </div>
      </div>
    );
  }

  // 搜书界面
  if (pageState === 'search') {
    if (showUploadForm) {
      return (
        <div className="flex h-full flex-col">
          {header}
          <div className="flex flex-1 flex-col p-4">
            <div className="mx-auto flex w-full max-w-lg flex-col gap-4">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold text-slate-700">上传原文提取画像</h3>
                <button
                  onClick={() => { setShowUploadForm(false); setError(null); }}
                  className="text-xs text-blue-600 hover:text-blue-800"
                >
                  返回搜索
                </button>
              </div>

              {/* 模式切换 */}
              <div className="flex rounded-lg border border-slate-200 bg-slate-100 p-0.5">
                <button
                  onClick={() => setUploadMode('file')}
                  className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                    uploadMode === 'file' ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                  }`}
                >
                  <Upload className="mr-1.5 inline h-3.5 w-3.5" />
                  上传文件
                </button>
                <button
                  onClick={() => setUploadMode('paste')}
                  className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                    uploadMode === 'paste' ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                  }`}
                >
                  <FileText className="mr-1.5 inline h-3.5 w-3.5" />
                  粘贴原文
                </button>
              </div>

              {/* 文件上传模式 — 直接上传不回显 */}
              {uploadMode === 'file' ? (
                <>
                  <p className="text-xs text-slate-500">
                    选择 .txt 文件直接上传，系统将自动按章节分割并提取作者画像（支持"第X章"或"# 第X章"格式），至少需要 3 章
                  </p>
                  <div className="flex items-center gap-2">
                    <input ref={fileInputRef} type="file" accept=".txt" onChange={handleFileSelect} className="hidden" />
                    {!uploadFileName ? (
                      <button
                        onClick={() => fileInputRef.current?.click()}
                        className="flex flex-1 items-center justify-center gap-2 rounded-lg border-2 border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-400 hover:border-blue-400 hover:bg-blue-50 hover:text-blue-600 transition-colors"
                      >
                        <Upload className="h-6 w-6" />
                        <span>选择 .txt 文件</span>
                      </button>
                    ) : (
                      <div className="flex w-full items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-3 text-sm text-blue-700">
                        <FileText className="h-5 w-5 shrink-0" />
                        <span className="truncate flex-1">{uploadFileName}</span>
                        <button onClick={handleClearFile} className="rounded p-0.5 text-blue-400 hover:bg-blue-100 hover:text-blue-600">
                          <XCircle className="h-4 w-4" />
                        </button>
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <>
                  <p className="text-xs text-slate-500">
                    粘贴小说全文，系统将自动按章节分割（支持"第X章"或"# 第X章"格式），至少需要 3 章
                  </p>
                </>
              )}

              <input
                type="text"
                value={uploadTitle}
                onChange={(e) => setUploadTitle(e.target.value)}
                placeholder="小说名称"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
              <input
                type="text"
                value={uploadAuthor}
                onChange={(e) => setUploadAuthor(e.target.value)}
                placeholder="作者（可选）"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />

              {/* 粘贴模式才显示 textarea */}
              {uploadMode === 'paste' && (
                <>
                  <textarea
                    value={uploadText}
                    onChange={(e) => setUploadText(e.target.value)}
                    placeholder="在此粘贴小说全文..."
                    className="min-h-[300px] flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono focus:border-blue-500 focus:outline-none"
                  />
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-slate-400">{uploadText.length} 字</span>
                    <button
                      onClick={handleImportText}
                      disabled={importing || !uploadTitle.trim() || !uploadText.trim()}
                      className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                    >
                      {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <ExternalLink className="h-4 w-4" />}
                      导入并提取
                    </button>
                  </div>
                </>
              )}

              {/* 文件模式的操作按钮 */}
              {uploadMode === 'file' && (
                <div className="flex justify-end">
                  <button
                    onClick={handleDirectFileUpload}
                    disabled={importing || !uploadFileName}
                    className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                  >
                    {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                    上传并提取
                  </button>
                </div>
              )}

              {error && (
                <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">{error}</div>
              )}
            </div>
          </div>
        </div>
      );
    }

    return (
      <div className="flex h-full flex-col">
        {header}
        <div className="flex flex-1 flex-col p-4">
          <div className="mb-6 text-center">
            <BookOpen className="mx-auto h-12 w-12 text-slate-300" />
            <h3 className="mt-3 text-lg font-semibold text-slate-700">搜索网络小说</h3>
            <p className="mt-1 text-sm text-slate-500">
              全网搜索小说，自动爬取免费章节进行深度拆解
            </p>
          </div>

          <div className="mx-auto flex w-full max-w-lg flex-col gap-2 mb-4">
            <div className="flex gap-2">
              <input
                type="text"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                placeholder="输入书名或关键词..."
                className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              />
              <button
                onClick={handleSearch}
                disabled={searching || !keyword.trim()}
                className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                搜索
              </button>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {PLATFORM_OPTIONS.map((opt) => {
                const active = searchPlatform === opt.value;
                const Icon = 'icon' in opt ? opt.icon : null;
                return (
                  <button
                    key={opt.value}
                    onClick={() => setSearchPlatform(opt.value)}
                    className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
                      active
                        ? 'bg-blue-600 text-white'
                        : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                    }`}
                  >
                    {Icon && <Icon className="h-3 w-3" />}
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </div>

          {error && (
            <div className="mx-auto w-full max-w-lg rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">
              {error}
            </div>
          )}

          <div className="mx-auto flex w-full max-w-lg flex-1 flex-col overflow-auto">
            {searchResults.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-xs text-slate-500">找到 {searchResults.length} 个结果</p>
                  <button
                    onClick={() => { setShowUploadForm(true); setError(null); }}
                    className="text-xs text-blue-600 hover:text-blue-800"
                  >
                    搜索不到？上传原文
                  </button>
                </div>
                {searchResults.map((book) => {
                  const supported = REMOTE_CRAWL_SUPPORTED.includes(book.platform);
                  return (
                    <div
                      key={book.book_id}
                      className="rounded-lg border border-slate-200 p-3 hover:border-blue-300"
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1 min-w-0">
                          <h4 className="font-semibold text-slate-800 truncate">
                            {book.title}
                          </h4>
                          <p className="text-xs text-slate-500 mt-0.5">
                            {book.author}
                            {book.genre ? ` · ${book.genre}` : ''}
                            {book.platform && PLATFORM_BADGES[book.platform] ? (
                              <span className={`ml-1.5 inline-flex items-center rounded-full px-1.5 py-0.5 text-xs font-medium ${PLATFORM_BADGES[book.platform].className}`}>
                                {PLATFORM_BADGES[book.platform].label}
                              </span>
                            ) : book.platform ? ` · ${book.platform}` : ''}
                          </p>
                          <p className="text-xs text-slate-400 mt-0.5">{book.status}</p>
                          {book.desc && (
                            <p className="mt-1 text-xs text-slate-600 line-clamp-2">
                              {book.desc}
                            </p>
                          )}
                        </div>
                        {supported ? (
                          <button
                            onClick={() => handleCreate(book)}
                            disabled={creating}
                            className="ml-2 flex shrink-0 items-center gap-1 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
                          >
                            {creating ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <ExternalLink className="h-3.5 w-3.5" />
                            )}
                            爬取并提取
                          </button>
                        ) : (
                          <span className="ml-2 inline-flex flex-col items-end gap-1">
                            <button
                              onClick={() => { setShowUploadForm(true); setError(null); }}
                              className="rounded-lg bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-100"
                            >
                              上传原文
                            </button>
                            <span className="text-xs text-amber-500 whitespace-nowrap">
                              {CRAWL_UNSUPPORTED_MESSAGE[book.platform] || '暂不支持自动爬取'}
                            </span>
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {searchResults.length === 0 && !searching && (
              <div className="flex flex-1 flex-col items-center justify-center gap-4">
                <p className="text-sm text-slate-400">
                  跨平台搜索网络小说，系统将自动爬取免费章节内容并深度拆解
                </p>
                <button
                  onClick={() => { setShowUploadForm(true); setError(null); }}
                  className="flex items-center gap-1.5 rounded-lg border border-blue-300 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100"
                >
                  <ExternalLink className="h-4 w-4" />
                  或上传原文提取
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  // 爬取中
  if (pageState === 'crawling') {
    return (
      <div className="flex h-full flex-col">
        {header}
        <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
          <Loader2 className="h-12 w-12 animate-spin text-blue-500" />
          <div className="text-center">
            <h3 className="text-lg font-semibold text-slate-700">正在爬取章节</h3>
            <p className="mt-1 text-sm text-slate-500">
              {crawlStatus?.crawled_chapters ?? 0}
              {crawlStatus?.total_chapters ? ` / ${crawlStatus.total_chapters}` : ''} 章
            </p>
          </div>
          {crawlStatus?.total_chapters && crawlStatus.total_chapters > 0 ? (
            <div className="w-full max-w-md">
              <div className="h-2 overflow-hidden rounded-full bg-slate-200">
                <div
                  className="h-full rounded-full bg-blue-500 transition-all duration-500"
                  style={{
                    width: `${Math.min(100, Math.round((crawlStatus.crawled_chapters / crawlStatus.total_chapters) * 100))}%`,
                  }}
                />
              </div>
              <p className="mt-1 text-center text-xs text-slate-400">
                {Math.min(100, Math.round((crawlStatus.crawled_chapters / crawlStatus.total_chapters) * 100))}%
              </p>
            </div>
          ) : (
            <div className="w-full max-w-md">
              <div className="h-2 overflow-hidden rounded-full bg-slate-200">
                <div className="h-full w-1/3 animate-pulse rounded-full bg-blue-400" />
              </div>
              <p className="mt-1 text-center text-xs text-slate-400">正在获取章节...</p>
            </div>
          )}
          <p className="text-xs text-slate-400">爬取完成后可提取作者风格/套路</p>
        </div>
      </div>
    );
  }

  if (pageState === 'deconstructing') {
    return (
      <div className="flex h-full flex-col">
        {header}
        <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
          <BookOpen className="h-16 w-16 text-slate-300" />
          <div className="text-center">
            <h3 className="text-lg font-semibold text-slate-700">准备分析</h3>
            <p className="mt-1 text-sm text-slate-500">
              章节已爬取完成，可开始作者画像分析
            </p>
          </div>
          {renderAuthorStyleEntry()}
          <div className="w-full max-w-2xl space-y-3">
            {renderAuthorStyleProgress()}
            {renderAuthorStyleResult()}
          </div>
          {error && <p className="text-sm text-red-500">{error}</p>}
        </div>
      </div>
    );
  }

  // 已完成
  if (pageState === 'completed') {
    if (isEditingAuthorStyle) {
      const hasChanges = draftAuthorStyleContent !== (authorStyleResult?.report_markdown || '');
      return (
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
            <button
              onClick={handleCancelEditAuthorStyle}
              className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-4 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50"
            >
              <ArrowLeft className="h-4 w-4" />
              取消
            </button>
            <h3 className="text-sm font-semibold text-slate-700">编辑作者画像报告</h3>
            <button
              onClick={handleSaveAuthorStyle}
              disabled={savingAuthorStyle || !hasChanges}
              className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {savingAuthorStyle ? '保存中...' : '保存更改'}
            </button>
          </div>
          <div className="flex-1 p-4">
            <textarea
              value={draftAuthorStyleContent}
              onChange={(e) => setDraftAuthorStyleContent(e.target.value)}
              className="h-full w-full resize-none rounded-lg border border-slate-200 bg-white px-6 py-4 text-sm leading-relaxed whitespace-pre-wrap focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
          </div>
        </div>
      );
    }

    return (
      <div className="flex h-full flex-col">
        {header}
        <div className="flex flex-1 flex-col gap-4 overflow-auto p-6">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="h-8 w-8 text-green-500" />
            <div>
              <h3 className="text-lg font-semibold text-slate-700">分析完成</h3>
              <p className="text-sm text-slate-500">作者画像已生成，可查看或编辑报告</p>
            </div>
          </div>
          <div className="flex-1 space-y-3">
            {renderAuthorStyleProgress()}
            {renderAuthorStyleResult()}
          </div>
        </div>
      </div>
    );
  }

  // 失败状态
  return (
    <div className="flex h-full flex-col">
      {header}
      <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
        <XCircle className="h-16 w-16 text-red-300" />
        <div className="text-center">
          <h3 className="text-lg font-semibold text-slate-700">
            {work?.decon_status === 'failed' ? '分析失败' : '操作失败'}
          </h3>
          <p className="mt-1 text-sm text-slate-500">{error || '请重试'}</p>
        </div>
        {shouldShowAuthorStyleEntry(work?.decon_status) && renderAuthorStyleEntry()}
        <div className="w-full max-w-3xl space-y-3">
          {renderAuthorStyleProgress()}
          {renderAuthorStyleResult()}
        </div>
      </div>
    </div>
  );
}
