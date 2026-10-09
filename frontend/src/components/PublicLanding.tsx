import { useEffect, useMemo, useState } from 'react';
import {
  ArrowRight,
  Bot,
  BookOpen,
  Brush,
  CheckCircle2,
  Clapperboard,
  Cpu,
  CreditCard,
  FileText,
  Film,
  History,
  Image,
  ScrollText,
  ShieldCheck,
  Sparkles,
  Users,
} from 'lucide-react';
import { getPublicAiModels, type PublicAiModelItem, type PublicPlatformSettings } from '../api';

type PublicLandingProps = {
  onLogin: () => void;
  onRegister: () => void;
  onPricing: () => void;
  onModelCatalog: () => void;
  platform: PublicPlatformSettings;
};

type IconType = React.ComponentType<{ size?: number; className?: string }>;

const CARD = 'rounded-[28px] border border-[#d9dfd7] bg-white/92 shadow-[0_18px_42px_rgba(59,130,246,0.08)]';

/** 英雄区右侧：一个项目贯穿「小说剧本 → 漫画 → 漫剧」三段创作，纯 CSS，不依赖接口 */
function StudioShowcase({ siteName }: { siteName: string }) {
  const lanes: { no: string; title: string; icon: IconType; chips: string[]; dark?: boolean }[] = [
    { no: '01', title: '小说与剧本创作', icon: BookOpen, chips: ['故事框架', '章节扩写', '转剧本'] },
    { no: '02', title: '漫画创作', icon: Brush, chips: ['自动分镜', '漫画出图', '单图重绘'] },
    { no: '03', title: '漫剧创作', icon: Clapperboard, chips: ['场景审核', '视频生成', '一键合片'], dark: true },
  ];
  return (
    <div className="relative">
      <div className="absolute -left-6 top-8 h-28 w-28 rounded-full bg-[#dbeafe] blur-3xl" />
      <div className="absolute right-6 top-0 h-24 w-24 rounded-full bg-[#e0e7ff] blur-3xl" />
      <div className="relative overflow-hidden rounded-[32px] border border-[#d7e3f4] bg-[linear-gradient(180deg,_rgba(255,255,255,0.96)_0%,_rgba(248,251,255,0.98)_100%)] p-4 shadow-[0_28px_70px_rgba(59,130,246,0.14)] sm:p-5">
        <div className="flex items-start justify-between gap-3 rounded-[24px] border border-[#dfe8f6] bg-[#fdfefd] p-4">
          <div>
            <div className="text-sm font-semibold text-slate-900">{siteName} 一站式创作</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">同一个项目，设定共享，一路从文字做到成片。</div>
          </div>
          <div className="shrink-0 rounded-full bg-[#eef5ff] px-3 py-1 text-[11px] font-medium text-[#2563eb]">设定共享</div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2 px-1">
          {([
            [Users, '角色库'],
            [ScrollText, '世界观'],
            [Image, '画风参考'],
          ] as [IconType, string][]).map(([Icon, label]) => (
            <span key={label} className="inline-flex items-center gap-1.5 rounded-full border border-[#dbe5f3] bg-white px-3 py-1 text-[11px] text-slate-600">
              <Icon size={12} className="text-[#2563eb]" />
              {label}
            </span>
          ))}
        </div>

        <div className="relative mt-3 space-y-3">
          <div className="absolute bottom-8 left-[36px] top-8 w-px bg-[#c9d9f0]" aria-hidden="true" />
          {lanes.map((lane) => {
            const Icon = lane.icon;
            return (
              <div
                key={lane.no}
                className={`relative flex items-start gap-3 rounded-[24px] border p-4 ${lane.dark ? 'border-transparent bg-[#1e3a5f] text-white shadow-[0_22px_44px_rgba(29,78,216,0.22)]' : 'border-[#dbe5f3] bg-white'}`}
              >
                <div className={`relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl ${lane.dark ? 'bg-[#2c4d79] text-[#bfdbfe]' : 'bg-[#eef5ff] text-[#2563eb]'}`}>
                  <Icon size={18} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className={`text-[11px] font-semibold tracking-[0.18em] ${lane.dark ? 'text-[#bfdbfe]' : 'text-[#7b988c]'}`}>{lane.no}</span>
                    <span className="text-sm font-semibold">{lane.title}</span>
                  </div>
                  <div className="mt-2.5 flex flex-wrap gap-1.5">
                    {lane.chips.map((chip) => (
                      <span key={chip} className={`rounded-full px-2.5 py-1 text-[11px] ${lane.dark ? 'bg-white/10 text-white/80' : 'bg-[#f3f7ff] text-slate-600'}`}>{chip}</span>
                    ))}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/** 漫剧创作区：无限画布示意（节点 + 连线 + 助手预览条），节点以连线端点为中心定位 */
function CanvasShowcase() {
  const nodes: { title: string; sub: string; tag?: string; tagTone?: string; icon: IconType; left: string; top: string; w: string }[] = [
    { title: '剧本', sub: '章节导入 / 手写', icon: FileText, left: '3%', top: '49.3%', w: '25%' },
    { title: '场景 01', sub: '开场 · 8 秒', tag: '已批准', tagTone: 'bg-emerald-50 text-emerald-600', icon: Clapperboard, left: '38%', top: '19%', w: '27%' },
    { title: '场景 02', sub: '冲突 · 12 秒', tag: '待审核', tagTone: 'bg-amber-50 text-amber-600', icon: Clapperboard, left: '38%', top: '49.3%', w: '27%' },
    { title: '场景 03', sub: '收束 · 6 秒', tag: '已批准', tagTone: 'bg-emerald-50 text-emerald-600', icon: Clapperboard, left: '38%', top: '80%', w: '27%' },
    { title: '合片', sub: '导出成片', icon: Film, left: '73%', top: '49.3%', w: '24%' },
  ];
  return (
    <div className="relative">
      <div className="absolute -left-6 top-8 h-28 w-28 rounded-full bg-[#dbeafe] blur-3xl" />
      <div className="absolute right-6 top-0 h-24 w-24 rounded-full bg-[#e0e7ff] blur-3xl" />
      <div className="relative overflow-hidden rounded-[32px] border border-[#d7e3f4] bg-[linear-gradient(180deg,_rgba(255,255,255,0.96)_0%,_rgba(248,251,255,0.98)_100%)] p-4 shadow-[0_28px_70px_rgba(59,130,246,0.14)] sm:p-5">
        <div className="mb-3 flex items-center justify-between px-1">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Clapperboard size={16} className="text-[#2563eb]" />
            无限画布 · 漫剧工作台
          </div>
          <span className="rounded-full bg-[#eef5ff] px-3 py-1 text-[11px] font-medium text-[#2563eb]">自动保存版本</span>
        </div>

        <div className="relative aspect-[4/5] overflow-hidden rounded-[24px] border border-[#dbe5f3] bg-[#fbfdff] [background-image:radial-gradient(circle,_#cfd9ea_1px,_transparent_1px)] [background-size:18px_18px] sm:aspect-[4/3]">
          <svg viewBox="0 0 400 300" preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden="true">
            <g fill="none" stroke="#93b4ea" strokeWidth="1.6">
              <path d="M112 148 C132 148 132 56 152 56" vectorEffect="non-scaling-stroke" />
              <path d="M112 148 L152 148" vectorEffect="non-scaling-stroke" />
              <path d="M112 148 C132 148 132 240 152 240" vectorEffect="non-scaling-stroke" />
              <path d="M262 56 C278 56 278 148 294 148" vectorEffect="non-scaling-stroke" />
              <path d="M262 148 L294 148" vectorEffect="non-scaling-stroke" />
              <path d="M262 240 C278 240 278 148 294 148" vectorEffect="non-scaling-stroke" />
            </g>
          </svg>
          {nodes.map((node) => {
            const Icon = node.icon;
            return (
              <div
                key={node.title}
                style={{ left: node.left, top: node.top, width: node.w }}
                className="absolute -translate-y-1/2 rounded-2xl border border-[#d4e1f5] bg-white p-2 shadow-[0_10px_24px_rgba(59,130,246,0.12)] sm:p-2.5"
              >
                <div className="flex items-center gap-1.5">
                  <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-[#eef5ff] text-[#2563eb]">
                    <Icon size={13} />
                  </div>
                  <div className="truncate text-[11px] font-semibold text-slate-900 sm:text-xs">{node.title}</div>
                </div>
                <div className="mt-1 truncate text-[10px] text-slate-500">{node.sub}</div>
                {node.tag ? <span className={`mt-1.5 inline-block rounded-full px-1.5 py-0.5 text-[9px] font-medium ${node.tagTone}`}>{node.tag}</span> : null}
              </div>
            );
          })}
        </div>

        <div className="mt-3 rounded-[24px] bg-[#1e3a5f] p-4 text-white shadow-[0_22px_44px_rgba(29,78,216,0.22)]">
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl bg-white/10 text-[#bfdbfe]">
              <Bot size={18} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-xs text-white/60">你：把场景 02 的节奏再收紧一点，镜头更干脆</div>
              <div className="mt-1.5 text-sm font-medium">已读取画布并生成改动预览，等你确认后才会落地</div>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <div className="rounded-xl bg-white/8 px-3 py-2 text-[11px] leading-5 text-white/55 line-through decoration-white/30">镜头 1：缓慢推进，停留 4 秒</div>
                <div className="rounded-xl bg-[#2563eb]/40 px-3 py-2 text-[11px] leading-5 text-white">镜头 1：快速推进，停留 2 秒</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** 模型广场预览：实时读取公开接口，失败时静默回退为静态说明 */
function ModelSquarePreview({ onModelCatalog }: { onModelCatalog: () => void }) {
  const [models, setModels] = useState<PublicAiModelItem[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    getPublicAiModels()
      .then((result) => {
        if (!cancelled) setModels(result.models || []);
      })
      .catch(() => {
        if (!cancelled) setModels([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const groups = useMemo(() => {
    const config = [
      { key: 'text', label: '文本模型', desc: '小说创作 · 剧本 · AI 对话' },
      { key: 'image', label: '图片模型', desc: '漫画出图 · 角色 · 故事版' },
      { key: 'video', label: '视频模型', desc: '文生视频 · 图生视频' },
    ];
    return config.map((item) => {
      const list = (models || []).filter((model) => model.modality === item.key);
      return { ...item, count: list.length, names: list.slice(0, 3).map((model) => model.display_name) };
    });
  }, [models]);

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {groups.map((group) => (
        <div key={group.key} className="rounded-[24px] border border-[#dbe5f3] bg-[linear-gradient(180deg,_#f8fbff_0%,_#ffffff_100%)] p-4">
          <div className="flex items-baseline justify-between">
            <div className="text-sm font-semibold text-slate-900">{group.label}</div>
            <div className="text-2xl font-semibold text-[#2563eb]">{models === null ? '·' : group.count}</div>
          </div>
          <div className="mt-1 text-xs leading-5 text-slate-500">{group.desc}</div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {group.names.length ? (
              group.names.map((name) => (
                <span key={name} className="rounded-full bg-[#f3f7ff] px-2.5 py-1 text-[11px] text-slate-600">{name}</span>
              ))
            ) : (
              <span className="rounded-full bg-[#f3f7ff] px-2.5 py-1 text-[11px] text-slate-400">{models === null ? '加载中…' : '查看全部'}</span>
            )}
          </div>
        </div>
      ))}
      <button
        onClick={onModelCatalog}
        className="inline-flex items-center justify-center gap-2 rounded-full bg-[#2563eb] px-5 py-3 text-sm font-medium text-white shadow-[0_18px_34px_rgba(59,130,246,0.22)] transition hover:bg-[#1d4ed8] sm:col-span-3"
      >
        免登录浏览全部模型与积分定价
        <ArrowRight size={16} />
      </button>
    </div>
  );
}

export default function PublicLanding({
  onLogin,
  onRegister,
  onPricing,
  onModelCatalog,
  platform,
}: PublicLandingProps) {
  const siteName = platform.site_name || 'StoryCanvas';
  const siteSlogan = platform.site_slogan || 'AI 小说与漫画创作平台';

  const creations: { id: string; no: string; title: string; subtitle: string; icon: IconType; points: string[] }[] = [
    {
      id: 'novel',
      no: '01',
      title: '小说与剧本创作',
      subtitle: '从一句灵感到可连载的长篇，再改成可拍的剧本',
      icon: BookOpen,
      points: [
        '一句灵感生成题材、世界观、三幕式大纲与章节规划',
        '角色小传、关系线、外观与参考图统一管理',
        '章节扩写保持节奏与风格，AI 助手随时帮你改写',
        '小说内容转剧本，直接作为漫画与漫剧的底稿',
      ],
    },
    {
      id: 'manga',
      no: '02',
      title: '漫画创作',
      subtitle: '小说一键转分镜，分镜直接出漫画',
      icon: Brush,
      points: [
        '自动拆分场景、镜头与对白，生成分镜脚本',
        '角色一致性参考，减少画风与形象漂移',
        '漫画批量生成，关键画面支持单图重绘与修正',
        '成图留在项目里，方便复盘与连载迭代',
      ],
    },
    {
      id: 'drama',
      no: '03',
      title: '漫剧创作',
      subtitle: '在无限画布上把剧本做成视频，合成完整漫剧',
      icon: Clapperboard,
      points: [
        '剧本拆成场景，逐场景审核批准后才会生成',
        '角色、故事版与参考图贯穿，视频保持连贯',
        '画布助手对话驱动改写与生成，改动先预览再确认',
        '各场景汇合合片，画布版本可对比、可回退',
      ],
    },
  ];

  const journey = [
    { step: '01', title: '故事框架', desc: '题材、主线冲突与大纲。' },
    { step: '02', title: '角色设定', desc: '外观与参考图统一管理。' },
    { step: '03', title: '章节与剧本', desc: '扩写正文，转成剧本。' },
    { step: '04', title: '分镜脚本', desc: '拆分场景、镜头与对白。' },
    { step: '05', title: '漫画出图', desc: '批量生成与单图重绘。' },
    { step: '06', title: '漫剧成片', desc: '画布生成视频并合片。' },
  ];

  const canvasSteps = [
    { title: '写入剧本', desc: '直接编写，或从小说章节一次性导入，导入只读，不改动原作品。' },
    { title: 'AI 拆分场景', desc: '按剧情密度拆成多个视频单元，附镜头节拍和建议时长。' },
    { title: '逐场景审核', desc: '批准的场景才会被编译，没批准的不会悄悄生成。' },
    { title: '生成视频', desc: '时长自动对齐模型支持的档位，再提交生成。' },
    { title: '合片导出', desc: '各场景视频在画布上汇合，合成完整成片。' },
  ];

  const toolkit: { title: string; desc: string; icon: IconType; points: string[] }[] = [
    {
      title: 'AI 创作助手',
      desc: '小说工作台与漫剧画布都有助手，对话就能读取、改写和生成。',
      icon: Bot,
      points: ['改动先出前后对比，确认后才落地', '读懂画布，按选中节点精确定位', '上传参考图先做风格分析，后续复用', '画布每次改动留存版本，可回退'],
    },
    {
      title: '创作台',
      desc: '不绑定作品，灵感来了随时独立出图、出视频。',
      icon: Sparkles,
      points: ['图片、视频自由切换，自选模型与参数', '生成记录与素材集中管理，方便复用', '需要时唤起助手打磨提示词'],
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
              <div className="text-[11px] text-slate-500 max-sm:hidden">{siteSlogan}</div>
            </div>
          </button>
          <nav className="hidden items-center gap-7 text-sm text-slate-600 lg:flex">
            <a href="#novel" className="transition hover:text-[#2563eb]">小说剧本</a>
            <a href="#manga" className="transition hover:text-[#2563eb]">漫画创作</a>
            <a href="#drama" className="transition hover:text-[#2563eb]">漫剧创作</a>
            <a href="#toolkit" className="transition hover:text-[#2563eb]">配套能力</a>
            <button onClick={onModelCatalog} className="transition hover:text-[#2563eb]">模型广场</button>
            <button onClick={onPricing} className="transition hover:text-[#2563eb]">套餐方案</button>
          </nav>
          <div className="flex items-center gap-2">
            <button onClick={onModelCatalog} className="rounded-full border border-[#d9dfd7] bg-white px-4 py-2 text-sm text-slate-700 shadow-[0_10px_24px_rgba(15,23,42,0.04)] max-sm:hidden lg:hidden">模型广场</button>
            <button onClick={onPricing} className="hidden rounded-full border border-[#d9dfd7] bg-white px-4 py-2 text-sm text-slate-700 shadow-[0_10px_24px_rgba(15,23,42,0.04)] sm:inline-flex lg:hidden xl:inline-flex">套餐</button>
            <button onClick={onLogin} className="whitespace-nowrap rounded-full border border-[#d9dfd7] bg-white px-4 py-2 text-sm text-slate-700 shadow-[0_10px_24px_rgba(15,23,42,0.04)]">登录</button>
            <button onClick={onRegister} className="inline-flex items-center gap-2 whitespace-nowrap rounded-full bg-[#2563eb] px-4 py-2 text-sm font-medium text-white shadow-[0_16px_34px_rgba(59,130,246,0.24)] transition hover:bg-[#1d4ed8]">
              开始创作
              <ArrowRight size={15} />
            </button>
          </div>
        </div>
      </header>

      <main className="relative">
        {/* 英雄区：核心叙事是 小说剧本 → 漫画 → 漫剧 一站式 */}
        <section className="mx-auto grid max-w-7xl gap-10 px-4 pb-10 pt-10 sm:px-6 lg:grid-cols-[minmax(0,1fr)_520px] lg:items-center lg:pt-16">
          <div>
            <div className="inline-flex flex-wrap items-center gap-2 rounded-full border border-[#d7e3f4] bg-white/80 px-3 py-1 text-xs font-medium text-[#2563eb] shadow-[0_10px_24px_rgba(59,130,246,0.08)]">
              <img src="/brand-mark.svg" alt="" className="h-4 w-4 rounded-md" />
              小说 · 剧本 · 漫画 · 漫剧，一个平台一站式完成
            </div>
            <h1 className="mt-6 max-w-3xl text-4xl font-semibold leading-[1.08] tracking-tight text-slate-950 sm:text-5xl lg:text-[54px]">
              写小说、做漫画、拍漫剧，
              <span className="block text-[#2563eb]">一个平台，一站式完成。</span>
            </h1>
            <p className="mt-6 max-w-2xl text-[15px] leading-8 text-slate-600 sm:text-base">
              {siteName} 把小说与剧本创作、漫画创作、漫剧创作串成一条完整链路：同一个故事、同一套角色设定，
              从第一行文字一路做到漫画成图，再到视频成片。AI 助手、创作台与模型广场贯穿其中，不必在多个工具之间来回搬运。
            </p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:flex-wrap">
              <button onClick={onRegister} className="inline-flex items-center justify-center gap-2 rounded-full bg-[#2563eb] px-6 py-3 text-sm font-medium text-white shadow-[0_20px_40px_rgba(59,130,246,0.24)] transition hover:bg-[#1d4ed8]">
                免费开始创作
                <ArrowRight size={16} />
              </button>
              <button onClick={onModelCatalog} className="inline-flex items-center justify-center gap-2 rounded-full border border-[#d9dfd7] bg-white/92 px-6 py-3 text-sm font-medium text-slate-800 shadow-[0_14px_30px_rgba(15,23,42,0.05)] transition hover:border-[#bfd0ea] hover:bg-white">
                浏览模型广场
                <Cpu size={16} />
              </button>
              <button onClick={onPricing} className="inline-flex items-center justify-center gap-2 rounded-full border border-[#d9dfd7] bg-white/92 px-6 py-3 text-sm font-medium text-slate-800 shadow-[0_14px_30px_rgba(15,23,42,0.05)] transition hover:border-[#bfd0ea] hover:bg-white">
                查看套餐方案
                <CreditCard size={16} />
              </button>
            </div>
            <div className="mt-10 grid max-w-2xl gap-4 sm:grid-cols-3">
              <div className="rounded-[24px] border border-[#d9dfd7] bg-white/88 p-4 shadow-[0_16px_36px_rgba(31,95,88,0.06)]">
                <div className="text-2xl font-semibold text-slate-950">3 种成品</div>
                <div className="mt-2 text-sm leading-6 text-slate-600">小说剧本、漫画、漫剧，同一个项目里依次产出。</div>
              </div>
              <div className="rounded-[24px] border border-[#d9dfd7] bg-white/88 p-4 shadow-[0_16px_36px_rgba(31,95,88,0.06)]">
                <div className="text-2xl font-semibold text-slate-950">设定统一</div>
                <div className="mt-2 text-sm leading-6 text-slate-600">角色、世界观与参考图贯穿全流程，不再前后脱节。</div>
              </div>
              <div className="rounded-[24px] border border-[#d9dfd7] bg-white/88 p-4 shadow-[0_16px_36px_rgba(31,95,88,0.06)]">
                <div className="text-2xl font-semibold text-slate-950">全程可控</div>
                <div className="mt-2 text-sm leading-6 text-slate-600">AI 改动先预览再确认，关键内容可审核、可回退。</div>
              </div>
            </div>
          </div>

          <StudioShowcase siteName={siteName} />
        </section>

        {/* 三大创作 */}
        <section className="mx-auto max-w-7xl px-4 py-18 sm:px-6">
          <div className="max-w-3xl">
            <div className="text-sm font-medium text-[#2563eb]">三大创作，一站打通</div>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">先写好故事，再画成漫画，最后拍成漫剧。</h2>
            <p className="mt-4 text-base leading-8 text-slate-600">
              三个阶段共用同一个项目与同一套设定：小说是底稿，分镜是桥梁，漫画与视频是成品，前一步的结果直接成为下一步的输入。
            </p>
          </div>
          <div className="mt-10 grid gap-4 lg:grid-cols-3">
            {creations.map((item) => {
              const Icon = item.icon;
              return (
                <div id={item.id} key={item.id} className={`scroll-mt-24 p-6 ${CARD}`}>
                  <div className="flex items-center justify-between">
                    <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#e8f1ff] text-[#2563eb] shadow-[inset_0_1px_0_rgba(255,255,255,0.65)]">
                      <Icon size={18} />
                    </div>
                    <span className="text-xs font-semibold tracking-[0.18em] text-[#7b988c]">{item.no}</span>
                  </div>
                  <h3 className="mt-5 text-xl font-semibold text-slate-950">{item.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-600">{item.subtitle}</p>
                  <ul className="mt-5 space-y-3">
                    {item.points.map((point) => (
                      <li key={point} className="flex items-start gap-2.5 text-sm leading-6 text-slate-600">
                        <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-[#2563eb]" />
                        {point}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>

          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-6">
            {journey.map((item) => (
              <div key={item.step} className="rounded-[24px] border border-[#d9dfd7] bg-white/88 p-4 shadow-[0_16px_36px_rgba(31,95,88,0.06)]">
                <div className="text-xs font-semibold tracking-[0.18em] text-[#7b988c]">{item.step}</div>
                <div className="mt-3 text-base font-semibold text-slate-950">{item.title}</div>
                <p className="mt-2 text-sm leading-6 text-slate-600">{item.desc}</p>
              </div>
            ))}
          </div>
        </section>

        {/* 漫剧创作详解：无限画布是漫剧的工作台 */}
        <section id="drama-detail" className="border-y border-[#e4ebe5] bg-[linear-gradient(180deg,_rgba(239,245,241,0.78)_0%,_rgba(252,253,251,0.92)_100%)]">
          <div className="mx-auto max-w-7xl px-4 py-18 sm:px-6">
            <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_500px] lg:items-center">
              <div>
                <div className="text-sm font-medium text-[#2563eb]">漫剧创作 · 无限画布</div>
                <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">漫剧的工作台：把剧本一步步做成视频。</h2>
                <p className="mt-4 text-base leading-8 text-slate-600">
                  剧本、场景、角色、故事版和视频都是画布上的节点，上下游关系一目了然。剧本一改，旧的拆分结果会被标记为过期，不会悄悄带着旧内容往下走。
                </p>
                <div className="mt-8 space-y-3">
                  {canvasSteps.map((item, index) => (
                    <div key={item.title} className="flex items-start gap-4 rounded-[24px] border border-[#d9dfd7] bg-white p-4 shadow-[0_14px_32px_rgba(59,130,246,0.06)]">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#eef5ff] text-xs font-semibold text-[#2563eb]">{String(index + 1).padStart(2, '0')}</div>
                      <div>
                        <div className="text-base font-semibold text-slate-950">{item.title}</div>
                        <p className="mt-1 text-sm leading-6 text-slate-600">{item.desc}</p>
                      </div>
                    </div>
                  ))}
                </div>
                <button onClick={onRegister} className="mt-8 inline-flex items-center gap-2 rounded-full bg-[#2563eb] px-5 py-3 text-sm font-medium text-white shadow-[0_18px_34px_rgba(59,130,246,0.22)] transition hover:bg-[#1d4ed8]">
                  开始做我的第一部漫剧
                  <ArrowRight size={16} />
                </button>
              </div>
              <CanvasShowcase />
            </div>
          </div>
        </section>

        {/* 配套能力 */}
        <section id="toolkit" className="mx-auto max-w-7xl px-4 py-18 sm:px-6">
          <div className="max-w-3xl">
            <div className="text-sm font-medium text-[#2563eb]">配套能力</div>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">贯穿三个阶段的助手、创作台与模型广场。</h2>
            <p className="mt-4 text-base leading-8 text-slate-600">
              不管你在写小说、画漫画还是做漫剧，这些能力都在手边：让助手帮你动手，让创作台接住零散灵感，让模型与价格公开透明。
            </p>
          </div>
          <div className="mt-10 grid gap-4 lg:grid-cols-2">
            {toolkit.map((item) => {
              const Icon = item.icon;
              return (
                <div key={item.title} className={`p-6 ${CARD}`}>
                  <div className="flex items-center gap-3">
                    <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#e8f1ff] text-[#2563eb]">
                      <Icon size={18} />
                    </div>
                    <h3 className="text-xl font-semibold text-slate-950">{item.title}</h3>
                  </div>
                  <p className="mt-4 text-sm leading-7 text-slate-600">{item.desc}</p>
                  <div className="mt-4 grid gap-2">
                    {item.points.map((point) => (
                      <div key={point} className="flex items-start gap-2.5 rounded-[18px] bg-[#f4f8ff] px-4 py-2.5 text-sm leading-6 text-slate-600">
                        <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-[#2563eb]" />
                        {point}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
          <div className={`mt-4 p-6 sm:p-8 ${CARD}`}>
            <div className="grid gap-6 lg:grid-cols-[0.7fr_minmax(0,1.3fr)] lg:items-center">
              <div>
                <div className="flex items-center gap-2 text-sm font-medium text-[#2563eb]">
                  <Cpu size={16} />
                  模型广场
                </div>
                <h3 className="mt-3 text-2xl font-semibold tracking-tight text-slate-950">用什么模型、花多少积分，先看清楚再创作。</h3>
                <p className="mt-3 text-sm leading-7 text-slate-600">文本、图片、视频模型的能力参数与积分单价全部公开，无需注册即可浏览，下面的数据实时读取自平台。</p>
              </div>
              <ModelSquarePreview onModelCatalog={onModelCatalog} />
            </div>
          </div>
        </section>

        {/* 平台优势 + 适合谁 */}
        <section id="advantages" className="mx-auto max-w-7xl px-4 pb-18 sm:px-6">
          <div className="grid gap-4 lg:grid-cols-[1.05fr_0.95fr]">
            <div className={`p-6 sm:p-8 ${CARD}`}>
              <div className="text-sm font-medium text-[#2563eb]">平台优势</div>
              <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-950">为长期创作而生，而不是一次性的随机生成。</h2>
              <div className="mt-8 grid gap-4 md:grid-cols-2">
                {([
                  [Users, '设定一致', '角色资料与参考图贯穿全项目，章节、漫画与视频沿用同一套上下文。'],
                  [ScrollText, '文本到镜头自然衔接', '正文语义直接转为分镜与画面表达，不必换工具重新开始。'],
                  [History, '可审核、可回退', '场景需批准才生成，画布每次改动都留有版本，随时恢复。'],
                  [ShieldCheck, '透明计费', '模型积分单价公开可查，套餐与额度清晰，没有隐藏消耗。'],
                ] as [IconType, string, string][]).map(([Icon, title, desc]) => (
                  <div key={title} className="rounded-[24px] bg-[#f4f8ff] p-4">
                    <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                      <Icon size={16} className="text-[#2563eb]" />
                      {title}
                    </div>
                    <p className="mt-3 text-sm leading-7 text-slate-600">{desc}</p>
                  </div>
                ))}
              </div>
            </div>

            <div id="scenarios" className="rounded-[32px] bg-[#163b73] p-6 text-white shadow-[0_28px_70px_rgba(16,24,40,0.22)] sm:p-8">
              <div className="text-sm font-medium text-[#bfdbfe]">适合谁使用</div>
              <h2 className="mt-3 text-3xl font-semibold tracking-tight">面向想把内容持续做下去的人。</h2>
              <div className="mt-8 space-y-4">
                {[
                  { title: '网文作者', desc: '快速搭建长篇框架，稳定日更连载，再把爆款章节延伸成漫画与漫剧。' },
                  { title: '漫画工作室', desc: '把剧本、分镜和角色参考整合在同一工作流里，减少沟通成本。' },
                  { title: '漫剧与短视频创作者', desc: '从剧本到视频合片都在画布上完成，用助手加速反复调整。' },
                  { title: '内容创业团队', desc: '适合做 IP 孵化、短篇试水、爆款验证和图文视频内容矩阵扩展。' },
                ].map((group) => (
                  <div key={group.title} className="rounded-[24px] border border-white/10 bg-white/6 p-4">
                    <div className="text-lg font-semibold">{group.title}</div>
                    <p className="mt-2 text-sm leading-7 text-white/72">{group.desc}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-4 pb-18 sm:px-6">
          <div className="overflow-hidden rounded-[36px] border border-[#d9dfd7] bg-[linear-gradient(135deg,_#1e40af_0%,_#2563eb_48%,_#3b82f6_100%)] p-8 text-white shadow-[0_28px_70px_rgba(59,130,246,0.22)] sm:p-10">
            <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
              <div>
                <div className="text-sm font-medium text-[#dbeafe]">准备开始你的第一个项目</div>
                <h2 className="mt-3 max-w-2xl text-3xl font-semibold tracking-tight sm:text-4xl">从一句故事灵感出发，一路做成小说、漫画和漫剧。</h2>
                <p className="mt-4 max-w-2xl text-sm leading-7 text-white/78 sm:text-base">
                  现在就体验 {siteName}：把世界观、角色、章节、漫画和视频放到同一条生产线上，一个账号全部可用。
                </p>
              </div>
              <div className="flex flex-col gap-3 sm:flex-row">
                <button onClick={onRegister} className="inline-flex items-center justify-center gap-2 rounded-full bg-white px-6 py-3 text-sm font-medium text-[#1d4ed8] shadow-[0_18px_40px_rgba(6,18,16,0.2)] transition hover:bg-[#eff6ff]">
                  立即免费开始
                  <ArrowRight size={16} />
                </button>
                <button onClick={onModelCatalog} className="inline-flex items-center justify-center gap-2 rounded-full border border-white/20 bg-white/8 px-6 py-3 text-sm font-medium text-white transition hover:bg-white/12">
                  浏览模型广场
                  <Cpu size={16} />
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
