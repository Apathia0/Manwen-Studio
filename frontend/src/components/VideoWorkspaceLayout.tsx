import { useCallback, useEffect, useState } from 'react';
import {
  type Story,
  type Chapter,
  type ScriptScene,
  type VideoShot,
  type VideoGenerationJob,
  type RenderedClip,
  type EntitlementResponse,
  apiHeaders,
  listScreenplayScenes,
  listSceneShots,
} from '../api';
import FrameworkPanel from './FrameworkPanel';
import EditorPanel from './EditorPanel';
import ScreenplayPanel from './ScreenplayPanel';
import StoryboardPanel from './StoryboardPanel';
import ShotAssetWorkflowPanel from './ShotAssetWorkflowPanel';
import ClipTimelinePanel from './ClipTimelinePanel';
import VideoCharacterLibrary from './VideoCharacterLibrary';

interface Props {
  story: Story;
  chapters: Chapter[];
  currentChapter: Chapter | null;
  entitlements?: EntitlementResponse | null;
  onChapterChange: (chapter: Chapter) => void;
  onContentUpdated: () => void | Promise<void>;
}

type VideoTab = 'content' | 'screenplay' | 'storyboard' | 'clips' | 'project';
type RightPanelTab = 'assets' | 'characters';

const LS_VIDEO_ACTIVE_TAB = 'lorevista.videoActiveTab';
const LS_VIDEO_SELECTED_SCENE_ID = 'lorevista.videoSelectedSceneId';
const LS_VIDEO_SELECTED_SHOT_ID = 'lorevista.videoSelectedShotId';

