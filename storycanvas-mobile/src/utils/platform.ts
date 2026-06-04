export function isWeixin(): boolean {
  // #ifdef MP-WEIXIN
  return true
  // #endif
  // #ifndef MP-WEIXIN
  return false
  // #endif
}

export function isApp(): boolean {
  // #ifdef APP-PLUS
  return true
  // #endif
  // #ifndef APP-PLUS
  return false
  // #endif
}

export function isH5(): boolean {
  // #ifdef H5
  return true
  // #endif
  // #ifndef H5
  return false
  // #endif
}

export function getStatusBarHeight(): number {
  const systemInfo = uni.getSystemInfoSync()
  return systemInfo.statusBarHeight || 0
}

export function getSafeAreaBottom(): number {
  const systemInfo = uni.getSystemInfoSync()
  return systemInfo.safeAreaInsets?.bottom || 0
}

export function getPlatform(): string {
  const systemInfo = uni.getSystemInfoSync()
  return systemInfo.platform
}
