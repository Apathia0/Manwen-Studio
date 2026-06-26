import { useState, useEffect, useCallback } from 'react';
import { BookOpen, Play, Square, RefreshCw, Loader2, CheckCircle2, XCircle, Clock, ExternalLink } from 'lucide-react';
import type { Story, DeconstructionStatus, DeconstructionResult } from '../api';
import {
  startDeconstruction,
  getDeconstructionStatus,
  getDeconstructionResult,
  cancelDeconstruction,
  applyDeconstructionToBible,
  getCrawlStatus,
} from '../api';
import NovelSearchPanel from './NovelSearchPanel';

interface Props {
  story: Story;
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

const STAGE_ICONS: Record<number, string> = {
  0: '📋',
  1: '🔍',
  2: '📝',
  3: '🧩',
  4: '🏰',
  5: '📊',
  6: '🎨',
};

export default function DeconstructionPanel({ story }: Props) {
  const [status, setStatus] = useState<DeconstructionStatus | null>(null);
  const [result, setResult] = useState<DeconstructionResult | null>(null);
  const [activeTab, setActiveTab] = useState<'progress' | 'report' | 'characters' | 'plots' | 'style'>('progress');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSearch, setShowSearch] = useState(false);
  const [crawlStatus, setCrawlStatus] = useState<string | null>(null);

  // 轮询拆书状态
  useEffect(() => {
    let timer: ReturnType<typeof setInterval>;
    loadStatus();

    if (status?.status === 'running' || status?.status === 'pending') {
      timer = setInterval(loadStatus, 3000);
    }

    return () => { if (timer) clearInterval(timer); };
  }, [status?.status]);

  // 轮询爬取状态
  useEffect(() => {
    if (!showSearch) return;
    const timer = setInterval(async () => {
      try {
        const s = await getCrawlStatus(story.id);
        setCrawlStatus(s.status);
        if (s.status === 'completed') {
          setShowSearch(false);
          setCrawlStatus(null);
          loadStatus();
        }
      } catch {}
    }, 3000);
    return () => clearInterval(timer);
  }, [showSearch, story.id]);

  const loadStatus = useCallback(async () => {
    try {
      const s = await getDeconstructionStatus(story.id);
      setStatus(s);
      if (s.status === 'completed') {
        const r = await getDeconstructionResult(story.id);
        setResult(r);
        setActiveTab('report');
      }
    } catch {}
  }, [story.id]);

  const handleStart = async () => {
    setLoading(true);
    setError(null);
    try {
      await startDeconstruction(story.id);
      setStatus({ status: 'running', current_stage: 0, stages_completed: [], progress: null, result_id: null });
    } catch (e: any) {
      setError(e.message || '启动失败');
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async () => {
    try {
      await cancelDeconstruction(story.id);
      setStatus(prev => prev ? { ...prev, status: 'failed' } : null);
    } catch (e: any) {
      setError(e.message || '取消失败');
    }
  };

  const handleApplyToBible = async () => {
    try {
      await applyDeconstructionToBible(story.id);
      setError(null);
      alert('拆书结果已注入作品圣经，Agent 可在写作中参考');
    } catch (e: any) {
      setError(e.message || '注入失败');
    }
  };

  const handleCrawlStarted = (taskId: string) => {
    setCrawlStatus('crawling');
  };

  // 搜书面板
  if (showSearch) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
          <h3 className="text-sm font-semibold text-slate-700">搜索网络小说</h3>
          <button
            onClick={() => setShowSearch(false)}
            className="text-xs text-slate-400 hover:text-slate-600"
          >
            返回
          </button>
        </div>
        {crawlStatus === 'crawling' && (
          <div className="flex items-center gap-2 bg-blue-50 px-4 py-2 text-xs text-blue-600">
            <Loader2 className="h-3 w-3 animate-spin" />
            正在爬取小说章节...
          </div>
        )}
        <NovelSearchPanel storyId={story.id} onCrawlStarted={handleCrawlStarted} />
      </div>
    );
  }

