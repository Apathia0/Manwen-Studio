import { useState } from 'react';
import { Search, Download, Loader2 } from 'lucide-react';
import { searchNovels, startCrawl, type NovelSearchResult } from '../api';

interface Props {
  storyId: number;
  onCrawlStarted: (taskId: string) => void;
}

export default function NovelSearchPanel({ storyId, onCrawlStarted }: Props) {
  const [keyword, setKeyword] = useState('');
  const [results, setResults] = useState<NovelSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [crawling, setCrawling] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = async () => {
    if (!keyword.trim()) return;
    setSearching(true);
    setError(null);
    try {
      const data = await searchNovels(keyword.trim());
      setResults(data.results);
    } catch (e: any) {
      setError(e.message || '搜索失败');
    } finally {
      setSearching(false);
    }
  };

  const handleCrawl = async (book: NovelSearchResult) => {
    setCrawling(book.book_id);
    setError(null);
    try {
      const { task_id } = await startCrawl(storyId, book.book_id, book.platform, 100);
      onCrawlStarted(task_id);
    } catch (e: any) {
      setError(e.message || '爬取失败');
    } finally {
      setCrawling(null);
    }
  };

  return (
    <div className="flex h-full flex-col p-4">
      <h3 className="text-lg font-semibold text-slate-700 mb-4">搜索网络小说</h3>

      <div className="flex gap-2 mb-4">
        <input
          type="text"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder="输入书名或关键词..."
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
        <button
          onClick={handleSearch}
          disabled={searching || !keyword.trim()}
          className="flex items-center gap-1 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          搜索
        </button>
      </div>

      {error && <p className="mb-3 text-sm text-red-500">{error}</p>}

      {results.length > 0 && (
        <div className="flex-1 overflow-auto space-y-3">
          <p className="text-xs text-slate-500">找到 {results.length} 个结果</p>
          {results.map((book) => (
            <div key={book.book_id} className="rounded-lg border border-slate-200 p-3 hover:border-blue-300">
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <h4 className="font-semibold text-slate-800 truncate">{book.title}</h4>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {book.author} {book.genre && `· ${book.genre}`}
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">{book.status}</p>
                  {book.desc && (
                    <p className="text-xs text-slate-600 mt-1 line-clamp-2">{book.desc}</p>
                  )}
                </div>
                <button
                  onClick={() => handleCrawl(book)}
                  disabled={crawling === book.book_id}
                  className="ml-2 flex shrink-0 items-center gap-1 rounded-lg bg-green-600 px-3 py-1.5 text-xs text-white hover:bg-green-700 disabled:opacity-50"
                >
                  {crawling === book.book_id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Download className="h-3.5 w-3.5" />
                  )}
                  爬取
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {results.length === 0 && !searching && (
        <div className="flex flex-1 items-center justify-center">
          <p className="text-sm text-slate-400">
            搜索起点中文网的热门小说，系统将自动爬取免费章节内容
          </p>
        </div>
      )}
    </div>
  );
}