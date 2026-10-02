import { useState } from 'react';
import { Loader2, AlertTriangle, CheckCircle, BarChart3, Eye, Users } from 'lucide-react';
import type { ConsistencyCheckResponse, WritingMonitorResponse } from '../../api';

interface Props {
  consistency?: ConsistencyCheckResponse | null;
  monitor?: WritingMonitorResponse | null;
  onCheck?: () => Promise<ConsistencyCheckResponse>;
}

export default function ConsistencyCheckPanel({ consistency: initialConsistency = null, monitor = null, onCheck }: Props) {
  const [consistency, setConsistency] = useState<ConsistencyCheckResponse | null>(initialConsistency);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState('');

  const handleCheck = async () => {
    if (!onCheck) return;
    setChecking(true);
    setError('');
    try {
      setConsistency(await onCheck());
    } catch (error: unknown) {
      setError(error instanceof Error ? error.message : '检测失败');
    } finally {
      setChecking(false);
    }
  };

  const severityColor = (s: string) => {
    switch (s) {
      case 'high': return 'text-red-600 bg-red-50 border-red-200';
      case 'medium': return 'text-amber-600 bg-amber-50 border-amber-200';
      default: return 'text-blue-600 bg-blue-50 border-blue-200';
    }
  };

  const severityLabel = (s: string) => {
    switch (s) {
      case 'high': return '严重';
      case 'medium': return '中等';
      default: return '轻微';
    }
  };

  return (
    <div className="p-4 space-y-4">
      {monitor && (
        <div className="rounded-xl border border-[#d7e3f4] bg-white p-3 space-y-2">
          <h4 className="text-xs font-semibold text-gray-700 flex items-center gap-1.5">
            <BarChart3 size={14} className="text-blue-600" />
            写作状态
          </h4>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-lg bg-blue-50 px-2.5 py-2">
              <span className="text-slate-500">阶段</span>
              <p className="font-medium text-blue-800">{monitor.current_stage}</p>
            </div>
            <div className="rounded-lg bg-blue-50 px-2.5 py-2">
              <span className="text-slate-500">当前卷</span>
              <p className="font-medium text-blue-800">{monitor.current_volume || '--'}</p>
            </div>
          </div>
          {monitor.inactive_characters?.length > 0 && (
            <div className="flex items-start gap-1.5 text-xs text-amber-700">
              <Users size={13} className="mt-0.5 shrink-0" />
              <span>可能掉线的角色：{monitor.inactive_characters.slice(0, 3).join('、')}</span>
            </div>
          )}
          {monitor.pace_alerts?.map((alert, i) => (
            <div key={i} className="flex items-start gap-1.5 text-xs text-slate-600">
              <Eye size={13} className="mt-0.5 shrink-0" />
              <span>{alert}</span>
            </div>
          ))}
          {monitor.next_recommendations?.map((rec, i) => (
            <div key={i} className="rounded-lg bg-green-50 px-2.5 py-1.5 text-xs text-green-700">
              {rec}
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
          <AlertTriangle size={16} className="text-blue-600" />
          一致性检测
        </h3>
        <button
          onClick={handleCheck}
          disabled={checking || !onCheck}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg
                     bg-[#2563eb] text-white shadow-[0_8px_20px_rgba(37,99,235,0.2)]
                     hover:bg-[#1d4ed8] disabled:opacity-50 disabled:cursor-not-allowed transition-all"
        >
          {checking ? <Loader2 size={14} className="animate-spin" /> : <AlertTriangle size={14} />}
          {checking ? '检测中...' : '检测一致性'}
        </button>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-600">{error}</div>
      )}

      {consistency?.issues && consistency.issues.length > 0 && (
        <div className="space-y-2">
          {consistency.issues.map((issue, i) => (
            <div
              key={i}
              className={`rounded-xl border p-3 ${severityColor(issue.severity)}`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-semibold">{issue.type}</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-white/60">
                  {severityLabel(issue.severity)}
                  {issue.chapter_number ? ` · 第${issue.chapter_number}章` : ''}
                </span>
              </div>
              <p className="text-xs opacity-80">{issue.message}</p>
              {issue.suggestion && (
                <p className="text-xs opacity-60 mt-1 italic">建议：{issue.suggestion}</p>
              )}
            </div>
          ))}
        </div>
      )}

      {consistency?.issues && consistency.issues.length === 0 && (
        <div className="rounded-xl border border-green-200 bg-green-50 p-4 text-center">
          <CheckCircle size={24} className="mx-auto text-green-500 mb-1" />
          <p className="text-xs text-green-700 font-medium">未发现设定一致性问题</p>
        </div>
      )}

      {!consistency && !checking && (
        <div className="rounded-xl border border-dashed border-[#d7e3f4] bg-white/50 p-6 text-center">
          <AlertTriangle size={32} className="mx-auto text-slate-300 mb-2" />
          <p className="text-xs text-slate-500">检测故事中人设、时间线、伏笔等一致性问题</p>
        </div>
      )}
    </div>
  );
}
