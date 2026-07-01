import { useState, useEffect, useCallback } from 'react';
import { BookOpen, Search, Play, Square, RefreshCw, Loader2, CheckCircle2, XCircle, Clock, ExternalLink, ClipboardList, FileText, Puzzle, Landmark, BarChart3, Palette } from 'lucide-react';
import type { Story, DeconstructionStatus, DeconstructionResult } from '../api';
import {
  startDeconstruction,
  getDeconstructionStatus,
  getDeconstructionResult,
  cancelDeconstruction,
  resumeDeconstruction,
  applyDeconstructionToBible,
  getCrawlStatus,
} from '../api';
import NovelSearchPanel from './NovelSearchPanel';

interface Props {
  story: Story;
}

const STAGE_NAMES: Record<number, string> = {
  0: '概要提取',
  0.5: '故事框架识别',
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

export default function DeconstructionPanel({ story }: Props) {
  const [status, setStatus] = useState<DeconstructionStatus | null>(null);
  const [result, setResult] = useState<DeconstructionResult | null>(null);
  const [activeTab, setActiveTab] = useState<'progress' | 'report' | 'characters' | 'plots' | 'style'>('progress');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSearch, setShowSearch] = useState(false);
  const [crawlStatus, setCrawlStatus] = useState<string | null>(null);
  const [partialCount, setPartialCount] = useState(50);
  const [showPartialInput, setShowPartialInput] = useState(false);

  // 轮询拆书状态
  useEffect(() => {
    let timer: ReturnType<typeof setInterval>;
    loadStatus();

    if (status?.status === 'running' || status?.status === 'pending' || status?.status === 'paused_after_stage1' || (status?.status && status.status.startsWith('paused_after_partial'))) {
      timer = setInterval(loadStatus, 3000);
    }

    return () => { if (timer) clearInterval(timer); };
  }, [status?.status]);

  // 轮询爬取状态，完成后自动拆书
  useEffect(() => {
    if (!showSearch) return;
    let autoStarted = false;
    const timer = setInterval(async () => {
      try {
        const s = await getCrawlStatus(story.id);
        setCrawlStatus(s.status);
        if (s.status === 'completed' && !autoStarted) {
          autoStarted = true;
          setShowSearch(false);
          setCrawlStatus(null);
          await startDeconstruction(story.id);
          setStatus({ status: 'running', current_stage: 0, stages_completed: [], progress: null, result_id: null });
        }
      } catch {}
    }, 3000);
    return () => clearInterval(timer);
  }, [showSearch, story.id]);

  const loadStatus = useCallback(async () => {
    try {
      const s = await getDeconstructionStatus(story.id);
      setStatus(prev => {
        if (prev?.status === 'running' && s.status === 'not_started') return prev;
        return s;
      });
      if (s.status === 'paused_after_stage1' || (s.status && s.status.startsWith('paused_after_partial'))) {
        // 停靠状态：取结果（试读报告或三章快速报告）
        setStatus(s);
        try {
          const r = await getDeconstructionResult(story.id);
          if (r && r.report_markdown) {
            setResult(r);
            setActiveTab('report');
          }
        } catch {}
      } else if (s.status === 'completed') {
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

  const handleResume = async () => {
    setLoading(true);
    setError(null);
    try {
      await resumeDeconstruction(story.id, 'full');
      setStatus({ status: 'running', current_stage: 2, stages_completed: [0, 0.5, 1], progress: null, result_id: null });
    } catch (e: any) {
      setError(e.message || '续跑失败');
    } finally {
      setLoading(false);
    }
  };

  const handlePartialResume = async () => {
    setLoading(true);
    setError(null);
    try {
      await resumeDeconstruction(story.id, 'partial');
      setStatus({ status: 'running', current_stage: 2, stages_completed: [0, 0.5, 1], progress: null, result_id: null });
    } catch (e: any) {
      setError(e.message || '试读启动失败');
    } finally {
      setLoading(false);
    }
  };

  const handleQuickReport = async () => {
    setLoading(true);
    setError(null);
    try {
      await resumeDeconstruction(story.id, 'quick_report');
      setStatus(prev => prev ? { ...prev, status: 'running' } : null);
    } catch (e: any) {
      setError(e.message || '报告生成失败');
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

  const handleCrawlStarted = (_taskId: string) => {
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

  // 停靠中（黄金三章后）
  if (status.status === 'paused_after_stage1') {
    return (
      <div className="flex h-full flex-col p-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-amber-700">黄金三章拆解完成</h3>
          {!showPartialInput ? (
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={handleResume}
                disabled={loading}
                className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                继续全量拆解
              </button>
              <button
                onClick={() => setShowPartialInput(true)}
                disabled={loading}
                className="flex items-center gap-2 rounded-lg border border-amber-400 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-700 hover:bg-amber-100 disabled:opacity-50"
              >
                <BookOpen className="h-4 w-4" />
                试读前 {partialCount} 章
              </button>
              <button
                onClick={handleQuickReport}
                disabled={loading}
                className="flex items-center gap-2 rounded-lg border border-green-400 bg-green-50 px-4 py-2 text-sm font-medium text-green-700 hover:bg-green-100 disabled:opacity-50"
              >
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                生成三章报告
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={10}
                value={partialCount}
                onChange={(e) => setPartialCount(Math.max(10, parseInt(e.target.value) || 10))}
                placeholder="章节数"
                className="w-20 rounded-lg border border-amber-300 bg-white px-2.5 py-2 text-sm text-slate-700 text-center focus:border-amber-500 focus:outline-none focus:ring-1 focus:ring-amber-500 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
              />
              <button
                onClick={handlePartialResume}
                disabled={loading}
                className="flex items-center gap-2 rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
              >
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                开始试读
              </button>
              <button
                onClick={() => setShowPartialInput(false)}
                disabled={loading}
                className="text-sm text-slate-400 hover:text-slate-600 disabled:opacity-50"
              >
                取消
              </button>
            </div>
          )}
        </div>

        <div className="space-y-2 mb-4">
          {[0, 0.5, 1].map((stage) => (
            <div
              key={stage}
              className="flex items-center gap-3 rounded-lg p-2.5 text-sm bg-green-50 text-green-700"
            >
              {getStageIcon(Math.floor(stage))}
              <span className="flex-1">{STAGE_NAMES[stage] || '未知阶段'}</span>
              <CheckCircle2 className="h-4 w-4 text-green-500" />
            </div>
          ))}
          {[2, 3, 4, 5, 6].map((stage) => (
            <div
              key={stage}
              className="flex items-center gap-3 rounded-lg p-2.5 text-sm bg-slate-50 text-slate-400"
            >
              {getStageIcon(stage)}
              <span className="flex-1">{STAGE_NAMES[stage]}</span>
              <Clock className="h-4 w-4 text-slate-300" />
            </div>
          ))}
        </div>

        {status.progress && (
          <div className="flex-1 overflow-auto rounded-lg bg-slate-50 p-4">
            <div className="prose prose-sm max-w-none text-sm leading-relaxed whitespace-pre-wrap text-slate-700">
              {status.progress.split('\n').slice(-50).join('\n')}
            </div>
          </div>
        )}

        {error && <p className="text-sm text-red-500 mt-2">{error}</p>}
      </div>
    );
  }

  // 试读完成 / 三章快速报告完成
  if (status.status && status.status.startsWith('paused_after_partial')) {
    const rangeNum = status.status.split(':')[1] || '?';
    if (result?.report_markdown) {
      return (
        <div className="flex h-full flex-col">
          <div className="flex items-center gap-1 border-b border-slate-200 px-4 py-2">
            <span className="text-sm font-semibold text-green-700">试读报告（前{rangeNum}章）</span>
            <div className="flex-1" />
            <button
              onClick={handleResume}
              className="flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700"
            >
              <Play className="h-3 w-3" />
              继续全量拆解
            </button>
          </div>
          <div className="flex-1 overflow-auto p-4">
            <div className="prose prose-sm max-w-none text-sm leading-relaxed whitespace-pre-wrap text-slate-700">
              {result.report_markdown}
            </div>
          </div>
        </div>
      );
    }
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-4">
        <CheckCircle2 className="h-12 w-12 text-green-400" />
        <p className="text-sm text-slate-500">试读已完成，报告生成中...</p>
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
          {[0, 0.5, 1, 2, 3, 4, 5, 6].map((stage) => (
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
              {getStageIcon(stage)}
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