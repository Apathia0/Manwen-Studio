import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

interface Props {
  url: string;
  isVideo?: boolean;
  title?: string;
  onClose: () => void;
}

/** 大图/视频预览：点击遮罩、右上角关闭或按 Esc 退出。渲染到 body，层级高于画布上所有浮层。 */
export default function MediaLightbox({ url, isVideo = false, title, onClose }: Props) {
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
        : <img src={url} alt={title || '预览'} className="max-h-full max-w-full rounded-lg object-contain shadow-2xl" onClick={(event) => event.stopPropagation()} />}
      {title && <div className="pointer-events-none absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-black/60 px-3 py-1 text-xs text-white/80">{title}</div>}
    </div>,
    document.body,
  );
}
