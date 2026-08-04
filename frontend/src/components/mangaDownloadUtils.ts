export interface MangaDownloadSource {
  image_path: string;
}

/** 判断图片是否为可由浏览器直接请求的 HTTP/HTTPS 远程资源。 */
export function isRemoteMangaImagePath(imagePath: string): boolean {
  try {
    const url = new URL(String(imagePath || '').trim());
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}

/** 只有全部图片均为远程资源时才使用浏览器本地打包。 */
export function shouldUseBrowserMangaZip(images: MangaDownloadSource[]): boolean {
  return images.length > 0 && images.every((image) => isRemoteMangaImagePath(image.image_path));
}
