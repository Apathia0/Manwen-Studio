import { BookOpen, PenLine, ClipboardList, BarChart3, User, Search, Film, GitBranch, Clock, UserCheck, Sparkles } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { AgentWorkflowType } from '../../api';

interface 快捷动作 {
  图标: LucideIcon;
  标题: string;
  描述: string;
  提示词: string;
}

const 动作列表: 快捷动作[] = [
  {
    图标: BookOpen,
    标题: '阅读当前章节',
    描述: '分析本章写作质量',
    提示词: '请阅读当前章节全文，分析本章的写作质量，包括结构、文笔、节奏和逻辑连贯性，给出具体的改进建议。',
  },
  {
    图标: PenLine,
    标题: '修改当前章节',
    描述: '按需求调整本章内容',
    提示词: '请根据我的要求修改当前章节的内容，保持整体风格一致。',
  },
  {
    图标: ClipboardList,
    标题: '优化故事框架',
    描述: '检查并改进故事结构',
    提示词: '请检查当前故事的框架结构（三幕结构、伏笔、节奏等），提出优化建议并允许我确认后进行调整。',
  },
  {
    图标: BarChart3,
    标题: '质量评估',
    描述: '对已完成的章节评分',
    提示词: '请评估已完成章节的整体质量，从内容、文笔、角色塑造、情节设计等维度给出评分和改进建议。',
  },
  {
    图标: Sparkles,
    标题: '去AI味',
    描述: '检测并清除AI写作痕迹',
    提示词: '请对当前章节进行去AI味处理，检测并清除AI写作痕迹，包括禁用词、句式套路、心理描写外化、结尾升华、解释腔等，让文字回归自然、非模板化。',
  },
  {
    图标: User,
    标题: '角色设定建议',
    描述: '分析角色弧光',
    提示词: '请分析当前故事中的角色弧光发展，给出角色设定方面的优化建议。',
  },
];

const 视频动作列表: 快捷动作[] = [
  {
    图标: Search,
    标题: '分析提示词一致性',
    描述: '检查故事版与视频提示词',
    提示词: '分析当前镜头的故事版提示词和视频提示词是否一致',
  },
  {
    图标: Film,
    标题: '优化视频提示词',
    描述: '强化运镜和动作连续性',
    提示词: '帮我优化当前镜头的视频提示词，强化运镜和动作连续性',
  },
  {
    图标: GitBranch,
    标题: '检查镜头连续性',
    描述: '角色、场景、情绪是否连贯',
    提示词: '检查本章视频镜头是否存在角色、场景或情绪不连续',
  },
  {
    图标: BookOpen,
    标题: '优化剧本镜头',
    描述: '指出最需要调整的镜头',
    提示词: '读取剧本并指出最需要调整的镜头',
  },
  {
    图标: Clock,
    标题: '适配15秒视频',
    描述: '优化当前镜头时长',
    提示词: '帮我把当前镜头改得更适合 15 秒视频生成',
  },
  {
    图标: UserCheck,
    标题: '检查角色素材',
    描述: '验证引用素材合理性',
    提示词: '检查当前镜头引用的角色素材是否合理',
  },
];

interface 快捷动作属性 {
  onAction: (prompt: string) => void;
  disabled?: boolean;
  workflowType?: AgentWorkflowType;
}

export default function QuickActions({ onAction, disabled, workflowType }: 快捷动作属性) {
  const 当前列表 = workflowType === 'video' ? 视频动作列表 : 动作列表;

  return (
    <div className="grid grid-cols-2 gap-3">
      {当前列表.map((动作) => {
        const IconComp = 动作.图标;
        return (
          <button
            key={动作.标题}
            onClick={() => onAction(动作.提示词)}
            disabled={disabled}
            className="flex flex-col items-start gap-1.5 p-3 rounded-xl bg-white border border-[#d7e3f4]
                       hover:border-blue-400 hover:shadow-[0_4px_12px_rgba(59,130,246,0.08)] transition-all text-left disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <IconComp size={18} className="text-blue-500" />
            <span className="text-sm font-medium text-gray-700">{动作.标题}</span>
            <span className="text-xs text-gray-500 leading-relaxed">{动作.描述}</span>
          </button>
        );
      })}
    </div>
  );
}
