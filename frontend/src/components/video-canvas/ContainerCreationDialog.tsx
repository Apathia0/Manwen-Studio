import { Folder, Save } from 'lucide-react';
import { useState, type ReactNode } from 'react';

interface Props {
  availableNodes: Array<{ id: string; label?: string; type: string }>;
  onSelectAll?: () => void;
  onClose: () => void;
  onCreate: (name: string, nodeIds: string[]) => void;
}

export default function ContainerCreationDialog({ availableNodes, onSelectAll, onClose, onCreate }: Props): ReactNode {
  const [name, setName] = useState('');
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);

  // Auto-select all image/video nodes by default
  useEffect(() => {
    const mediaNodes = availableNodes.filter(n => ['image', 'video', 'asset', 'video_asset'].includes(n.type));
    if (mediaNodes.length > 0) setSelectedNodeIds(mediaNodes.map(n => n.id));
  }, [availableNodes]);

  const handleToggleNode = (nodeId: string) => {
    setSelectedNodeIds(prev => prev.includes(nodeId) ? prev.filter(id => id !== nodeId) : [...prev, nodeId]);
  };

  const filtered = availableNodes.filter(n => selectedNodeIds.includes(n.id));
  const categories: Record<string, typeof filtered> = {};
  filtered.forEach(node => {
    const cat = ['image', 'asset'].includes(node.type) ? '图片资产' : ['video', 'video_asset'].includes(node.type) ? '视频资产' : '其他';
    categories[cat] = categories[cat] || [];
    categories[cat].push(node);
  });

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="w-[520px] rounded-xl border border-[#403833] bg-[#2a2724] p-4 shadow-[0_20px_50px_rgba(0,0,0,.6)]" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Folder size={16} className="text-[#d4c9b9]" />
            <h3 className="text-sm font-semibold text-white">创建资产容器</h3>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1 text-[#78818f] hover:bg-white/5 hover:text-white">×</button>
        </div>

        {/* Input name */}
        <div className="mb-3">
          <label className="mb-1.5 block text-xs text-[#8b93a1]">容器名称（可选）</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例如：角色资产 / 场景库 / 道具集合"
            className="w-full rounded-lg border border-[#3b3f45] bg-[#1e2025] px-3 py-2 text-sm text-white placeholder:text-[#6b7280] focus:border-[#73a7ff] focus:outline-none"
          />
        </div>

        {/* Node selection */}
        <div className="mb-4">
          <div className="mb-2 flex items-center justify-between">
            <label className="text-xs text-[#8b93a1]">选择资产节点</label>
            {availableNodes.length > 0 && (
              <button type="button" onClick={onSelectAll} className="text-xs text-[#73a7ff] hover:text-[#8db6ff]">全选媒体节点</button>
            )}
          </div>
          <div className="max-h-[240px] overflow-y-auto rounded-lg border border-[#35393f] bg-[#1e2025]">
            {Object.entries(categories).map(([cat, nodes]) => (
              <div key={cat} className="border-b border-[#35393f] last:border-0">
                <div className="sticky top-0 z-10 bg-[#1a1c20] px-3 py-1.5 text-[10px] font-medium text-[#78818f]">{cat} ({nodes.length})</div>
                {nodes.map(node => (
                  <label key={node.id} className="flex cursor-pointer items-center gap-2 px-3 py-2 text-xs text-[#aeb3be] hover:bg-white/[.03]">
                    <input
                      type="checkbox"
                      checked={selectedNodeIds.includes(node.id)}
                      onChange={() => handleToggleNode(node.id)}
                      className="mr-1 h-3 w-3 rounded border-[#3b3f45] bg-[#15171a] accent-[#73a7ff]"
                    />
                    <span className="truncate">{node.label || `${node.type} · ${node.id.slice(0,8)}`}</span>
                  </label>
                ))}
              </div>
            ))}
            {filtered.length === 0 && (
              <div className="flex h-[120px] items-center justify-center text-xs text-[#6b7280]">暂无资产节点</div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-[#403833] bg-[#25272c] px-4 py-2 text-xs text-[#b6babe] transition-colors hover:bg-[#30333b]">取消</button>
          <button
            type="button"
            disabled={selectedNodeIds.length < 1}
            onClick={() => onCreate(name.trim() || '未命名容器', selectedNodeIds)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[#73a7ff] px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-[#8db6ff] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Save size={14} />
            创建容器
          </button>
        </div>
      </div>
    </div>
  );
}
