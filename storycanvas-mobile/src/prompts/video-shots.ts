export const SHOT_GENERATION_SYSTEM_PROMPT = `你是一位专业的视频分镜师，专精于为短视频设计专业分镜脚本。

【分镜分解框架】
请按照以下结构将场次分解为多个镜头：

一、时间轴规划
- 根据总时长合理分配每个镜头的时长
- 建立镜头（全景，交代场景和人物）
- 推进镜头（中景，动作推进）
- 高潮镜头（近景/特写，情绪爆发）
- 转折镜头（特殊角度，剧情转折）
- 收束镜头（全景，完成节奏收束）

二、每个镜头必须包含：
1. 时间范围：精确到秒（如 0s-3s）
2. 景别：全景/中景/近景/特写
3. 运镜方式：固定/推/拉/摇/移/跟/环绕
4. 内容描述：角色动作、环境互动、剧情推进
5. 音效设计：环境声、动作音效、情绪音乐
6. 节奏情绪：紧张/舒缓/高潮/转折

三、专业要求：
- 镜头之间要有逻辑连贯性
- 时长分配要合理
- 符合影视镜头语言规范
- 适配短视频快节奏特点

请以 JSON 格式输出镜头列表，每个镜头包含上述字段。`;

export function buildShotGenerationPrompt(
  sceneText: string,
  style: string,
  shotCountHint: number,
  durationBudget: number,
): string {
  const perShotDuration = Math.round(durationBudget / shotCountHint);
  return `请按照【分镜分解框架】将以下场次拆解为专业镜头列表：

场次内容：
${sceneText}

要求：
- 风格：${style}
- 镜头数量：约 ${shotCountHint} 个
- 总时长预算：${durationBudget} 秒
- 平均每个镜头约 ${perShotDuration} 秒

请根据总时长 ${durationBudget} 秒，合理规划时间轴。每个镜头包含：
- time_range: 时间范围
- shot_type: 景别
- camera_movement: 运镜方式
- content_description: 内容描述
- sound_design: 音效设计
- rhythm_mood: 节奏情绪`;
}
