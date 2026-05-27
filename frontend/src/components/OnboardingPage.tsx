import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  Check,
  ChevronRight,
  Cpu,
  Loader2,
  MessageSquare,
  Send,
  Sparkles,
  X,
} from 'lucide-react';
import {
  confirmOnboarding,
  sendOnboardingMessage,
  skipOnboarding,
  type CreativeBrief,
  type OnboardingChatMessage,
  type Story,
} from '../api';

const STEPS = ['故事概念', '题材定位', '核心卖点', '目标体量', '核心设定'];

const INITIAL_PROMPT =
  '你好！我是灵感捕手，很高兴能帮你梳理创作思路。说说你想写一个怎样的故事吧？主角是什么样的人？大概会发生什么？';

interface Props {
  story: Story;
  onComplete: (storyId: number) => void;
  onBack: () => void;
}

export default function OnboardingPage({ story, onComplete, onBack }: Props) {
  const [messages, setMessages] = useState<OnboardingChatMessage[]>([
    { role: 'assistant', content: INITIAL_PROMPT },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [collectedInfo, setCollectedInfo] = useState<Record<string, string>>({});
  const [creativeBrief, setCreativeBrief] = useState<CreativeBrief | null>(null);
  const [step, setStep] = useState(1);
  const [totalSteps] = useState(5);
  const [isComplete, setIsComplete] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [confirmLoading, setConfirmLoading] = useState(false);
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
      const result = await sendOnboardingMessage(story.id, updatedMessages, collectedInfo, step);
      const assistantMsg: OnboardingChatMessage = {
        role: 'assistant',
        content: result.reply,
      };
      setMessages((prev) => [...prev, assistantMsg]);
      setCollectedInfo(result.collected_info);
      setCreativeBrief((result.creative_brief as CreativeBrief | undefined) ?? null);
      setStep(result.step);
      setIsComplete(result.is_complete);

      if (result.is_complete) {
        setShowConfirm(true);
      }
    } catch (err: any) {
      setError(err.message || '对话失败，请重试');
    } finally {
      setLoading(false);
    }
  }, [collectedInfo, input, loading, messages, step, story.id]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  const handleConfirm = async () => {
    setConfirmLoading(true);
    setError('');
    try {
      await confirmOnboarding(story.id, collectedInfo, messages);
      onComplete(story.id);
    } catch (err: any) {
      setError(err.message || '确认失败，请重试');
    } finally {
      setConfirmLoading(false);
    }
  };

  const handleContinueEdit = () => {
    setShowConfirm(false);
    setInput('');
    inputRef.current?.focus();
  };

  const handleSkipOnboarding = async () => {
    setLoading(true);
    setError('');
    try {
      await skipOnboarding(story.id);
      onComplete(story.id);
    } catch (err: any) {
      setError(err.message || '跳过引导失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto flex h-[calc(100vh-120px)] max-w-7xl flex-col overflow-hidden rounded-2xl border border-[#d7e3f4] bg-white shadow-[0_14px_34px_rgba(59,130,246,0.08)]">
      {/* 顶部栏 */}
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
              AI 引导建书
            </div>
            <div className="text-xs text-slate-500">{story.title}</div>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <Cpu size={14} />
          <span>
            第 {step} 步 / 共 {totalSteps} 步
          </span>
        </div>
      </div>

      {/* 步骤进度条 */}
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
                {isDone ? (
                  <Check size={12} />
                ) : (
                  <span className="flex h-3.5 w-3.5 items-center justify-center rounded-full text-[10px] font-bold">
                    {stepNum}
                  </span>
                )}
                <span className="hidden sm:inline">{label}</span>
              </div>
              {idx < STEPS.length - 1 && (
                <ChevronRight size={14} className="text-slate-300" />
              )}
            </div>
          );
        })}
      </div>

      {/* 主体内容 */}
      <div className="flex min-h-0 flex-1">
        {/* 聊天区域 */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex-1 overflow-y-auto px-5 py-4">
            {/* 系统消息提示 */}
            <div className="mb-4 rounded-2xl border border-[#bfdbfe] bg-[#eff6ff] px-4 py-3 text-xs leading-6 text-[#1d4ed8]">
              这是 AI 引导建书模式。AI 会逐步提问，帮助你梳理创作思路。回答越详细，后续框架生成越精准。
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
                  正在思考...
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* 输入区域 */}
          <div className="border-t border-[#e5edf8] bg-white px-5 py-3">
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  showConfirm
                    ? '继续补充你的想法...'
                    : '输入你的想法，按 Enter 发送，Shift+Enter 换行...'
                }
                rows={2}
                disabled={loading}
                className="min-h-[44px] flex-1 resize-none rounded-2xl border border-[#d7e3f4] bg-[#fafdff] px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#93c5fd] focus:bg-white focus:ring-4 focus:ring-[#dbeafe] disabled:cursor-not-allowed disabled:opacity-60"
              />
              <button
                onClick={() => void handleSend()}
                disabled={loading || !input.trim()}
                className="flex h-[44px] w-[44px] shrink-0 items-center justify-center rounded-2xl bg-[#2563eb] text-white transition hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? (
                  <Loader2 size={18} className="animate-spin" />
                ) : (
                  <Send size={18} />
                )}
              </button>
            </div>
            {error && (
              <div className="mt-2 text-xs text-rose-600">{error}</div>
            )}
            <div className="mt-3 flex items-center justify-between">
              <button
                onClick={() => void handleSkipOnboarding()}
                disabled={loading}
                className="rounded-2xl border border-[#d7e3f4] bg-white px-4 py-2 text-sm text-slate-500 transition hover:bg-[#f8fbff] disabled:cursor-not-allowed disabled:opacity-60"
              >
                跳过引导，直接开始
              </button>
              <div className="text-xs text-slate-400">
                已有故事内容可跳过引导
              </div>
            </div>
          </div>
        </div>

        {/* 右侧摘要面板 */}
        <div className="hidden w-72 shrink-0 border-l border-[#e5edf8] bg-[#f8fbff] p-4 lg:block">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            当前理解
          </div>
          <div className="mt-3 space-y-3">
            {creativeBrief?.one_line_premise ? (
              <div className="rounded-2xl border border-[#d7e3f4] bg-[#eff6ff] p-3">
                <div className="text-[11px] font-medium text-[#2563eb]">创意理解卡</div>
                <div className="mt-1 text-xs leading-5 text-slate-600">
                  {creativeBrief.one_line_premise}
                </div>
                <div className="mt-2 text-[11px] text-slate-500">
                  {creativeBrief.genre} · {creativeBrief.audience} · {creativeBrief.serial_length_target}
                </div>
              </div>
            ) : null}
            {collectedInfo.story_concept ? (
              <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
                <div className="text-[11px] font-medium text-[#2563eb]">故事概念</div>
                <div className="mt-1 text-xs leading-5 text-slate-600 line-clamp-4">
                  {collectedInfo.story_concept}
                </div>
              </div>
            ) : null}
            {collectedInfo.genre_audience ? (
              <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
                <div className="text-[11px] font-medium text-[#2563eb]">题材方向</div>
                <div className="mt-1 text-xs leading-5 text-slate-600">
                  {collectedInfo.genre_audience}
                </div>
              </div>
            ) : null}
            {collectedInfo.core_hook ? (
              <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
                <div className="text-[11px] font-medium text-[#2563eb]">核心卖点</div>
                <div className="mt-1 text-xs leading-5 text-slate-600">
                  {collectedInfo.core_hook}
                </div>
              </div>
            ) : null}
            {collectedInfo.target_length ? (
              <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
                <div className="text-[11px] font-medium text-[#2563eb]">目标体量</div>
                <div className="mt-1 text-xs leading-5 text-slate-600">
                  {collectedInfo.target_length}
                </div>
              </div>
            ) : null}
            {collectedInfo.must_keep ? (
              <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
                <div className="text-[11px] font-medium text-[#2563eb]">必保留设定</div>
                <div className="mt-1 text-xs leading-5 text-slate-600">
                  {collectedInfo.must_keep}
                </div>
              </div>
            ) : null}
            {Object.keys(collectedInfo).length === 0 && (
              <div className="flex flex-col items-center gap-2 py-8 text-center text-xs text-slate-400">
                <MessageSquare size={24} className="opacity-40" />
                <div>AI 正在理解你的创意...</div>
                <div>在左侧对话后，这里会显示实时摘要</div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 创意理解卡确认弹窗 */}
      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-[28px] border border-[#d7e3f4] bg-white p-6 shadow-[0_24px_60px_rgba(15,23,42,0.2)]">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-2">
                <Sparkles size={20} className="text-[#2563eb]" />
                <div className="text-lg font-semibold text-slate-900">
                  创意理解卡
                </div>
              </div>
              <button
                onClick={handleContinueEdit}
                className="rounded-full border border-[#d7e3f4] bg-white p-1.5 text-slate-400 transition hover:bg-[#f8fbff]"
              >
                <X size={16} />
              </button>
            </div>
            <p className="mt-1 text-sm text-slate-500">
              AI 已经理解了你关于《{story.title}》的创作构思。请确认以下理解是否准确：
            </p>

            <div className="mt-4 space-y-3">
              <div className="rounded-2xl border border-[#d7e3f4] bg-[#f8fbff] p-4">
                <div className="text-xs font-medium uppercase tracking-wide text-[#2563eb]">
                  作品定位
                </div>
                <div className="mt-1.5 text-sm leading-6 text-slate-700">
                  {creativeBrief?.project_positioning || collectedInfo.story_concept || '等待确认...'}
                </div>
              </div>
              {creativeBrief && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <BriefCard label="一句话梗概" value={creativeBrief.one_line_premise} />
                  <BriefCard label="核心卖点" value={creativeBrief.core_hook} />
                  <BriefCard label="主线矛盾" value={creativeBrief.main_conflict} />
                  <BriefCard label="长线悬念" value={creativeBrief.longline_mystery} />
                  <BriefCard label="目标篇幅" value={creativeBrief.serial_length_target} />
                  <BriefCard label="揭秘策略" value={creativeBrief.reveal_strategy} />
                  <BriefCard label="节奏策略" value={creativeBrief.pacing_strategy} />
                  <BriefCard label="主角核心" value={creativeBrief.protagonist_core} />
                </div>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                {collectedInfo.genre_audience && (
                  <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
                    <div className="text-xs font-medium text-[#2563eb]">题材与受众</div>
                    <div className="mt-1 text-sm text-slate-700">
                      {collectedInfo.genre_audience}
                    </div>
                  </div>
                )}
                {collectedInfo.core_hook && (
                  <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
                    <div className="text-xs font-medium text-[#2563eb]">核心卖点</div>
                    <div className="mt-1 text-sm text-slate-700">
                      {collectedInfo.core_hook}
                    </div>
                  </div>
                )}
                {collectedInfo.target_length && (
                  <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
                    <div className="text-xs font-medium text-[#2563eb]">目标体量</div>
                    <div className="mt-1 text-sm text-slate-700">
                      {collectedInfo.target_length}
                    </div>
                  </div>
                )}
                {collectedInfo.must_keep && (
                  <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
                    <div className="text-xs font-medium text-[#2563eb]">必保留设定</div>
                    <div className="mt-1 text-sm text-slate-700">
                      {collectedInfo.must_keep}
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div className="mt-6 flex flex-wrap items-center justify-end gap-3">
              <button
                onClick={handleContinueEdit}
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
                    正在生成作品圣经...
                  </>
                ) : (
                  <>
                    <Check size={14} />
                    按此生成
                  </>
                )}
              </button>
            </div>
            {error && (
              <div className="mt-3 text-xs text-rose-600">{error}</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function BriefCard({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
      <div className="text-xs font-medium text-[#2563eb]">{label}</div>
      <div className="mt-1 text-sm text-slate-700">{value}</div>
    </div>
  );
}
