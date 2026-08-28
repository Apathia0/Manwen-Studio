import { useState } from 'react';
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  MapPin,
  MessageSquare,
  SquarePen,
  Tag,
  ThumbsUp,
  UserRound,
  Zap,
} from 'lucide-react';
import { useFieldEditing } from './useFieldEditing';

/**
 * 画布"场景卡片"节点视图 — 1:1 复刻 ChapterVideoWorkflowPanel 剧本审核区的场景卡片。
 * 节拍不拆独立节点，作为卡片内子卡片区渲染（设计文档 §3.8.2）。
 * 所有字段 click-to-edit，提交经 onChange({ field: newValue }) 写回节点 config。
 */

// ── 字段中文映射（从 ChapterVideoWorkflowPanel 复制） ──
const beatTypeLabels: Record<string, string> = {
  action: '动作', dialogue: '对话', narration: '旁白', conflict: '冲突', transition: '转场',
};
const beatTypeColors: Record<string, string> = {
  action: 'bg-[#73a7ff]/12 text-[#73a7ff]',
  dialogue: 'bg-emerald-500/15 text-emerald-400',
  narration: 'bg-purple-500/15 text-purple-300',
  conflict: 'bg-red-500/15 text-red-300',
  transition: 'bg-amber-500/15 text-amber-300',
};
const importanceLabels: Record<string, string> = {
  major: '关键', medium: '一般', minor: '次要',
};
const importanceColors: Record<string, string> = {
  major: 'bg-rose-500/15 text-rose-300',
  medium: 'bg-[#2a2e33] text-[#8b93a1]',
  minor: 'bg-amber-500/15 text-amber-300',
};

interface SceneNodeBeat {
  beat_id: string | number;
  type?: string;
  importance?: string;
  emotion_shift?: string;
  action?: string;
  dialogue?: unknown;
  transition_to_next?: string;
}

export interface SceneNodeConfig {
  scene_id?: string | number;
  title?: string;
  location?: string;
  time_of_day?: string;
  characters?: string[];
  scene_purpose?: string;
  visual_anchors?: string;
  importance?: string;
  approved?: boolean;
  beats?: SceneNodeBeat[];
  duration_seconds?: number;
}

export interface SceneNodeViewProps {
  config: SceneNodeConfig;
  /** 字段写回：partial 合并进节点 config */
  onChange: (partial: Record<string, unknown>) => void;
  /** 批准 / 撤销批准 */
  onToggleApproved?: () => void;
  /** 在聚合审核节点内使用时隐藏单场景批准按钮（审批统一在聚合层） */
  hideApproval?: boolean;
}

/** dialogue 渲染为行数组：兼容 string / string[] / {character,line}[] */
function renderDialogueLines(dialogue: unknown): string[] {
  if (typeof dialogue === 'string') {
    return dialogue.trim() ? [dialogue] : [];
  }
  if (Array.isArray(dialogue)) {
    return dialogue.map((line) => {
      if (typeof line === 'string') return line;
      if (typeof line === 'object' && line !== null) {
        const rec = line as Record<string, unknown>;
        return `${rec.character || ''}: ${rec.line || ''}`;
      }
      return String(line);
    }).filter((s) => s.trim());
  }
  return [];
}

/** 把 {character,line}[] 归一为 "角色: 台词" 行文本，供 textarea 编辑 */
function dialogueToEditingText(dialogue: unknown): string {
  if (typeof dialogue === 'string') return dialogue;
  return renderDialogueLines(dialogue).join('\n');
}

