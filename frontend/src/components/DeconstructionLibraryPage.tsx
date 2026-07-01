import { useState, useEffect, useCallback } from 'react';
import { BookOpen, Loader2, Trash2, Plus, ExternalLink, Clock } from 'lucide-react';
import type { DeconstructionWorkItem } from '../api';
import {
  listDeconstructionWorks,
  getDeconstructWorkCrawlStatus,
  getDeconstructWorkStatus,
  deleteDeconstructionWork,
} from '../api';

interface Props {
  onNavigate: (route: string, workId?: number) => void;
}

/** 爬取状态中文映射 */
const CRAWL_LABELS: Record<string, string> = {
  not_started: '未爬取',
  crawling: '爬取中',
  completed: '已爬取',
  failed: '爬取失败',
};

/** 拆书状态中文映射 */
const DECON_LABELS: Record<string, string> = {
  not_started: '未拆书',
  pending: '等待中',
  running: '拆书中',
  completed: '已完成',
  failed: '拆书失败',
};

/** 状态对应的颜色类 */
function statusColor(status: string): string {
  if (status === 'completed' || status === '已爬取' || status === '已完成') return 'text-green-600 bg-green-50';
  if (status === 'running' || status === 'crawling' || status === 'pending' || status === '爬取中' || status === '拆书中' || status === '等待中') return 'text-blue-600 bg-blue-50';
  if (status === 'failed' || status === '爬取失败' || status === '拆书失败') return 'text-red-600 bg-red-50';
  return 'text-slate-500 bg-slate-50';
}

export default function DeconstructionLibraryPage({ onNavigate }: Props) {
  const [works, setWorks] = useState<DeconstructionWorkItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);

  const loadWorks = useCallback(async () => {
    try {
      setError(null);
      const data = await listDeconstructionWorks();
      setWorks(data);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '加载拆书库失败';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  // 初次加载 + 轮询爬取/拆书中的作品状态
  useEffect(() => {
    loadWorks();
  }, [loadWorks]);

  useEffect(() => {
    const hasActive = works.some(
      (w) =>
        w.crawl_status === 'crawling' ||
        w.decon_status === 'running' ||
        w.decon_status === 'pending'
    );
    if (!hasActive) return;

    const timer = setInterval(async () => {
      const updated = await Promise.all(
        works.map(async (w) => {
          if (w.crawl_status === 'crawling') {
            try {
              const cs = await getDeconstructWorkCrawlStatus(w.id);
              return { ...w, crawl_status: cs.status, crawled_chapters: cs.crawled_chapters, total_chapters: cs.total_chapters };
            } catch {
              return w;
            }
          }
          if (w.decon_status === 'running' || w.decon_status === 'pending') {
            try {
              const ds = await getDeconstructWorkStatus(w.id);
              return { ...w, decon_status: ds.status };
            } catch {
              return w;
            }
          }
          return w;
        })
      );
      setWorks(updated);
    }, 5000);

    return () => clearInterval(timer);
  }, [works]);

  const handleDelete = async (workId: number) => {
    setDeleting(workId);
    try {
      await deleteDeconstructionWork(workId);
      setWorks((prev) => prev.filter((w) => w.id !== workId));
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '删除失败';
      setError(msg);
    } finally {
      setDeleting(null);
    }
  };

  // 加载中
  if (loading) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
        <Loader2 className="h-10 w-10 animate-spin text-blue-500" />
        <p className="text-sm text-slate-500">加载拆书库...</p>
      </div>
    );
  }

  // 错误状态
  if (error && works.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
        <BookOpen className="h-16 w-16 text-slate-300" />
        <div className="text-center">
          <h3 className="text-lg font-semibold text-slate-700">加载失败</h3>
          <p className="mt-1 text-sm text-slate-500">{error}</p>
        </div>
        <button
          onClick={loadWorks}
          className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          重试
        </button>
      </div>
    );
  }

  // 空状态
  if (works.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
        <BookOpen className="h-16 w-16 text-slate-300" />
        <div className="text-center">
          <h3 className="text-lg font-semibold text-slate-700">拆书库</h3>
          <p className="mt-1 text-sm text-slate-500">
            搜索网络小说，自动爬取章节并进行深度拆解分析
          </p>
        </div>
        <button
          onClick={() => onNavigate('deconstruction-work')}
          className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          <Plus className="h-4 w-4" />
          新建拆书
        </button>
      </div>
    );
  }

  // 列表
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-800">拆书库</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            共 {works.length} 部作品
          </p>
        </div>
        <button
          onClick={() => onNavigate('deconstruction-work')}
          className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          <Plus className="h-4 w-4" />
          新建拆书
        </button>
      </div>

      {error && (
        <div className="mx-6 mt-3 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">
          {error}
        </div>
      )}

      <div className="flex-1 overflow-auto p-6">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {works.map((work) => (
            <div
              key={work.id}
              className="group relative rounded-lg border border-slate-200 bg-white p-4 transition-shadow hover:shadow-md"
            >
              {/* 标题行 */}
              <div className="flex items-start justify-between">
                <h3 className="font-semibold text-slate-800 truncate pr-8">
                  {work.title}
                </h3>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(work.id);
                  }}
                  disabled={deleting === work.id}
                  className="absolute right-3 top-3 rounded p-1 text-slate-300 opacity-0 transition-opacity hover:bg-red-50 hover:text-red-500 group-hover:opacity-100 disabled:opacity-100"
                  title="删除"
                >
                  {deleting === work.id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                </button>
              </div>

              {/* 作者/平台信息 */}
              <div className="mt-1.5 flex items-center gap-2 text-xs text-slate-500">
                {work.author && <span>{work.author}</span>}
                {work.genre && (
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
                    {work.genre}
                  </span>
                )}
                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
                  {work.platform}
                </span>
              </div>

              {/* 章节/字数 */}
              <div className="mt-2 flex items-center gap-3 text-xs text-slate-400">
                <span>
                  章节：{work.total_chapters ?? '--'}
                </span>
                {work.word_count != null && (
                  <span>
                    {work.word_count.toLocaleString()} 字
                  </span>
                )}
              </div>

              {/* 状态标签 */}
              <div className="mt-3 flex items-center gap-2">
                <span
                  className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${statusColor(CRAWL_LABELS[work.crawl_status] || work.crawl_status)}`}
                >
                  {work.crawl_status === 'crawling' && (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  )}
                  {work.crawl_status === 'completed' && (
                    <ExternalLink className="h-3 w-3" />
                  )}
                  {work.crawl_status === 'not_started' && (
                    <Clock className="h-3 w-3" />
                  )}
                  {CRAWL_LABELS[work.crawl_status] || work.crawl_status}
                </span>
                <span
                  className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${statusColor(DECON_LABELS[work.decon_status] || work.decon_status)}`}
                >
                  {work.decon_status === 'running' && (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  )}
                  {DECON_LABELS[work.decon_status] || work.decon_status}
                </span>
              </div>

              {/* 点击进入详情 */}
              <button
                onClick={() => onNavigate('deconstruction-work', work.id)}
                className="mt-3 w-full rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100"
              >
                查看详情
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}