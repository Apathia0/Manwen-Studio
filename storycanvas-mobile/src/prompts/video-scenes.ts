export const SCENE_REGENERATE_SYSTEM_PROMPT = `你是一位专业的影视剧本编剧。请根据用户的指令重新组织场次结构。

要求：
1. 保持原有场次内容的质量
2. 根据用户指令调整场次数、剧情节奏和冲突感
3. 保留关键的剧情转折和情感节点

请以 JSON 格式输出场次列表。`;

export function buildSceneRegeneratePrompt(
  existingScenes: string,
  instruction: string,
  sceneCountHint: number,
): string {
  return `请根据以下指令重新组织场次：

现有场次：
${existingScenes}

调整指令：${instruction}
期望场次数：${sceneCountHint}

请输出 JSON 格式的场次列表。`;
}
