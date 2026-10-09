import { useEffect, useMemo, useState } from 'react';
import { buildImageSources, type MediaWidth } from './mediaVariant';

export interface ProgressiveImage {
  /** 已解码完成、可以直接显示的地址；尚未就绪为 null */
  src: string | null;
  /** 所有来源都失败且没有任何可显示的图片 */
  failed: boolean;
  /** 手动重试（失败态点击重试） */
  retry: () => void;
  /** 当前显示图片的自然尺寸（缩略图保持原图宽高比） */
  naturalSize: { width: number; height: number } | null;
}

/**
 * 画布节点图片加载：用 `new Image()` 预加载并 decode，完成后才切换到 `src`。
 * - 切换前一直保留上一张已显示的图片：重新生成、放大换更高清档位时不会闪回深色占位；
 * - 缩略图失败自动退回原图，再失败带随机参数重试一次（最后一次延迟 1.5 秒）；
 * - `enabled` 为 false 时不发起请求（用于视口外节点的懒加载）。
 */
export function useProgressiveImage(url: string | null | undefined, width: MediaWidth | null, enabled = true): ProgressiveImage {
  const sources = useMemo(() => buildImageSources(url || '', width), [url, width]);
  const sourceKey = sources.join('|');
  const [attempt, setAttempt] = useState(0);
  const [shown, setShown] = useState<{ src: string; width: number; height: number } | null>(null);
  const [exhausted, setExhausted] = useState(false);
  const [manualRetry, setManualRetry] = useState(0);

  // 来源变化（换图或换档位）时从头尝试；已显示的图片保留到新图就绪
  useEffect(() => {
    setAttempt(0);
    setExhausted(false);
  }, [sourceKey, manualRetry]);

  const target = enabled ? sources[Math.min(attempt, sources.length - 1)] : undefined;

  useEffect(() => {
    if (!target) return undefined;
    let cancelled = false;
    let timer: number | undefined;
    const image = new Image();
    image.decoding = 'async';
    image.onload = () => {
      const finish = () => {
        if (!cancelled) setShown({ src: target, width: image.naturalWidth, height: image.naturalHeight });
      };
      if (typeof image.decode === 'function') void image.decode().catch(() => undefined).finally(finish);
      else finish();
    };
    image.onerror = () => {
      if (cancelled) return;
      if (attempt + 1 < sources.length) {
        const isLast = attempt + 2 >= sources.length;
        if (isLast) timer = window.setTimeout(() => { if (!cancelled) setAttempt((value) => value + 1); }, 1500);
        else setAttempt((value) => value + 1);
      } else {
        setExhausted(true);
      }
    };
    image.src = target;
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
      image.onload = null;
      image.onerror = null;
    };
  }, [target, attempt, sources.length]);

  // 当前显示的图片必须属于当前 url（换图后旧图仅作过渡，不能影响失败判断）
  return {
    src: shown?.src ?? null,
    failed: exhausted && !shown,
    retry: () => setManualRetry((value) => value + 1),
    naturalSize: shown ? { width: shown.width, height: shown.height } : null,
  };
}
