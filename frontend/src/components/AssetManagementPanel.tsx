import { useState, useEffect } from 'react';
import { listChapterShotFrames, apiHeaders, type ChapterShotFramesResponse } from '../api';

interface AssetPanelProps {
  chapter: any;
  stylePresets: any[];
  chapterStylePreset: any;
  onStylePresetChange: (presetId: number) => void;
  loading: boolean;
  onCharacterSelect?: (asset: any) => void;
  onSceneConceptSetReference?: (asset: any, sceneId: number) => void;
  onShotFrameSelect?: (asset: any, shotId: number) => void;
}

function formatStyleName(name?: string | null) {
  if (!name) return '';
  const trimmed = name.trim();
  const nameMap: Record<string, string> = {
    '3A游戏渲析': '3A游戏渲染',
    '3A游戏滚析': '3A游戏渲染',
    '3A游戏渲染': '3D游戏渲染',
    '日式动漏风': '日式动漫风',
    '水壁国风': '水墨国风',
    '水彩手画风': '水彩手绘风',
    '科技赛模风': '科技赛博风',
  };
  return nameMap[trimmed] || trimmed;
}

const AssetManagementPanel: React.FC<AssetPanelProps> = ({
  chapter,
  stylePresets,
  chapterStylePreset,
  onStylePresetChange,
  loading,
  onCharacterSelect,
  onSceneConceptSetReference,
  onShotFrameSelect,
}) => {
  const [activeSection, setActiveSection] = useState<'style' | 'characters' | 'scenes' | 'frames'>('style');
  const [characterAssets, setCharacterAssets] = useState<any[]>([]);
  const [sceneAssets, setSceneAssets] = useState<any[]>([]);
  const [scenes, setScenes] = useState<any[]>([]);
  const [generatingSceneId, setGeneratingSceneId] = useState<number | null>(null);
  const [characterRefLoading, setCharacterRefLoading] = useState(false);
  const [shotFrames, setShotFrames] = useState<ChapterShotFramesResponse['shots']>([]);
  const [shotFramesLoading, setShotFramesLoading] = useState(false);
  const [previewAsset, setPreviewAsset] = useState<any | null>(null);
  const [previewSection, setPreviewSection] = useState<'character' | 'scene' | 'frame' | null>(null);

  useEffect(() => {
    loadAssets();
    loadScenes();
    loadShotFrames();
  }, [chapter?.id]);

  const loadAssets = async () => {
    if (!chapter) return;
    try {
      const res = await fetch(`/api/chapters/${chapter.id}/video-assets`, { headers: apiHeaders() });
      const data = await res.json();
      const assets = data.assets || [];
      setCharacterAssets(assets.filter((a: any) => a.asset_type === 'character_reference'));
      setSceneAssets(assets.filter((a: any) => a.asset_type === 'scene_reference'));
    } catch (e) {
      console.error('Failed to load assets:', e);
    }
  };

  const loadScenes = async () => {
    if (!chapter) return;
    try {
      const res = await fetch(`/api/chapters/${chapter.id}/screenplay/scenes`, { headers: apiHeaders() });
      const data = await res.json();
      setScenes(data.scenes || []);
    } catch (e) {
      console.error('Failed to load scenes:', e);
    }
  };

  const generateCharacterRefs = async () => {
    if (!chapter) return;
    setCharacterRefLoading(true);
    try {
      const res = await fetch(`/api/stories/${chapter.story_id}/character-ref-images/generate`, {
        method: 'POST',
        headers: apiHeaders(true),
        body: JSON.stringify({
          style_preset: chapterStylePreset?.style_preset?.name || '写实电影感',
          force: true,
        }),
      });
      if (res.ok) {
        await loadAssets();
      }
    } catch (e) {
      console.error('Failed to generate character refs:', e);
    } finally {
      setCharacterRefLoading(false);
    }
  };

  const generateSceneConceptArt = async (sceneId: number) => {
    setGeneratingSceneId(sceneId);
    try {
      await fetch(`/api/scenes/${sceneId}/concept-art/generate`, {
        method: 'POST',
        headers: apiHeaders(true),
        body: JSON.stringify({
          style_preset: chapterStylePreset?.style_preset?.name || '写实电影感',
          overwrite: true,
        }),
      });
      await loadAssets();
    } catch (e) {
      console.error('Failed to generate concept art:', e);
    } finally {
      setGeneratingSceneId(null);
    }
  };

  const loadShotFrames = async () => {
    if (!chapter) return;
    setShotFramesLoading(true);
    try {
      const data = await listChapterShotFrames(chapter.id);
      setShotFrames(data.shots || []);
    } catch (e) {
      console.error('Failed to load shot frames:', e);
    } finally {
      setShotFramesLoading(false);
    }
  };

  const getAssetFileUrl = (filePath: string) => {
    if (!filePath) return '';
    if (filePath.startsWith('http')) return filePath;
    return `/static/video/${filePath.replace(/\\/g, '/')}`;
  };

  const renderStyleSection = () => (
    <div className="space-y-4">
      <h3 className="text-sm font-medium text-gray-700">视频风格预设</h3>
      <p className="text-xs text-gray-500">
        选择一种视频风格，所有后续生成的角色参考图、场景概念图都将按此风格生成。
      </p>

      {loading ? (
        <div className="flex justify-center py-4">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-indigo-500"></div>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          {stylePresets.map((preset: any) => (
            <button
              key={preset.id}
              onClick={() => onStylePresetChange(preset.id)}
              className={`p-3 rounded-lg border-2 text-left transition-all ${
                chapterStylePreset?.style_preset_id === preset.id
                  ? 'border-indigo-500 bg-indigo-50 shadow-sm'
                  : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
              }`}
            >
              <div className="text-sm font-medium text-gray-800">{formatStyleName(preset.name)}</div>
              <div className="text-xs text-gray-500 mt-1">{preset.category}</div>
              <div className={`mt-2 inline-block px-2 py-0.5 rounded text-xs font-medium ${
                chapterStylePreset?.style_preset_id === preset.id
                  ? 'bg-indigo-100 text-indigo-700'
                  : 'bg-gray-100 text-gray-500'
              }`}>
                {preset.category === 'realistic' ? '写实' :
                 preset.category === 'anime' ? '动漫' :
                 preset.category === 'game' ? '游戏' :
                 preset.category === 'artistic' ? '艺术' : '自定义'}
              </div>
            </button>
          ))}
        </div>
      )}

      {chapterStylePreset?.style_preset && (
        <div className="p-3 bg-indigo-50 rounded-lg border border-indigo-200">
          <div className="text-xs text-indigo-700">
            当前风格：<strong>{formatStyleName(chapterStylePreset.style_preset.name)}</strong>
          </div>
        </div>
      )}
    </div>
  );

  const renderCharacterSection = () => (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-700">角色参考图</h3>
        <button
          onClick={generateCharacterRefs}
          disabled={characterRefLoading}
          className="px-3 py-1.5 bg-indigo-600 text-white text-xs rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {characterRefLoading ? '生成中...' : '批量生成'}
        </button>
      </div>

      {characterAssets.length === 0 ? (
        <div className="text-center py-8 text-gray-400 text-sm">
          <p>暂无角色参考图</p>
          <p className="text-xs mt-1">点击"批量生成"根据故事角色描述生成</p>
        </div>
      ) : (
        <div className="space-y-3">
          {characterAssets.map((asset: any) => (
            <div key={asset.id} className="border rounded-lg overflow-hidden bg-white">
              <div
                className="flex gap-3 p-2 cursor-pointer hover:bg-gray-50 transition"
                onClick={() => {
                  setPreviewAsset(asset);
                  setPreviewSection('character');
                }}
              >
                <div className="w-20 h-20 bg-gray-100 rounded flex-shrink-0 overflow-hidden">
                  {asset.file_path ? (
                    <img
                      src={getAssetFileUrl(asset.file_path)}
                      alt={asset.name}
                      className="w-full h-full object-cover cursor-pointer"
                    />
                  ) : (
                    <div className="flex items-center justify-center h-full text-gray-300 text-xs">
                      加载中...
                    </div>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-gray-800 truncate">{asset.name}</div>
                  <div className="text-xs text-gray-500">{asset.style_preset || '默认风格'}</div>
                  {asset.prompt && (
                    <div className="text-xs text-gray-400 mt-1 line-clamp-2">{asset.prompt}</div>
                  )}
                  <div className="flex gap-2 mt-1">
                    {onCharacterSelect && (
                      <button
                        onClick={(e) => { e.stopPropagation(); onCharacterSelect(asset); }}
                        className="text-xs text-indigo-600 hover:text-indigo-800"
                      >
                        用作参考
                      </button>
                    )}
                    <span className="text-xs text-indigo-500">点击预览</span>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  const renderSceneSection = () => (
    <div className="space-y-4">
      <h3 className="text-sm font-medium text-gray-700">场景概念图</h3>

      {scenes.length === 0 ? (
        <div className="text-center py-8 text-gray-400 text-sm">
          <p>暂无场次数据，请先在"影视剧本"tab 生成场次</p>
        </div>
      ) : (
        <div className="space-y-3">
          {scenes.map((scene: any) => {
            const sceneArt = sceneAssets.find(
              (a: any) => a.scene_id === scene.id
            );
            const isGenerating = generatingSceneId === scene.id;

            return (
              <div key={scene.id} className="border rounded-lg p-3 bg-white">
                <div className="flex items-start gap-3">
                  <div className="w-24 h-16 bg-gray-100 rounded flex-shrink-0 overflow-hidden">
                    {sceneArt?.file_path ? (
                      <img
                        src={getAssetFileUrl(sceneArt.file_path)}
                        alt={scene.title}
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <div className="flex items-center justify-center h-full text-gray-300 text-xs">
                        未生成
                      </div>
                    )}
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-gray-800 truncate">
                      场次{scene.scene_number}: {scene.title}
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5">
                      {scene.location} / {scene.time_of_day}
                    </div>
                    <div className="text-xs text-gray-400 mt-0.5 line-clamp-1">
                      {scene.summary}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1">
                      <button
                        onClick={() => generateSceneConceptArt(scene.id)}
                        disabled={isGenerating}
                        className="text-xs px-2.5 py-1 bg-gray-100 text-gray-600 rounded hover:bg-gray-200 disabled:opacity-50 transition-colors"
                      >
                        {isGenerating ? '生成中...' : sceneArt ? '重新生成' : '生成概念图'}
                      </button>
                      {sceneArt && onSceneConceptSetReference && (
                        <button
                          onClick={() => onSceneConceptSetReference(sceneArt, scene.id)}
                          className="text-xs px-2.5 py-1 bg-indigo-50 text-indigo-600 rounded hover:bg-indigo-100 transition-colors"
                        >
                          设为镜头背景
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );

  const renderShotFramesSection = () => (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-700">镜头首尾帧</h3>
        <button
          onClick={loadShotFrames}
          disabled={shotFramesLoading}
          className="px-3 py-1.5 bg-indigo-600 text-white text-xs rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {shotFramesLoading ? '加载中...' : '刷新'}
        </button>
      </div>

      {shotFramesLoading ? (
        <div className="flex justify-center py-8">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-indigo-500"></div>
        </div>
      ) : shotFrames.length === 0 ? (
        <div className="text-center py-8 text-gray-400 text-sm">
          <p>暂无镜头首尾帧</p>
          <p className="text-xs mt-1">进入"镜头拆解"tab，选择镜头后生成首尾帧</p>
        </div>
      ) : (
        <div className="space-y-4">
          {shotFrames.map((shot) => (
            <div key={shot.shot_id} className="border rounded-lg p-3 bg-white">
              <div className="text-sm font-medium text-gray-800 mb-2">
                镜头 {shot.shot_number || `#${shot.shot_id}`}
                {onShotFrameSelect && (
                  <button
                    onClick={() => onShotFrameSelect(shot.frames.first_frames[0] || shot.frames.last_frames[0], shot.shot_id)}
                    className="ml-2 text-xs text-indigo-500 hover:text-indigo-700"
                  >
                    跳转
                  </button>
                )}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <div className="text-xs text-gray-500 mb-1">首帧</div>
                  {shot.frames.first_frames.length > 0 ? (
                    <img
                      src={getAssetFileUrl(shot.frames.first_frames[0].file_path)}
                      alt="首帧"
                      className="w-full h-24 object-cover rounded border cursor-pointer hover:ring-2 hover:ring-indigo-400"
                      onClick={() => { setPreviewAsset(shot.frames.first_frames[0]); setPreviewSection('frame'); }}
                    />
                  ) : (
                    <div className="w-full h-24 bg-gray-100 rounded border flex items-center justify-center text-xs text-gray-400">
                      未生成
                    </div>
                  )}
                </div>
                <div>
                  <div className="text-xs text-gray-500 mb-1">末帧</div>
                  {shot.frames.last_frames.length > 0 ? (
                    <img
                      src={getAssetFileUrl(shot.frames.last_frames[0].file_path)}
                      alt="末帧"
                      className="w-full h-24 object-cover rounded border cursor-pointer hover:ring-2 hover:ring-indigo-400"
                      onClick={() => { setPreviewAsset(shot.frames.last_frames[0]); setPreviewSection('frame'); }}
                    />
                  ) : (
                    <div className="w-full h-24 bg-gray-100 rounded border flex items-center justify-center text-xs text-gray-400">
                      未生成
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <div className="p-4 overflow-y-auto h-full">
      <div className="flex gap-1 mb-4 bg-gray-100 rounded-lg p-1">
        {[
          { key: 'style' as const, label: '风格预设', icon: '🎨' },
          { key: 'characters' as const, label: '角色参考', icon: '👤' },
          { key: 'scenes' as const, label: '场景概念', icon: '🏞' },
          { key: 'frames' as const, label: '镜头帧', icon: '🎬' },
        ].map((section) => (
          <button
            key={section.key}
            onClick={() => setActiveSection(section.key)}
            className={`flex-1 py-2 px-3 text-xs font-medium rounded-md transition-all ${
              activeSection === section.key
                ? 'bg-white text-indigo-700 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {section.icon} {section.label}
          </button>
        ))}
      </div>

      <div className="min-h-0">
        {activeSection === 'style' && renderStyleSection()}
        {activeSection === 'characters' && renderCharacterSection()}
        {activeSection === 'scenes' && renderSceneSection()}
        {activeSection === 'frames' && renderShotFramesSection()}
      </div>

      {/* ── Asset Preview Modal ──────────────────────────────── */}
      {previewAsset && (
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
          onClick={() => { setPreviewAsset(null); setPreviewSection(null); }}
        >
          <div
            className="flex w-[min(900px,90vw)] max-h-[80vh] overflow-hidden rounded-2xl bg-white shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Left: image */}
            <div className="flex-1 bg-gray-900 flex items-center justify-center p-4 min-h-[300px]">
              {getAssetFileUrl(previewAsset.file_path) ? (
                <img
                  src={getAssetFileUrl(previewAsset.file_path)}
                  alt={previewAsset.name}
                  className="max-w-full max-h-[65vh] object-contain rounded-lg"
                />
              ) : (
                <div className="text-white/60 text-sm">图片加载中...</div>
              )}
            </div>
            {/* Right: details + actions */}
            <div className="w-72 border-l border-gray-200 p-4 overflow-y-auto bg-white">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-gray-900 truncate">{previewAsset.name}</h3>
                <button
                  onClick={() => { setPreviewAsset(null); setPreviewSection(null); }}
                  className="text-gray-400 hover:text-gray-600"
                >
                  ✕
                </button>
              </div>

              {previewSection === 'character' && (
                <div className="space-y-3">
                  {previewAsset.prompt && (
                    <div>
                      <div className="text-xs font-medium text-gray-600 mb-1">提示词</div>
                      <div className="text-xs text-gray-700 whitespace-pre-wrap leading-5 bg-gray-50 rounded p-2">
                        {previewAsset.prompt}
                      </div>
                    </div>
                  )}
                  <div className="text-xs text-gray-500">
                    风格: {previewAsset.style_preset || '默认'}
                  </div>
                  {onCharacterSelect && (
                    <button
                      onClick={() => { onCharacterSelect(previewAsset); setPreviewAsset(null); }}
                      className="w-full rounded-lg bg-indigo-600 px-3 py-2 text-xs font-medium text-white hover:bg-indigo-700"
                    >
                      用作镜头参考
                    </button>
                  )}
                </div>
              )}

              {previewSection === 'scene' && (
                <div className="space-y-3">
                  {previewAsset.prompt && (
                    <div>
                      <div className="text-xs font-medium text-gray-600 mb-1">提示词</div>
                      <div className="text-xs text-gray-700 whitespace-pre-wrap leading-5 bg-gray-50 rounded p-2">
                        {previewAsset.prompt}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {previewSection === 'frame' && (
                <div className="space-y-3">
                  <div className="text-xs text-gray-500">
                    {previewAsset.asset_subtype === 'first_frame' ? '首帧' : '末帧'}
                    {previewAsset.revision && ` (v${previewAsset.revision})`}
                  </div>
                  {previewAsset.prompt && (
                    <div>
                      <div className="text-xs font-medium text-gray-600 mb-1">生成提示</div>
                      <div className="text-xs text-gray-700 whitespace-pre-wrap leading-5 bg-gray-50 rounded p-2">
                        {previewAsset.prompt}
                      </div>
                    </div>
                  )}
                  {onShotFrameSelect && previewAsset.shot_id && (
                    <button
                      onClick={() => { onShotFrameSelect(previewAsset, previewAsset.shot_id); setPreviewAsset(null); }}
                      className="w-full rounded-lg bg-indigo-600 px-3 py-2 text-xs font-medium text-white hover:bg-indigo-700"
                    >
                      跳转到镜头
                    </button>
                  )}
                </div>
              )}

              <button
                onClick={() => { setPreviewAsset(null); setPreviewSection(null); }}
                className="w-full mt-3 rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium text-gray-600 hover:bg-gray-50"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AssetManagementPanel;
