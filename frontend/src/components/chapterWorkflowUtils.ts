export function canStartChapterWorkflowParse(params: {
  workflowExists: boolean;
  status: string;
  hasShots: boolean;
  parsing: boolean;
  workflowRunning: boolean;
}): boolean {
  if (params.parsing || params.workflowRunning) return false;
  if (!params.workflowExists) return true;
  return !params.hasShots;
}
