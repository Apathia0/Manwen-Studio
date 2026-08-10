import { createContext, useContext, type ReactNode } from 'react';
import type { Chapter, Story } from '../api';

export type WorkspaceMode = 'novel' | 'manga' | 'video';

type WorkspaceContextValue = {
  activeStory: Story | null;
  chapters: Chapter[];
  activeChapterId: number | null;
  activeChapter: Chapter | null;
  workspaceMode: WorkspaceMode;
  setActiveStory: (story: Story | null) => void;
  setChapters: (chapters: Chapter[]) => void;
  setActiveChapterId: (id: number | null) => void;
  setWorkspaceMode: (mode: WorkspaceMode) => void;
};

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ value, children }: { value: WorkspaceContextValue; children: ReactNode }) {
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

/** 读取当前作品上下文（作品/章节/创作模式），未在 Provider 内时返回 null */
export function useWorkspaceContext(): WorkspaceContextValue | null {
  return useContext(WorkspaceContext);
}

/** 读取当前作品上下文，要求必须处于 WorkspaceProvider 内 */
export function useWorkspaceRequired(): WorkspaceContextValue {
  const value = useContext(WorkspaceContext);
  if (!value) {
    throw new Error('useWorkspaceRequired 必须在 WorkspaceProvider 内使用');
  }
  return value;
}
