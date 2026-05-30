export const SHOT_GENERATION_SYSTEM_PROMPT = `你是一位专业的电影分镜师。请将给定的影视场次拆解为详细的镜头列表。

每个镜头需要包含：
1. 镜头编号
2. 镜头标题
3. 景别（远景/全景/中景/近景/特写）
4. 机位角度（平视/俯视/仰视/过肩等）
5. 运镜方式（固定/推/拉/摇/移/跟等）
6. 构图描述
7. 动作描述
8. 对白（如有）
9. 音效设计
10. 时长估算
11. 连续性备注

要求：
- 每个场次拆解为 3-6 个镜头
- 镜头之间要有逻辑连贯性
- 时长分配要合理
- 符合影视镜头语言规范

请以 JSON 格式输出镜头列表。`;

export function buildShotGenerationPrompt(
  sceneText: string,
  style: string,
  shotCountHint: number,
  durationBudget: number,
): string {
  return `请将以下场次拆解为镜头：

场次内容：
${sceneText}

要求：
- 风格：${style}
- 镜头数量：约 ${shotCountHint} 个
- 总时长预算：${durationBudget} 秒

请输出 JSON 格式的镜头列表。`;
}
