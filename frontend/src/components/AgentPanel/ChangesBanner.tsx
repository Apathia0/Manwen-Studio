import { useState } from 'react';
import { Check, Undo2, Loader2, Eye } from 'lucide-react';
import ChangeDiffModal from './ChangeDiffModal';

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
  onConfirm: () => void;
  onRollback: () => void;
}

export default function ChangesBanner({ changes, storyId, conversationId, onConfirm, onRollback }: ChangesBannerProps) {
  const [busy, setBusy] = useState<'confirming' | 'rolling' | null>(null);
  const [showDiff, setShowDiff] = useState(false);

  if (changes.length === 0) return null;

  const handleConfirm = async () => {
    setBusy('confirming');
    try {
      const { agentConfirmChanges } = await import('../../api');
      await agentConfirmChanges(storyId, conversationId);
      onConfirm();
    } finally {
      setBusy(null);
    }
  };

  const handleRollback = async () => {
    setBusy('rolling');
    try {
      const { agentRollbackChanges } = await import('../../api');
      await agentRollbackChanges(storyId, conversationId);
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
              有 <span className="font-semibold">{changes.length}</span> 项修改待确认
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
              确认保存
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
          onConfirm={() => { setShowDiff(false); onConfirm(); }}
          onRollback={() => { setShowDiff(false); onRollback(); }}
          onClose={() => setShowDiff(false)}
        />
      )}
    </>
  );
}
