import { useEffect, useState } from 'react';

/**
 * 响应式断点标准（与改造方案一致）
 * - Mobile:  <768px
 * - Tablet:  768–1199px
 * - Desktop: ≥1200px
 */
export const BREAKPOINTS = {
  /** 移动端最大宽度（Mobile: <768px） */
  mobile: 768,
  /** 桌面端最小宽度（Desktop: ≥1200px） */
  desktop: 1200,
} as const;

export type DeviceMode = 'mobile' | 'tablet' | 'desktop';

/**
 * 订阅 CSS 媒体查询（SSR 安全，默认返回 fallback 值）
 * @param query CSS 媒体查询字符串
 * @param fallback 服务端渲染或初始阶段的值
 */
export function useMediaQuery(query: string, fallback = false): boolean {
  const [matches, setMatches] = useState<boolean>(() => {
    if (typeof window === 'undefined') return fallback;
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mediaQueryList = window.matchMedia(query);
    const handler = (event: MediaQueryListEvent) => setMatches(event.matches);
    // 处理初始状态（可能已变化）
    setMatches(mediaQueryList.matches);
    mediaQueryList.addEventListener('change', handler);
    return () => mediaQueryList.removeEventListener('change', handler);
  }, [query]);

  return matches;
}

/** 是否为移动端（<768px） */
export function useIsMobile(): boolean {
  return useMediaQuery(`(max-width: ${BREAKPOINTS.mobile - 1}px)`);
}

/** 是否为平板端（768–1199px） */
export function useIsTablet(): boolean {
  return useMediaQuery(
    `(min-width: ${BREAKPOINTS.mobile}px) and (max-width: ${BREAKPOINTS.desktop - 1}px)`,
  );
}

/** 是否为桌面端（≥1200px） */
export function useIsDesktop(): boolean {
  return useMediaQuery(`(min-width: ${BREAKPOINTS.desktop}px)`);
}

/** 当前设备模式（mobile / tablet / desktop），用于三套 App Shell 切换 */
export function useDeviceMode(): DeviceMode {
  const isMobile = useIsMobile();
  const isTablet = useIsTablet();
  if (isMobile) return 'mobile';
  if (isTablet) return 'tablet';
  return 'desktop';
}

/** 是否为触摸设备（支持 hover 能力较弱时返回 true，用于隐藏仅 hover 可发现的操作） */
export function useIsTouchDevice(): boolean {
  return useMediaQuery('(hover: none), (pointer: coarse)');
}

/**
 * 订阅软键盘弹出导致的视觉视口高度变化。
 * 返回当前视觉视口高度（px）；不支持 visualViewport 时返回 window.innerHeight。
 * 用于保证软键盘弹出时输入框与提交按钮保持可见。
 */
export function useVisualViewportHeight(): number {
  const [height, setHeight] = useState<number>(() =>
    typeof window === 'undefined' ? 0 : window.visualViewport?.height ?? window.innerHeight,
  );

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const update = () => setHeight(window.visualViewport?.height ?? window.innerHeight);
    update();
    const viewport = window.visualViewport;
    if (viewport) {
      viewport.addEventListener('resize', update);
      viewport.addEventListener('scroll', update);
      return () => {
        viewport.removeEventListener('resize', update);
        viewport.removeEventListener('scroll', update);
      };
    }
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  return height;
}
