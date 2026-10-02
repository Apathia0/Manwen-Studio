import { useState } from 'react';
import {
  ChevronDown,
  Loader2,
  Pencil,
  Save,
  Sparkles,
  X,
} from 'lucide-react';
import type { VolumeItem } from '../../api';

interface Props {
  volumes: VolumeItem[] | null;
  onGenerate: () => Promise<void>;
  onUpdate: (volumes: VolumeItem[]) => Promise<void>;
  loading: boolean;
}

export default function VolumePanel({ volumes, onGenerate, onUpdate, loading }: Props) {
  const [展开状态, set展开状态] = useState<Record<string, boolean>>({});
  const [编辑中卷ID, set编辑中卷ID] = useState<string | null>(null);
  const [编辑表单, set编辑表单] = useState<VolumeItem | null>(null);
  const [保存中, set保存中] = useState(false);

  function 切换展开(volumeId: string) {
    set展开状态((prev) => ({ ...prev, [volumeId]: !prev[volumeId] }));
  }

  function 开始编辑(volume: VolumeItem) {
    set编辑中卷ID(volume.id);
    set编辑表单({ ...volume });
  }

  function 取消编辑() {
    set编辑中卷ID(null);
    set编辑表单(null);
  }

  function 处理编辑变更(field: keyof VolumeItem, value: string) {
    if (!编辑表单) return;
    set编辑表单({ ...编辑表单, [field]: value });
  }

  async function 保存编辑() {
    if (!volumes || !编辑表单) return;
    set保存中(true);
    try {
      const 更新后的卷 = volumes.map((vol) => (vol.id === 编辑表单.id ? 编辑表单 : vol));
      await onUpdate(更新后的卷);
      set编辑中卷ID(null);
      set编辑表单(null);
    } finally {
      set保存中(false);
    }
  }

  function 渲染卷卡片(volume: VolumeItem, index: number) {
    const 展开 = 展开状态[volume.id] ?? false;
    const 正在编辑 = 编辑中卷ID === volume.id;
    const data = 正在编辑 && 编辑表单 ? 编辑表单 : volume;

    return (
      <div
        key={volume.id}
        className="rounded-xl border border-[#d7e3f4] bg-white overflow-hidden transition-all"
      >
        <button
          onClick={() => 切换展开(volume.id)}
          className="w-full flex items-center justify-between px-4 py-3 hover:bg-[#fafdff] transition-colors"
        >
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex items-center justify-center w-7 h-7 rounded-lg bg-blue-50 text-[#2563eb] text-xs font-bold shrink-0">
              {index + 1}
            </div>
            <div className="text-left min-w-0">
              <div className="text-sm font-semibold text-slate-800 truncate">{data.title || `第 ${index + 1} 卷`}</div>
              <div className="text-[10px] text-slate-500 mt-0.5">
                第 {data.chapter_start}–{data.chapter_end}章
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            {!正在编辑 && (
              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-blue-50 text-blue-700 border border-blue-200">
                第{data.chapter_start}-{data.chapter_end}章
              </span>
            )}
            <ChevronDown
              size={15}
              className={`text-slate-400 transition-transform duration-200 ${展开 ? '' : '-rotate-90'}`}
            />
          </div>
        </button>

        {展开 && (
          <div className="border-t border-[#d7e3f4] px-4 py-3 space-y-2.5">
            {正在编辑 ? (
              <>
                <编辑字段 label="卷名" value={data.title} onChange={(v) => 处理编辑变更('title', v)} />
                <编辑字段 label="摘要" value={data.summary} onChange={(v) => 处理编辑变更('summary', v)} />
                <编辑字段 label="目标" value={data.goal} onChange={(v) => 处理编辑变更('goal', v)} />
                <编辑字段 label="核心冲突" value={data.core_conflict} onChange={(v) => 处理编辑变更('core_conflict', v)} />
                <编辑字段 label="高潮" value={data.climax} onChange={(v) => 处理编辑变更('climax', v)} />
                <编辑字段 label="结尾钩子" value={data.ending_hook} onChange={(v) => 处理编辑变更('ending_hook', v)} />
                <编辑字段 label="关联阶段" value={data.linked_phase} onChange={(v) => 处理编辑变更('linked_phase', v)} />
                <div className="flex items-center gap-2 pt-2">
                  <button
                    onClick={() => void 保存编辑()}
                    disabled={保存中}
                    className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg
                               bg-[#2563eb] hover:bg-[#1d4ed8] text-white disabled:opacity-40 transition-colors"
                  >
                    {保存中 ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                    保存
                  </button>
                  <button
                    onClick={取消编辑}
                    disabled={保存中}
                    className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg
                               border border-[#d7e3f4] text-slate-600 hover:bg-slate-50 disabled:opacity-40 transition-colors"
                  >
                    <X size={12} />
                    取消
                  </button>
                </div>
              </>
            ) : (
              <>
                <详情行 label="摘要" value={data.summary} />
                <详情行 label="目标" value={data.goal} />
                <详情行 label="核心冲突" value={data.core_conflict} />
                <详情行 label="高潮" value={data.climax} />
                <详情行 label="结尾钩子" value={data.ending_hook} />
                <详情行 label="关联阶段" value={data.linked_phase} />
                <div className="pt-1">
                  <button
                    onClick={() => 开始编辑(volume)}
                    className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg
                               border border-[#d7e3f4] text-slate-600 hover:bg-slate-50 transition-colors"
                  >
                    <Pencil size={12} />
                    编辑
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-[#fcfcfa]">
      <div className="flex items-center justify-between px-5 py-3 border-b border-[#d7e3f4] shrink-0">
        <div className="flex items-center gap-2">
          <Sparkles size={15} className="text-[#2563eb]" />
          <h2 className="text-sm font-semibold text-slate-900 tracking-wide">卷纲规划</h2>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {!volumes || volumes.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full px-5 text-center">
            <Sparkles size={36} className="text-[#93c5fd] mb-3" />
            <p className="text-sm text-slate-600 mb-4 leading-relaxed">
              生成卷纲规划，将长篇小说分卷管理，每卷设定独立的目标、冲突和高潮，让长篇创作更有条理。
            </p>
            <button
              onClick={() => void onGenerate()}
              disabled={loading}
              className="inline-flex items-center gap-1.5 px-5 py-2.5 text-sm font-medium rounded-xl
                         bg-[#2563eb] hover:bg-[#1d4ed8] text-white shadow-[0_8px_20px_rgba(37,99,235,0.2)]
                         disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              {loading ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
              {loading ? '正在生成...' : '生成卷纲规划'}
            </button>
          </div>
        ) : (
          <div className="px-5 py-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-500">
                共 {volumes.length} 卷 · {volumes.reduce((sum, v) => sum + v.chapter_end - v.chapter_start + 1, 0)} 章
              </span>
              <button
                onClick={() => void onGenerate()}
                disabled={loading}
                className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg
                           bg-blue-50 text-blue-700 border border-blue-200 hover:bg-blue-100
                           disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {loading ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                {loading ? '生成中...' : '重新生成'}
              </button>
            </div>
            <div className="relative pl-6 space-y-3">
              <div className="absolute left-2.5 top-0 bottom-0 w-px bg-[#d7e3f4]" />
              {volumes.map((volume, index) => (
                <div key={volume.id} className="relative">
                  <div className="absolute -left-[18px] top-4 w-[10px] h-[10px] rounded-full bg-[#2563eb] border-2 border-white shadow-[0_0_0_2px_#dbeafe]" />
                  {渲染卷卡片(volume, index)}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function 详情行({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div>
      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</span>
      <p className="text-xs text-slate-700 mt-0.5 leading-relaxed whitespace-pre-wrap">{value}</p>
    </div>
  );
}

function 编辑字段({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1 block">{label}</label>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={2}
        className="w-full rounded-lg border border-[#d7e3f4] bg-[#fafdff] px-3 py-1.5 text-xs text-slate-800
                   outline-none focus:border-[#93c5fd] focus:bg-white transition-colors resize-y"
      />
    </div>
  );
}