export default function SceneNodeView({ config, onChange, onToggleApproved, hideApproval }: SceneNodeViewProps) {
  const { editingField, setEditingField, makeInputProps, makeTextareaProps } = useFieldEditing();
  const [expanded, setExpanded] = useState(!config.approved);

  const sceneId = config.scene_id ?? '?';
  const beats = Array.isArray(config.beats) ? config.beats : [];
  const approved = Boolean(config.approved);
  // 场景级重要性徽标沿用参考实现：取首个节拍的重要性
  const headerImportance = beats[0]?.importance || '';

  const fieldKey = (field: string) => `${sceneId}.${field}`;
  const beatFieldKey = (beatId: string | number, field: string) => `${sceneId}.${beatId}.${field}`;
  const isEditing = (key: string) => editingField === key;

  // input 类提交：写回字段并结束编辑（hook 已保证 Enter/blur 只提交一次）
  const commitInput = (partial: Record<string, unknown>) => {
    onChange(partial);
    setEditingField(null);
  };
  // textarea 类提交
  const commitTextarea = (partial: Record<string, unknown>) => {
    onChange(partial);
    setEditingField(null);
  };
  // 节拍字段提交：合并进 config.beats 对应项后整体写回
  const commitBeat = (beatId: string | number, partial: Record<string, unknown>) => {
    const nextBeats = beats.map((b) => (b.beat_id === beatId ? { ...b, ...partial } : b));
    onChange({ beats: nextBeats });
    setEditingField(null);
  };

  return (
    <div className="w-[320px] max-h-[420px] rounded-xl border border-[#3a3f45] bg-[#202226] shadow-sm overflow-hidden flex flex-col">
      {/* ── 卡片头部：点击整体展开/收起 ── */}
      <div
        onClick={() => setExpanded((prev) => !prev)}
        className="flex items-center justify-between w-full px-3 py-2.5 hover:bg-[#26292e]/70 transition-colors cursor-pointer shrink-0"
      >
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <span className="shrink-0 inline-flex items-center justify-center w-6 h-6 rounded-lg bg-[#73a7ff]/12 text-xs font-semibold text-[#73a7ff]">
            {sceneId}
          </span>
          {/* 标题：点击编辑 */}
          {isEditing(fieldKey('title')) ? (
            <input
              {...makeInputProps(fieldKey('title'), (v) => commitInput({ title: v }), config.title || '')}
              className="text-sm font-medium text-[#e8ebf0] border border-[#73a7ff]/60 rounded px-1.5 py-0.5 bg-[#2a2e33] outline-none min-w-[120px]"
            />
          ) : (
            <span
              onClick={(e) => { e.stopPropagation(); setEditingField(fieldKey('title')); }}
              className="text-sm font-medium text-[#e8ebf0] truncate cursor-pointer hover:text-[#73a7ff] hover:bg-[#2a2e33] rounded px-1 -mx-1 transition-colors"
              title="点击编辑标题"
            >
              {config.title || `场景 ${sceneId}`}
            </span>
          )}
          {/* 地点：点击编辑 */}
          {isEditing(fieldKey('location')) ? (
            <input
              {...makeInputProps(fieldKey('location'), (v) => commitInput({ location: v }), config.location || '')}
              className="inline-flex items-center gap-0.5 text-[11px] text-[#b3bac6] border border-[#73a7ff]/60 rounded px-1.5 py-0.5 bg-[#2a2e33] outline-none min-w-[80px]"
            />
          ) : (
            <span
              onClick={(e) => { e.stopPropagation(); setEditingField(fieldKey('location')); }}
              className="inline-flex items-center gap-0.5 text-[11px] text-[#78818f] shrink-0 cursor-pointer hover:text-[#73a7ff] hover:bg-[#2a2e33] rounded px-1 -mx-1 transition-colors"
              title="点击编辑地点"
            >
              <MapPin size={10} />
              {config.location || '点击设置地点'}
            </span>
          )}
          {/* 时间：点击编辑 */}
          {isEditing(fieldKey('time_of_day')) ? (
            <input
              {...makeInputProps(fieldKey('time_of_day'), (v) => commitInput({ time_of_day: v }), config.time_of_day || '')}
              className="inline-flex items-center gap-0.5 text-[11px] text-[#b3bac6] border border-[#73a7ff]/60 rounded px-1.5 py-0.5 bg-[#2a2e33] outline-none min-w-[70px]"
            />
          ) : (
            <span
              onClick={(e) => { e.stopPropagation(); setEditingField(fieldKey('time_of_day')); }}
              className="inline-flex items-center gap-0.5 text-[11px] text-[#78818f] shrink-0 cursor-pointer hover:text-[#73a7ff] hover:bg-[#2a2e33] rounded px-1 -mx-1 transition-colors"
              title="点击编辑时间"
            >
              <Clock size={10} />
              {config.time_of_day || '点击设置时间'}
            </span>
          )}
          {headerImportance && (
            <span className={`inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-medium shrink-0 ${importanceColors[headerImportance] || 'bg-[#2a2e33] text-[#8b93a1]'}`}>
              <Tag size={9} />
              {importanceLabels[headerImportance] || headerImportance}
            </span>
          )}
          {approved && (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-400 shrink-0">
              <CheckCircle2 size={11} />
              已批准
            </span>
          )}
        </div>
        <span className="shrink-0 ml-2">
          {expanded ? <ChevronDown size={16} className="text-[#78818f]" /> : <ChevronRight size={16} className="text-[#78818f]" />}
        </span>
      </div>

      {/* ── 展开内容 ── */}
      {expanded && (
        <div className="px-3 pb-3 border-t border-[#3a3f45] overflow-y-auto flex-1 min-h-0">
          {/* 角色标签 — 点击编辑（逗号分隔） */}
          <div className="flex flex-wrap items-center gap-1.5 mt-3 mb-2">
            <UserRound size={12} className="text-[#78818f] shrink-0" />
            {isEditing(fieldKey('characters')) ? (
              <input
                {...makeInputProps(
                  fieldKey('characters'),
                  (v) => commitInput({ characters: v.split(',').map((c) => c.trim()).filter(Boolean) }),
                  Array.isArray(config.characters) ? config.characters.join(', ') : '',
                )}
                className="text-[11px] text-[#b3bac6] border border-[#73a7ff]/60 rounded px-1.5 py-0.5 bg-[#2a2e33] outline-none min-w-[120px]"
                placeholder="角色名, 逗号分隔"
              />
            ) : (
              <>
                {Array.isArray(config.characters) && config.characters.length > 0 ? (
                  config.characters.map((char, i) => (
                    <span key={i} className="rounded-full bg-[#73a7ff]/12 px-2 py-0.5 text-[11px] text-[#73a7ff]">
                      {typeof char === 'string' ? char : String((char as Record<string, unknown>).name || (char as Record<string, unknown>).character || char)}
                    </span>
                  ))
                ) : (
                  <span
                    onClick={() => setEditingField(fieldKey('characters'))}
                    className="text-[11px] text-[#78818f] cursor-pointer hover:text-[#73a7ff] hover:bg-[#2a2e33] rounded px-1.5 py-0.5 transition-colors"
                    title="点击编辑角色"
                  >
                    点击添加角色
                  </span>
                )}
                {Array.isArray(config.characters) && config.characters.length > 0 && (
                  <button
                    onClick={() => setEditingField(fieldKey('characters'))}
                    className="text-[10px] text-[#78818f] hover:text-[#73a7ff] hover:bg-[#73a7ff]/12 rounded px-1 py-0.5 transition-colors"
                    title="编辑角色列表"
                  >
                    <SquarePen size={10} />
                  </button>
                )}
              </>
            )}
          </div>

          {/* 场景目的 — 点击编辑 textarea */}
          <div className="mt-2 text-xs text-[#b3bac6] leading-relaxed">
            <span className="font-medium text-[#8b93a1] shrink-0">场景目的：</span>
            {isEditing(fieldKey('scene_purpose')) ? (
              <textarea
                {...makeTextareaProps(fieldKey('scene_purpose'), (v) => commitTextarea({ scene_purpose: v }), config.scene_purpose || '')}
                className="w-full mt-1 text-xs text-[#b3bac6] border border-[#73a7ff]/60 rounded px-2 py-1 bg-[#2a2e33] outline-none resize-none"
                rows={2}
                placeholder="场景目的描述..."
              />
            ) : (
              <span
                onClick={() => setEditingField(fieldKey('scene_purpose'))}
                className="cursor-pointer hover:text-[#73a7ff] hover:bg-[#2a2e33] rounded px-1 -mx-1 transition-colors"
                title="点击编辑场景目的"
              >
                {config.scene_purpose || '点击设置场景目的'}
              </span>
            )}
          </div>

          {/* 视觉锚点 — 点击编辑（纯文本，JSON 字符串原样展示） */}
          <div className="mt-2">
            <div className="flex items-center gap-1 mb-1.5">
              <span className="text-[11px] font-medium text-[#8b93a1]">视觉锚点</span>
            </div>
            {isEditing(fieldKey('visual_anchors')) ? (
              <textarea
                {...makeTextareaProps(fieldKey('visual_anchors'), (v) => commitTextarea({ visual_anchors: v }), config.visual_anchors || '')}
                className="w-full text-xs text-[#b3bac6] border border-[#73a7ff]/60 rounded px-2 py-1 bg-[#2a2e33] outline-none resize-none"
                rows={2}
                placeholder="视觉锚点描述..."
              />
            ) : (
              <span
                onClick={() => setEditingField(fieldKey('visual_anchors'))}
                className={`text-xs cursor-pointer hover:text-[#73a7ff] hover:bg-[#2a2e33] rounded px-1 -mx-1 transition-colors ${config.visual_anchors ? 'text-[#b3bac6]' : 'text-[#78818f]'}`}
                title="点击编辑视觉锚点"
              >
                {config.visual_anchors || '点击编辑添加视觉锚点'}
              </span>
            )}
          </div>

          {/* ── 节拍子卡片列表 ── */}
          {beats.length > 0 && (
            <div className="mt-3 space-y-2">
              {beats.map((beat) => {
                const bf = (field: string) => beatFieldKey(beat.beat_id, field);
                const dialogueLines = renderDialogueLines(beat.dialogue);
                return (
                  <div key={beat.beat_id} className="rounded-lg border border-[#35393f] bg-[#26292e] p-2.5">
                    <div className="flex items-center gap-1.5 mb-1.5 flex-wrap">
                      <span className="text-[11px] font-medium text-[#b3bac6]">节拍 {beat.beat_id}</span>
                      {/* 类型 pill */}
                      {isEditing(bf('type')) ? (
                        <select
                          autoFocus
                          defaultValue={beat.type || 'action'}
                          onBlur={(e) => commitBeat(beat.beat_id, { type: e.target.value })}
                          onChange={(e) => commitBeat(beat.beat_id, { type: e.target.value })}
                          onClick={(e) => e.stopPropagation()}
                          className="rounded-full px-1.5 py-0.5 text-[10px] font-medium border border-[#73a7ff]/60 bg-[#2a2e33] outline-none text-[#c3c9d4]"
                        >
                          {Object.entries(beatTypeLabels).map(([val, label]) => (
                            <option key={val} value={val}>{label}</option>
                          ))}
                        </select>
                      ) : (
                        <span
                          onClick={() => setEditingField(bf('type'))}
                          className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium cursor-pointer hover:ring-1 hover:ring-[#73a7ff]/50 transition-all ${beatTypeColors[beat.type || ''] || 'bg-[#2a2e33] text-[#8b93a1]'}`}
                          title="点击编辑类型"
                        >
                          <Zap size={9} className="inline mr-0.5" />
                          {beatTypeLabels[beat.type || ''] || beat.type || '动作'}
                        </span>
                      )}
                      {/* 重要性 pill */}
                      {isEditing(bf('importance')) ? (
                        <select
                          autoFocus
                          defaultValue={beat.importance || 'medium'}
                          onBlur={(e) => commitBeat(beat.beat_id, { importance: e.target.value })}
                          onChange={(e) => commitBeat(beat.beat_id, { importance: e.target.value })}
                          onClick={(e) => e.stopPropagation()}
                          className="rounded-full px-1.5 py-0.5 text-[10px] font-medium border border-[#73a7ff]/60 bg-[#2a2e33] outline-none text-[#c3c9d4]"
                        >
                          {Object.entries(importanceLabels).map(([val, label]) => (
                            <option key={val} value={val}>{label}</option>
                          ))}
                        </select>
                      ) : (
                        <span
                          onClick={() => setEditingField(bf('importance'))}
                          className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium cursor-pointer hover:ring-1 hover:ring-[#73a7ff]/50 transition-all ${importanceColors[beat.importance || ''] || 'bg-[#2a2e33] text-[#8b93a1]'}`}
                          title="点击编辑重要性"
                        >
                          {importanceLabels[beat.importance || ''] || beat.importance || '一般'}
                        </span>
                      )}
                      {/* 情绪紫色 pill */}
                      {isEditing(bf('emotion_shift')) ? (
                        <input
                          {...makeInputProps(bf('emotion_shift'), (v) => commitBeat(beat.beat_id, { emotion_shift: v }), beat.emotion_shift || '')}
                          className="rounded-full px-1.5 py-0.5 text-[10px] border border-[#73a7ff]/60 bg-[#2a2e33] outline-none text-violet-300 min-w-[60px]"
                          placeholder="情绪"
                        />
                      ) : (
                        <span
                          onClick={() => setEditingField(bf('emotion_shift'))}
                          className="rounded-full bg-violet-500/15 px-1.5 py-0.5 text-[10px] text-violet-300 cursor-pointer hover:ring-1 hover:ring-[#73a7ff]/50 transition-all"
                          title="点击编辑情绪"
                        >
                          {beat.emotion_shift || '情绪'}
                        </span>
                      )}
                    </div>

                    {/* 动作描述 — 点击编辑 textarea */}
                    {isEditing(bf('action')) ? (
                      <textarea
                        {...makeTextareaProps(bf('action'), (v) => commitBeat(beat.beat_id, { action: v }), typeof beat.action === 'string' ? beat.action : '')}
                        className="w-full text-xs text-[#c3c9d4] border border-[#73a7ff]/60 rounded px-2 py-1 bg-[#2a2e33] outline-none resize-none mb-1.5"
                        rows={3}
                        placeholder="动作描述..."
                      />
                    ) : (
                      <div
                        onClick={() => setEditingField(bf('action'))}
                        className="text-xs text-[#c3c9d4] leading-relaxed mb-1.5 cursor-pointer hover:text-[#73a7ff] hover:bg-[#73a7ff]/12/30 rounded px-1 -mx-1 transition-colors"
                        title="点击编辑动作描述"
                      >
                        {beat.action || '点击编辑动作描述'}
                      </div>
                    )}

                    {/* 对白 — 点击编辑 textarea，每行 "角色: 台词" */}
                    {isEditing(bf('dialogue')) ? (
                      <textarea
                        {...makeTextareaProps(bf('dialogue'), (v) => commitBeat(beat.beat_id, { dialogue: v.split('\n').filter(Boolean) }), dialogueToEditingText(beat.dialogue))}
                        className="w-full text-xs text-[#b3bac6] border border-[#73a7ff]/60 rounded px-2 py-1 bg-[#2a2e33] outline-none resize-none mb-1.5"
                        rows={3}
                        placeholder="每行格式: 角色: 台词"
                      />
                    ) : (
                      <div
                        onClick={() => setEditingField(bf('dialogue'))}
                        className="space-y-0.5 mb-1.5 cursor-pointer hover:bg-[#73a7ff]/12/30 rounded px-1 -mx-1 transition-colors"
                        title="点击编辑对话"
                      >
                        {dialogueLines.length > 0 ? (
                          dialogueLines.map((line, i) => (
                            <div key={i} className="flex items-start gap-1 text-xs">
                              <MessageSquare size={11} className="mt-0.5 text-[#78818f] shrink-0" />
                              <span className="text-[#b3bac6]">{line}</span>
                            </div>
                          ))
                        ) : (
                          <div className="flex items-start gap-1 text-xs text-[#78818f]">
                            <MessageSquare size={11} className="mt-0.5 shrink-0" />
                            <span>点击编辑对话</span>
                          </div>
                        )}
                      </div>
                    )}

                    {/* 转场 — 点击编辑 input */}
                    {isEditing(bf('transition_to_next')) ? (
                      <input
                        {...makeInputProps(bf('transition_to_next'), (v) => commitBeat(beat.beat_id, { transition_to_next: v }), beat.transition_to_next || '')}
                        className="w-full text-[10px] text-[#b3bac6] border border-[#73a7ff]/60 rounded px-1.5 py-0.5 bg-[#2a2e33] outline-none mt-1"
                        placeholder="转场描述..."
                      />
                    ) : (
                      <div
                        onClick={() => setEditingField(bf('transition_to_next'))}
                        className="text-[10px] text-[#78818f] italic mt-1 cursor-pointer hover:text-[#73a7ff] hover:bg-[#73a7ff]/12/30 rounded px-1 -mx-1 transition-colors"
                        title="点击编辑转场"
                      >
                        → {beat.transition_to_next || '点击编辑转场'}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* 场景时长提示 */}
          {typeof config.duration_seconds === 'number' && (
            <div className="mt-3 text-[11px] text-[#78818f]">
              预计时长：{config.duration_seconds}s
            </div>
          )}

          {/* ── 批准操作（聚合节点内隐藏） ── */}
          <div className={hideApproval ? 'hidden' : 'mt-3 pt-2 border-t border-dashed border-[#3a3f45]'}>
            {approved ? (
              <button
                onClick={() => onToggleApproved?.()}
                className="inline-flex items-center gap-1 rounded-lg border border-emerald-500/30 px-2.5 py-1.5 text-xs text-emerald-400 hover:bg-emerald-500/15 transition-colors"
                title="撤销批准"
              >
                <CheckCircle2 size={12} />
                已批准（点击撤销）
              </button>
            ) : (
              <button
                onClick={() => onToggleApproved?.()}
                className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-2.5 py-1.5 text-xs text-white hover:bg-emerald-700 transition-colors"
              >
                <ThumbsUp size={12} />
                批准本场景
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
