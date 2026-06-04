import { ref } from 'vue'

export function useImagePicker() {
  const loading = ref(false)

  function chooseImage(options?: { count?: number; sourceType?: string[] }): Promise<string[]> {
    return new Promise((resolve) => {
      let settled = false

      function finish(paths: string[]) {
        if (settled) return
        settled = true
        resolve(paths)
      }

      uni.chooseImage({
        count: options?.count || 1,
        sourceType: (options?.sourceType as any) || ['album', 'camera'],
        sizeType: ['compressed'],
        success: (res) => {
          finish(res.tempFilePaths as string[])
        },
        fail: () => {
          // 用户取消或任何失败，都视为空结果
          finish([])
        }
      })

      // H5 等平台取消选择时可能不触发任何回调，超时兜底
      setTimeout(() => finish([]), 3000)
    })
  }

  function imageToBase64(filePath: string): Promise<string> {
    return new Promise((resolve, reject) => {
      uni.getFileSystemManager().readFile({
        filePath,
        encoding: 'base64',
        success: (res) => {
          resolve(`data:image/jpeg;base64,${res.data}`)
        },
        fail: (err) => {
          reject(new Error(err.errMsg))
        }
      })
    })
  }

  async function chooseAndConvert(options?: { count?: number }): Promise<string[]> {
    loading.value = true
    try {
      const paths = await chooseImage(options)
      const base64List = await Promise.all(paths.map(imageToBase64))
      return base64List
    } finally {
      loading.value = false
    }
  }

  return {
    loading,
    chooseImage,
    imageToBase64,
    chooseAndConvert
  }
}
