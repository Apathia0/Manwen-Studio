import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FileText, ListTree, Save, X } from 'lucide-react';
import { getScenes, updateScenes, type Chapter, type Story } from '../api';
import ChapterListPanel from './ChapterListPanel';
import { RouteLoadingFallback } from './ui/RouteLoadingFallback';

const MangaPanel = lazy(() => import('./MangaPanel'));

interface Props {
  story: Story;
  chapters: Chapter[];
  currentChapter: Chapter | null;
  entitlements?: Record<string, any> | null;
  onChapterChange: (chapter: Chapter) => void;
  onContentUpdated: () => void | Promise<void>;
}

export default function MangaWorkspaceLayout({
  story: _story,
  chapters,
  currentChapter,
  entitlements,
  onChapterChange,
  onContentUpdated,
}: Props) {
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [sourceViewerOpen, setSourceViewerOpen] = useState(false);
  const [panelVersion, setPanelVersion] = useState(0);

  const chapterInfos = useMemo(
    () => chapters.map((chapter) => ({
      chapter,
      shotCount: 0,
      hasFrames: (chapter.images?.length || 0) > 0,
    })),
    [chapters],
  );

  useEffect(() => {
    setSourceViewerOpen(false);
  }, [currentChapter?.id]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 bg-[linear-gradient(180deg,_#f4f8ff_0%,_#eef4ff_100%)] p-4 sm:flex-row">
      <ChapterListPanel
        chapters={chapterInfos}
        selectedChapterId={currentChapter?.id ?? null}
        collapsed={leftCollapsed}
        className="max-sm:h-[132px] max-sm:w-full"
        onSelect={onChapterChange}
        onToggleCollapse={() => setLeftCollapsed((value) => !value)}
      />

      <section className="min-w-0 flex-1 overflow-hidden rounded-[24px] border border-[#d7e3f4] bg-[rgba(255,255,255,0.92)] shadow-[0_18px_42px_rgba(59,130,246,0.12)] backdrop-blur-xl">
        <div className="h-full min-h-0 overflow-hidden">
          <Suspense fallback={<RouteLoadingFallback />}>
            <MangaPanel
              key={`${currentChapter?.id ?? 'no-chapter'}-${panelVersion}`}
              chapter={currentChapter}
              entitlements={entitlements}
              onChapterRefresh={onContentUpdated}
              onOpenSourceViewer={() => setSourceViewerOpen(true)}
            />
          </Suspense>
        </div>
      </section>

      {sourceViewerOpen && currentChapter ? (
        <MangaSourceViewer
          chapter={currentChapter}
          onClose={() => setSourceViewerOpen(false)}
          onScenesSaved={async () => {
            await onContentUpdated();
            setPanelVersion((value) => value + 1);
          }}
        />
      ) : null}
    </div>
  );
}

function MangaSourceViewer({ chapter, onClose, onScenesSaved }: { chapter: Chapter; onClose: () => void; onScenesSaved: () => void | Promise<void> }) {
  const [scenes, setScenes] = useState<string[]>([]);
  const [draftScenes, setDraftScenes] = useState<string[]>([]);
  const [loadingScenes, setLoadingScenes] = useState(false);
  const [sceneError, setSceneError] = useState('');
  const [savingScenes, setSavingScenes] = useState(false);
  const dialogRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const hasSceneChanges = draftScenes.some((scene, index) => scene !== scenes[index]) || draftScenes.length !== scenes.length;
  const requestClose = useCallback(() => {
    if (hasSceneChanges && !window.confirm('分镜修改尚未保存，确定放弃这些修改吗？')) return;
    onClose();
  }, [hasSceneChanges, onClose]);
  const requestCloseRef = useRef(requestClose);

  useEffect(() => {
    requestCloseRef.current = requestClose;
  }, [requestClose]);

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButtonRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        requestCloseRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      previouslyFocused?.focus();
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoadingScenes(true);
    setSceneError('');
    setScenes([]);
    void getScenes(chapter.id)
      .then((result) => {
        if (active) {
          setScenes(result.scenes || []);
          setDraftScenes(result.scenes || []);
        }
      })
      .catch(() => {
        if (active) setSceneError('暂时无法读取漫画分镜，请稍后重试。');
      })
      .finally(() => {
        if (active) setLoadingScenes(false);
      });
    return () => {
      active = false;
    };
  }, [chapter.id]);

  const saveSceneChanges = async () => {
    setSavingScenes(true);
    setSceneError('');
    try {
      await updateScenes(chapter.id, draftScenes);
      setScenes(draftScenes);
      await onScenesSaved();
    } catch {
      setSceneError('保存漫画分镜失败，请稍后重试。');
    } finally {
      setSavingScenes(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-[rgba(15,23,42,0.52)] p-4 backdrop-blur-sm"
      role="presentation"
      onClick={(event) => {
        if (event.target === event.currentTarget) requestClose();
      }}
    >
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="manga-source-viewer-title"
        className="flex h-[min(760px,88vh)] w-[min(1320px,96vw)] flex-col overflow-hidden rounded-2xl border border-[#d7e3f4] bg-white shadow-[0_28px_80px_rgba(15,23,42,0.3)]"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-[#e5edf8] px-5 py-4">
          <div className="min-w-0">
            <h3 id="manga-source-viewer-title" className="truncate text-base font-semibold text-slate-900">第{chapter.chapter_number}章 · 正文与漫画分镜</h3>
            <p className="mt-1 truncate text-xs text-slate-500">{chapter.title || '未命名章节'}</p>
          </div>
          <button ref={closeButtonRef} type="button" onClick={requestClose} className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700" aria-label="关闭正文与分镜查看器">
            <X size={18} aria-hidden="true" />
          </button>
        </header>

        <div className="grid min-h-0 flex-1 grid-cols-1 divide-y divide-[#e5edf8] lg:grid-cols-2 lg:divide-x lg:divide-y-0">
          <article className="min-h-0 overflow-y-auto px-5 py-5">
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-800"><FileText size={16} className="text-blue-600" /> 原文正文</div>
            <div className="whitespace-pre-wrap text-sm leading-8 text-slate-700">{chapter.novel_content?.trim() || '当前章节还没有可查看的正文内容。'}</div>
          </article>
          <section className="flex min-h-0 flex-col overflow-hidden">
            <div className="flex shrink-0 items-center justify-between gap-3 border-b border-[#e5edf8] px-5 py-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-800"><ListTree size={16} className="text-blue-600" /> 漫画分镜脚本 <span className="text-xs font-normal text-slate-400">{draftScenes.length} 格</span></div>
              <button type="button" disabled={!hasSceneChanges || savingScenes || loadingScenes} onClick={() => void saveSceneChanges()} className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"><Save size={13} />{savingScenes ? '保存中...' : '保存分镜'}</button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
              {loadingScenes ? <div className="py-12 text-center text-sm text-slate-400">正在读取漫画分镜...</div> : sceneError ? <div className="py-12 text-center text-sm text-rose-500">{sceneError}</div> : draftScenes.length === 0 ? <div className="py-12 text-center text-sm text-slate-400">当前章节还没有漫画分镜。</div> : (
                <ol className="space-y-3">{draftScenes.map((scene, index) => { const inputId = `manga-scene-${chapter.id}-${index}`; return <li key={index} className="rounded-lg border border-[#dce8f8] bg-[#fbfdff] p-3"><label htmlFor={inputId} className="mb-2 block text-xs font-semibold text-blue-700">分镜 {index + 1}</label><textarea id={inputId} value={scene} onChange={(event) => setDraftScenes((previous) => previous.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} className="min-h-24 w-full resize-y rounded-md border border-[#d7e3f4] bg-white px-3 py-2 text-sm leading-6 text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" /></li>; })}</ol>
              )}
            </div>
          </section>
        </div>
      </section>
    </div>
  );
}
