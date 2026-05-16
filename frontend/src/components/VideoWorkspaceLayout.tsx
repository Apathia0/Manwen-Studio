import { useCallback, useEffect, useState } from 'react';
import {
  type Story,
  type Chapter,
  type ScriptScene,
  type VideoShot,
  type VideoGenerationJob,
  type RenderedClip,
} from '../api';
import FrameworkPanel from './FrameworkPanel';
import EditorPanel from './EditorPanel';
import ScreenplayPanel from './ScreenplayPanel';
import StoryboardPanel from './StoryboardPanel';
import VideoPanel from './VideoPanel';
import ClipTimelinePanel from './ClipTimelinePanel';

interface Props {
  story: Story;
  chapters: Chapter[];
  currentChapter: Chapter | null;
  onChapterChange: (chapter: Chapter) => void;
  onContentUpdated: () => void | Promise<void>;
}

type VideoTab = 'content' | 'screenplay' | 'storyboard' | 'clips' | 'project';

export default function VideoWorkspaceLayout({
  story,
  chapters,
  currentChapter,
  onChapterChange,
  onContentUpdated,
}: Props) {
  const [scenes, setScenes] = useState<ScriptScene[]>([]);
  const [screenplay, setScreenplay] = useState<string>('');
  const [selectedScene, setSelectedScene] = useState<ScriptScene | null>(null);
  const [shots, setShots] = useState<VideoShot[]>([]);
  const [selectedShot, setSelectedShot] = useState<VideoShot | null>(null);
  const [activeTab, setActiveTab] = useState<VideoTab>('content');
  const [jobs, setJobs] = useState<VideoGenerationJob[]>([]);
  const [clips, setClips] = useState<RenderedClip[]>([]);
  const [activeClipId, setActiveClipId] = useState<number | null>(null);

  const resolvedChapter = currentChapter;

  useEffect(() => {
    setScenes([]);
    setScreenplay('');
    setSelectedScene(null);
    setShots([]);
    setSelectedShot(null);
    setJobs([]);
    setClips([]);
    setActiveClipId(null);
    setActiveTab('content');
  }, [resolvedChapter?.id]);

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

      <div className="w-[400px] shrink-0 overflow-y-auto rounded-[24px] border border-[#d7e3f4] bg-[rgba(255,255,255,0.92)] shadow-[0_18px_42px_rgba(59,130,246,0.12)] backdrop-blur-xl">
        <VideoPanel
          shot={selectedShot}
          jobs={jobs}
          clips={clips}
          onJobsChange={setJobs}
          onClipsChange={setClips}
        />
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
