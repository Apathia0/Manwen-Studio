import type { CanvasOpsPreview, CanvasPreviewNodeItem } from '../../api';

/** 字段路径转成用户可读名称；未收录的字段原样显示。 */
const FIELD_LABELS: Record<string, string> = {
  'data.label': '标题',
  'data.config.prompt': '提示词',
  'data.config.negative_prompt': '负面提示词',
  'data.config.content': '正文',
  'data.config.style': '风格',
  'data.config.duration': '时长',
  'data.config.aspect_ratio': '画面比例',
};

const OP_META: Record<CanvasPreviewNodeItem['op'], { text: string; className: string }> = {
  add_node: { text: '新增', className: 'bg-emerald-100 text-emerald-700' },
  update_node: { text: '修改', className: 'bg-amber-100 text-amber-700' },
  delete_node: { text: '删除', className: 'bg-rose-100 text-rose-700' },
};

function fieldLabel(field: string): string {
  return FIELD_LABELS[field] || field.replace(/^data\.(config\.)?/, '');
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '（空）';
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

interface Props {
  preview: CanvasOpsPreview;
  /** 版本恢复场景下“前/后”含义不同，可自定义列标题 */
  beforeTitle?: string;
  afterTitle?: string;
}

/** 画布改动的前后对比：按节点、按字段展示，供用户在写入前审阅。 */
export default function CanvasPreviewDiff({ preview, beforeTitle = '修改前', afterTitle = '修改后' }: Props) {
  const { summary } = preview;
  const parts = [
    summary.added_nodes && `新增 ${summary.added_nodes} 个节点`,
    summary.updated_nodes && `修改 ${summary.updated_nodes} 个节点`,
    summary.deleted_nodes && `删除 ${summary.deleted_nodes} 个节点`,
    summary.added_edges && `新增 ${summary.added_edges} 条连线`,
    summary.deleted_edges && `删除 ${summary.deleted_edges} 条连线`,
  ].filter(Boolean) as string[];

  if (!preview.nodes.length && !preview.edges.length) {
    return <p className="mt-2 rounded-lg border border-blue-100 bg-white p-2 text-xs text-slate-500">没有检测到内容变化。</p>;
  }

  return (
    <div className="mt-2 rounded-lg border border-blue-100 bg-white p-2" aria-label="改动预览">
      <p className="mb-2 text-xs font-medium text-blue-700">{parts.join('，')}</p>
      <div className="max-h-80 space-y-3 overflow-y-auto">
        {preview.nodes.map((node) => (
          <div key={`${node.op}-${node.node_id}`} className="rounded-md border border-slate-200 p-2">
            <div className="flex items-center gap-2 text-xs">
              <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${OP_META[node.op].className}`}>{OP_META[node.op].text}</span>
              <strong className="truncate text-slate-700">{node.label || node.node_id}</strong>
              <span className="shrink-0 text-[10px] text-slate-400">{node.type}</span>
            </div>
            {node.changes.map((change) => (
              <div key={change.field} className="mt-2">
                <p className="mb-1 text-[11px] font-semibold text-slate-500">{fieldLabel(change.field)}</p>
                {node.op !== 'add_node' && (
                  <div className="rounded border border-rose-100 bg-rose-50 p-1.5">
                    <p className="text-[10px] text-rose-500">{beforeTitle}</p>
                    <pre className="whitespace-pre-wrap break-words font-sans text-xs leading-5 text-slate-600 line-through decoration-rose-300">{formatValue(change.before)}</pre>
                  </div>
                )}
                <div className="mt-1 rounded border border-emerald-100 bg-emerald-50 p-1.5">
                  <p className="text-[10px] text-emerald-600">{afterTitle}</p>
                  <pre className="whitespace-pre-wrap break-words font-sans text-xs leading-5 text-slate-700">{formatValue(change.after)}</pre>
                </div>
              </div>
            ))}
          </div>
        ))}
        {preview.edges.map((edge) => (
          <div key={`${edge.op}-${edge.source}-${edge.target}`} className="flex items-center gap-2 rounded-md border border-slate-200 p-2 text-xs">
            <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${edge.op === 'add_edge' ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'}`}>{edge.op === 'add_edge' ? '新增连线' : '删除连线'}</span>
            <span className="truncate text-slate-600">{edge.source_label} → {edge.target_label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
