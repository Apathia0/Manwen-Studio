import type { ReactNode } from 'react';

/** 对展示给用户的 Agent 文本做最小必要脱敏，避免回显凭据和内部路径。 */
export function sanitizeAgentText(value: string): string {
  return value
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/gi, 'Bearer [已隐藏]')
    .replace(/\b(?:sk|pk|rk)-[A-Za-z0-9_-]{12,}\b/gi, '[已隐藏密钥]')
    .replace(/\b(?:api[_ -]?key|token|secret|password)\s*[:=]\s*[^\s,;]+/gi, '$1: [已隐藏]')
    .replace(/([?&](?:api[_-]?key|token|secret|password)=)[^&\s]+/gi, '$1[已隐藏]')
    .replace(/(?:[A-Za-z]:\\|\\\\|\/home\/|\/opt\/|\/var\/|\/tmp\/)[^\s`<>]+/g, '[内部路径]');
}

function inlineText(value: string, keyPrefix: string): ReactNode[] {
  const tokens = value.split(/(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\[[^\]]+\]\([^)]+\))/g);
  return tokens.map((token, index) => {
    const key = `${keyPrefix}-${index}`;
    if ((token.startsWith('**') && token.endsWith('**')) || (token.startsWith('__') && token.endsWith('__'))) return <strong key={key} className="font-semibold text-slate-900">{token.slice(2, -2)}</strong>;
    if (token.startsWith('`') && token.endsWith('`')) return <code key={key} className="rounded bg-blue-100 px-1 py-0.5 font-mono text-[12px] text-blue-700">{token.slice(1, -1)}</code>;
    const link = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link) return <a key={key} href={link[2]} target="_blank" rel="noreferrer" className="text-blue-600 underline underline-offset-2">{link[1]}</a>;
    return token;
  });
}

/** 将常见 Markdown 语法转换成适合对话气泡的轻量排版。 */
export function renderAgentText(value: string): ReactNode {
  const text = sanitizeAgentText(value).replace(/\r\n?/g, '\n').trim();
  if (!text) return null;
  const blocks = text.split(/(```[\s\S]*?```)/g).filter(Boolean);
  return blocks.map((block, blockIndex) => {
    if (block.startsWith('```')) {
      const code = block.replace(/^```[^\n]*\n?/, '').replace(/```\s*$/, '');
      return <pre key={`code-${blockIndex}`} className="my-2 max-h-60 overflow-auto rounded-lg bg-slate-900 p-3 text-xs leading-relaxed text-slate-200"><code>{code}</code></pre>;
    }
    const lines = block.split('\n');
    const nodes: ReactNode[] = [];
    let list: { ordered: boolean; items: string[] } | null = null;
    const flushList = () => {
      if (!list) return;
      const List = list.ordered ? 'ol' : 'ul';
      nodes.push(<List key={`list-${nodes.length}`} className={`${list.ordered ? 'list-decimal' : 'list-disc'} my-2 space-y-1 pl-5`}>{list.items.map((item, index) => <li key={`${index}-${item.slice(0, 12)}`}>{inlineText(item, `item-${nodes.length}-${index}`)}</li>)}</List>);
      list = null;
    };
    lines.forEach((line, lineIndex) => {
      const heading = line.match(/^#{1,3}\s+(.+)$/);
      const bullet = line.match(/^\s*[-*+]\s+(.+)$/);
      const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
      if (bullet || ordered) {
        const orderedList = Boolean(ordered);
        if (!list || list.ordered !== orderedList) { flushList(); list = { ordered: orderedList, items: [] }; }
        list.items.push((bullet || ordered)![1]);
      } else {
        flushList();
        if (!line.trim()) return;
        if (heading) nodes.push(<h4 key={`heading-${lineIndex}`} className="mt-3 mb-1 text-sm font-semibold text-slate-900">{inlineText(heading[1], `heading-${lineIndex}`)}</h4>);
        else if (line.startsWith('> ')) nodes.push(<blockquote key={`quote-${lineIndex}`} className="my-2 border-l-2 border-blue-300 pl-3 text-slate-500">{inlineText(line.slice(2), `quote-${lineIndex}`)}</blockquote>);
        else nodes.push(<p key={`paragraph-${lineIndex}`} className="my-1.5">{inlineText(line, `paragraph-${lineIndex}`)}</p>);
      }
    });
    flushList();
    return <div key={`block-${blockIndex}`}>{nodes}</div>;
  });
}
