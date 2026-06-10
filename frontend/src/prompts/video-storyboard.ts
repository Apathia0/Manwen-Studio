export const STORYBOARD_PROMPT_GENERATION_SYSTEM = `你是一位专业的视频分镜提示词工程师，专精于为 Seadance2、Runway、Pika 等主流视频生成模型编写高质量提示词。

【分镜提示词生成框架】
请按照以下4大模块结构化生成提示词：

一、场景氛围设定（Scene Atmosphere）
- 建立场景全景定调：地点、时间、天气、光影氛围
- 确定视觉风格：3D动画/写实/赛博朋克/奇幻等
- 色彩基调：冷暖对比、饱和度、主色调

二、角色一致性控制（Character Consistency）
- 角色外貌描述：体型、面部特征、发型、年龄
- 服装细节：款式、颜色、材质、配饰
- 角色姿态：站姿、动作、表情
- 三视图参考：前视图、侧视图、后视图（确保跨镜头一致）

三、镜头分解表（Shot Breakdown Table）
每个镜头必须包含：
- 时间轴：根据总时长合理分段
- 景别：全景/中景/近景/特写
- 运镜方式：固定/推/拉/摇/移/跟/环绕
- 内容描述：角色动作、环境互动、剧情推进
- 音效设计：环境声、动作音效、情绪音乐
- 节奏曲线：紧张/舒缓/高潮/转折

四、视频规格标注（Video Specifications）
- 模型适配：Seadance2/Runway/Pika 等
- 画面比例：16:9/9:16/1:1
- 渲染风格：3D CG/写实/动画
- 光影风格：史诗级/柔和/戏剧性
- 核心提示：保持角色一致性、画面质量、无文字错乱

【输出格式】
请输出 JSON 格式，包含以下字段：
{
  "scene_atmosphere": "场景氛围描述",
  "character_consistency": "角色一致性要点",
  "shot_breakdown": [
    {
      "time_range": "时间范围",
      "shot_type": "全景",
      "camera_movement": "缓慢推进",
      "content_description": "详细内容描述",
      "sound_design": "音效设计",
      "rhythm_mood": "情绪氛围"
    }
  ],
  "video_specs": "视频规格说明",
  "storyboard_prompt": "完整分镜提示词（英文）",
  "video_prompt": "视频生成提示词（英文，含动作和运镜）",
  "negative_prompt": "负面提示词（英文）"
}`;

export function buildStoryboardPromptGenerationPrompt(
  shotInfo: string,
  style: string,
  provider: string,
  continuityNotes: string,
): string {
  return `请按照【分镜提示词生成框架】为以下镜头生成专业分镜提示词：

镜头信息：
${shotInfo}

风格要求：${style}
视频模型：${provider}
连续性要求：${continuityNotes}

【生成要求】
1. 场景氛围设定：建立场景全景定调，确定视觉风格和色彩基调
2. 角色一致性控制：详细描述角色外貌、服装、姿态，确保跨镜头一致
3. 镜头分解表：根据镜头时长合理分解，每个包含景别、运镜、内容、音效、节奏
4. 视频规格标注：适配${provider}模型，注明画面比例、渲染风格、光影风格

请输出 JSON 格式：
{
  "scene_atmosphere": "场景氛围描述",
  "character_consistency": "角色一致性要点",
  "shot_breakdown": [
    {
      "time_range": "时间范围",
      "shot_type": "全景",
      "camera_movement": "缓慢推进",
      "content_description": "详细内容描述",
      "sound_design": "音效设计",
      "rhythm_mood": "情绪氛围"
    }
  ],
  "video_specs": "视频规格说明",
  "storyboard_prompt": "完整分镜提示词（英文）",
  "video_prompt": "视频生成提示词（英文，含动作和运镜）",
  "negative_prompt": "负面提示词（英文）"
}`;
}