export default function VideoWorkspaceLayout({
  story,
  chapters,
  currentChapter,
  entitlements,
  onChapterChange,
  onContentUpdated,
}: Props) {
  const [scenes, setScenes] = useState<ScriptScene[]>([]);
  const [screenplay, setScreenplay] = useState<string>('');
  const [selectedScene, setSelectedScene] = useState<ScriptScene | null>(null);
  const [shots, setShots] = useState<VideoShot[]>([]);
  const [selectedShot, setSelectedShot] = useState<VideoShot | null>(null);
  const [activeTab, setActiveTab] = useState<VideoTab>(() => {
    const saved = localStorage.getItem(LS_VIDEO_ACTIVE_TAB) as VideoTab | null;
    return saved && ['content', 'screenplay', 'storyboard', 'clips', 'project'].includes(saved) ? saved : 'content';
  });
  const [jobs, setJobs] = useState<VideoGenerationJob[]>([]);
  const [clips, setClips] = useState<RenderedClip[]>([]);
  const [activeClipId, setActiveClipId] = useState<number | null>(null);
  const [scenesLoading, setScenesLoading] = useState(false);
  const [shotsLoading, setShotsLoading] = useState(false);
  const [stylePresets, setStylePresets] = useState<any[]>([]);
  const [chapterStylePreset, setChapterStylePreset] = useState<any>(null);
  const [storyStylePreset, setStoryStylePreset] = useState<any>(null);
  const [assetsLoading, setAssetsLoading] = useState(false);
  const [rightTab, setRightTab] = useState<RightPanelTab>('assets');

  const resolvedChapter = currentChapter;

  // 章节切换时重置内部状态，并从后端自动加载已保存的场次/剧本
  useEffect(() => {
    if (!resolvedChapter?.id) return;
    setScenes([]);
    setScreenplay('');
    setSelectedScene(null);
    setShots([]);
    setSelectedShot(null);
    setJobs([]);
    setClips([]);
    setActiveClipId(null);

    // 从后端加载已有场次和剧本
    setScenesLoading(true);
    listScreenplayScenes(resolvedChapter.id)
      .then((result) => {
        setScenes(result.scenes || []);
        setScreenplay(result.screenplay || '');
        // 尝试恢复上次选中的场次
        const savedSceneId = localStorage.getItem(LS_VIDEO_SELECTED_SCENE_ID);
        if (savedSceneId && result.scenes.length > 0) {
          const saved = result.scenes.find((s) => s.id === Number(savedSceneId));
          if (saved) setSelectedScene(saved);
        }
      })
      .catch(() => {
        // 没有已保存的数据是正常情况（第一次进入）
      })
      .finally(() => setScenesLoading(false));
  }, [resolvedChapter?.id]);

  // 选中场次变化时自动加载已保存的镜头
  useEffect(() => {
    if (!selectedScene?.id) {
      setShots([]);
      setSelectedShot(null);
      return;
    }
    setShotsLoading(true);
    listSceneShots(selectedScene.id)
      .then((result) => {
        setShots(result.shots || []);
        if (result.shots.length > 0) {
          const savedShotId = localStorage.getItem(LS_VIDEO_SELECTED_SHOT_ID);
          if (savedShotId) {
            const saved = result.shots.find((s) => s.id === Number(savedShotId));
            if (saved) {
              setSelectedShot(saved);
              return;
            }
          }
          setSelectedShot(result.shots[0]);
        }
      })
      .catch(() => {
        // 没有已保存的镜头
      })
      .finally(() => setShotsLoading(false));
  }, [selectedScene?.id]);

  // 持久化当前 tab 到 localStorage
  useEffect(() => {
    localStorage.setItem(LS_VIDEO_ACTIVE_TAB, activeTab);
  }, [activeTab]);

  // 持久化选中的场次 ID 到 localStorage
  useEffect(() => {
    if (selectedScene?.id) {
      localStorage.setItem(LS_VIDEO_SELECTED_SCENE_ID, String(selectedScene.id));
    } else {
      localStorage.removeItem(LS_VIDEO_SELECTED_SCENE_ID);
    }
  }, [selectedScene?.id]);

  // 持久化选中的镜头 ID 到 localStorage
  useEffect(() => {
    if (selectedShot?.id) {
      localStorage.setItem(LS_VIDEO_SELECTED_SHOT_ID, String(selectedShot.id));
    } else {
      localStorage.removeItem(LS_VIDEO_SELECTED_SHOT_ID);
    }
  }, [selectedShot?.id]);

  useEffect(() => {
    if (resolvedChapter) {
      loadStylePresets();
      loadChapterStylePreset();
      loadStoryStylePreset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolvedChapter?.id]);

  const loadStylePresets = async () => {
    try {
      setAssetsLoading(true);
      const res = await fetch('/api/video-style-presets', { headers: apiHeaders() });
      const data = await res.json();
      setStylePresets(data.presets || []);
    } catch (e) {
      console.error('Failed to load style presets:', e);
    } finally {
      setAssetsLoading(false);
    }
  };

  const loadChapterStylePreset = async () => {
    if (!resolvedChapter) return;
    try {
      const res = await fetch(`/api/chapters/${resolvedChapter.id}/video-style-preset`, { headers: apiHeaders() });
      const data = await res.json();
      setChapterStylePreset(data);
    } catch (e) {
      console.error('Failed to load chapter style preset:', e);
    }
  };

  const loadStoryStylePreset = async () => {
    try {
      const res = await fetch(`/api/stories/${story.id}/video-style-preset`, { headers: apiHeaders() });
      const data = await res.json();
      setStoryStylePreset(data);
    } catch (e) {
      console.error('Failed to load story style preset:', e);
    }
  };

  const handleShotStylePresetChange = async (shotId: number, stylePreset: string | null) => {
    try {
      await fetch(`/api/shots/${shotId}/video-style-preset`, {
        method: 'PUT',
        headers: apiHeaders(true),
        body: JSON.stringify({ style_preset: stylePreset }),
      });
      if (selectedShot) {
        setSelectedShot({ ...selectedShot, style_preset: stylePreset ?? undefined });
      }
    } catch (e) {
      console.error('Failed to set shot style preset:', e);
    }
  };

  const handleChapterSelect = useCallback(
    (chapterNumber: number) => {
      const chapter = chapters.find((item) => item.chapter_number === chapterNumber);
      if (chapter) onChapterChange(chapter);
    },
    [chapters, onChapterChange],
  );

  return (
    <div className="flex h-full min-h-0 gap-4 bg-[linear-gradient(180deg,_#f4f8ff_0%,_#eef4ff_100%)] p-4">
      <div className="w-[320px] shrink-0 overflow-y-auto rounded-[24px] border border-[#d7e3f4] bg-[rgba(255,255,255,0.92)] shadow-[0_18px_42px_rgba(59,130,246,0.12)] backdrop-blur-xl">
        <FrameworkPanel
          story={story}
          chapters={chapters}
          onChapterSelect={handleChapterSelect}
          onFrameworkUpdate={onContentUpdated}
        />

        <div className="border-t px-3 py-3 bg-gray-50">
          <div className="text-xs font-medium text-gray-600 mb-2">视频制作进度</div>
          {[
            { step: 1, label: '正文拆解', key: 'screenplay' as VideoTab, done: screenplay !== null && scenes.length > 0, active: activeTab === 'screenplay' },
            { step: 2, label: '分镜设计', key: 'storyboard' as VideoTab, done: selectedScene !== null && shots.length > 0, active: activeTab === 'storyboard' },
            { step: 3, label: '视频生成', key: 'clips' as VideoTab, done: clips.length > 0, active: activeTab === 'clips' },
            { step: 4, label: '成片编译', key: 'project' as VideoTab, done: false, active: activeTab === 'project' },
          ].map((item) => (
            <button
              key={item.key}
              onClick={() => setActiveTab(item.key)}
              className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors ${
                item.active ? 'bg-indigo-50 text-indigo-700' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-medium ${
                item.done ? 'bg-green-100 text-green-700' :
                item.active ? 'bg-indigo-200 text-indigo-700' :
                'bg-gray-200 text-gray-400'
              }`}>
                {item.done ? '✓' : item.step}
              </div>
              <span>{item.label}</span>
              {item.done && <span className="ml-auto text-green-500 text-[10px]">已完成</span>}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 min-w-0 overflow-hidden rounded-[24px] border border-[#d7e3f4] bg-[rgba(255,255,255,0.92)] shadow-[0_18px_42px_rgba(59,130,246,0.12)] backdrop-blur-xl">
        <div className="flex border-b border-[#d7e3f4] px-4">
          <TabButton active={activeTab === 'content'} onClick={() => setActiveTab('content')}>
            正文内容
          </TabButton>
          <TabButton active={activeTab === 'screenplay'} onClick={() => setActiveTab('screenplay')}>
            影视剧本
          </TabButton>
          <TabButton active={activeTab === 'storyboard'} onClick={() => setActiveTab('storyboard')}>
            镜头拆解
          </TabButton>
          <TabButton active={activeTab === 'clips'} onClick={() => setActiveTab('clips')}>
            片段管理
          </TabButton>
          <TabButton active={activeTab === 'project'} onClick={() => setActiveTab('project')}>
            成片项目
          </TabButton>
        </div>

        <div className="h-[calc(100%-48px)] overflow-y-auto">
          {activeTab === 'content' && (
            <EditorPanel
              story={story}
              chapters={chapters}
              currentChapter={resolvedChapter}
              onChapterChange={onChapterChange}
              onContentUpdated={onContentUpdated}
              onTextSelected={() => {}}
            />
          )}

          {activeTab === 'screenplay' && (
            <ScreenplayPanel
              chapterId={resolvedChapter?.id}
              chapterContent={resolvedChapter?.novel_content}
              scenes={scenes}
              screenplay={screenplay}
              entitlements={entitlements}
              onScenesChange={setScenes}
              onScreenplayChange={setScreenplay}
              onSceneSelect={(scene) => {
                setSelectedScene(scene);
                setSelectedShot(null);
                setActiveTab('storyboard');
              }}
            />
          )}

          {activeTab === 'storyboard' && (
            <StoryboardPanel
              scene={selectedScene}
              shots={shots}
              shotsLoading={shotsLoading}
              scenesLoading={scenesLoading}
              entitlements={entitlements}
              onShotsChange={(nextShots) => {
                setShots(nextShots);

                if (nextShots.length === 0) {
                  setSelectedShot(null);
                  return;
                }

                setSelectedShot((currentShot) => {
                  if (!currentShot) return nextShots[0];
                  return nextShots.find((shot) => shot.id === currentShot.id) ?? nextShots[0];
                });
              }}
              onShotSelect={(shot) => {
                setSelectedShot(shot);
              }}
            />
          )}

          {activeTab === 'clips' && (
            <ClipTimelinePanel
              shots={shots}
              clips={clips}
              activeClipId={activeClipId}
              jobs={jobs}
              onClipsChange={setClips}
              onActiveClipChange={setActiveClipId}
            />
          )}

          {activeTab === 'project' && (
            <div className="flex h-full items-center justify-center text-slate-500">
              成片项目功能即将上线
            </div>
          )}
        </div>
      </div>

      <div className="w-[360px] shrink-0 overflow-hidden rounded-[20px] border border-[#d7e3f4] bg-white xl:w-[380px]">
        <div className="flex gap-1 p-1 bg-slate-100 mx-3 mt-3 mb-0 rounded-xl">
          <button
            className={`flex-1 py-1.5 text-xs font-medium rounded-lg transition ${rightTab === 'assets' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
            onClick={() => setRightTab('assets')}
          >
            资产管理
          </button>
          <button
            className={`flex-1 py-1.5 text-xs font-medium rounded-lg transition ${rightTab === 'characters' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'}`}
            onClick={() => setRightTab('characters')}
          >
            角色库
          </button>
        </div>
        {rightTab === 'assets' ? (
          <ShotAssetWorkflowPanel
            shot={selectedShot}
            jobs={jobs}
            clips={clips}
            onJobsChange={setJobs}
            onClipsChange={setClips}
            chapter={resolvedChapter}
            stylePresets={stylePresets}
            chapterStylePreset={chapterStylePreset}
            storyStylePreset={storyStylePreset}
            entitlements={entitlements}
            onShotStylePresetChange={(preset) => {
              if (selectedShot) handleShotStylePresetChange(selectedShot.id, preset);
            }}
            loading={assetsLoading}
          />
        ) : (
          <div className="p-4">
            <VideoCharacterLibrary storyId={story.id} />
          </div>
        )}
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`-mb-px border-b-2 px-4 py-3 text-sm font-medium transition ${
        active
          ? 'border-[#2563eb] text-[#2563eb]'
          : 'border-transparent text-slate-500 hover:text-slate-700'
      }`}
    >
      {children}
    </button>
  );
}
