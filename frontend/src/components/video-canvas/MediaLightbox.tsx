import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, X } from 'lucide-react';
import { useProgressiveImage } from '../../lib/useProgressiveImage';

interface Props {
  url: string;
  isVideo?: boolean;
  title?: string;
  onClose: () => void;
}

/** 大图/视频预览：点击遮罩、右上角关闭或按 Esc 退出。渲染到 body，层级高于画布上所有浮层。
 *  图片先显示 1280 宽预览（通常已被节点缩略图预热），原图解码完成后无缝替换，避免点开后长时间空白。 */
export default function MediaLightbox({ url, isVideo = false, title, onClose }: Props) {
  const preview = useProgressiveImage(isVideo ? null : url, 1280);
  const full = useProgressiveImage(isVideo ? null : url, null);
  const imageSrc = full.src ?? preview.src;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return createPortal(
    <div role="dialog" aria-modal="true" aria-label={title || '预览'} className="fixed inset-0 z-[200] flex items-center justify-center bg-black/80 p-6 backdrop-blur-sm" onClick={onClose}>
      <button type="button" aria-label="关闭预览" onClick={onClose} className="absolute right-4 top-4 rounded-full bg-white/10 p-2 text-white hover:bg-white/20"><X className="h-5 w-5" /></button>
      {isVideo
        ? <video src={url} controls autoPlay disablePictureInPicture disableRemotePlayback className="max-h-full max-w-full rounded-lg" onClick={(event) => event.stopPropagation()} />
        : imageSrc
          ? <img src={imageSrc} alt={title || '预览'} className="max-h-full max-w-full rounded-lg object-contain shadow-2xl" onClick={(event) => event.stopPropagation()} />
          : full.failed && preview.failed
            ? <div className="rounded-lg bg-black/60 px-4 py-3 text-sm text-white/80" onClick={(event) => event.stopPropagation()}>图片加载失败</div>
            : <Loader2 className="h-8 w-8 animate-spin text-white/70" />}
      {title && <div className="pointer-events-none absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-black/60 px-3 py-1 text-xs text-white/80">{title}</div>}
    </div>,
    document.body,
  );
}
