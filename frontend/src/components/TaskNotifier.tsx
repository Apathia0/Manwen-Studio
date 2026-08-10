import { useEffect, useRef } from 'react';
import { genStore } from '../genStore';
import { videoGenStore } from '../videoGenStore';

/**
 * 任务完成桌面通知
 * - 订阅漫画/视频生成状态，检测「进行中 → 结束」状态跃迁后发送系统通知
 * - 仅当浏览器通知权限已授予时生效；权限通过首次用户交互请求（不主动打扰）
 * - 页面关闭后由 Service Worker 兜底（sw.js 已注册）
 */
export default function TaskNotifier() {
  const notified = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!('Notification' in window)) return;

    function maybeNotify(title: string, body: string) {
      if (Notification.permission !== 'granted') return;
      const key = `${title}|${body}`;
      if (notified.current.has(key)) return;
      notified.current.add(key);
      try {
        new Notification(title, { body, icon: '/pwa-192.png', badge: '/pwa-192.png' });
      } catch {
        /* 通知可能因配额或浏览器限制失败，忽略避免打断主流程 */
      }
    }

    const unsubs: Array<() => void> = [];

    // 漫画生成：active 从 true → false 视为结束
    unsubs.push(
      genStore.subscribe(() => {
        genStore.snapshot().forEach((state, chapterId) => {
          if (state.active) return;
          const key = `manga-${chapterId}`;
          if (notified.current.has(key)) return;
          notified.current.add(key);
          if (state.errorMsg) {
            maybeNotify('漫画生成未完成', `章节 #${chapterId}：${state.errorMsg}`);
          } else {
            maybeNotify('漫画生成完成', `章节 #${chapterId} 已生成 ${state.images.length} 张图片`);
          }
        });
      }),
    );

    // 视频链路：四个资产类型统一监听 ended 状态
    unsubs.push(
      videoGenStore.subscribe(() => {
        videoGenStore.snapshot().forEach((state, key) => {
          if (!state.active) {
            const id = `video-${key}`;
            if (notified.current.has(id)) return;
            notified.current.add(id);
            if (state.status === 'failed') {
              maybeNotify('生成未完成', `${state.statusMsg}: ${state.errorMsg || '未知错误'}`);
            } else if (state.status === 'succeeded') {
              maybeNotify('生成完成', state.statusMsg);
            }
          }
        });
      }),
    );

    return () => unsubs.forEach((u) => u());
  }, []);

  return null;
}