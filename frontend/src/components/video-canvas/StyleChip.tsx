import { Palette } from 'lucide-react';
import MediaImage from '../shared/MediaImage';
import { styleDisplay, type CanvasStyle } from './canvasStyle';

interface Props {
  style: CanvasStyle | null;
  onClick: () => void;
  /** 紧凑样式用于进度条与面板标题行 */
  compact?: boolean;
}

/** 画布风格标识：缩略图 + 名称；没选风格时用琥珀色提醒，点击打开风格选择。 */
export default function StyleChip({ style, onClick, compact = false }: Props) {
  const { name, imageUrl, enabled } = styleDisplay(style);
  return (
    <button
      type="button"
      onClick={onClick}
      title={style ? '更换整张画布的画风（未单独设置风格的资产、分镜和视频都会使用它）' : '还没有选择画风：不同图片的画风可能不一致，点击选择'}
      className={`inline-flex items-center gap-1.5 rounded-md border ${compact ? 'px-1.5 py-0.5 text-[11px]' : 'px-2 py-1 text-xs'} ${style ? (enabled ? 'border-[#4a4540] text-[#e1ddd9] hover:border-[#73a7ff]' : 'border-[#393633] text-[#7d756e] hover:border-[#73a7ff]') : 'border-amber-400/50 bg-amber-400/10 text-amber-200 hover:bg-amber-400/20'}`}
    >
      {imageUrl
        ? <span className={`h-4 w-4 shrink-0 overflow-hidden rounded ${style && !enabled ? 'opacity-40 grayscale' : ''}`}><MediaImage src={imageUrl} alt={name} width={96} className="h-full w-full object-cover" /></span>
        : <Palette className="h-3.5 w-3.5 shrink-0" />}
      <span className="max-w-[9rem] truncate">画风：{name}{style && !enabled && '（已关闭）'}</span>
    </button>
  );
}
