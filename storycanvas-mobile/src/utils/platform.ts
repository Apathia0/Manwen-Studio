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
  // H5 的浏览器工具栏位于页面视口之外，不应作为应用状态栏重复占位
  // #ifdef H5
  return 0
  // #endif

  // #ifndef H5
  const systemInfo = uni.getSystemInfoSync()
  return systemInfo.statusBarHeight || 0
  // #endif
}

export function getSafeAreaBottom(): number {
  const systemInfo = uni.getSystemInfoSync()
  return systemInfo.safeAreaInsets?.bottom || 0
}

export function getPlatform(): string {
  const systemInfo = uni.getSystemInfoSync()
  return systemInfo.platform
}
