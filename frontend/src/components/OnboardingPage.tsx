import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  Cpu,
  Loader2,
  MessageSquare,
  Send,
  Sparkles,
} from 'lucide-react';
import {
  confirmOnboarding,
  sendOnboardingMessage,
  skipOnboarding,
  type CreativeBrief,
  type OnboardingChatMessage,
  type Story,
  type Understanding,
} from '../api';

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
  const [understanding, setUnderstanding] = useState<Partial<Understanding>>({});
  const [understandingDepth, setUnderstandingDepth] = useState(0);
  const [showBrief, setShowBrief] = useState(false);
  const [creativeBrief, setCreativeBrief] = useState<CreativeBrief | null>(null);
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
      const result = await sendOnboardingMessage(story.id, updatedMessages, understanding as Record<string, string>);

      setUnderstanding(result.understanding || {});
      setUnderstandingDepth(result.understanding_depth || 0);

      if (result.has_brief && result.creative_brief) {
        setCreativeBrief(result.creative_brief);
        setShowBrief(true);
        const briefMsg: OnboardingChatMessage = {
          role: 'assistant',
          content: result.reply,
          creative_brief: result.creative_brief,
        };
        setMessages((prev) => [...prev, briefMsg]);
      } else {
        const assistantMsg: OnboardingChatMessage = {
          role: 'assistant',
          content: result.reply,
        };
        setMessages((prev) => [...prev, assistantMsg]);
      }
    } catch (err: any) {
      setError(err.message || '对话失败，请重试');
    } finally {
      setLoading(false);
    }
  }, [understanding, input, loading, messages, story.id]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  const handleConfirm = async () => {
    setLoading(true);
    setError('');
    try {
      await confirmOnboarding(story.id, understanding as Record<string, string>, messages, creativeBrief ?? undefined);
      onComplete(story.id);
    } catch (err: any) {
      setError(err.message || '确认失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  const handleContinueEdit = () => {
    setShowBrief(false);
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
          <span>理解深度</span>
          <div className="w-24 h-1.5 bg-slate-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-[#2563eb] rounded-full transition-all duration-500"
              style={{ width: `${understandingDepth}%` }}
            />
          </div>
          <span>{understandingDepth}%</span>
        </div>
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
                {msg.role === 'assistant' && msg.creative_brief ? (
                  <BriefCardInline
                    brief={msg.creative_brief}
                    onConfirm={() => void handleConfirm()}
                    onContinue={handleContinueEdit}
                  />
                ) : (
                  <div
                    className={`max-w-[75%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-6 ${
                      msg.role === 'user'
                        ? 'bg-[#2563eb] text-white shadow-[0_4px_12px_rgba(37,99,235,0.2)]'
                        : 'border border-[#e5edf8] bg-[#f8fbff] text-slate-700'
                    }`}
                  >
                    {msg.content}
                  </div>
                )}
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
                  showBrief
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
            {understanding.concept ? (
              <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
                <div className="text-[11px] font-medium text-[#2563eb]">💡 故事概念</div>
                <div className="mt-1 text-xs leading-5 text-slate-600 line-clamp-4">
                  {understanding.concept}
                </div>
              </div>
            ) : null}
            {understanding.setting ? (
              <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
                <div className="text-[11px] font-medium text-[#2563eb]">🌍 世界观设定</div>
                <div className="mt-1 text-xs leading-5 text-slate-600">
                  {understanding.setting}
                </div>
              </div>
            ) : null}
            {understanding.tone ? (
              <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
                <div className="text-[11px] font-medium text-[#2563eb]">🎭 风格基调</div>
                <div className="mt-1 text-xs leading-5 text-slate-600">
                  {understanding.tone}
                </div>
              </div>
            ) : null}
            {understanding.goals ? (
              <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
                <div className="text-[11px] font-medium text-[#2563eb]">🎯 创作目标</div>
                <div className="mt-1 text-xs leading-5 text-slate-600">
                  {understanding.goals}
                </div>
              </div>
            ) : null}
            {understanding.synthesis ? (
              <div className="rounded-2xl border border-[#d7e3f4] bg-[#eff6ff] p-3">
                <div className="text-[11px] font-medium text-[#2563eb]">📝 综合理解</div>
                <div className="mt-1 text-xs leading-5 text-slate-600">
                  {understanding.synthesis}
                </div>
              </div>
            ) : null}
            {Object.keys(understanding).length === 0 && (
              <div className="flex flex-col items-center gap-2 py-8 text-center text-xs text-slate-400">
                <MessageSquare size={24} className="opacity-40" />
                <div>AI 正在理解你的创意...</div>
                <div>在左侧对话后，这里会显示实时摘要</div>
              </div>
            )}
          </div>
        </div>
      </div>

    </div>
  );
}

function BriefField({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className="rounded-2xl border border-[#d7e3f4] bg-white p-3">
      <div className="text-xs font-medium text-[#2563eb]">{label}</div>
      <div className="mt-1 text-sm text-slate-700">{value}</div>
    </div>
  );
}

function BriefCardInline({
  brief,
  onConfirm,
  onContinue,
}: {
  brief: CreativeBrief;
  onConfirm: () => void;
  onContinue: () => void;
}) {
  return (
    <div className="w-full max-w-[85%] rounded-2xl border border-[#bfdbfe] bg-[#f0f7ff] p-4">
      <div className="flex items-center gap-2 text-sm font-semibold text-[#1d4ed8]">
        <Sparkles size={14} />
        创意分析卡
      </div>
      <p className="mt-1 text-xs text-slate-500">
        我已经理解了你的创作构思，请确认以下分析是否准确：
      </p>
      <div className="mt-3 space-y-2">
        {brief.project_positioning && (
          <div className="rounded-xl bg-white p-3">
            <div className="text-[11px] font-medium text-[#2563eb]">作品定位</div>
            <div className="mt-1 text-sm text-slate-700">{brief.project_positioning}</div>
          </div>
        )}
        <div className="grid gap-2 sm:grid-cols-2">
          {brief.one_line_premise && <BriefField label="一句话梗概" value={brief.one_line_premise} />}
          {brief.core_hook && <BriefField label="核心卖点" value={brief.core_hook} />}
          {brief.main_conflict && <BriefField label="主线矛盾" value={brief.main_conflict} />}
          {brief.longline_mystery && <BriefField label="长线悬念" value={brief.longline_mystery} />}
          {brief.serial_length_target && <BriefField label="目标篇幅" value={brief.serial_length_target} />}
          {brief.reveal_strategy && <BriefField label="揭秘策略" value={brief.reveal_strategy} />}
          {brief.pacing_strategy && <BriefField label="节奏策略" value={brief.pacing_strategy} />}
          {brief.protagonist_core && <BriefField label="主角核心" value={brief.protagonist_core} />}
        </div>
      </div>
      <div className="mt-4 flex gap-2">
        <button
          onClick={onContinue}
          className="rounded-xl border border-[#d7e3f4] bg-white px-4 py-2 text-sm text-slate-600 hover:bg-[#f8fbff]"
        >
          继续对话修改
        </button>
        <button
          onClick={onConfirm}
          className="rounded-xl bg-[#2563eb] px-4 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8]"
        >
          确认生成
        </button>
      </div>
    </div>
  );
}
