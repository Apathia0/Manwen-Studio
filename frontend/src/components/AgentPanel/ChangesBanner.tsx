import { useState } from 'react';
import { Check, Undo2, Loader2, Eye } from 'lucide-react';
import ChangeDiffModal from './ChangeDiffModal';
import { toast } from '../../lib/toast';

export interface PendingChangeItem {
  type: string;
  record_id: number;
  display_name: string;
  field: string;
}

interface ChangesBannerProps {
  changes: PendingChangeItem[];
  storyId: number;
  conversationId?: number | null;
  runId?: string | null;
  onConfirm: () => void;
  onRollback: () => void;
}

export default function ChangesBanner({ changes, storyId, conversationId, runId, onConfirm, onRollback }: ChangesBannerProps) {
  const [busy, setBusy] = useState<'confirming' | 'rolling' | null>(null);
  const [showDiff, setShowDiff] = useState(false);

  if (changes.length === 0) return null;

  const handleConfirm = async () => {
    setBusy('confirming');
    try {
      const { agentConfirmChanges } = await import('../../api');
      await agentConfirmChanges(storyId, conversationId, runId);
      onConfirm();
    } finally {
      setBusy(null);
    }
  };

  const handleRollback = async () => {
    setBusy('rolling');
    try {
      const { agentRollbackChanges } = await import('../../api');
      const result = await agentRollbackChanges(storyId, conversationId, runId);
      if (result.pending_retained) {
        const message = result.results?.find((item) => !item.ok)?.error || '部分修改已发生变化，无法安全撤回';
        toast.error(message, 8000);
        return;
      }
      onRollback();
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <div className="border-t border-blue-200 bg-blue-50/60 px-4 py-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse shrink-0" />
            <span className="text-xs text-blue-600 truncate">
              已保存 <span className="font-semibold">{changes.length}</span> 项修改，可查看或撤回
            </span>
          </div>
          <div className="flex items-center gap-2 shrink-0 ml-3">
            <button
              onClick={() => setShowDiff(true)}
              disabled={busy !== null}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-100 hover:bg-blue-200 disabled:opacity-50 text-blue-700 text-xs font-medium transition-colors"
            >
              <Eye size={14} />
              查看对比
            </button>
            <button
              onClick={handleConfirm}
              disabled={busy !== null}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white text-xs font-medium transition-colors"
            >
              {busy === 'confirming' ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Check size={14} />
              )}
              保留修改
            </button>
            <button
              onClick={handleRollback}
              disabled={busy !== null}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-100 hover:bg-red-200 disabled:opacity-50 text-red-600 text-xs font-medium transition-colors"
            >
              {busy === 'rolling' ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Undo2 size={14} />
              )}
              撤回修改
            </button>
          </div>
        </div>
      </div>

      {showDiff && (
        <ChangeDiffModal
          storyId={storyId}
          conversationId={conversationId}
          runId={runId}
          onConfirm={() => { setShowDiff(false); onConfirm(); }}
          onRollback={() => { setShowDiff(false); onRollback(); }}
          onClose={() => setShowDiff(false)}
        />
      )}
    </>
  );
}
