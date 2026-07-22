import { useEffect, useState } from 'react';

interface MediaImageProps {
  src: string;
  alt: string;
  className?: string;
  priority?: boolean;
}

export default function MediaImage({ src, alt, className = '', priority = false }: MediaImageProps) {
  const [loadedSrc, setLoadedSrc] = useState('');
  const [failedSrc, setFailedSrc] = useState('');
  const loaded = loadedSrc === src;
  const failed = failedSrc === src;

  useEffect(() => {
    setLoadedSrc('');
    setFailedSrc('');
  }, [src]);

  return (
    <>
      {!loaded && !failed ? <span aria-hidden="true" className="absolute inset-0 animate-pulse bg-slate-200/70" /> : null}
      <img
        src={src}
        alt={alt}
        className={`${className} transition-opacity duration-200 ${loaded ? 'opacity-100' : 'opacity-0'}`}
        loading={priority ? 'eager' : 'lazy'}
        decoding={priority ? 'sync' : 'async'}
        onLoad={() => setLoadedSrc(src)}
        onError={() => setFailedSrc(src)}
      />
      {failed ? <span className="absolute inset-0 grid place-items-center bg-slate-100 text-xs text-slate-400">图片加载失败</span> : null}
    </>
  );
}
