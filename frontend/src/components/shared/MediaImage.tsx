import { useEffect, useState, type MouseEvent } from 'react';

interface MediaImageProps {
  src: string;
  alt: string;
  className?: string;
  priority?: boolean;
  onClick?: (event: MouseEvent<HTMLImageElement>) => void;
}

/**
 * 统一图片回显组件。
 *
 * 规范：所有用户生成图片（漫画图、故事版、画布结果、角色卡、资产、封面等）必须经过
 * 本组件渲染，**加载完成后整体渲染**——`img.decode()` 完成后才显示（opacity 淡入），
 * 避免浏览器渐进式一帧一帧渲染。失败时保持隐藏并显示灰色占位。
 *
 * 占位采用 img 自身背景（不依赖父容器 relative），可安全替换任意裸 `<img>`。
 */
export default function MediaImage({ src, alt, className = '', priority = false, onClick }: MediaImageProps) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setLoaded(false);
    setFailed(false);
  }, [src]);

  const handleLoad = (event: React.SyntheticEvent<HTMLImageElement>) => {
    const image = event.currentTarget;
    const finish = () => setLoaded(true);
    if (typeof image.decode === 'function') {
      void image.decode().catch(() => undefined).finally(finish);
    } else {
      finish();
    }
  };

  return (
    <img
      src={src}
      alt={alt}
      onClick={onClick}
      className={`${className} transition-opacity duration-200 ${loaded ? 'opacity-100' : 'opacity-0'} ${!loaded && !failed ? 'bg-slate-200/70 animate-pulse' : ''}`}
      loading={priority ? 'eager' : 'lazy'}
      decoding={priority ? 'sync' : 'async'}
      onLoad={handleLoad}
      onError={() => setFailed(true)}
    />
  );
}