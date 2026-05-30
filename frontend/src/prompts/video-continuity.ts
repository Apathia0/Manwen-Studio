export const CONTINUITY_SYSTEM_PROMPT = `你是一位专业的影视连续性监督员。请检查一组镜头之间的视觉和叙事一致性。

检查要点：
1. 角色外观一致性（服装、发型、状态）
2. 场景环境连续性（光线、天气、道具位置）
3. 动作衔接流畅性
4. 对白和情绪连贯性
5. 镜头运动逻辑

请输出问题列表和改进建议。`;

export function buildContinuityCheckPrompt(
  shots: Array<{ id: number; title: string; action_description: string; continuity_notes: string }>,
): string {
  const shotList = shots.map((s, i) =>
    `镜头 ${i + 1} (ID: ${s.id}): ${s.title}\n动作: ${s.action_description}\n连续性备注: ${s.continuity_notes}`
  ).join('\n\n');

  return `请检查以下镜头序列的连续性：

${shotList}

请输出检查结果，包括发现的问题和改进建议。`;
}
