import { useEffect, useMemo, useState, type MouseEvent } from 'react';
import { buildImageSources, type MediaWidth } from '../../lib/mediaVariant';

interface MediaImageProps {
  src: string;
  alt: string;
  className?: string;
  priority?: boolean;
  /** 显示宽度档位：本站生成图按该宽度请求 WebP 缩略图，失败自动退回原图；不传则加载原图 */
  width?: MediaWidth;
  onClick?: (event: MouseEvent<HTMLImageElement>) => void;
}

/**
 * 统一图片回显组件。
 *
 * 规范：所有用户生成图片（漫画图、故事版、画布结果、角色卡、资产、封面等）必须经过
 * 本组件渲染，**加载完成后整体渲染**——`img.decode()` 完成后才显示（opacity 淡入），
 * 避免浏览器渐进式一帧一帧渲染。失败时保持隐藏并显示灰色占位。
 *
 * 加载失败会依次退回：缩略图 → 原图 → 带随机参数的原图（最后一次延迟 1.5 秒），仍失败才显示灰色占位。
 * 占位采用 img 自身背景（不依赖父容器 relative），可安全替换任意裸 `<img>`。
 */
export default function MediaImage({ src, alt, className = '', priority = false, width, onClick }: MediaImageProps) {
  const sources = useMemo(() => buildImageSources(src, width), [src, width]);
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setAttempt(0);
    setLoaded(false);
    setFailed(false);
  }, [sources]);

  const handleLoad = (event: React.SyntheticEvent<HTMLImageElement>) => {
    const image = event.currentTarget;
    const finish = () => setLoaded(true);
    if (typeof image.decode === 'function') {
      void image.decode().catch(() => undefined).finally(finish);
    } else {
      finish();
    }
  };

  const handleError = () => {
    if (attempt + 1 >= sources.length) {
      setFailed(true);
      return;
    }
    // 最后一次重试延迟发起，避开瞬时的网络/后端抖动
    if (attempt + 2 >= sources.length) window.setTimeout(() => setAttempt((value) => value + 1), 1500);
    else setAttempt((value) => value + 1);
  };

  return (
    <img
      src={sources[Math.min(attempt, sources.length - 1)] || src}
      alt={alt}
      onClick={onClick}
      className={`${className} transition-opacity duration-200 ${loaded ? 'opacity-100' : 'opacity-0'} ${!loaded && !failed ? 'bg-slate-200/70 animate-pulse' : ''}`}
      loading={priority ? 'eager' : 'lazy'}
      decoding={priority ? 'sync' : 'async'}
      onLoad={handleLoad}
      onError={handleError}
    />
  );
}
