const ACTIVE_CHAPTER_WORKFLOW_STATUSES = new Set([
  'parsing_shots',
  'generating_storyboards',
  'generating_videos',
  'reanalyzing_prompts',
  'generating_details',
]);

export function isChapterWorkflowActive(status: string): boolean {
  return ACTIVE_CHAPTER_WORKFLOW_STATUSES.has(status);
}

export function canStartChapterWorkflowParse(params: {
  workflowExists: boolean;
  status: string;
  hasShots: boolean;
  parsing: boolean;
  workflowRunning: boolean;
}): boolean {
  if (params.parsing || params.workflowRunning) return false;
  if (!params.workflowExists) return true;
  if (params.status === 'failed') return true;
  return !params.hasShots;
}
