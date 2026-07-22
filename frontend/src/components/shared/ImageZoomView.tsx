import { useRef, useState, useCallback, useEffect, type CSSProperties, type ReactNode } from 'react';
import { RotateCcw, Download } from 'lucide-react';

interface ImageZoomViewProps {
  src: string;
  alt?: string;
  className?: string;
  style?: CSSProperties;
  maxZoom?: number;
  fallback?: ReactNode;
  onZoomChange?: (zoom: number) => void;
  onLoadError?: () => void;
}

export default function ImageZoomView({
  src,
  alt = '',
  className = '',
  style,
  maxZoom = 5,
  fallback,
  onZoomChange,
  onLoadError,
}: ImageZoomViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const fitZoomRef = useRef(1);
  const [fitZoom, setFitZoom] = useState(1);

  const [zoom, setZoom] = useState(1);
  const [translateX, setTranslateX] = useState(0);
  const [translateY, setTranslateY] = useState(0);

  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef({ x: 0, y: 0, translateX: 0, translateY: 0 });

  const [imgStatus, setImgStatus] = useState<'loading' | 'loaded' | 'error'>('loading');

  const lastTouchDistanceRef = useRef<number | null>(null);

  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);

  const isModified = Math.abs(zoom - fitZoom) > 0.01 || translateX !== 0 || translateY !== 0;

  useEffect(() => {
    onZoomChange?.(zoom);
  }, [zoom, onZoomChange]);

  const clampTranslate = useCallback(
    (tx: number, ty: number) => {
      const container = containerRef.current;
      if (!container) return { x: tx, y: ty };
      const rect = container.getBoundingClientRect();
      const maxX = rect.width * 0.8;
      const maxY = rect.height * 0.8;
      return {
        x: Math.max(-maxX, Math.min(maxX, tx)),
        y: Math.max(-maxY, Math.min(maxY, ty)),
      };
    },
    []
  );

  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      setZoom((prev) => Math.max(fitZoomRef.current, Math.min(maxZoom, prev * delta)));
    },
    [maxZoom]
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (e.button !== 0) return;
      if ((e.target as HTMLElement).tagName === 'CANVAS') return;
      e.preventDefault();
      setIsDragging(true);
      dragStartRef.current = {
        x: e.clientX,
        y: e.clientY,
        translateX,
        translateY,
      };
    },
    [translateX, translateY]
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!isDragging) return;
      e.preventDefault();
      const dx = e.clientX - dragStartRef.current.x;
      const dy = e.clientY - dragStartRef.current.y;
      const newX = dragStartRef.current.translateX + dx;
      const newY = dragStartRef.current.translateY + dy;
      const clamped = clampTranslate(newX, newY);
      setTranslateX(clamped.x);
      setTranslateY(clamped.y);
    },
    [isDragging, clampTranslate]
  );

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleReset = useCallback(() => {
    setZoom(fitZoomRef.current);
    setTranslateX(0);
    setTranslateY(0);
  }, []);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (e.touches.length === 2) {
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      lastTouchDistanceRef.current = Math.sqrt(dx * dx + dy * dy);
    } else if (e.touches.length === 1) {
      setIsDragging(true);
      dragStartRef.current = {
        x: e.touches[0].clientX,
        y: e.touches[0].clientY,
        translateX,
        translateY,
      };
    }
  }, [translateX, translateY]);

  const handleTouchMove = useCallback(
    (e: React.TouchEvent) => {
      if (e.touches.length === 2 && lastTouchDistanceRef.current !== null) {
        e.preventDefault();
        const dx = e.touches[0].clientX - e.touches[1].clientX;
        const dy = e.touches[0].clientY - e.touches[1].clientY;
        const distance = Math.sqrt(dx * dx + dy * dy);
        const scale = distance / lastTouchDistanceRef.current;
        lastTouchDistanceRef.current = distance;
        setZoom((prev) => Math.max(fitZoomRef.current, Math.min(maxZoom, prev * scale)));
      } else if (e.touches.length === 1 && isDragging) {
        e.preventDefault();
        const dx = e.touches[0].clientX - dragStartRef.current.x;
        const dy = e.touches[0].clientY - dragStartRef.current.y;
        const newX = dragStartRef.current.translateX + dx;
        const newY = dragStartRef.current.translateY + dy;
        const clamped = clampTranslate(newX, newY);
        setTranslateX(clamped.x);
        setTranslateY(clamped.y);
      }
    },
    [isDragging, maxZoom, clampTranslate]
  );

  const handleTouchEnd = useCallback(() => {
    setIsDragging(false);
    lastTouchDistanceRef.current = null;
  }, []);

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY });
  }, []);

  const handleDownload = useCallback(() => {
    window.open(src, '_blank');
    setContextMenu(null);
  }, [src]);

  // 右键菜单外点关闭
  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    window.addEventListener('click', close);
    return () => window.removeEventListener('click', close);
  }, [contextMenu]);

  const handleImageLoad = useCallback(() => {
    const img = imgRef.current;
    const container = containerRef.current;
    if (!img || !container) return;

    const imgNaturalW = img.naturalWidth;
    const imgNaturalH = img.naturalHeight;
    const containerRect = container.getBoundingClientRect();
    const containerW = containerRect.width;
    const containerH = containerRect.height;

    if (imgNaturalW > 0 && imgNaturalH > 0 && containerW > 0 && containerH > 0) {
      const scaleX = containerW / imgNaturalW;
      const scaleY = containerH / imgNaturalH;
      const fitZoom = Math.min(scaleX, scaleY, 1);
      fitZoomRef.current = fitZoom;
      setFitZoom(fitZoom);
      setZoom(fitZoom);
    }

    setImgStatus('loaded');
  }, []);

  const handleImageError = useCallback(() => {
    setImgStatus('error');
    onLoadError?.();
  }, [onLoadError]);

  useEffect(() => {
    setImgStatus('loading');
    fitZoomRef.current = 1;
    setFitZoom(1);
    setZoom(1);
    setTranslateX(0);
    setTranslateY(0);
  }, [src]);

  return (
    <div
      ref={containerRef}
      className={`relative select-none overflow-hidden ${isDragging ? 'cursor-grabbing' : 'cursor-grab'} ${className}`}
      style={{ touchAction: 'none', ...style }}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
      onContextMenu={handleContextMenu}
    >
      {imgStatus !== 'error' && (
        <img
          ref={imgRef}
          src={src}
          alt={alt}
          draggable={false}
          onLoad={handleImageLoad}
          onError={handleImageError}
          className="pointer-events-none absolute left-1/2 top-1/2 h-auto max-w-none"
          style={{
            transform: `translate(-50%, -50%) translate(${translateX}px, ${translateY}px) scale(${zoom})`,
            transition: isDragging ? 'none' : 'transform 0.15s ease-out',
            opacity: imgStatus === 'loaded' ? 1 : 0,
          }}
        />
      )}

      {isModified && (
        <button
          type="button"
          onClick={handleReset}
          className="absolute right-3 top-3 z-10 flex items-center gap-1.5 rounded-full bg-black/60 px-3 py-1.5 text-xs text-white backdrop-blur-sm transition hover:bg-black/80"
        >
          <RotateCcw size={12} />
          重置
        </button>
      )}

      {imgStatus === 'loading' && (
        <div className="absolute inset-0 flex items-center justify-center">
          {fallback || <div className="text-sm text-white/50">加载中...</div>}
        </div>
      )}

      {imgStatus === 'error' && (
        <div className="absolute inset-0 flex items-center justify-center">
          {fallback || <div className="text-sm text-white/50">图片加载失败</div>}
        </div>
      )}

      {contextMenu && (
        <div
          className="fixed z-[100] min-w-[140px] overflow-hidden rounded-xl border border-white/10 bg-[#1e293b] py-1 shadow-2xl backdrop-blur-xl"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            type="button"
            onClick={handleDownload}
            className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm text-white/90 transition hover:bg-white/10"
          >
            <Download size={14} />
            下载图片
          </button>
        </div>
      )}
    </div>
  );
}
