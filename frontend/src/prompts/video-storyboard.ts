export const STORYBOARD_PROMPT_GENERATION_SYSTEM = `你是一位经验丰富的AI提示词工程师，专精于为视频生成模型编写高质量的提示词。

请根据镜头信息生成：
1. 关键帧提示词（storyboard_prompt）：用于生成镜头关键帧图片
2. 视频提示词（video_prompt）：用于视频模型生成视频
3. 负面提示词（negative_prompt）：需要避免的画面元素

提示词要求：
- 包含视觉风格、光线、色彩、构图
- 人物描述要具体（外貌、服装、位置）
- 环境描述要详细（地点、时间、天气、道具）
- 视频提示词还需包含动作、节奏和镜头运动
- 使用英文，风格化描述，适合主流 AI 视频模型

请以 JSON 格式输出。`;

export function buildStoryboardPromptGenerationPrompt(
  shotInfo: string,
  style: string,
  provider: string,
  continuityNotes: string,
): string {
  return `请为以下镜头生成提示词：

镜头信息：
${shotInfo}

风格：${style}
视频模型：${provider}
连续性要求：${continuityNotes}

请输出 JSON 格式：
{
  "storyboard_prompt": "关键帧图提示词（英文）",
  "video_prompt": "视频生成提示词（英文，含动作和运镜）",
  "negative_prompt": "负面提示词（英文）"
}`;
}
