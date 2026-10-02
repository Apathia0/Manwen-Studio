import StyleChip from './StyleChip';
import type { CanvasStyle } from './canvasStyle';

interface Props {
  style: CanvasStyle | null;
  onPick: () => void;
  onToggle: (enabled: boolean) => void;
  compact?: boolean;
}

/** 画风控制：当前画风 + 全局开关。开关关闭后保留所选风格，节点各自的风格设置不受影响。 */
export default function StyleControl({ style, onPick, onToggle, compact = true }: Props) {
  const enabled = Boolean(style?.enabled);
  return (
    <span className="compact-controls inline-flex items-center gap-1.5">
      <StyleChip style={style} onClick={onPick} compact={compact} />
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label="全局画风开关"
        disabled={!style}
        onClick={() => onToggle(!enabled)}
        title={!style ? '先选择一个画风' : enabled ? '全局画风已开启：未单独设置风格的资产、分镜和视频都会使用它。点击关闭。' : '全局画风已关闭：所选风格保留，但不会应用。点击开启。'}
        className={`relative h-4 w-7 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${enabled ? 'bg-[#73a7ff]' : 'bg-[#4a4540]'}`}
      >
        <span className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${enabled ? 'left-[14px]' : 'left-0.5'}`} />
      </button>
    </span>
  );
}