  // 未开始状态
  if (!status || status.status === 'not_started') {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
        <BookOpen className="h-16 w-16 text-slate-300" />
        <div className="text-center">
          <h3 className="text-lg font-semibold text-slate-700">拆书分析</h3>
          <p className="mt-1 text-sm text-slate-500">
            深度分析作品结构、角色、节奏、文风
          </p>
          <p className="mt-2 text-xs text-amber-600">
            需要至少 3 章有内容的章节
          </p>
        </div>
        <div className="flex flex-col gap-2">
          <button
            onClick={() => setShowSearch(true)}
            className="flex items-center gap-2 rounded-lg border border-blue-300 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-700 hover:bg-blue-100"
          >
            <ExternalLink className="h-4 w-4" />
            从网络搜索小说
          </button>
          <button
            onClick={handleStart}
            disabled={loading}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            对已有章节拆书
          </button>
        </div>
        {error && <p className="text-sm text-red-500">{error}</p>}
      </div>
    );
  }

  // 进行中
  if (status.status === 'running' || status.status === 'pending') {
    const currentStage = status.current_stage ?? 0;
    return (
      <div className="flex h-full flex-col p-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-slate-700">拆书分析进行中</h3>
          <button
            onClick={handleCancel}
            className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50"
          >
            <Square className="h-3.5 w-3.5" />
            取消
          </button>
        </div>

        <div className="space-y-2 mb-4">
          {[0, 1, 2, 3, 4, 5, 6].map((stage) => (
            <div
              key={stage}
              className={`flex items-center gap-3 rounded-lg p-2.5 text-sm ${
                stage < currentStage
                  ? 'bg-green-50 text-green-700'
                  : stage === currentStage
                  ? 'bg-blue-50 text-blue-700'
                  : 'bg-slate-50 text-slate-400'
              }`}
            >
              <span className="text-lg">{STAGE_ICONS[stage]}</span>
              <span className="flex-1">{STAGE_NAMES[stage]}</span>
              {stage < currentStage && <CheckCircle2 className="h-4 w-4 text-green-500" />}
              {stage === currentStage && <Loader2 className="h-4 w-4 animate-spin text-blue-500" />}
              {stage > currentStage && <Clock className="h-4 w-4 text-slate-300" />}
            </div>
          ))}
        </div>

        {status.progress && (
          <div className="flex-1 overflow-auto rounded-lg bg-slate-900 p-3">
            <pre className="text-xs text-green-400 whitespace-pre-wrap font-mono">
              {status.progress.split('\n').slice(-20).join('\n')}
            </pre>
          </div>
        )}
      </div>
    );
  }

  // 已完成
  if (status.status === 'completed' && result) {
    const tabs = [
      { key: 'report' as const, label: '拆文报告' },
      { key: 'characters' as const, label: '角色档案' },
      { key: 'plots' as const, label: '剧情线' },
      { key: 'style' as const, label: '文风分析' },
    ];

    return (
      <div className="flex h-full flex-col">
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
            onClick={handleApplyToBible}
            className="flex items-center gap-1 rounded bg-green-50 px-2 py-1 text-xs text-green-700 hover:bg-green-100"
          >
            注入 Bible
          </button>
          <button
            onClick={loadStatus}
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
              {result.characters?.map((char: any, i: number) => (
                <div key={i} className="rounded-lg border border-slate-200 p-3">
                  <h4 className="font-semibold text-slate-800">{char.name}</h4>
                  <p className="text-xs text-slate-500 mt-1">等级：{char.level} | 身份：{char.identity}</p>
                  <p className="text-sm text-slate-600 mt-1">动机：{char.motivation}</p>
                  <p className="text-sm text-slate-600">弱点：{char.weakness}</p>
                </div>
              ))}
              {(!result.characters || result.characters.length === 0) && (
                <p className="text-sm text-slate-400">暂无角色数据</p>
              )}
            </div>
          )}

          {activeTab === 'plots' && (
            <div className="space-y-4">
              {result.plot_lines?.map((plot: any, i: number) => (
                <div key={i} className="rounded-lg border border-slate-200 p-3">
                  <h4 className="font-semibold text-slate-800">
                    {plot.title}
                    <span className="ml-2 text-xs font-normal text-slate-400">
                      ({plot.type}) {plot.chapter_range}
                    </span>
                  </h4>
                  <p className="text-sm text-slate-600 mt-1">{plot.summary}</p>
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
                  平均句长：{(result.writing_style as any).sentence_length?.average || 'N/A'} 字
                </p>
                <p className="text-sm text-slate-600">
                  模式：{(result.writing_style as any).sentence_length?.pattern || 'N/A'}
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3">
                <h4 className="font-semibold text-slate-800">对话潜台词</h4>
                <p className="text-sm text-slate-600 mt-1">
                  {(result.writing_style as any).dialogue_subtext?.pattern || 'N/A'}
                </p>
              </div>
              <div className="rounded-lg border border-slate-200 p-3">
                <h4 className="font-semibold text-slate-800">情绪交替周期</h4>
                <p className="text-sm text-slate-600 mt-1">
                  {(result.writing_style as any).emotion_cycle?.pattern || 'N/A'}
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
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
      <XCircle className="h-16 w-16 text-red-300" />
      <div className="text-center">
        <h3 className="text-lg font-semibold text-slate-700">拆书分析失败</h3>
        <p className="mt-1 text-sm text-slate-500">请查看日志了解详情，或重新开始</p>
      </div>
      <button
        onClick={handleStart}
        className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
      >
        <Play className="h-4 w-4" />
        重新开始
      </button>
      {status.progress && (
        <div className="w-full max-w-lg overflow-auto rounded-lg bg-slate-900 p-3">
          <pre className="text-xs text-red-400 whitespace-pre-wrap font-mono">
            {status.progress.split('\n').slice(-30).join('\n')}
          </pre>
        </div>
      )}
    </div>
  );
}