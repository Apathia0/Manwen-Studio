import { describe, expect, it } from 'vitest';
import { canStartChapterWorkflowParse, isChapterWorkflowActive } from './chapterWorkflowUtils';

describe('isChapterWorkflowActive', () => {
  it('拆镜失败是终态，不应继续显示 loading', () => {
    expect(isChapterWorkflowActive('failed')).toBe(false);
  });

  it('拆镜执行中仍是活动态', () => {
    expect(isChapterWorkflowActive('parsing_shots')).toBe(true);
  });
});

describe('canStartChapterWorkflowParse', () => {
  it('parsing 中禁止再次拆镜', () => {
    expect(
      canStartChapterWorkflowParse({
        workflowExists: true,
        status: 'pending',
        hasShots: true,
        parsing: true,
        workflowRunning: false,
      }),
    ).toBe(false);
  });

  it('workflowRunning 中禁止再次拆镜', () => {
    expect(
      canStartChapterWorkflowParse({
        workflowExists: true,
        status: 'shots_ready',
        hasShots: true,
        parsing: false,
        workflowRunning: true,
      }),
    ).toBe(false);
  });

  it('空工作流且空闲时允许拆镜', () => {
    expect(
      canStartChapterWorkflowParse({
        workflowExists: false,
        status: '',
        hasShots: false,
        parsing: false,
        workflowRunning: false,
      }),
    ).toBe(true);
  });

  it('失败后即使存在部分镜头也允许重新拆镜', () => {
    expect(
      canStartChapterWorkflowParse({
        workflowExists: true,
        status: 'failed',
        hasShots: true,
        parsing: false,
        workflowRunning: false,
      }),
    ).toBe(true);
  });
});
