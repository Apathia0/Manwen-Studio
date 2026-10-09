/**
 * 图片衍生版本（缩略图）URL 工具。
 *
 * 后端对本站 /static/manga、/static/video 下的图片支持 `?w=<宽度>` 返回 WebP 缩略图，
 * 宽度只允许下面的白名单档位。外部图片（OSS 外链等）不处理，原样返回。
 */

export const MEDIA_WIDTHS = [96, 240, 480, 720, 1280, 1920] as const;
export type MediaWidth = (typeof MEDIA_WIDTHS)[number];

const LOCAL_IMAGE_RE = /^(\/static\/(?:manga|video)\/[^?#]+\.(?:png|jpe?g|webp))$/i;

/** 取出同源的本站静态图片路径；不是本站图片、或已经带查询参数返回 null */
function localImagePath(url: string): string | null {
  if (!url || url.startsWith('data:') || url.startsWith('blob:')) return null;
  let path = url;
  if (/^https?:\/\//i.test(url)) {
    try {
      const parsed = new URL(url);
      if (typeof window === 'undefined' || parsed.origin !== window.location.origin) return null;
      if (parsed.search || parsed.hash) return null;
      path = parsed.pathname;
    } catch {
      return null;
    }
  }
  return LOCAL_IMAGE_RE.test(path) ? path : null;
}

/** 返回指定宽度的缩略图 URL；无法生成衍生版本时返回原 URL */
export function mediaVariantUrl(url: string, width: MediaWidth): string {
  const path = localImagePath(url);
  return path ? `${path}?w=${width}` : url;
}

/** 按显示宽度（CSS 像素）选择档位：考虑设备像素比（最多按 2 倍），取不小于需求的最小档位 */
export function pickMediaWidth(cssWidth: number): MediaWidth {
  const ratio = typeof window === 'undefined' ? 1 : Math.min(window.devicePixelRatio || 1, 2);
  const need = Math.max(1, cssWidth) * ratio;
  return MEDIA_WIDTHS.find((width) => width >= need) ?? MEDIA_WIDTHS[MEDIA_WIDTHS.length - 1];
}

/**
 * 依次尝试的图片来源：缩略图 → 原图 → 带随机参数的原图（绕过可能被缓存的失败响应）。
 * 缩略图失败（旧后端、转换失败）自动退回原图，保证回显不会因衍生版本而变差。
 */
export function buildImageSources(url: string, width?: MediaWidth | null): string[] {
  if (!url) return [];
  const variant = width ? mediaVariantUrl(url, width) : url;
  const retry = `${url}${url.includes('?') ? '&' : '?'}_r=${Date.now()}`;
  return Array.from(new Set(variant === url ? [url, retry] : [variant, url, retry]));
}
