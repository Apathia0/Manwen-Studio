import { useCallback, useEffect, useState } from 'react';
import { History, Loader2, RotateCcw, X } from 'lucide-react';
import {
  diffVideoCanvasVersion,
  listVideoCanvasVersions,
  restoreVideoCanvasVersion,
  type CanvasOpsPreview,
  type VideoCanvasVersionSummary,
} from '../../api';
import { confirm } from '../../lib/confirm';
import { toast } from '../../lib/toast';
import CanvasPreviewDiff from '../AgentPanel/CanvasPreviewDiff';

const SOURCE_LABELS: Record<string, string> = {
  manual: '手动保存',
  agent: '助手修改',
  agent_rollback: '撤回助手修改',
  restore: '版本恢复',
  import: '导入',
};

function formatTime(value: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}

interface Props {
  canvasId: number;
  /** 恢复成功后由画布重新读取服务端内容 */
  onRestored: () => void | Promise<void>;
  onClose: () => void;
}

/** 画布版本历史：查看每次保存/助手修改/撤回产生的版本，预览差异并一键恢复（恢复本身也会产生新版本，可再次回退）。 */
export default function CanvasVersionHistoryModal({ canvasId, onRestored, onClose }: Props) {
  const [versions, setVersions] = useState<VideoCanvasVersionSummary[]>([]);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selectedNo, setSelectedNo] = useState<number | null>(null);
  const [diff, setDiff] = useState<CanvasOpsPreview | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [restoring, setRestoring] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await listVideoCanvasVersions(canvasId, 50);
      setVersions(result.versions);
      setRevision(result.definition_revision);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '读取画布版本历史失败');
    } finally {
      setLoading(false);
    }
  }, [canvasId]);

  useEffect(() => { void load(); }, [load]);

  const selectVersion = async (versionNo: number) => {
    setSelectedNo(versionNo);
    setDiff(null);
    setDiffLoading(true);
    try {
      const result = await diffVideoCanvasVersion(canvasId, versionNo);
      setDiff(result.diff);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '读取版本差异失败');
    } finally {
      setDiffLoading(false);
    }
  };

  const restore = async (versionNo: number) => {
    const accepted = await confirm({
      title: '恢复画布版本',
      message: `将画布恢复为版本 ${versionNo} 的内容。当前内容会保留为历史版本，之后仍可再次切换回来。`,
      confirmText: '恢复',
    });
    if (!accepted) return;
    setRestoring(true);
    try {
      await restoreVideoCanvasVersion(canvasId, versionNo, revision);
      toast.success(`已恢复到版本 ${versionNo}`);
      await onRestored();
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '恢复画布版本失败');
      void load();
    } finally {
      setRestoring(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/55 p-4" role="dialog" aria-modal="true" aria-label="画布版本历史">
      <div className="flex max-h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-[#393633] bg-[#25231f] text-[#ded7d0] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[#393633] px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold"><History className="h-4 w-4" />画布版本历史</div>
          <button type="button" aria-label="关闭" onClick={onClose} className="rounded-md p-1.5 text-[#a49b94] hover:bg-white/10 hover:text-white"><X className="h-4 w-4" /></button>
        </div>
        <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[280px_1fr]">
          <div className="min-h-0 overflow-y-auto border-b border-[#393633] md:border-b-0 md:border-r">
            {loading && <div className="flex items-center gap-2 p-4 text-xs text-[#a49b94]"><Loader2 className="h-4 w-4 animate-spin" />加载中…</div>}
            {!loading && !versions.length && <p className="p-4 text-xs text-[#a49b94]">暂无版本记录。</p>}
            {versions.map((version) => (
              <button
                key={version.id}
                type="button"
                onClick={() => void selectVersion(version.version_no)}
                className={`block w-full border-b border-[#393633]/60 px-4 py-3 text-left text-xs hover:bg-white/5 ${selectedNo === version.version_no ? 'bg-white/10' : ''}`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold">版本 {version.version_no}{version.is_current && <span className="ml-2 rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] text-emerald-300">当前</span>}</span>
                  <span className="text-[10px] text-[#a49b94]">{SOURCE_LABELS[version.source] || version.source}</span>
                </div>
                <p className="mt-1 truncate text-[#a49b94]">{version.change_summary || '无说明'}</p>
                <p className="mt-0.5 text-[10px] text-[#7d756f]">{formatTime(version.created_at)} · {version.node_count} 节点 · {version.edge_count} 连线</p>
              </button>
            ))}
          </div>
          <div className="min-h-0 overflow-y-auto p-4">
            {selectedNo === null && <p className="text-xs text-[#a49b94]">选择左侧版本，查看“恢复到该版本”会带来的变化。</p>}
            {selectedNo !== null && (
              <>
                <div className="mb-3 flex items-center justify-between">
                  <p className="text-sm font-semibold">恢复到版本 {selectedNo} 的变化</p>
                  <button
                    type="button"
                    disabled={restoring || diffLoading || selectedNo === revision}
                    onClick={() => void restore(selectedNo)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-xs font-semibold text-[#24211f] hover:bg-[#f0ebde] disabled:opacity-40"
                  >
                    {restoring ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}恢复到此版本
                  </button>
                </div>
                {diffLoading && <div className="flex items-center gap-2 text-xs text-[#a49b94]"><Loader2 className="h-4 w-4 animate-spin" />读取差异…</div>}
                {diff && <CanvasPreviewDiff preview={diff} beforeTitle="当前" afterTitle="恢复后" />}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
