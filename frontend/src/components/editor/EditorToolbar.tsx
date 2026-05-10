import { useState } from 'react';
import {
  assessQuality,
  expandChapter,
  generateNovel,
  rewriteSelection,
  saveChapterContent,
  type Chapter,
  type QualityScore,
  type Story,
} from '../../api';

interface Props {
  chapter: Chapter;
  story: Story;
  selectedText: string;
  selectedRange: { start: number; end: number } | null;
  onContentUpdated: () => void | Promise<void>;
  onScenesRequest: (text: string) => void;
}

type ButtonAction = 'generate' | 'rewrite' | 'assess' | null;

export default function EditorToolbar({
  chapter,
  story,
  selectedText,
  selectedRange,
  onContentUpdated,
  onScenesRequest,
}: Props) {
  const [activeAction, setActiveAction] = useState<ButtonAction>(null);
  const [errorMsg, setErrorMsg] = useState('');
  const [qualityScore, setQualityScore] = useState<QualityScore | null>(null);
  const [qualityModalOpen, setQualityModalOpen] = useState(false);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [rewrittenText, setRewrittenText] = useState('');
  const [rewriteModalOpen, setRewriteModalOpen] = useState(false);
  const [rewriteApplying, setRewriteApplying] = useState(false);

  const hasSelection = selectedText.length > 0;
  const hasFrameworkPlan = Boolean(chapter.act || (chapter.key_events && chapter.key_events.length > 0));
  const hasExistingChat = Array.isArray(chapter.messages) && chapter.messages.length > 0;

  const clearError = () => setErrorMsg('');

  const handleGenerate = async () => {
    if (activeAction) return;
    setActiveAction('generate');
    clearError();
    try {
      if (hasExistingChat) {
        await generateNovel(chapter.id);
      } else if (hasFrameworkPlan) {
        await expandChapter(chapter.story_id, {
          act: chapter.act || '1',
          chapter_number: chapter.chapter_number,
          chapter_title: chapter.title || `第${chapter.chapter_number}话`,
          key_events: chapter.key_events?.map((item) => String(item)),
        });
      } else {
        throw new Error('当前章节既没有聊天记录，也没有可用的大纲约束，无法生成正文');
      }
      await onContentUpdated();
    } catch (err: any) {
      setErrorMsg(`AI 生成失败: ${err.message}`);
    } finally {
      setActiveAction(null);
    }
  };

  const handleRewrite = async () => {
    if (activeAction || !hasSelection) return;
    setActiveAction('rewrite');
    clearError();
    try {
      const context = buildContextString(story, chapter);
      const rewritten = await rewriteSelection(chapter.id, selectedText, context);
      setRewrittenText(rewritten);
      setRewriteModalOpen(true);
    } catch (err: any) {
      setErrorMsg(`AI 改写失败: ${err.message}`);
    } finally {
      setActiveAction(null);
    }
  };

  const handleApplyRewrite = async () => {
    if (!selectedRange || !chapter.novel_content || !rewrittenText.trim()) return;
    setRewriteApplying(true);
    clearError();
    try {
      const nextContent =
        chapter.novel_content.slice(0, selectedRange.start) +
        rewrittenText +
        chapter.novel_content.slice(selectedRange.end);
      await saveChapterContent(chapter.id, nextContent);
      setRewriteModalOpen(false);
      setRewrittenText('');
      await onContentUpdated();
    } catch (err: any) {
      setErrorMsg(`应用改写失败: ${err.message}`);
    } finally {
      setRewriteApplying(false);
    }
  };

  const handleScenes = () => {
    if (!hasSelection) return;
    onScenesRequest(selectedText);
  };

  const handleAssess = async () => {
    if (activeAction) return;
    setActiveAction('assess');
    setQualityLoading(true);
    clearError();
    try {
      const result = await assessQuality(chapter.id);
      setQualityScore(result);
      setQualityModalOpen(true);
    } catch (err: any) {
      setErrorMsg(`质量评估失败: ${err.message}`);
    } finally {
      setActiveAction(null);
      setQualityLoading(false);
    }
  };

  const isLoading = (action: ButtonAction): boolean => {
    if (action === 'assess') return qualityLoading;
    return activeAction === action;
  };

  const generateLabel = isLoading('generate')
    ? '生成中...'
    : hasExistingChat
      ? 'AI 生成本章'
      : hasFrameworkPlan
        ? '按大纲生成正文'
        : 'AI 生成本章';

  return (
    <>
      <div className="flex items-center gap-2 px-4 py-2.5 bg-gray-900/90 border-t border-gray-800">
        <button
          onClick={handleGenerate}
          disabled={activeAction !== null}
          className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded-lg
                     bg-amber-600 hover:bg-amber-500 text-white
                     disabled:opacity-40 disabled:cursor-not-allowed transition-all active:scale-95"
        >
          {isLoading('generate') ? <Spinner /> : <span>📝</span>}
          {generateLabel}
        </button>

        <button
          onClick={handleRewrite}
          disabled={activeAction !== null || !hasSelection}
          className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded-lg
                     bg-gray-800 hover:bg-gray-700 text-gray-300
                     disabled:opacity-30 disabled:cursor-not-allowed transition-all active:scale-95 border border-gray-700/50"
        >
          {isLoading('rewrite') ? <Spinner /> : <span>🔵</span>}
          {isLoading('rewrite') ? '改写中...' : 'AI 改写选中'}
        </button>

        <button
          onClick={handleScenes}
          disabled={!hasSelection}
          className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded-lg
                     bg-gray-800 hover:bg-gray-700 text-gray-300
                     disabled:opacity-30 disabled:cursor-not-allowed transition-all active:scale-95 border border-gray-700/50"
        >
          <span>🎬</span>
          选中文字生成分镜
        </button>

        <div className="flex-1" />

        <button
          onClick={handleAssess}
          disabled={activeAction !== null}
          className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded-lg
                     bg-gray-800 hover:bg-gray-700 text-gray-400
                     disabled:opacity-40 disabled:cursor-not-allowed transition-all active:scale-95 border border-gray-700/50"
        >
          {isLoading('assess') ? <Spinner /> : <span>📳</span>}
          {isLoading('assess') ? '评估中...' : '质量评估'}
        </button>
      </div>

      {errorMsg && (
        <div className="px-4 py-2 bg-red-900/30 border-t border-red-800/50 flex items-center justify-between">
          <span className="text-xs text-red-300">{errorMsg}</span>
          <button onClick={clearError} className="text-xs text-red-400 hover:text-red-300 ml-3 shrink-0">
            关闭
          </button>
        </div>
      )}

      {qualityModalOpen && qualityScore && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={() => setQualityModalOpen(false)}>
          <div className="w-full max-w-sm rounded-xl border border-gray-800 bg-gray-950 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-800">
              <div className="flex items-center gap-2">
                <span>📳</span>
                <h3 className="text-sm font-semibold text-gray-200">质量评估</h3>
              </div>
              <button onClick={() => setQualityModalOpen(false)} className="p-1 text-gray-500 hover:text-white rounded transition-colors">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="p-5 space-y-3">
              {renderScore('整体', qualityScore.overall)}
              {renderScore('内容', qualityScore.content)}
              {renderScore('文笔', qualityScore.writing)}
              {renderScore('情节', qualityScore.plot)}
              {renderScore('角色', qualityScore.character)}
            </div>
            <div className="px-5 py-3 border-t border-gray-800 flex justify-end">
              <button
                onClick={() => setQualityModalOpen(false)}
                className="px-4 py-1.5 text-xs font-medium rounded-lg bg-amber-600 hover:bg-amber-500 text-white transition-colors"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}

      {rewriteModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={() => !rewriteApplying && setRewriteModalOpen(false)}>
          <div className="w-full max-w-2xl rounded-xl border border-gray-800 bg-gray-950 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-800">
              <div className="flex items-center gap-2">
                <span>🔵</span>
                <h3 className="text-sm font-semibold text-gray-200">改写结果</h3>
              </div>
              <button
                onClick={() => setRewriteModalOpen(false)}
                disabled={rewriteApplying}
                className="p-1 text-gray-500 hover:text-white rounded transition-colors disabled:opacity-40"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="p-5 space-y-3">
              <div className="rounded-lg border border-gray-800 bg-gray-900/70 p-3">
                <p className="text-xs text-gray-500 mb-2">原文选段</p>
                <p className="text-sm text-gray-300 whitespace-pre-wrap leading-7">{selectedText}</p>
              </div>
              <div className="rounded-lg border border-amber-800/40 bg-amber-950/20 p-3">
                <p className="text-xs text-amber-300/80 mb-2">AI 改写</p>
                <p className="text-sm text-gray-100 whitespace-pre-wrap leading-7">{rewrittenText}</p>
              </div>
            </div>
            <div className="px-5 py-3 border-t border-gray-800 flex items-center justify-end gap-2">
              <button
                onClick={() => setRewriteModalOpen(false)}
                disabled={rewriteApplying}
                className="px-4 py-1.5 text-xs font-medium rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 disabled:opacity-40"
              >
                关闭
              </button>
              <button
                onClick={handleApplyRewrite}
                disabled={rewriteApplying || !selectedRange || !rewrittenText.trim()}
                className="px-4 py-1.5 text-xs font-medium rounded-lg bg-amber-600 hover:bg-amber-500 text-white disabled:opacity-40"
              >
                {rewriteApplying ? '应用中...' : '替换到正文'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function Spinner() {
  return (
    <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

function renderScore(label: string, score: number | undefined): React.ReactNode {
  const normalized = score !== undefined ? Math.round(Math.min(Math.max(score, 0), 10) * 10) / 10 : 0;
  const percentage = (normalized / 10) * 100;
  const color = normalized >= 8 ? 'bg-emerald-500' : normalized >= 6 ? 'bg-amber-500' : normalized >= 4 ? 'bg-orange-500' : 'bg-red-500';
  const textColor = normalized >= 8 ? 'text-emerald-400' : normalized >= 6 ? 'text-amber-400' : normalized >= 4 ? 'text-orange-400' : 'text-red-400';

  return (
    <div className="flex items-center gap-3">
      <span className="w-10 text-xs text-gray-500 shrink-0">{label}</span>
      <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-500 ${color}`} style={{ width: `${percentage}%` }} />
      </div>
      <span className={`w-8 text-xs font-mono font-bold text-right ${textColor}`}>{normalized.toFixed(1)}</span>
    </div>
  );
}

function buildContextString(story: Story, chapter: Chapter): string {
  const parts: string[] = [];
  if (chapter.act) parts.push(`幕：${chapter.act}`);
  if (chapter.key_events?.length) {
    const events = chapter.key_events
      .slice(0, 5)
      .map((e) => (typeof e === 'string' ? e : e.title || e.event || ''))
      .filter(Boolean)
      .join('、');
    if (events) parts.push(`关键事件：${events}`);
  }
  if (story.characters?.length) {
    const names = story.characters.filter((c) => c.name).map((c) => c.name!).slice(0, 6).join('、');
    if (names) parts.push(`角色：${names}`);
  }
  return parts.join(' | ');
}
