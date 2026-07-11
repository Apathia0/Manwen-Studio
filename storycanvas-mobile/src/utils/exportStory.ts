import { storiesApi, chaptersApi } from '@/api'
import type { Story, Chapter } from '@/api/types'

export interface ExportData {
  version: number
  exported_at: string
  story: {
    title: string
    description: string
    tags: Record<string, any>
    characters: any[]
    outline: Record<string, any>
    story_bible: Record<string, any> | null
  }
  chapters: {
    chapter_number: number
    title: string
    act: string | null
    status: string
    novel_content: string | null
    key_events: any[]
    word_count: number | null
    quality_score: Record<string, number> | null
  }[]
}

/**
 * 导出故事数据为 JSON 文件
 * 在移动端通过 uni.saveFile 保存，或通过分享功能发送
 */
export async function exportStory(storyId: number): Promise<string> {
  // 获取故事详情和章节列表
  const [story, chapters] = await Promise.all([
    storiesApi.getStory(storyId),
    chaptersApi.getChapters(storyId),
  ])

  const exportData: ExportData = {
    version: 1,
    exported_at: new Date().toISOString(),
    story: {
      title: story.title || '未命名作品',
      description: story.description || '',
      tags: story.tags || {},
      characters: story.characters || [],
      outline: story.outline || {},
      story_bible: story.story_bible || null,
    },
    chapters: chapters.map(ch => ({
      chapter_number: ch.chapter_number,
      title: ch.title || '',
      act: ch.act || null,
      status: ch.status || 'pending',
      novel_content: ch.novel_content || null,
      key_events: ch.key_events || [],
      word_count: ch.word_count || null,
      quality_score: ch.quality_score || null,
    })),
  }

  const jsonStr = JSON.stringify(exportData, null, 2)
  const baseTitle = sanitizeName(story.title || '未命名作品')
  const dateStr = new Date().toISOString().slice(0, 10)
  const fileName = `${baseTitle}_导出_${dateStr}.json`

  // #ifdef H5
  // H5 环境：通过 Blob 下载
  const blob = new Blob([jsonStr], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  return fileName
  // #endif

  // #ifndef H5
  // 小程序/App 环境：保存文件
  return new Promise((resolve, reject) => {
    const fs = uni.getFileSystemManager()
    const filePath = `${(uni as any).env.USER_DATA_PATH}/${fileName}`
    fs.writeFile({
      filePath,
      data: jsonStr,
      encoding: 'utf8',
      success: () => {
        // 尝试保存到手机存储
        uni.saveFile({
          tempFilePath: filePath,
          success: (res) => {
            uni.showToast({ title: '导出成功', icon: 'success' })
            resolve(res.savedFilePath)
          },
          fail: () => {
            // 如果保存失败，至少文件已在用户数据目录
            uni.showToast({ title: '已保存到应用目录', icon: 'success' })
            resolve(filePath)
          },
        })
      },
      fail: (err) => {
        reject(new Error(err.errMsg || '导出失败'))
      },
    })
  })
  // #endif
}

function sanitizeName(value: string): string {
  return value.replace(/[\\/:*?"<>|]/g, '_')
}
