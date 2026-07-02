import { useState, useEffect, useRef } from 'react';
import {
  BookOpen, Search, Loader2, CheckCircle2, XCircle, Play, Square, RefreshCw, Clock, ArrowLeft, ExternalLink,
  ClipboardList, FileText, Puzzle, Landmark, BarChart3, Palette, Globe, Upload,
} from 'lucide-react';
import type {
  DeconstructionWorkItem, DeconstructionWorkResult, NovelSearchResult, CrawlStatus, DeconstructionStatus,
} from '../api';
import {
  listDeconstructionWorks,
  searchDeconstructNovels,
  createDeconstructionWork,
  importDeconstructionText,
  importDeconstructionFile,
  getDeconstructWorkCrawlStatus,
  startDeconstructWork,
  getDeconstructWorkStatus,
  getDeconstructWorkResult,
  cancelDeconstructWork,
  resumeDeconstructWork,
} from '../api';

interface Props {
  workId: number;
  onBack: () => void;
}

const STAGE_NAMES: Record<number, string> = {
  0: '概要提取',
  1: '黄金三章深度拆解',
  2: '逐章摘要',
  3: '聚合分析',
  4: '设定与关系',
  5: '汇总报告',
  6: '文风分析',
};

function getStageIcon(stage: number): React.ReactNode {
  const cls = 'h-5 w-5';
  switch (stage) {
    case 0: return <ClipboardList className={cls} />;
    case 1: return <Search className={cls} />;
    case 2: return <FileText className={cls} />;
    case 3: return <Puzzle className={cls} />;
    case 4: return <Landmark className={cls} />;
    case 5: return <BarChart3 className={cls} />;
    case 6: return <Palette className={cls} />;
    default: return <FileText className={cls} />;
  }
}

