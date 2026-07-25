import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from 'react';
import { AlertTriangle, CheckCircle2, Download, FileText, Loader2, Upload, X } from 'lucide-react';
import { createPortal } from 'react-dom';
import {
  commitMangaStoryboardImport,
  previewMangaStoryboardImport,
  previewMangaStoryboardImportFile,
  type MangaStoryboardImportResult,
} from '../api';

interface Props {
  chapterId: number;
  chapterTitle: string;
  onClose: () => void;
  onImported: (result: MangaStoryboardImportResult) => void | Promise<void>;
}

type ImportMode = 'file' | 'paste' | 'chapter_content';

const MAX_FILE_SIZE = 5 * 1024 * 1024;
const ALLOWED_EXTENSIONS = ['txt', 'md', 'docx'];
const TEMPLATE_CONTENT = `第一话
景别：中景
画面：雨夜，女主推开咖啡馆大门，门外霓虹倒映在积水中。
对白：女主：“还有人在吗？”

第二话
景别：近景
画面：柜台后的男人缓缓抬头，半张脸藏在暖色灯影里。
对白：男人：“等你很久了。”
`;

function downloadTemplate() {
  const blob = new Blob([TEMPLATE_CONTENT], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = 'StoryCanvas-漫画分镜导入模板.txt';
  anchor.click();
  URL.revokeObjectURL(url);
}

function validateFile(file: File): string | null {
  const extension = file.name.split('.').pop()?.toLowerCase() || '';
  if (!ALLOWED_EXTENSIONS.includes(extension)) return '仅支持 .txt、.md、.docx 文件。';
  if (file.size > MAX_FILE_SIZE) return '文件不能超过 5 MB。';
  return null;
}

export default function MangaStoryboardImportModal({ chapterId, chapterTitle, onClose, onImported }: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<ImportMode>('file');
  const [file, setFile] = useState<File | null>(null);
  const [pasteText, setPasteText] = useState('');
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState<MangaStoryboardImportResult | null>(null);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [busy, onClose]);

  const selectMode = (nextMode: ImportMode) => {
    setMode(nextMode);
    setPreview(null);
    setError('');
  };

  const selectFile = (nextFile: File) => {
    const validationError = validateFile(nextFile);
    if (validationError) {
      setFile(null);
      setError(validationError);
      return;
    }
    setFile(nextFile);
    setPreview(null);
    setError('');
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextFile = event.target.files?.[0];
    if (nextFile) selectFile(nextFile);
    event.target.value = '';
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const nextFile = event.dataTransfer.files?.[0];
    if (nextFile) selectFile(nextFile);
  };

  const handlePreview = async () => {
    setBusy(true);
    setError('');
    try {
      const result = mode === 'file'
        ? await previewMangaStoryboardImportFile(chapterId, file!)
        : await previewMangaStoryboardImport(chapterId, {
            source_kind: mode,
            content: mode === 'paste' ? pasteText : undefined,
          });
      setPreview(result);
    } catch (err: any) {
      setError(err.message || '解析分镜失败。');
    } finally {
      setBusy(false);
    }
  };

  const handleCommit = async () => {
    if (!preview) return;
    setBusy(true);
    setError('');
    try {
      const result = await commitMangaStoryboardImport(chapterId, {
        scenes: preview.scenes,
        expected_revision: preview.revision,
        canonical_hash: preview.canonical_hash,
      });
      await onImported(result);
      onClose();
    } catch (err: any) {
      setError(err.message || '导入分镜失败。');
    } finally {
      setBusy(false);
    }
  };

  const canPreview = mode === 'file' ? Boolean(file) : mode === 'paste' ? Boolean(pasteText.trim()) : true;

  const modal = (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm" onMouseDown={() => { if (!busy) onClose(); }}>
      <section className="flex max-h-[90vh] w-[min(980px,96vw)] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_28px_80px_rgba(15,23,42,0.32)]" onMouseDown={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="manga-storyboard-import-title">
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
          <div className="min-w-0">
            <h2 id="manga-storyboard-import-title" className="text-base font-semibold text-slate-900">导入漫画分镜</h2>
            <p className="mt-1 truncate text-xs text-slate-500">{chapterTitle} · 支持任意 1–20 格分镜</p>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={downloadTemplate} className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"><Download size={14} />下载模板</button>
            <button type="button" disabled={busy} onClick={onClose} className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-40" aria-label="关闭导入窗口"><X size={18} /></button>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          <div className="inline-flex rounded-lg bg-slate-100 p-1" role="tablist" aria-label="分镜导入方式">
            {([
              ['file', '上传文件'],
              ['paste', '粘贴脚本'],
              ['chapter_content', '从正文识别'],
            ] as Array<[ImportMode, string]>).map(([value, label]) => (
              <button key={value} type="button" role="tab" aria-selected={mode === value} onClick={() => selectMode(value)} className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${mode === value ? 'bg-white text-blue-700 shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}>{label}</button>
            ))}
          </div>

          {!preview ? (
            <div className="mt-5 space-y-4">
              {mode === 'file' ? (
                <div onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={handleDrop} onClick={() => fileInputRef.current?.click()} className={`cursor-pointer rounded-xl border-2 border-dashed px-6 py-12 text-center transition ${dragging ? 'border-blue-400 bg-blue-50' : 'border-slate-300 bg-slate-50 hover:border-blue-300 hover:bg-blue-50/50'}`}>
                  <Upload size={26} className="mx-auto text-blue-500" />
                  <p className="mt-3 text-sm font-medium text-slate-800">拖入文件或点击选择</p>
                  <p className="mt-1 text-xs text-slate-500">支持 .txt / .md / .docx，最多 5 MB</p>
                  {file ? <div className="mt-4 inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700"><FileText size={14} />{file.name}</div> : null}
                  <input ref={fileInputRef} type="file" accept=".txt,.md,.docx" className="hidden" onChange={handleFileChange} />
                </div>
              ) : mode === 'paste' ? (
                <textarea value={pasteText} onChange={(event) => setPasteText(event.target.value)} rows={16} placeholder={TEMPLATE_CONTENT} className="w-full resize-y rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 font-mono text-xs leading-6 text-slate-800 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" />
              ) : (
                <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-4 text-sm leading-6 text-blue-900">
                  系统会识别正文中独占一行的“第一话”“第二话”“第三话”等标题，并将每个标题下面的内容作为一格分镜。正文不会被修改。
                </div>
              )}
            </div>
          ) : (
            <div className="mt-5 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3">
                <div className="flex items-center gap-2 text-sm font-medium text-emerald-800"><CheckCircle2 size={17} />已正确识别 {preview.scene_count} 格分镜</div>
                {preview.generated_image_indices.length > 0 ? <span className="text-xs text-amber-700">本章已有 {preview.generated_image_indices.length} 张漫画图</span> : null}
              </div>

              {preview.warnings.length > 0 ? <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-800">{preview.warnings.map((message, index) => <div key={`${message}-${index}`}>{message}</div>)}</div> : null}
              {preview.errors.length > 0 ? <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs leading-5 text-rose-700">{preview.errors.map((message, index) => <div key={`${message}-${index}`}>{message}</div>)}</div> : null}
              {preview.stale_image_indices.length > 0 ? <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-800"><AlertTriangle size={16} className="mt-0.5 shrink-0" /><span>导入后第 {preview.stale_image_indices.join('、')} 格的已有图片将与新脚本不一致，需要重新生成。</span></div> : null}

              <ol className="space-y-3">
                {preview.scenes.map((scene, index) => (
                  <li key={index} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                    <div className="mb-2 text-xs font-semibold text-blue-700">第 {index + 1} 格</div>
                    <div className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">{scene}</div>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {error ? <div className="mt-4 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700"><AlertTriangle size={17} className="mt-0.5 shrink-0" />{error}</div> : null}
        </div>

        <footer className="flex shrink-0 items-center justify-end gap-2 border-t border-slate-200 px-5 py-4">
          {preview ? <button type="button" disabled={busy} onClick={() => { setPreview(null); setError(''); }} className="rounded-md border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-40">返回修改</button> : null}
          <button type="button" disabled={busy} onClick={onClose} className="rounded-md px-4 py-2 text-sm text-slate-500 hover:text-slate-800 disabled:opacity-40">取消</button>
          {preview ? (
            <button type="button" disabled={busy || !preview.can_commit || preview.errors.length > 0} onClick={() => void handleCommit()} className="inline-flex min-w-28 items-center justify-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40">{busy ? <Loader2 size={15} className="animate-spin" /> : null}{busy ? '导入中...' : '确认导入'}</button>
          ) : (
            <button type="button" disabled={busy || !canPreview} onClick={() => void handlePreview()} className="inline-flex min-w-28 items-center justify-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40">{busy ? <Loader2 size={15} className="animate-spin" /> : null}{busy ? '解析中...' : '解析并预览'}</button>
          )}
        </footer>
      </section>
    </div>
  );

  return createPortal(modal, document.body);
}
