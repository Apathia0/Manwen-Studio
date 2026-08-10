import { useEffect, useMemo, useRef, useState, type ChangeEvent, type DragEvent } from 'react';
import { AlertCircle, Check, ChevronDown, FileText, Loader2, Upload } from 'lucide-react';
import { createImportStory, parseImportFile, type ImportChapterInfo, type ImportParseResponse } from '../api';
import { FullScreenDialog } from './mobile/FullScreenDialog';

interface ImportDialogProps {
  open: boolean;
  onClose: () => void;
  onImportComplete: (storyId: number) => void;
}

type Step = 'select' | 'uploading' | 'preview' | 'creating' | 'done';

const ALLOWED_EXTENSIONS = ['txt', 'md', 'docx'];
const MAX_FILE_SIZE = 10 * 1024 * 1024;

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ImportDialog({ open, onClose, onImportComplete }: ImportDialogProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<Step>('select');
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [progress, setProgress] = useState(0);
  const [parseResult, setParseResult] = useState<ImportParseResponse | null>(null);
  const [storyTitle, setStoryTitle] = useState('');
  const [chapters, setChapters] = useState<ImportChapterInfo[]>([]);

  useEffect(() => {
    if (!open) {
      setStep('select');
      setFile(null);
      setError('');
      setDragOver(false);
      setProgress(0);
      setParseResult(null);
      setStoryTitle('');
      setChapters([]);
    }
  }, [open]);

  const totalWords = useMemo(
    () => chapters.reduce((sum, chapter) => sum + (chapter.content?.trim().length || 0), 0),
    [chapters],
  );

  function validateFile(nextFile: File): string | null {
    const ext = nextFile.name.split('.').pop()?.toLowerCase() || '';
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      return '仅支持 .txt、.md、.docx 文件。';
    }
    if (nextFile.size > MAX_FILE_SIZE) {
      return `文件过大，当前 ${formatFileSize(nextFile.size)}，最大支持 10 MB。`;
    }
    return null;
  }

  function handleSelectedFile(nextFile: File) {
    const validationError = validateFile(nextFile);
    if (validationError) {
      setError(validationError);
      setFile(null);
      return;
    }
    setError('');
    setFile(nextFile);
  }

  function handleInputChange(event: ChangeEvent<HTMLInputElement>) {
    const nextFile = event.target.files?.[0];
    if (nextFile) {
      handleSelectedFile(nextFile);
    }
    event.target.value = '';
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragOver(true);
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragOver(false);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragOver(false);
    const nextFile = event.dataTransfer.files?.[0];
    if (nextFile) {
      handleSelectedFile(nextFile);
    }
  }

  async function handleParse() {
    if (!file) return;
    setStep('uploading');
    setProgress(15);
    setError('');
    const timer = window.setInterval(() => {
      setProgress((value) => Math.min(90, value + 12));
    }, 250);
    try {
      const result = await parseImportFile(file);
      window.clearInterval(timer);
      setProgress(100);
      setParseResult(result);
      setStoryTitle(result.detected_title || file.name.replace(/\.[^.]+$/, ''));
      setChapters(result.chapters);
      setStep('preview');
    } catch (err: any) {
      window.clearInterval(timer);
      setStep('select');
      setError(err.message || '文件解析失败。');
    }
  }

  async function handleCreate() {
    if (!parseResult) return;
    setStep('creating');
    setError('');
    try {
      const story = await createImportStory({
        title: storyTitle.trim() || parseResult.detected_title,
        chapters,
        analyze_framework: true,
      });
      setStep('done');
      onImportComplete(story.id);
    } catch (err: any) {
      setStep('preview');
      setError(err.message || '导入失败。');
    }
  }

  function updateChapterTitle(chapterNumber: number, value: string) {
    setChapters((current) =>
      current.map((chapter) =>
        chapter.chapter_number === chapterNumber ? { ...chapter, title: value } : chapter,
      ),
    );
  }

  if (!open) return null;

  const renderFooter = () => {
    if (step === 'select') {
      return (
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="flex h-11 items-center rounded-lg px-5 text-sm text-slate-600 transition hover:bg-slate-100 active:bg-slate-200"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void handleParse()}
            disabled={!file}
            className="flex h-11 items-center rounded-lg bg-blue-600 px-6 text-sm font-medium text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
          >
            开始解析
          </button>
        </div>
      );
    }
    if (step === 'preview') {
      return (
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={() => setStep('select')}
            className="flex h-11 items-center rounded-lg px-5 text-sm text-slate-600 transition hover:bg-slate-100 active:bg-slate-200"
          >
            返回
          </button>
          <button
            type="button"
            onClick={() => void handleCreate()}
            disabled={chapters.length === 0 || !storyTitle.trim()}
            className="flex h-11 items-center rounded-lg bg-blue-600 px-6 text-sm font-medium text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
          >
            确认导入
          </button>
        </div>
      );
    }
    return null;
  };

  return (
    <FullScreenDialog open={open} onClose={onClose} title="导入小说" footer={renderFooter()}>
      <div className="p-4 sm:p-6">
        {step === 'select' && (
          <div className="space-y-4">
            <div
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => inputRef.current?.click()}
              className={`rounded-2xl border-2 border-dashed px-6 py-14 text-center cursor-pointer transition-colors ${
                dragOver ? 'border-blue-400 bg-blue-50' : 'border-slate-300 bg-slate-50 hover:border-blue-300 hover:bg-blue-50/50'
              }`}
            >
              <Upload size={28} className="mx-auto mb-3 text-blue-500" />
              <p className="text-sm font-medium text-slate-800">拖拽文件到这里，或点击选择文件</p>
              <p className="mt-2 text-xs text-slate-500">支持 .txt / .md / .docx，单文件最大 10 MB</p>
              {file && (
                <div className="mt-4 inline-flex items-center gap-2 rounded-full bg-white px-3 py-1.5 text-xs text-slate-600 border border-slate-200">
                  <FileText size={14} />
                  <span>{file.name}</span>
                  <span>{formatFileSize(file.size)}</span>
                </div>
              )}
            </div>
            <input ref={inputRef} type="file" accept=".txt,.md,.docx" className="hidden" onChange={handleInputChange} />
            {error && (
              <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                <AlertCircle size={16} className="mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}
          </div>
        )}

        {step === 'uploading' && (
          <div className="p-8 text-center">
            <Loader2 size={28} className="mx-auto mb-4 text-blue-500 animate-spin" />
            <p className="text-sm font-medium text-slate-800">正在解析文稿...</p>
            <div className="mt-4 h-2 rounded-full bg-slate-100 overflow-hidden">
              <div className="h-full bg-blue-500 transition-all" style={{ width: `${progress}%` }} />
            </div>
            <p className="mt-2 text-xs text-slate-500">{Math.round(progress)}%</p>
          </div>
        )}

        {step === 'preview' && (
          <div className="space-y-4">
            <div className="grid gap-4 md:grid-cols-[1.4fr,0.8fr]">
              <div className="space-y-2">
                <label className="text-xs font-medium text-slate-600">作品名</label>
                <input
                  value={storyTitle}
                  onChange={(event) => setStoryTitle(event.target.value)}
                  className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-blue-400"
                />
              </div>
              <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                <div>识别章节: {chapters.length}</div>
                <div>原始字数: {parseResult?.total_word_count ?? totalWords}</div>
              </div>
            </div>

            <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
              当前导入会强制接入 AI 分析原文，并自动生成标签、角色、大纲与章节规划，不再按本地规则直接拆章。
            </div>

            <div className="overflow-y-auto rounded-2xl border border-slate-200 md:max-h-[360px]">
              {chapters.map((chapter) => (
                <details key={chapter.chapter_number} className="border-b border-slate-100 last:border-b-0" open={chapter.chapter_number <= 2}>
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm text-slate-800">
                    <div className="min-w-0 flex-1">
                      <div className="text-xs text-slate-400">第 {chapter.chapter_number} 章</div>
                      <input
                        value={chapter.title}
                        onClick={(event) => event.stopPropagation()}
                        onChange={(event) => updateChapterTitle(chapter.chapter_number, event.target.value)}
                        className="mt-1 w-full bg-transparent text-sm font-medium text-slate-900 outline-none"
                      />
                    </div>
                    <ChevronDown size={16} className="shrink-0 text-slate-400" />
                  </summary>
                  <div className="px-4 pb-4">
                    <p className="whitespace-pre-wrap break-words text-xs leading-6 text-slate-500">
                      {chapter.content?.slice(0, 1200) || '该章节暂无内容。'}
                    </p>
                  </div>
                </details>
              ))}
            </div>

            {error && <p className="text-sm text-red-600">{error}</p>}
          </div>
        )}

        {step === 'creating' && (
          <div className="p-8 text-center">
            <Loader2 size={28} className="mx-auto mb-4 text-blue-500 animate-spin" />
            <p className="text-sm font-medium text-slate-800">正在创建作品并写入章节...</p>
            <p className="mt-2 text-xs text-slate-500">完成后会自动进入作品工作台。</p>
          </div>
        )}

        {step === 'done' && (
          <div className="p-8 text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
              <Check size={24} />
            </div>
            <p className="text-sm font-medium text-slate-800">导入成功</p>
          </div>
        )}
      </div>
    </FullScreenDialog>
  );
}
