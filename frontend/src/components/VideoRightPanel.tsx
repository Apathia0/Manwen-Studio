import { useState, useEffect } from 'react';
import VideoPanel from './VideoPanel';
import AssetManagementPanel from './AssetManagementPanel';
import VideoCharacterLibrary from './VideoCharacterLibrary';
import type { VideoShot, VideoGenerationJob, RenderedClip } from '../api';

interface VideoRightPanelProps {
  shot: VideoShot | null;
  jobs: VideoGenerationJob[];
  clips: RenderedClip[];
  onJobsChange: React.Dispatch<React.SetStateAction<VideoGenerationJob[]>>;
  onClipsChange: React.Dispatch<React.SetStateAction<RenderedClip[]>>;
  chapter: any;
  stylePresets: any[];
  chapterStylePreset: any;
  onStylePresetChange: (presetId: number) => void;
  loading: boolean;
  onCharacterSelect?: (asset: any) => void;
  onSceneConceptSetReference?: (asset: any, sceneId: number) => void;
  onShotFrameSelect?: (asset: any, shotId: number) => void;
}

const STORAGE_KEY = 'storycanvas.videoRightTab';

export default function VideoRightPanel(props: VideoRightPanelProps) {
  const [activeTab, setActiveTab] = useState<'video' | 'assets' | 'characters'>(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'video' || saved === 'assets' || saved === 'characters') return saved;
    return 'video';
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, activeTab);
  }, [activeTab]);

  return (
    <div className="w-[400px] shrink-0 overflow-y-auto rounded-[24px] border border-[#d7e3f4] bg-[rgba(255,255,255,0.92)] shadow-[0_18px_42px_rgba(59,130,246,0.12)] backdrop-blur-xl">
      <div className="flex gap-1 p-1 bg-slate-100 rounded-xl mx-4 mt-3 mb-2">
        <button
          className={`px-4 py-2 text-sm font-medium rounded-lg transition ${
            activeTab === 'video'
              ? 'bg-white text-slate-900 shadow-sm'
              : 'text-slate-500 hover:text-slate-700'
          }`}
          onClick={() => setActiveTab('video')}
        >
          视频预览
        </button>
        <button
          className={`px-4 py-2 text-sm font-medium rounded-lg transition ${
            activeTab === 'assets'
              ? 'bg-white text-slate-900 shadow-sm'
              : 'text-slate-500 hover:text-slate-700'
          }`}
          onClick={() => setActiveTab('assets')}
        >
          资产管理
        </button>
        <button
          className={`px-4 py-2 text-sm font-medium rounded-lg transition ${
            activeTab === 'characters'
              ? 'bg-white text-slate-900 shadow-sm'
              : 'text-slate-500 hover:text-slate-700'
          }`}
          onClick={() => setActiveTab('characters')}
        >
          角色库
        </button>
      </div>

      <div className="p-4">
        {activeTab === 'video' ? (
          <VideoPanel
            shot={props.shot}
            jobs={props.jobs}
            clips={props.clips}
            onJobsChange={props.onJobsChange}
            onClipsChange={props.onClipsChange}
          />
        ) : activeTab === 'characters' ? (
          <VideoCharacterLibrary
            storyId={props.chapter?.story_id}
          />
        ) : (
          <AssetManagementPanel
            chapter={props.chapter}
            stylePresets={props.stylePresets}
            chapterStylePreset={props.chapterStylePreset}
            onStylePresetChange={props.onStylePresetChange}
            loading={props.loading}
            onCharacterSelect={props.onCharacterSelect}
            onSceneConceptSetReference={props.onSceneConceptSetReference}
            onShotFrameSelect={props.onShotFrameSelect}
          />
        )}
      </div>
    </div>
  );
}
