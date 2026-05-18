import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  Check,
  ChevronRight,
  FileText,
  Loader2,
  MessageSquare,
  Send,
  Sparkles,
} from 'lucide-react';
import {
  confirmImportGuidance,
  sendImportGuidanceMessage,
  skipImportGuidance,
  type CreativeBrief,
  type OnboardingChatMessage,
  type Story,
} from '../api';

const STEPS = ['导入类型', '保留项', '后续目标', '可调整范围'];

const INITIAL_PROMPT =
  '已读取你导入的作品内容。接下来我会用 3 到 4 个问题，快速补齐后续续写和框架调整最关键的上下文。先告诉我：你导入的是旧正文、旧大纲，还是两者混合？';

interface Props {
  story: Story;
  onComplete: (storyId: number) => void;
  onBack: () => void;
}

export default function ImportGuidancePage({ story, onComplete, onBack }: Props) {
  const [messages, setMessages] = useState<OnboardingChatMessage[]>([
    { role: 'assistant', content: INITIAL_PROMPT },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [collectedInfo, setCollectedInfo] = useState<Record<string, string>>({});
  const [creativeBrief, setCreativeBrief] = useState<CreativeBrief | null>(
    (story.story_bible?.creative_brief as CreativeBrief | undefined) ?? null,
  );
  const [step, setStep] = useState(1);
  const [isComplete, setIsComplete] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [skipLoading, setSkipLoading] = useState(false);
  const [error, setError] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (!loading) {
      inputRef.current?.focus();
    }
  }, [loading]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;

    setInput('');
    setError('');

    const userMsg: OnboardingChatMessage = { role: 'user', content: text };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setLoading(true);

    try {
      const result = await sendImportGuidanceMessage(story.id, updatedMessages, collectedInfo, step);
      const assistantMsg: OnboardingChatMessage = { role: 'assistant', content: result.reply };
      setMessages((prev) => [...prev, assistantMsg]);
      setCollectedInfo(result.collected_info);
      setCreativeBrief((result.creative_brief as CreativeBrief | undefined) ?? null);
      setStep(result.step);
      setIsComplete(result.is_complete);
      if (result.is_complete) {
        setShowConfirm(true);
      }
    } catch (err: any) {
      setError(err.message || '导入补充对话失败，请重试');
    } finally {
      setLoading(false);
    }
  }, [collectedInfo, input, loading, messages, step, story.id]);

  const handleConfirm = async () => {
    setConfirmLoading(true);
    setError('');
    try {
      await confirmImportGuidance(story.id, collectedInfo, messages);
      onComplete(story.id);
    } catch (err: any) {
      setError(err.message || '确认失败，请重试');
    } finally {
      setConfirmLoading(false);
    }
  };

  const handleSkip = async () => {
    setSkipLoading(true);
    setError('');
    try {
      await skipImportGuidance(story.id);
      onComplete(story.id);
    } catch (err: any) {
      setError(err.message || '跳过失败，请重试');
    } finally {
      setSkipLoading(false);
    }
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void handleSend();
    }
  };

  const canShowSummary = Object.keys(collectedInfo).length > 0;

  return (
    <div className="mx-auto flex h-[calc(100vh-120px)] max-w-7xl flex-col overflow-hidden rounded-2xl border border-[#d7e3f4] bg-white shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
      <div className="flex items-center justify-between border-b border-[#d7e3f4] bg-[#f8fbff] px-5 py-3">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="rounded-full border border-[#d7e3f4] bg-white p-1.5 text-slate-500 transition hover:bg-[#eff6ff]"
            title="返回"
          >
            <ArrowLeft size={16} />
          </button>
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Sparkles size={16} className="text-[#2563eb]" />
              导入后补充上下文
            </div>
            <div className="text-xs text-slate-500">{story.title}</div>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <FileText size={14} />
          <span>
            第 {Math.min(step, 4)} 步 / 共 4 步
          </span>
        </div>
      </div>

      <div className="flex items-center gap-1 border-b border-[#e5edf8] bg-white px-5 py-3">
        {STEPS.map((label, idx) => {
          const stepNum = idx + 1;
          const isActive = stepNum === step;
          const isDone = stepNum < step || (stepNum === step && isComplete);
          return (
            <div key={label} className="flex items-center gap-1">
              <div
                className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition ${
                  isActive
                    ? 'bg-[#2563eb] text-white shadow-[0_4px_12px_rgba(37,99,235,0.3)]'
                    : isDone
                      ? 'bg-[#dbeafe] text-[#1d4ed8]'
                      : 'bg-[#f1f5f9] text-slate-400'
                }`}
              >
                {isDone ? <Check size={12} /> : <span>{stepNum}</span>}
                <span className="hidden sm:inline">{label}</span>
              </div>
              {idx < STEPS.length - 1 && <ChevronRight size={14} className="text-slate-300" />}
            </div>
          );
        })}
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex-1 overflow-y-auto px-5 py-4">
            <div className="mb-4 rounded-2xl border border-[#bfdbfe] bg-[#eff6ff] px-4 py-3 text-xs leading-6 text-[#1d4ed8]">
              这一步不会重做建书，只是为你导入的现有作品补充后续创作约束。补得越准，后面的框架续写、章节扩写和对话调整越不容易跑偏。
            </div>

            {messages.map((msg, idx) => (
              <div
                key={idx}
                className={`mb-4 flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[75%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-6 ${
                    msg.role === 'user'
                      ? 'bg-[#2563eb] text-white shadow-[0_4px_12px_rgba(37,99,235,0.2)]'
                      : 'border border-[#e5edf8] bg-[#f8fbff] text-slate-700'
                  }`}
                >
                  {msg.content}
                </div>
              </div>
            ))}

            {loading && (
              <div className="mb-4 flex justify-start">
                <div className="flex items-center gap-2 rounded-2xl border border-[#e5edf8] bg-[#f8fbff] px-4 py-3 text-sm text-slate-500">
                  <Loader2 size={14} className="animate-spin" />
                  正在整理你的导入作品上下文...
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="border-t border-[#e5edf8] bg-white px-5 py-3">
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="输入你的补充说明，按 Enter 发送，Shift+Enter 换行..."
                rows={2}
                disabled={loading}
                className="min-h-[44px] flex-1 resize-none rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe] disabled:cursor-not-allowed disabled:opacity-60"
              />
              <button
                onClick={() => void handleSend()}
                disabled={loading || !input.trim()}
                className="flex h-[44px] w-[44px] shrink-0 items-center justify-center rounded-2xl bg-[#2563eb] text-white transition hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
              </button>
            </div>
            {error && <div className="mt-2 text-xs text-rose-600">{error}</div>}
            <div className="mt-3 flex items-center justify-between">
              <div className="text-xs text-slate-400">
                可以跳过，但建议至少明确“必须保留项”和“后续创作目标”。
              </div>
              <button
                onClick={() => void handleSkip()}
                disabled={skipLoading || confirmLoading}
                className="rounded-xl border border-[#d7e3f4] bg-white px-3 py-2 text-xs font-medium text-slate-600 transition hover:bg-[#f8fbff] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {skipLoading ? '跳过中...' : '跳过，先进入工作台'}
              </button>
            </div>
          </div>
        </div>

        <div className="hidden w-80 shrink-0 border-l border-[#e5edf8] bg-[#f8fbff] p-4 lg:block">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">当前摘要</div>
          <div className="mt-3 space-y-3">
            {creativeBrief?.one_line_premise ? (
              <div className="rounded-2xl border border-[#d7e3f4] bg-[#eff6ff] p-3">
                <div className="text-[11px] font-medium text-[#2563eb]">创意理解卡预览</div>
                <div className="mt-1 text-xs leading-5 text-slate-600">{creativeBrief.one_line_premise}</div>
              </div>
            ) : null}
            {collectedInfo.must_keep ? <SummaryCard label="必须保留" value={collectedInfo.must_keep} /> : null}
            {collectedInfo.author_goal ? <SummaryCard label="后续目标" value={collectedInfo.author_goal} /> : null}
            {collectedInfo.adjustment_scope ? <SummaryCard label="可调整范围" value={collectedInfo.adjustment_scope} /> : null}
            {collectedInfo.longline_plan ? <SummaryCard label="长线计划" value={collectedInfo.longline_plan} /> : null}
            {collectedInfo.tone_guardrails ? <SummaryCard label="风格边界" value={collectedInfo.tone_guardrails} /> : null}
            {!canShowSummary && (
              <div className="flex flex-col items-center gap-2 py-8 text-center text-xs text-slate-400">
                <MessageSquare size={24} className="opacity-40" />
                <div>这里会实时显示已补充的作者意图。</div>
              </div>
            )}
          </div>
        </div>
      </div>

      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-2xl rounded-[28px] border border-[#d7e3f4] bg-white p-6 shadow-[0_24px_60px_rgba(15,23,42,0.2)]">
            <div className="flex items-center gap-2 text-lg font-semibold text-slate-900">
              <Sparkles size={20} className="text-[#2563eb]" />
              确认导入上下文
            </div>
            <p className="mt-2 text-sm text-slate-500">
              这些信息会写入作品圣经，后续框架生成、续写和对话调整都会默认参考它。
            </p>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <BriefCard label="必须保留" value={collectedInfo.must_keep} />
              <BriefCard label="后续目标" value={collectedInfo.author_goal} />
              <BriefCard label="可调整范围" value={collectedInfo.adjustment_scope} />
              <BriefCard label="长线计划" value={collectedInfo.longline_plan} />
            </div>

            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={() => setShowConfirm(false)}
                disabled={confirmLoading}
                className="rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-[#f8fbff] disabled:cursor-not-allowed disabled:opacity-60"
              >
                我再补充
              </button>
              <button
                onClick={() => void handleConfirm()}
                disabled={confirmLoading}
                className="inline-flex items-center gap-1.5 rounded-2xl bg-[#2563eb] px-5 py-2.5 text-sm font-medium text-white shadow-[0_10px_24px_rgba(37,99,235,0.24)] transition hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {confirmLoading ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    正在写入作品圣经...
                  </>
                ) : (
                  <>
                    <Check size={14} />
                    确认写入
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
      <div className="text-[11px] font-medium text-[#2563eb]">{label}</div>
      <div className="mt-1 text-xs leading-5 text-slate-600">{value}</div>
    </div>
  );
}

function BriefCard({ label, value }: { label: string; value?: string }) {
  return (
    <div className="rounded-2xl border border-[#d7e3f4] bg-[#f8fbff] p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-[#2563eb]">{label}</div>
      <div className="mt-1.5 text-sm leading-6 text-slate-700">{value || '待补充'}</div>
    </div>
  );
}
