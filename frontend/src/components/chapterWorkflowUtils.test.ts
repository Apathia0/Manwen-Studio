import { describe, expect, it } from 'vitest';
import { canStartChapterWorkflowParse } from './chapterWorkflowUtils';

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
});
