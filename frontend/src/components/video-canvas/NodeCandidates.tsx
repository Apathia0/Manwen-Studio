import { useEffect, useState } from 'react';
import { Check } from 'lucide-react';
import { listVideoCanvasNodeCandidates, type CanvasNodeCandidate } from '../../api';
import MediaImage from '../shared/MediaImage';

interface Props {
  canvasId: number;
  nodeId: string;
  isVideo: boolean;
  /** 运行状态变化时刷新候选列表 */
  refreshKey: string;
  /** 节点当前实际使用的素材：以浏览器里的为准。服务端只按“已保存的画布”标记当前项，刚切换、还没保存时会是旧的 */
  currentAssetId?: number | null;
  onPick: (candidate: CanvasNodeCandidate) => void;
}

/** 节点属性面板中的候选结果：历史结果一键切换，或再生成一个新的候选。 */
export default function NodeCandidates({ canvasId, nodeId, isVideo, refreshKey, currentAssetId = null, onPick }: Props) {
  const [candidates, setCandidates] = useState<CanvasNodeCandidate[]>([]);

  useEffect(() => {
    let active = true;
    listVideoCanvasNodeCandidates(canvasId, nodeId).then((result) => { if (active) setCandidates(result.candidates); }).catch(() => { if (active) setCandidates([]); });
    return () => { active = false; };
  }, [canvasId, nodeId, refreshKey]);

  if (candidates.length === 0) return null;
  return (
    <div className="compact-controls mt-3 border-t border-[#3b3734] pt-3">
      <div className="mb-2 text-[11px] text-[#8f8984]">候选结果（{candidates.length}）· 点击切换。要再生成一个，点输入框右下角的生成键</div>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {candidates.map((candidate) => {
          const isCurrent = currentAssetId !== null ? candidate.asset_id === currentAssetId : candidate.is_current;
          return (
          <button key={candidate.asset_id} type="button" title={`${candidate.created_at ? new Date(candidate.created_at).toLocaleString() : '历史结果'}${isCurrent ? '（当前使用）' : '（点击切换到这个结果）'}`} onClick={() => !isCurrent && onPick(candidate)}
            className={`relative h-16 w-24 shrink-0 cursor-pointer overflow-hidden rounded-md border ${isCurrent ? 'border-[#73a7ff]' : 'border-[#3b3734] hover:border-[#7d756e]'}`}>
            {isVideo
              ? <video src={candidate.url} muted preload="metadata" disablePictureInPicture disableRemotePlayback tabIndex={-1} className="pointer-events-none h-full w-full object-cover" />
              : <MediaImage src={candidate.url} alt="候选结果" className="h-full w-full object-cover" />}
            {isCurrent && <span className="absolute right-1 top-1 grid h-4 w-4 place-items-center rounded-full bg-[#73a7ff] text-[#111827]"><Check className="h-3 w-3" /></span>}
          </button>
          );
        })}
      </div>
    </div>
  );
}
