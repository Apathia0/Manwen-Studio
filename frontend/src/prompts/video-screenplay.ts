export const SCREENPLAY_SYSTEM_PROMPT = `你是一位专业的影视剧本编剧。请根据给定的小说章节内容，将其改编为影视剧本格式。

要求：
1. 将章节内容拆解为若干个场次（scenes）
2. 每个场次需要包含：场次编号、地点、时间、出场人物、剧情概要、核心对白、情绪氛围
3. 剧本语言要有画面感，适合直接用于视频拍摄
4. 保留原作的核心剧情和情感基调

请以 JSON 格式输出，包含 screenplay（完整剧本文本）和 scenes（场次列表）两个字段。`;

export function buildScreenplayUserPrompt(chapterContent: string, style: string, sceneCountHint: number): string {
  return `请根据以下小说章节内容，生成一部${style}风格的影视剧本。

章节内容：
${chapterContent}

要求：
- 风格：${style}
- 期望场次数：${sceneCountHint} 场
- 每个场次包含标题、地点、时间、人物、摘要、对白、情绪

请输出 JSON 格式：
{
  "screenplay": "完整剧本文本...",
  "scenes": [
    {
      "scene_number": 1,
      "title": "场次标题",
      "location": "地点",
      "time_of_day": "时间",
      "characters": ["人物1", "人物2"],
      "summary": "剧情概要",
      "dialogue": [{"speaker": "人物", "text": "对白"}],
      "voiceover": "旁白",
      "mood": "情绪氛围",
      "estimated_duration_seconds": 20
    }
  ]
}`;
}
