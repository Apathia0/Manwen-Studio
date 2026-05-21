import { BookOpen, PenLine, ClipboardList, BarChart3, Palette, User } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

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
    图标: Palette,
    标题: '优化分镜脚本',
    描述: '改进本章分镜设计',
    提示词: '请分析当前章节的分镜脚本，提出改进建议以增强画面表现力和叙事节奏。',
  },
  {
    图标: User,
    标题: '角色设定建议',
    描述: '分析角色弧光',
    提示词: '请分析当前故事中的角色弧光发展，给出角色设定方面的优化建议。',
  },
];

interface 快捷动作属性 {
  onAction: (prompt: string) => void;
  disabled?: boolean;
}

export default function QuickActions({ onAction, disabled }: 快捷动作属性) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {动作列表.map((动作) => {
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
