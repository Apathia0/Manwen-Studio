import {
  ArrowRight,
  BookOpen,
  Brush,
  CheckCircle2,
  CreditCard,
  Image,
  MessageSquareQuote,
  PencilRuler,
  PenTool,
  PlayCircle,
  ScrollText,
  ShieldCheck,
  Users,
} from 'lucide-react';
import type { PublicPlatformSettings } from '../api';

type PublicLandingProps = {
  onLogin: () => void;
  onRegister: () => void;
  onPricing: () => void;
  platform: PublicPlatformSettings;
};

type FeatureCardProps = {
  title: string;
  desc: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
};

function FeatureCard({ title, desc, icon: Icon }: FeatureCardProps) {
  return (
    <div className="rounded-[28px] border border-[#d9dfd7] bg-white/92 p-5 shadow-[0_18px_40px_rgba(34,77,70,0.08)] backdrop-blur">
      <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-2xl bg-[#e8f1ff] text-[#2563eb] shadow-[inset_0_1px_0_rgba(255,255,255,0.65)]">
        <Icon size={16} />
      </div>
      <h3 className="text-base font-semibold text-slate-900">{title}</h3>
      <p className="mt-2 text-sm leading-6 text-slate-600">{desc}</p>
    </div>
  );
}

export default function PublicLanding({
  onLogin,
  onRegister,
  onPricing,
  platform,
}: PublicLandingProps) {
  const siteName = platform.site_name || 'StoryCanvas';
  const siteSlogan = platform.site_slogan || 'AI 小说与漫画创作平台';
  const workflowSteps = [
    {
      step: '01',
      title: '一句灵感生成故事框架',
      desc: '从题材、世界观、主线冲突到三幕式大纲，先把长篇创作最难的起步阶段铺平。',
    },
    {
      step: '02',
      title: '角色设定与外观统一管理',
      desc: '角色小传、关系线、外观描述和参考图统一沉淀，减少后续章节与漫画出图的设定漂移。',
    },
    {
      step: '03',
      title: '章节扩写与节奏推进',
      desc: '把大纲快速扩成可继续打磨的正文草稿，保持叙事节奏、情绪推进与信息密度。',
    },
    {
      step: '04',
      title: '小说转分镜脚本',
      desc: '自动拆分场景、镜头与对白，直接为漫画镜头、页节奏和画面生成做准备。',
    },
    {
      step: '05',
      title: '漫画生成与单图重绘',
      desc: '从分镜到成图一条链路完成，支持局部修正和重绘，让内容产出更适合连载。',
    },
  ];

  const audienceGroups = [
    {
      title: '网文作者',
      desc: '快速搭建长篇框架，稳定推进日更、周更和多卷连载。',
    },
    {
      title: '漫画工作室',
      desc: '把剧本、分镜和角色参考整合在同一工作流里，减少沟通成本。',
    },
    {
      title: '内容创业团队',
      desc: '适合做 IP 孵化、短篇试水、爆款验证和图文内容矩阵扩展。',
    },
  ];
  const supportEmail = platform.support_email?.trim();
  const icp = platform.icp?.trim();
  const copyright = platform.copyright?.trim();
  const notice = platform.notice?.trim();

  return (
    <div className="min-h-screen bg-[linear-gradient(180deg,_#eef4ff_0%,_#f3f7ff_18%,_#f8fbff_44%,_#f3f8ff_100%)] text-slate-900">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[540px] bg-[radial-gradient(circle_at_16%_18%,_rgba(59,130,246,0.22),_transparent_30%),radial-gradient(circle_at_84%_14%,_rgba(191,219,254,0.72),_transparent_24%),radial-gradient(circle_at_52%_0%,_rgba(219,234,254,0.92),_transparent_38%)]" />

      <header className="sticky top-0 z-20 border-b border-[#d9dfd7]/80 bg-[rgba(252,253,251,0.82)] backdrop-blur-xl">
        <div className="mx-auto flex h-18 max-w-7xl items-center justify-between px-4 sm:px-6">
          <button onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })} className="flex items-center gap-3 text-left">
            <img
              src="/brand-mark.svg"
              alt={`${siteName} logo`}
              className="h-10 w-10 rounded-2xl shadow-[0_12px_30px_rgba(59,130,246,0.14)]"
            />
            <div>
              <div className="text-[17px] font-semibold tracking-tight">{siteName}</div>
              <div className="text-[11px] text-slate-500">{siteSlogan}</div>
            </div>
          </button>
          <nav className="hidden items-center gap-7 text-sm text-slate-600 lg:flex">
            <a href="#workflow" className="transition hover:text-[#2563eb]">创作流程</a>
            <a href="#advantages" className="transition hover:text-[#2563eb]">平台优势</a>
            <a href="#scenarios" className="transition hover:text-[#2563eb]">适合谁用</a>
            <a href="#contact" className="transition hover:text-[#2563eb]">联系信息</a>
            <button onClick={onPricing} className="transition hover:text-[#2563eb]">套餐方案</button>
          </nav>
          <div className="flex items-center gap-2">
            <button onClick={onPricing} className="hidden rounded-full border border-[#d9dfd7] bg-white px-4 py-2 text-sm text-slate-700 shadow-[0_10px_24px_rgba(15,23,42,0.04)] sm:inline-flex">套餐</button>
            <button onClick={onLogin} className="rounded-full border border-[#d9dfd7] bg-white px-4 py-2 text-sm text-slate-700 shadow-[0_10px_24px_rgba(15,23,42,0.04)]">登录</button>
            <button onClick={onRegister} className="inline-flex items-center gap-2 rounded-full bg-[#2563eb] px-4 py-2 text-sm font-medium text-white shadow-[0_16px_34px_rgba(59,130,246,0.24)] transition hover:bg-[#1d4ed8]">
              开始创作
              <ArrowRight size={15} />
            </button>
          </div>
        </div>
      </header>

      <main className="relative">
        <section className="mx-auto grid max-w-7xl gap-10 px-4 pb-18 pt-10 sm:px-6 lg:grid-cols-[minmax(0,1.08fr)_520px] lg:items-center lg:pt-18">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-[#d7e3f4] bg-white/80 px-3 py-1 text-xs font-medium text-[#2563eb] shadow-[0_10px_24px_rgba(59,130,246,0.08)]">
              <img src="/brand-mark.svg" alt="" className="h-4 w-4 rounded-md" />
              用一条完整工作流把灵感变成可持续更新的内容 IP
            </div>
            <h1 className="mt-6 max-w-3xl text-4xl font-semibold leading-[1.08] tracking-tight text-slate-950 sm:text-5xl lg:text-[62px]">
              从小说框架到漫画成图，
              <span className="block text-[#2563eb]">让创作、设定与出图在一个平台闭环完成。</span>
            </h1>
            <p className="mt-6 max-w-2xl text-[15px] leading-8 text-slate-600 sm:text-base">
              {siteName} 面向小说作者、漫画团队和内容创业者，把大纲生成、角色设定、章节扩写、分镜拆解和漫画生成串成一条真正可落地的创作链路。
              不再在多个工具之间来回切换，也不再让设定、文稿与画面彼此脱节。
            </p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <button onClick={onRegister} className="inline-flex items-center justify-center gap-2 rounded-full bg-[#2563eb] px-6 py-3 text-sm font-medium text-white shadow-[0_20px_40px_rgba(59,130,246,0.24)] transition hover:bg-[#1d4ed8]">
                免费开始创作
                <ArrowRight size={16} />
              </button>
              <button onClick={onPricing} className="inline-flex items-center justify-center gap-2 rounded-full border border-[#d9dfd7] bg-white/92 px-6 py-3 text-sm font-medium text-slate-800 shadow-[0_14px_30px_rgba(15,23,42,0.05)] transition hover:border-[#bfd0ea] hover:bg-white">
                查看套餐方案
                <CreditCard size={16} />
              </button>
            </div>
            <div className="mt-10 grid max-w-2xl gap-4 sm:grid-cols-3">
              <div className="rounded-[24px] border border-[#d9dfd7] bg-white/88 p-4 shadow-[0_16px_36px_rgba(31,95,88,0.06)]">
                <div className="text-2xl font-semibold text-slate-950">5 步</div>
                <div className="mt-2 text-sm leading-6 text-slate-600">覆盖从灵感、大纲、设定到分镜与漫画出图的完整流程。</div>
              </div>
              <div className="rounded-[24px] border border-[#d9dfd7] bg-white/88 p-4 shadow-[0_16px_36px_rgba(31,95,88,0.06)]">
                <div className="text-2xl font-semibold text-slate-950">统一</div>
                <div className="mt-2 text-sm leading-6 text-slate-600">角色设定、参考图和章节内容始终在同一项目里协同更新。</div>
              </div>
              <div className="rounded-[24px] border border-[#d9dfd7] bg-white/88 p-4 shadow-[0_16px_36px_rgba(31,95,88,0.06)]">
                <div className="text-2xl font-semibold text-slate-950">连载友好</div>
                <div className="mt-2 text-sm leading-6 text-slate-600">更适合长篇、连载和持续打磨，不只是一次性的单次生成。</div>
              </div>
            </div>
          </div>

          <div className="relative">
            <div className="absolute -left-6 top-8 h-28 w-28 rounded-full bg-[#dbeafe] blur-3xl" />
            <div className="absolute right-6 top-0 h-24 w-24 rounded-full bg-[#e0e7ff] blur-3xl" />
            <div className="relative overflow-hidden rounded-[32px] border border-[#d7e3f4] bg-[linear-gradient(180deg,_rgba(255,255,255,0.96)_0%,_rgba(248,251,255,0.98)_100%)] p-5 shadow-[0_28px_70px_rgba(59,130,246,0.14)]">
              <div className="flex items-start justify-between gap-3 rounded-[24px] border border-[#dfe8f6] bg-[#fdfefd] p-4">
                <div>
                  <div className="text-sm font-semibold text-slate-900">{siteName} 创作工作台</div>
                  <div className="mt-1 text-xs leading-5 text-slate-500">把文本规划、设定管理、分镜生成和漫画出图放进同一个项目上下文里。</div>
                </div>
                <div className="rounded-full bg-[#eef5ff] px-3 py-1 text-[11px] font-medium text-[#2563eb]">项目协同流</div>
              </div>

              <div className="mt-4 space-y-3">
                <div className="rounded-[24px] border border-[#dbe5f3] bg-white p-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[#eef5ff] text-[#2563eb]">
                        <PencilRuler size={18} />
                      </div>
                      <div>
                        <div className="text-sm font-semibold">故事框架生成</div>
                        <div className="text-xs text-slate-500">题材、主线冲突、卷宗规划</div>
                      </div>
                    </div>
                    <span className="rounded-full bg-[#f3f7ff] px-2.5 py-1 text-[11px] text-slate-500">起稿阶段</span>
                  </div>
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-[24px] border border-[#dbe5f3] bg-[linear-gradient(180deg,_#f8fbff_0%,_#ffffff_100%)] p-4">
                    <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                      <Users size={16} className="text-[#2563eb]" />
                      角色资料库
                    </div>
                    <div className="mt-3 space-y-2 text-xs text-slate-600">
                      <div className="rounded-2xl bg-[#f3f7ff] px-3 py-2">姓名、外貌、关系、口头禅统一管理</div>
                      <div className="rounded-2xl bg-[#f3f7ff] px-3 py-2">全局参考图同步给章节与漫画流程</div>
                    </div>
                  </div>
                  <div className="rounded-[24px] border border-[#dbe5f3] bg-[linear-gradient(180deg,_#f8fbff_0%,_#ffffff_100%)] p-4">
                    <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                      <BookOpen size={16} className="text-[#2563eb]" />
                      章节推进
                    </div>
                    <div className="mt-3 space-y-2 text-xs text-slate-600">
                      <div className="rounded-2xl bg-[#f3f7ff] px-3 py-2">从提纲扩成章节正文草稿</div>
                      <div className="rounded-2xl bg-[#f3f7ff] px-3 py-2">保留可继续润色和二次编辑的空间</div>
                    </div>
                  </div>
                </div>

                <div className="rounded-[28px] bg-[#1e3a5f] p-4 text-white shadow-[0_22px_44px_rgba(29,78,216,0.22)]">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold">小说转分镜，再到漫画出图</div>
                      <div className="mt-1 text-xs leading-5 text-white/70">镜头、对白、页面节奏与画面生成串行衔接，适合做持续连载和 IP 孵化。</div>
                    </div>
                    <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white/10 text-[#bfdbfe]">
                      <PlayCircle size={20} />
                    </div>
                  </div>
                  <div className="mt-4 grid gap-2 sm:grid-cols-3">
                    <div className="rounded-2xl bg-white/8 px-3 py-3 text-xs text-white/78">场景拆分与分镜脚本</div>
                    <div className="rounded-2xl bg-white/8 px-3 py-3 text-xs text-white/78">角色一致性参考</div>
                    <div className="rounded-2xl bg-white/8 px-3 py-3 text-xs text-white/78">单图重绘与修正</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-4 pb-6 sm:px-6">
          <div className="grid gap-4 md:grid-cols-3">
            <FeatureCard title="AI 小说框架" desc="自动生成题材、角色、三幕式大纲与章节规划，让灵感可以迅速落成一套可执行的长篇方案。" icon={PencilRuler} />
            <FeatureCard title="章节扩写与迭代" desc="把大纲推进成可继续打磨的正文内容，既保留效率，也保留作者对风格与细节的掌控。" icon={PenTool} />
            <FeatureCard title="漫画生成与重绘" desc="从分镜脚本到画面生成一体衔接，支持单图调整，适合做内容试水和正式连载。" icon={Brush} />
          </div>
        </section>

        <section id="workflow" className="mx-auto max-w-7xl px-4 py-18 sm:px-6">
          <div className="max-w-3xl">
            <div className="text-sm font-medium text-[#2563eb]">完整创作流程</div>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">不是单点功能堆叠，而是一条能持续推进内容生产的工作链。</h2>
            <p className="mt-4 text-base leading-8 text-slate-600">
              参考主流 AI 创作平台常见的首页节奏，我们保留了清晰入口和能力展示，但把重点收束到 {siteName} 最核心的价值上：
              从故事一路走到成图，过程不断层。
            </p>
          </div>
          <div className="mt-10 grid gap-4 lg:grid-cols-5">
            {workflowSteps.map((item) => (
              <div key={item.step} className="rounded-[28px] border border-[#d9dfd7] bg-white/92 p-5 shadow-[0_18px_42px_rgba(59,130,246,0.08)]">
                <div className="text-xs font-semibold tracking-[0.18em] text-[#7b988c]">{item.step}</div>
                <div className="mt-4 text-lg font-semibold leading-7 text-slate-950">{item.title}</div>
                <p className="mt-3 text-sm leading-7 text-slate-600">{item.desc}</p>
              </div>
            ))}
          </div>
        </section>

        <section id="advantages" className="border-y border-[#e4ebe5] bg-[linear-gradient(180deg,_rgba(239,245,241,0.78)_0%,_rgba(252,253,251,0.92)_100%)]">
          <div className="mx-auto max-w-7xl px-4 py-18 sm:px-6">
            <div className="grid gap-10 lg:grid-cols-[0.9fr_minmax(0,1.1fr)] lg:items-start">
              <div>
                <div className="text-sm font-medium text-[#2563eb]">平台优势</div>
                <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">更适合小说与漫画长期创作，而不是只做一次性的随机生成。</h2>
                <p className="mt-4 text-base leading-8 text-slate-600">
                  相比只强调“生成快、出图多”的首页表达，{siteName} 更强调创作上下文的连续性，让你的设定、正文和漫画结果彼此有据可循。
                </p>
                <button onClick={onRegister} className="mt-8 inline-flex items-center gap-2 rounded-full bg-[#2563eb] px-5 py-3 text-sm font-medium text-white shadow-[0_18px_34px_rgba(59,130,246,0.22)] transition hover:bg-[#1d4ed8]">
                  现在开始创建项目
                  <ArrowRight size={16} />
                </button>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded-[28px] border border-[#d9dfd7] bg-white p-5 shadow-[0_18px_42px_rgba(59,130,246,0.08)]">
                  <CheckCircle2 size={18} className="text-[#2563eb]" />
                  <div className="mt-4 text-lg font-semibold">统一管理角色与参考</div>
                  <p className="mt-3 text-sm leading-7 text-slate-600">人物设定、外观描述和参考图集中存放，后续章节与漫画生成都能沿用同一套上下文。</p>
                </div>
                <div className="rounded-[28px] border border-[#d9dfd7] bg-white p-5 shadow-[0_18px_42px_rgba(59,130,246,0.08)]">
                  <ScrollText size={18} className="text-[#2563eb]" />
                  <div className="mt-4 text-lg font-semibold">从文本到镜头自然衔接</div>
                  <p className="mt-3 text-sm leading-7 text-slate-600">不是把章节丢给另一个工具重新开始，而是直接把正文语义转换为分镜和画面表达。</p>
                </div>
                <div className="rounded-[28px] border border-[#d9dfd7] bg-white p-5 shadow-[0_18px_42px_rgba(59,130,246,0.08)]">
                  <Image size={18} className="text-[#2563eb]" />
                  <div className="mt-4 text-lg font-semibold">支持试水、迭代与重绘</div>
                  <p className="mt-3 text-sm leading-7 text-slate-600">先快速验证角色和画风，再对关键画面做单图修正，更适合实际内容生产的反复打磨。</p>
                </div>
                <div className="rounded-[28px] border border-[#d9dfd7] bg-white p-5 shadow-[0_18px_42px_rgba(59,130,246,0.08)]">
                  <ShieldCheck size={18} className="text-[#2563eb]" />
                  <div className="mt-4 text-lg font-semibold">兼顾创作与运营配置</div>
                  <p className="mt-3 text-sm leading-7 text-slate-600">平台内置套餐、额度和后台管理能力，后续如果面向用户开放，也有完整的商业化承接基础。</p>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-4 py-18 sm:px-6">
          <div className="grid gap-4 lg:grid-cols-[1.05fr_0.95fr]">
            <div className="rounded-[32px] border border-[#d9dfd7] bg-white p-6 shadow-[0_24px_58px_rgba(59,130,246,0.08)] sm:p-8">
              <div className="text-sm font-medium text-[#2563eb]">核心能力组合</div>
              <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-950">围绕内容生产最常见的断点，补齐真正有价值的协作环节。</h2>
              <div className="mt-8 grid gap-4 md:grid-cols-2">
                <div className="rounded-[24px] bg-[#f4f8ff] p-4">
                  <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                    <MessageSquareQuote size={16} className="text-[#2563eb]" />
                    大纲与情节推进
                  </div>
                  <p className="mt-3 text-sm leading-7 text-slate-600">帮助创作者快速进入状态，避免从空白文档开始反复卡住。</p>
                </div>
                <div className="rounded-[24px] bg-[#f4f8ff] p-4">
                  <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                    <Users size={16} className="text-[#2563eb]" />
                    人物一致性
                  </div>
                  <p className="mt-3 text-sm leading-7 text-slate-600">让角色资料与参考图成为贯穿全项目的基础设施，而不是一次性备注。</p>
                </div>
                <div className="rounded-[24px] bg-[#f4f8ff] p-4">
                  <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                    <ScrollText size={16} className="text-[#2563eb]" />
                    分镜结构化输出
                  </div>
                  <p className="mt-3 text-sm leading-7 text-slate-600">为漫画创作预先整理镜头逻辑、对白密度和画面拆分方式。</p>
                </div>
                <div className="rounded-[24px] bg-[#f4f8ff] p-4">
                  <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                    <Brush size={16} className="text-[#2563eb]" />
                    漫画生成与修正
                  </div>
                  <p className="mt-3 text-sm leading-7 text-slate-600">把最终产出继续留在项目链路中，方便复盘、重绘和版本迭代。</p>
                </div>
              </div>
            </div>

            <div id="scenarios" className="rounded-[32px] bg-[#163b73] p-6 text-white shadow-[0_28px_70px_rgba(16,24,40,0.22)] sm:p-8">
              <div className="text-sm font-medium text-[#bfdbfe]">适合谁使用</div>
              <h2 className="mt-3 text-3xl font-semibold tracking-tight">面向想把内容持续做下去的人，而不是只想试一次的人。</h2>
              <div className="mt-8 space-y-4">
                {audienceGroups.map((group) => (
                  <div key={group.title} className="rounded-[24px] border border-white/10 bg-white/6 p-4">
                    <div className="text-lg font-semibold">{group.title}</div>
                    <p className="mt-2 text-sm leading-7 text-white/72">{group.desc}</p>
                  </div>
                ))}
              </div>
              <div className="mt-8 rounded-[24px] bg-white/8 p-4 text-sm leading-7 text-white/76">
                如果你现在的流程还是“文案在一个工具、分镜在一个工具、画图又在另一个工具”，{siteName} 会更像一个真正的创作工作台，而不是功能拼盘。
              </div>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-4 pb-18 sm:px-6">
          <div className="overflow-hidden rounded-[36px] border border-[#d9dfd7] bg-[linear-gradient(135deg,_#1e40af_0%,_#2563eb_48%,_#3b82f6_100%)] p-8 text-white shadow-[0_28px_70px_rgba(59,130,246,0.22)] sm:p-10">
            <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
              <div>
                <div className="text-sm font-medium text-[#dbeafe]">准备开始你的第一个项目</div>
                <h2 className="mt-3 max-w-2xl text-3xl font-semibold tracking-tight sm:text-4xl">从一句故事灵感出发，逐步长成可更新、可出图、可运营的内容作品。</h2>
                <p className="mt-4 max-w-2xl text-sm leading-7 text-white/78 sm:text-base">
                  现在就体验 {siteName}，把世界观、角色、章节和漫画结果放到同一条生产线上，减少重复操作，提升内容稳定性。
                </p>
              </div>
              <div className="flex flex-col gap-3 sm:flex-row">
                <button onClick={onRegister} className="inline-flex items-center justify-center gap-2 rounded-full bg-white px-6 py-3 text-sm font-medium text-[#1d4ed8] shadow-[0_18px_40px_rgba(6,18,16,0.2)] transition hover:bg-[#eff6ff]">
                  立即免费开始
                  <ArrowRight size={16} />
                </button>
                <button onClick={onPricing} className="inline-flex items-center justify-center gap-2 rounded-full border border-white/20 bg-white/8 px-6 py-3 text-sm font-medium text-white transition hover:bg-white/12">
                  查看套餐与额度
                  <CreditCard size={16} />
                </button>
              </div>
            </div>
          </div>
        </section>

        <footer id="contact" className="mx-auto max-w-7xl px-4 pb-12 sm:px-6">
          <div className="rounded-[28px] border border-[#d7e3f4] bg-white/88 px-6 py-5 shadow-[0_16px_36px_rgba(59,130,246,0.08)]">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="text-sm font-semibold text-slate-900">{siteName}</div>
                <div className="mt-1 text-sm text-slate-500">{siteSlogan}</div>
                {notice ? <div className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">{notice}</div> : null}
              </div>
              <div className="grid gap-2 text-sm text-slate-500 sm:grid-cols-2 lg:text-right">
                {supportEmail ? <div>客服邮箱：{supportEmail}</div> : null}
                {icp ? <div>{icp}</div> : null}
                {copyright ? <div className="sm:col-span-2">{copyright}</div> : null}
              </div>
            </div>
          </div>
        </footer>
      </main>
    </div>
  );
}