type PageState = 'loading' | 'search' | 'crawling' | 'deconstructing' | 'completed' | 'failed' | 'not_found';

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

  // 拆书状态
  const [deconStatus, setDeconStatus] = useState<DeconstructionStatus | null>(null);
  const [result, setResult] = useState<DeconstructionWorkResult | null>(null);
  const [activeTab, setActiveTab] = useState<'report' | 'characters' | 'plots' | 'style'>('report');
  const [resuming, setResuming] = useState(false);

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
      // 运行中的任务先获取实时状态，避免展示空白进度
      if (found.decon_status === 'paused_after_stage1' || (found.decon_status && found.decon_status.startsWith('paused_after_partial'))) {
        setPageState('deconstructing');
        setDeconStatus({ status: found.decon_status, current_stage: 1, stages_completed: [0, 0.5, 1], progress: found.progress_markdown || null, result_id: null });
        fetchResult();
      } else if (found.decon_status === 'completed') {
        setPageState('completed');
        fetchResult();
      } else if (found.decon_status === 'running' || found.decon_status === 'pending') {
        try {
          const ds = await getDeconstructWorkStatus(found.id);
          setDeconStatus(ds);
        } catch {
          setDeconStatus({ status: found.decon_status, current_stage: null, stages_completed: [], progress: null, result_id: null });
        }
        setPageState('deconstructing');
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
        setDeconStatus({ status: 'not_started', current_stage: null, stages_completed: [], progress: null, result_id: null });
      } else {
        setPageState('search');
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '加载失败';
      setError(msg);
      setPageState('not_found');
    }
  };

  const fetchResult = async () => {
    try {
      const r = await getDeconstructWorkResult(work?.id || workId);
      setResult(r);
    } catch {
      // 静默失败
    }
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
          await startDeconstructWork(work.id);
          setDeconStatus({ status: 'running', current_stage: 0, stages_completed: [], progress: null, result_id: null });
        } else if (s.status === 'failed') {
          setPageState('failed');
          setError('爬取失败，请重试');
        }
      } catch {
        // 静默失败
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [pageState, work?.id]);

  // 轮询拆书状态
  useEffect(() => {
    if (pageState !== 'deconstructing' || !work?.id) return;
    const timer = setInterval(async () => {
      try {
        const s = await getDeconstructWorkStatus(work.id);
        setDeconStatus((prev) => {
          if (prev?.status === 'running' && s.status === 'not_started') return prev;
          return s;
        });
        if (s.status === 'paused_after_stage1' || (s.status && s.status.startsWith('paused_after_partial'))) {
          if (s.status && s.status.startsWith('paused_after_partial')) {
            fetchResult();
          }
          if (s.status === 'paused_after_stage1') {
            fetchResult();
          }
          return s;
        } else if (s.status === 'completed') {
          setPageState('completed');
          fetchResult();
        } else if (s.status === 'failed') {
          setPageState('failed');
          setError(s.progress || '拆书分析失败');
        }
      } catch {
        // 静默失败
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [pageState, work?.id]);

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
      setPageState('deconstructing');
      setDeconStatus({ status: 'not_started', current_stage: null, stages_completed: [], progress: null, result_id: null });
      setWork({ id: work_id, title: uploadTitle.trim(), author: uploadAuthor.trim() || null, platform: 'manual', genre: null, status_label: '手动导入', crawl_status: 'completed', decon_status: 'not_started', total_chapters: null, crawled_chapters: 0, word_count: null, task_id: null, created_at: null, updated_at: null, progress_markdown: null });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '导入失败';
      setError(msg);
    } finally {
      setImporting(false);
    }
  };

  // 直接上传文件到后端（跳过 textarea）
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
      setPageState('deconstructing');
      setDeconStatus({ status: 'running', current_stage: 0, stages_completed: [], progress: null, result_id: null });
      setWork({
        id: result.work_id,
        title,
        author: uploadAuthor.trim() || null,
        platform: 'manual',
        genre: null,
        status_label: '手动导入',
        crawl_status: 'completed',
        decon_status: 'running',
        total_chapters: null, crawled_chapters: 0, word_count: null,
        task_id: result.task_id || null,
        created_at: null, updated_at: null, progress_markdown: null,
      });
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

  // 启动拆书
  const handleStartDecon = async () => {
    setError(null);
    setResuming(true);
    const targetId = work?.id || workId;
    try {
      await startDeconstructWork(targetId);
      setPageState('deconstructing');
      setDeconStatus({ status: 'running', current_stage: 0, stages_completed: [], progress: null, result_id: null });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '启动失败';
      setError(msg);
    } finally {
      setResuming(false);
    }
  };

  const [partialCount, setPartialCount] = useState(50);

  // 续跑拆书
  const handleResume = async () => {
    setError(null);
    setResuming(true);
    const targetId = work?.id || workId;
    try {
      await resumeDeconstructWork(targetId, 'full');
      setPageState('deconstructing');
      setDeconStatus({ status: 'running', current_stage: 2, stages_completed: [0, 0.5, 1], progress: null, result_id: null });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '续跑失败';
      setError(msg);
    } finally {
      setResuming(false);
    }
  };

  const handlePartialResume = async () => {
    setError(null);
    setResuming(true);
    const targetId = work?.id || workId;
    try {
      const count = parseInt(String(partialCount), 10);
      await resumeDeconstructWork(targetId, 'partial', count);
      setPageState('deconstructing');
      setDeconStatus({ status: 'running', current_stage: 2, stages_completed: [0, 0.5, 1], progress: null, result_id: null });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '试读启动失败';
      setError(msg);
    } finally {
      setResuming(false);
    }
  };

  const handleQuickReport = async () => {
    setError(null);
    setResuming(true);
    const targetId = work?.id || workId;
    try {
      await resumeDeconstructWork(targetId, 'quick_report');
      setPageState('deconstructing');
      setDeconStatus({ status: 'running', current_stage: 5, stages_completed: [0, 0.5, 1], progress: null, result_id: null });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '报告生成失败';
      setError(msg);
    } finally {
      setResuming(false);
    }
  };

  // 取消拆书
  const handleCancel = async () => {
    const targetId = work?.id || workId;
    try {
      await cancelDeconstructWork(targetId);
      setDeconStatus((prev) => (prev ? { ...prev, status: 'failed' } : null));
      setPageState('failed');
      setError('已取消拆书分析');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '取消失败';
      setError(msg);
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

  // 加载中
  if (pageState === 'loading') {
    return (
      <div className="flex h-full flex-col">
        {header}
        <div className="flex flex-1 flex-col items-center justify-center gap-3">
          <Loader2 className="h-10 w-10 animate-spin text-blue-500" />
          <p className="text-sm text-slate-500">正在加载拆书进度...</p>
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
            <h3 className="text-lg font-semibold text-slate-700">未找到拆书作品</h3>
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
                <h3 className="text-lg font-semibold text-slate-700">上传原文拆书</h3>
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
                    选择 .txt 文件直接上传，系统将自动按章节分割，后台并行拆书（支持"第X章"或"# 第X章"格式），至少需要 3 章
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
                      导入并拆书
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
                    上传并拆书
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
                            爬取拆书
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
                  或上传原文拆书
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
          <p className="text-xs text-slate-400">爬取完成后将自动开始拆书分析</p>
        </div>
      </div>
    );
  }

  // 拆书中
  if (pageState === 'deconstructing') {
    // 停靠中（黄金三章后）
    if (deconStatus?.status === 'paused_after_stage1') {
      if (result?.report_markdown) {
        return (
          <div className="flex h-full flex-col">
            {header}
            <div className="flex flex-1 flex-col p-4">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-amber-700">黄金三章报告</h3>
                <button
                  onClick={handleResume}
                  disabled={resuming}
                  className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white transition ${resuming ? 'cursor-not-allowed bg-blue-400' : 'bg-blue-600 hover:bg-blue-700'}`}
                >
                  {resuming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                  继续全量拆解
                </button>
              </div>
              <div className="flex-1 overflow-auto rounded-lg bg-white p-4">
                <div className="prose prose-sm max-w-none text-sm leading-relaxed whitespace-pre-wrap text-slate-700">
                  {result.report_markdown}
                </div>
              </div>
            </div>
          </div>
        );
      }
      return (
        <div className="flex flex-1 flex-col items-center justify-center p-8">
          <CheckCircle2 className="h-16 w-16 text-amber-400" />
          <div className="mt-4 text-center">
            <h3 className="text-lg font-semibold text-amber-700">黄金三章拆解完成</h3>
            <p className="mt-1 text-sm text-slate-500">
              框架识别已完成，可选择继续全量拆解或试读前 N 章
            </p>
          </div>
          <div className="mt-4 flex items-center gap-3">
            <button
              onClick={handleResume}
              disabled={resuming}
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white transition ${resuming ? 'cursor-not-allowed bg-blue-400' : 'bg-blue-600 hover:bg-blue-700'}`}
            >
              {resuming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              继续全量拆解
            </button>
            <button
              onClick={() => {
                const count = parseInt(String(partialCount), 10);
                if (count >= 10) { handlePartialResume(); }
              }}
              disabled={resuming}
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white transition ${resuming ? 'cursor-not-allowed bg-amber-300' : 'bg-amber-500 hover:bg-amber-600'}`}
            >
              {resuming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              试读 前
              <input
                type="number"
                min={10}
                value={partialCount}
                onChange={(e) => setPartialCount(parseInt(e.target.value, 10) || 50)}
                onClick={(e) => e.stopPropagation()}
                disabled={resuming}
                className="w-16 rounded border border-amber-300 bg-amber-50 px-1 py-0.5 text-center text-sm font-bold text-amber-800"
              />
              章
            </button>
            <button
              onClick={handleQuickReport}
              disabled={resuming}
              className={`flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium transition ${resuming ? 'cursor-not-allowed border-slate-200 bg-slate-50 text-slate-400' : 'border-green-400 bg-green-50 text-green-700 hover:bg-green-100'}`}
            >
              {resuming ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
              生成三章报告
            </button>
          </div>
          {deconStatus.progress && (
            <div className="mt-4 w-full max-w-2xl max-h-64 overflow-auto rounded-lg bg-slate-50 p-4">
              <div className="prose prose-sm max-w-none text-sm leading-relaxed whitespace-pre-wrap text-slate-700">
                {deconStatus.progress.split('\\n').slice(-30).join('\\n')}
              </div>
            </div>
          )}
        </div>
      );
    }

    if (deconStatus?.status && deconStatus.status.startsWith('paused_after_partial')) {
      const rangeNum = deconStatus.status.split(':')[1] || '?';
      return (
        <div className="flex h-full flex-col">
          {header}
          <div className="flex flex-1 flex-col p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-green-700">试读报告（前{rangeNum}章）</h3>
              <button
                onClick={handleResume}
                disabled={resuming}
                className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white transition ${resuming ? 'cursor-not-allowed bg-blue-400' : 'bg-blue-600 hover:bg-blue-700'}`}
              >
                {resuming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                继续全量拆解
              </button>
            </div>
            {result?.report_markdown ? (
              <div className="flex-1 overflow-auto rounded-lg bg-white p-4">
                <div className="prose prose-sm max-w-none text-sm leading-relaxed whitespace-pre-wrap text-slate-700">
                  {result.report_markdown}
                </div>
              </div>
            ) : (
              <div className="flex flex-1 flex-col items-center justify-center gap-3">
                <Loader2 className="h-8 w-8 animate-spin text-slate-300" />
                <p className="text-sm text-slate-400">正在加载报告...</p>
              </div>
            )}
          </div>
        </div>
      );
    }

    const isDeconRunning = deconStatus?.status === 'running' || deconStatus?.status === 'pending';
    const isNotStarted = deconStatus?.status === 'not_started';
    const currentStage = deconStatus?.current_stage ?? 0;

    if (isNotStarted) {
      return (
        <div className="flex h-full flex-col">
          {header}
          <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
            <BookOpen className="h-16 w-16 text-slate-300" />
            <div className="text-center">
              <h3 className="text-lg font-semibold text-slate-700">准备拆书分析</h3>
              <p className="mt-1 text-sm text-slate-500">
                章节已爬取完成，可开始深度拆解分析
              </p>
            </div>
            <button
              onClick={handleStartDecon}
              disabled={resuming}
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white transition ${resuming ? 'cursor-not-allowed bg-blue-400' : 'bg-blue-600 hover:bg-blue-700'}`}
            >
              {resuming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              开始拆书
            </button>
            {error && <p className="text-sm text-red-500">{error}</p>}
          </div>
        </div>
      );
    }

    return (
      <div className="flex h-full flex-col">
        {header}
        <div className="flex flex-1 flex-col p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-slate-700">拆书分析进行中</h3>
            {isDeconRunning && (
              <button
                onClick={handleCancel}
                className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50"
              >
                <Square className="h-3.5 w-3.5" />
                取消
              </button>
            )}
          </div>

          <div className="space-y-2 mb-4">
            {[0, 1, 2, 3, 4, 5, 6].map((stage) => (
              <div
                key={stage}
                className={`flex items-center gap-3 rounded-lg p-2.5 text-sm ${
                  stage < currentStage
                    ? 'bg-green-50 text-green-700'
                    : stage === currentStage && isDeconRunning
                    ? 'bg-blue-50 text-blue-700'
                    : 'bg-slate-50 text-slate-400'
                }`}
              >
                {getStageIcon(stage)}
                <span className="flex-1">{STAGE_NAMES[stage]}</span>
                {stage < currentStage && <CheckCircle2 className="h-4 w-4 text-green-500" />}
                {stage === currentStage && isDeconRunning && <Loader2 className="h-4 w-4 animate-spin text-blue-500" />}
                {stage > currentStage && <Clock className="h-4 w-4 text-slate-300" />}
              </div>
            ))}
          </div>

          {deconStatus?.progress && (
            <div className="flex-1 overflow-auto rounded-lg bg-slate-900 p-3">
              <pre className="text-xs text-green-400 whitespace-pre-wrap font-mono">
                {deconStatus.progress.split('\n').slice(-20).join('\n')}
              </pre>
            </div>
          )}
        </div>
      </div>
    );
  }

  // 已完成
  if (pageState === 'completed' && result) {
    const tabs = [
      { key: 'report' as const, label: '拆文报告' },
      { key: 'characters' as const, label: '角色档案' },
      { key: 'plots' as const, label: '剧情线' },
      { key: 'style' as const, label: '文风分析' },
    ];

    return (
      <div className="flex h-full flex-col">
        {header}
        <div className="flex items-center gap-1 border-b border-slate-200 px-4 py-2">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`rounded-t-lg px-3 py-1.5 text-xs font-medium transition ${
                activeTab === tab.key
                  ? 'bg-white text-blue-600 border-b-2 border-blue-600'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              {tab.label}
            </button>
          ))}
          <div className="flex-1" />
          <button
            onClick={() => fetchResult()}
            className="flex items-center gap-1 rounded px-2 py-1 text-xs text-slate-400 hover:text-slate-600"
          >
            <RefreshCw className="h-3 w-3" />
          </button>
        </div>

        <div className="flex-1 overflow-auto p-4">
          {activeTab === 'report' && result.report_markdown && (
            <div className="prose prose-sm max-w-none text-sm leading-relaxed whitespace-pre-wrap text-slate-700">
              {result.report_markdown}
            </div>
          )}
          {activeTab === 'report' && !result.report_markdown && (
            <p className="text-sm text-slate-400">暂无报告数据</p>
          )}

          {activeTab === 'characters' && (
            <div className="space-y-4">
              {result.characters?.map((char: Record<string, unknown>, i: number) => (
                <div key={i} className="rounded-lg border border-slate-200 p-3">
                  <h4 className="font-semibold text-slate-800">{String(char.name ?? '')}</h4>
                  <p className="text-xs text-slate-500 mt-1">
                    等级：{String(char.level ?? '--')} | 身份：{String(char.identity ?? '--')}
                  </p>
                  <p className="text-sm text-slate-600 mt-1">动机：{String(char.motivation ?? '')}</p>
                  <p className="text-sm text-slate-600">弱点：{String(char.weakness ?? '')}</p>
                </div>
              ))}
              {(!result.characters || result.characters.length === 0) && (
                <p className="text-sm text-slate-400">暂无角色数据</p>
              )}
            </div>
          )}

          {activeTab === 'plots' && (
            <div className="space-y-4">
              {result.plot_lines?.map((plot: Record<string, unknown>, i: number) => (
                <div key={i} className="rounded-lg border border-slate-200 p-3">
                  <h4 className="font-semibold text-slate-800">
                    {String(plot.title ?? '')}
                    <span className="ml-2 text-xs font-normal text-slate-400">
                      ({String(plot.type ?? '')}) {String(plot.chapter_range ?? '')}
                    </span>
                  </h4>
                  <p className="text-sm text-slate-600 mt-1">{String(plot.summary ?? '')}</p>
                </div>
              ))}
              {(!result.plot_lines || result.plot_lines.length === 0) && (
                <p className="text-sm text-slate-400">暂无剧情线数据</p>
              )}
            </div>
          )}

          {activeTab === 'style' && result.writing_style && (
            <div className="space-y-4">
              <div className="rounded-lg border border-slate-200 p-3">
                <h4 className="font-semibold text-slate-800">句长特征</h4>
                <p className="text-sm text-slate-600 mt-1">
                  平均句长：{String(result.writing_style.sentence_length?.average ?? 'N/A')} 字
                </p>
                <p className="text-sm text-slate-600">
                  模式：{String(result.writing_style.sentence_length?.pattern ?? 'N/A')}
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3">
                <h4 className="font-semibold text-slate-800">对话潜台词</h4>
                <p className="text-sm text-slate-600 mt-1">
                  {String(result.writing_style.dialogue_subtext?.pattern ?? 'N/A')}
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3">
                <h4 className="font-semibold text-slate-800">情绪交替周期</h4>
                <p className="text-sm text-slate-600 mt-1">
                  {String(result.writing_style.emotion_cycle?.pattern ?? 'N/A')}
                </p>
              </div>
            </div>
          )}
          {activeTab === 'style' && !result.writing_style && (
            <p className="text-sm text-slate-400">暂无文风数据</p>
          )}
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
            {work?.decon_status === 'failed' ? '拆书分析失败' : '操作失败'}
          </h3>
          <p className="mt-1 text-sm text-slate-500">{error || '请重试'}</p>
        </div>
        <button
          onClick={handleStartDecon}
          disabled={resuming}
          className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white transition ${resuming ? 'cursor-not-allowed bg-blue-400' : 'bg-blue-600 hover:bg-blue-700'}`}
        >
          {resuming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          重新开始
        </button>
        {deconStatus?.progress && (
          <div className="w-full max-w-lg overflow-auto rounded-lg bg-slate-900 p-3">
            <pre className="text-xs text-red-400 whitespace-pre-wrap font-mono">
              {deconStatus.progress.split('\n').slice(-30).join('\n')}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
