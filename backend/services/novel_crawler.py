import asyncio
import json
import logging
import re
from typing import Any
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup

from database import SessionLocal
from models import NovelSource, Story, Chapter

logger = logging.getLogger("novel_crawler")

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

MOBILE_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# ── 平台 URL 常量 ────────────────────────────────────

# 起点
QIDIAN_SEARCH_URL = "https://m.qidian.com/soushu/{keyword}.html"
QIDIAN_BOOK_URL = "https://m.qidian.com/book/{book_id}/"
QIDIAN_CATALOG_URL = "https://m.qidian.com/book/{book_id}/catalog/"
QIDIAN_CHAPTER_URL = "https://m.qidian.com/book/{book_id}/{chapter_id}/"

# 番茄小说（fanqienovel.com）
FANQIE_SEARCH_URL = "https://fanqienovel.com/search"

# 七猫（qimao.com）
QIMAO_SEARCH_URL = "https://www.qimao.com/search/index/"
QIMAO_BOOK_URL = "https://www.qimao.com/shuku/{book_id}/"
QIMAO_CATALOG_URL = "https://www.qimao.com/shuku/{book_id}/list/"
QIMAO_CHAPTER_URL = "https://www.qimao.com/shuku/{book_id}/{chapter_id}/"

# 纵横（zongheng.com）
ZONGHENG_SEARCH_URL = "http://search.zongheng.com/s"
ZONGHENG_BOOK_URL = "http://book.zongheng.com/book/{book_id}.html"
ZONGHENG_CATALOG_URL = "http://book.zongheng.com/showchapter/{book_id}.html"
ZONGHENG_CHAPTER_URL = "http://book.zongheng.com/chapter/{book_id}/{chapter_id}.html"


# ── 通用工具 ──────────────────────────────────────────

def _extract_page_context(html: str) -> dict | None:
    m = re.search(
        r'<script[^>]+id=["\']vite-plugin-ssr_pageContext["\'][^>]*>([\s\S]*?)</script>',
        html,
        re.IGNORECASE,
    )
    if not m:
        return None
    try:
        return json.loads(m[1])
    except json.JSONDecodeError:
        return None


# ════════════════════════════════════════════════════════
# 起点中文网
# ════════════════════════════════════════════════════════

async def search_qidian(keyword: str, limit: int = 10) -> list[dict]:
    async with httpx.AsyncClient(timeout=15, headers=MOBILE_HEADERS, follow_redirects=True) as client:
        resp = await client.get(
            QIDIAN_SEARCH_URL.format(keyword=quote(keyword)),
        )
        resp.raise_for_status()
        html = resp.text

        page_ctx = _extract_page_context(html)
        if page_ctx:
            try:
                page_data = page_ctx.get("pageContext", {}).get("pageProps", {}).get("pageData", {})
                books = page_data.get("bookInfo", {}).get("records", [])
                if books:
                    return [
                        {
                            "book_id": str(b.get("bid", "")),
                            "title": b.get("bName", ""),
                            "author": b.get("bAuth", ""),
                            "genre": "·".join(filter(None, [b.get("cat", ""), b.get("subCatName", "")])),
                            "desc": (b.get("desc", "") or "")[:200],
                            "status": "已完结" if b.get("state") == "完结" else "连载中",
                            "platform": "qidian",
                            "url": f"https://m.qidian.com/book/{b.get('bid', '')}/",
                        }
                        for b in books[:limit]
                        if b.get("bName")
                    ]
            except (KeyError, TypeError):
                pass

        soup = BeautifulSoup(html, "html.parser")
        results = []
        for item in soup.select(".book-img-text li, .search-result-list li")[:limit]:
            link = item.select_one("h2 a, h3 a, .book-name a")
            if not link:
                continue
            href = link.get("href", "")
            book_id = ""
            id_match = re.search(r"/book/(\d+)", href)
            if id_match:
                book_id = id_match.group(1)

            author_el = item.select_one(".author, .book-author")
            results.append({
                "book_id": book_id,
                "title": link.get_text(strip=True),
                "author": author_el.get_text(strip=True) if author_el else "",
                "genre": "",
                "desc": "",
                "status": "未知",
                "platform": "qidian",
                "url": urljoin(QIDIAN_BOOK_URL, href) if href else "",
            })
        return results


async def get_qidian_catalog(book_id: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15, headers=MOBILE_HEADERS, follow_redirects=True) as client:
        resp = await client.get(QIDIAN_CATALOG_URL.format(book_id=book_id))
        resp.raise_for_status()
        html = resp.text

        page_ctx = _extract_page_context(html)
        if page_ctx:
            try:
                vol_data = page_ctx.get("pageContext", {}).get("pageProps", {}).get("pageData", {})
                chapters = []
                for vol in vol_data.get("vs", []):
                    vol_name = vol.get("vN", "")
                    for ch in vol.get("cs", []):
                        chapters.append({
                            "chapter_id": str(ch.get("id", "")),
                            "title": ch.get("cN", ""),
                            "volume": vol_name,
                            "free": ch.get("sS") != "vip",
                        })
                return chapters
            except (KeyError, TypeError):
                pass

        soup = BeautifulSoup(html, "html.parser")
        chapters = []
        for li in soup.select(".catalog-list li, .chapter-list li"):
            link = li.select_one("a")
            if not link:
                continue
            href = link.get("href", "")
            ch_id_match = re.search(r"/(\d+)/?$", href)
            if not ch_id_match:
                continue
            chapters.append({
                "chapter_id": ch_id_match.group(1),
                "title": link.get_text(strip=True),
                "volume": "",
                "free": True,
            })
        return chapters


async def get_qidian_chapter(book_id: str, chapter_id: str) -> str | None:
    async with httpx.AsyncClient(timeout=15, headers=MOBILE_HEADERS, follow_redirects=True) as client:
        resp = await client.get(
            QIDIAN_CHAPTER_URL.format(book_id=book_id, chapter_id=chapter_id)
        )
        resp.raise_for_status()
        html = resp.text

        page_ctx = _extract_page_context(html)
        if page_ctx:
            try:
                page_data = page_ctx.get("pageContext", {}).get("pageProps", {}).get("pageData", {})
                content = page_data.get("chapterInfo", {}).get("content", "")
                if content:
                    content = re.sub(r"<[^>]+>", "", content)
                    content = re.sub(r"&nbsp;", " ", content)
                    return content.strip()
            except (KeyError, TypeError):
                pass

        soup = BeautifulSoup(html, "html.parser")
        content_el = soup.select_one(".read-content, .chapter-content, #chapter-content")
        if content_el:
            return content_el.get_text("\n", strip=True)
        return None


async def crawl_qidian_chapter(chapter_data: dict, book_id: str) -> dict | None:
    """爬取单章内容，供并行调用"""
    try:
        content = await get_qidian_chapter(book_id, chapter_data["chapter_id"])
        if not content:
            return None
        return {
            "chapter_number": chapter_data["_index"],
            "title": chapter_data["title"],
            "content": content,
            "word_count": len(content),
            "source_url": QIDIAN_CHAPTER_URL.format(book_id=book_id, chapter_id=chapter_data["chapter_id"]),
        }
    except Exception as e:
        logger.warning(f"起点第{chapter_data['_index']}章爬取失败: {e}")
        return None


async def crawl_qidian_novel(
    book_id: str,
    story_id: int,
    max_chapters: int = 100,
    task_id: str | None = None,
    **kwargs,
) -> dict:
    db = SessionLocal()
    try:
        story = db.query(Story).filter(Story.id == story_id).first()
        if not story:
            raise ValueError(f"故事 {story_id} 不存在")

        logger.info(f"获取起点小说 {book_id} 目录...")
        catalog = await get_qidian_catalog(book_id)
        if not catalog:
            raise ValueError("无法获取章节目录")

        free_chapters = [c for c in catalog if c.get("free", True)][:max_chapters]
        logger.info(f"共 {len(catalog)} 章，其中 {len(free_chapters)} 章免费可爬取")

        source = db.query(NovelSource).filter(
            NovelSource.story_id == story_id,
            NovelSource.platform == "qidian",
        ).first()
        if source:
            source.total_chapters = len(catalog)
            source.crawl_status = "crawling"
            db.commit()

        # 并行爬取
        for i, ch in enumerate(free_chapters):
            ch["_index"] = i + 1

        sem = asyncio.Semaphore(5)

        async def fetch_one(ch):
            if task_id and asyncio.current_task() and asyncio.current_task().cancelled():
                return None
            async with sem:
                return await crawl_qidian_chapter(ch, book_id)

        tasks = [fetch_one(ch) for ch in free_chapters]
        results = await asyncio.gather(*tasks)
        chapters_data = [r for r in results if r is not None]

        # 写入数据库
        crawled = 0
        for i, ch_data in enumerate(chapters_data):
            content = ch_data["content"]
            try:
                existing = db.query(Chapter).filter(
                    Chapter.story_id == story_id,
                    Chapter.chapter_number == ch_data["chapter_number"],
                ).first()

                ch_info = free_chapters[i] if i < len(free_chapters) else {}
                title = ch_data["title"] or ch_info.get("title", "")

                if existing:
                    existing.novel_content = content
                    existing.content_source = "crawled"
                    existing.title = title
                else:
                    new_chapter = Chapter(
                        story_id=story_id,
                        chapter_number=ch_data["chapter_number"],
                        title=title,
                        novel_content=content,
                        content_source="crawled",
                        status="completed",
                        word_count=ch_data["word_count"],
                    )
                    db.add(new_chapter)

                crawled += 1
                if crawled % 10 == 0:
                    db.commit()
                    logger.info(f"已入库 {crawled}/{len(chapters_data)} 章")
            except Exception as e:
                logger.error(f"入库第 {ch_data['chapter_number']} 章失败: {e}")

        db.commit()

        if source:
            source.crawled_chapters = crawled
            source.word_count = sum(
                len(c.novel_content or "")
                for c in db.query(Chapter).filter(Chapter.story_id == story_id).all()
            )
            source.crawl_status = "completed"
            db.commit()

        return {
            "status": "completed",
            "total_chapters": len(catalog),
            "crawled_chapters": crawled,
        }

    finally:
        db.close()


async def crawl_qidian_novel_raw(
    book_id: str,
    max_chapters: int = 100,
    task_id: str | None = None,
    **kwargs,
) -> list[dict]:
    """爬取起点小说章节（并行），返回原始数据列表"""
    logger.info(f"获取起点小说 {book_id} 目录...")
    catalog = await get_qidian_catalog(book_id)
    if not catalog:
        raise ValueError("无法获取章节目录")

    free_chapters = [c for c in catalog if c.get("free", True)][:max_chapters]
    logger.info(f"共 {len(catalog)} 章，其中 {len(free_chapters)} 章免费可爬取")

    for i, ch in enumerate(free_chapters):
        ch["_index"] = i + 1

    total = len(free_chapters)
    sem = asyncio.Semaphore(5)
    completed = [0]

    async def fetch_one(ch):
        if task_id and asyncio.current_task() and asyncio.current_task().cancelled():
            return None
        async with sem:
            try:
                content = await get_qidian_chapter(book_id, ch["chapter_id"])
                if not content:
                    logger.warning(f"起点第{ch['_index']}章内容为空: {ch.get('title', '')}")
                    return None
                completed[0] += 1
                if completed[0] % 10 == 0:
                    logger.info(f"起点并行爬取: {completed[0]}/{total} 章")
                return {
                    "chapter_number": ch["_index"],
                    "title": ch.get("title", ""),
                    "content": content,
                    "word_count": len(content),
                    "source_url": QIDIAN_CHAPTER_URL.format(book_id=book_id, chapter_id=ch["chapter_id"]),
                }
            except Exception as e:
                logger.error(f"起点第{ch['_index']}章爬取失败: {e}")
                completed[0] += 1
                return None

    tasks = [fetch_one(ch) for ch in free_chapters]
    results = await asyncio.gather(*tasks)
    chapters_data = [r for r in results if r is not None]
    chapters_data.sort(key=lambda x: x["chapter_number"])

    logger.info(f"起点爬取完成: {len(chapters_data)}/{total} 章")
    return chapters_data


# ════════════════════════════════════════════════════════
# 番茄小说（fanqienovel.com）
# ════════════════════════════════════════════════════════

# 番茄小说第三方搜索 API（当主站搜索不可用时使用）
FANQIE_THIRD_PARTY_API = "http://140.143.165.56:5000"


async def search_fanqie(keyword: str, limit: int = 10) -> list[dict]:
    """搜索番茄小说（优先第三方 API，失败后尝试搜索页 HTML）"""
    # 第一版：第三方 API 搜索
    try:
        async with httpx.AsyncClient(timeout=15, headers=MOBILE_HEADERS) as client:
            resp = await client.get(
                f"{FANQIE_THIRD_PARTY_API}/searchNovel",
                params={"title": keyword},
            )
            if resp.status_code == 200:
                data = resp.json()
                books = data.get("data", {}).get("book_data", [])
                if books:
                    return [
                        {
                            "book_id": b.get("book_id", "").replace("_fanqie", ""),
                            "title": b.get("book_name", ""),
                            "author": b.get("author", ""),
                            "genre": b.get("genre", ""),
                            "desc": (b.get("description", "") or "")[:200],
                            "status": b.get("status", "未知"),
                            "platform": "fanqie",
                            "url": f"https://fanqienovel.com/page/{b.get('book_id', '').replace('_fanqie', '')}",
                        }
                        for b in books[:limit]
                        if b.get("book_name")
                    ]
    except Exception as e:
        logger.warning(f"番茄第三方 API 搜索失败，切换 HTML 模式: {e}")

    # 第二版：搜索页 HTML 解析（原方式）
    try:
        headers = {
            **MOBILE_HEADERS,
            "Referer": "https://fanqienovel.com/",
        }
        async with httpx.AsyncClient(timeout=15, headers=headers, follow_redirects=True) as client:
            resp = await client.get(
                FANQIE_SEARCH_URL,
                params={"query": keyword, "type": 3},
            )
            if resp.status_code != 200:
                logger.warning(f"番茄搜索页返回 {resp.status_code}")
                return []

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")
            results = []

            try:
                script = soup.find("script", {"id": "__NEXT_DATA__"})
                if script:
                    data = json.loads(script.string)
                    books = data.get("props", {}).get("pageProps", {}).get("bookList", [])
                    if books:
                        return [
                            {
                                "book_id": str(b.get("bookId", "")),
                                "title": b.get("bookName", ""),
                                "author": b.get("author", ""),
                                "genre": b.get("categoryName", ""),
                                "desc": (b.get("abstract", "") or "")[:200],
                                "status": "已完结" if b.get("bookStatus") == 2 else "连载中",
                                "platform": "fanqie",
                                "url": f"https://fanqienovel.com/page/{b.get('bookId', '')}",
                            }
                            for b in books[:limit]
                            if b.get("bookName")
                        ]
            except (KeyError, TypeError, json.JSONDecodeError):
                pass

            page_ctx = _extract_page_context(html)
            if page_ctx:
                try:
                    page_data = page_ctx.get("pageContext", {}).get("pageProps", {}).get("pageData", {})
                    books = page_data.get("bookList", [])
                    if books:
                        return [
                            {
                                "book_id": str(b.get("bookId", "")),
                                "title": b.get("bookName", ""),
                                "author": b.get("author", ""),
                                "genre": b.get("categoryName", ""),
                                "desc": (b.get("abstract", "") or "")[:200],
                                "status": "已完结" if b.get("bookStatus") == 2 else "连载中",
                                "platform": "fanqie",
                                "url": f"https://fanqienovel.com/page/{b.get('bookId', '')}",
                            }
                            for b in books[:limit]
                            if b.get("bookName")
                        ]
                except (KeyError, TypeError):
                    pass

            for item in soup.select(".search-book-item, .book-item, [class*='search'] [class*='item'], .result-item")[:limit]:
                link = item.select_one("a[href*='/page/']")
                if not link:
                    link = item.select_one("a")
                    if not link:
                        continue
                href = link.get("href", "")
                book_id = ""
                id_match = re.search(r"/page/(\d+)", href)
                if id_match:
                    book_id = id_match.group(1)
                if not book_id:
                    continue
                title_el = item.select_one(".book-name, .book-title, .name, h3")
                author_el = item.select_one(".author, .author-name")
                desc_el = item.select_one(".desc, .abstract, .intro, .summary")
                results.append({
                    "book_id": book_id,
                    "title": title_el.get_text(strip=True) if title_el else "",
                    "author": author_el.get_text(strip=True) if author_el else "",
                    "genre": "",
                    "desc": (desc_el.get_text(strip=True) if desc_el else "")[:200],
                    "status": "未知",
                    "platform": "fanqie",
                    "url": f"https://fanqienovel.com/page/{book_id}",
                })

            return results
    except Exception as e:
        logger.error(f"番茄搜索全部失败: {e}")
        return []


async def get_fanqie_catalog(book_id: str) -> list[dict]:
    """获取番茄小说章节目录（优先 API，失败后 HTML 降级）"""
    # 第一版：API 快速获取
    try:
        async with httpx.AsyncClient(timeout=15, headers={
            **MOBILE_HEADERS, "Referer": "https://fanqienovel.com/",
        }) as client:
            resp = await client.get(
                "https://fanqienovel.com/api/reader/directory/detail",
                params={"bookId": book_id},
            )
            if resp.status_code == 200:
                data = resp.json()
                inner = data.get("data", {})
                # 可能的格式1: chapterListWithVolume（每卷一个列表）
                vol_list = inner.get("chapterListWithVolume", [])
                if vol_list:
                    chapters = []
                    for vol in vol_list:
                        vol_name = ""
                        if isinstance(vol, dict):
                            vol_name = vol.get("volume_name", "")
                            items = vol.get("chapterList", vol.get("items", []))
                        elif isinstance(vol, list):
                            items = vol
                        else:
                            continue
                        for ch in items if isinstance(items, list) else []:
                            chapters.append({
                                "chapter_id": str(ch.get("itemId", ch.get("chapterId", ""))),
                                "title": ch.get("title", ""),
                                "volume": vol_name or ch.get("volume_name", ""),
                                "free": True,
                            })
                    if chapters:
                        return chapters

                # 可能的格式2: chapterList（扁平列表）
                chapter_list = inner.get("chapterList", [])
                if chapter_list:
                    return [
                        {
                            "chapter_id": str(ch.get("itemId", "")),
                            "title": ch.get("title", ""),
                            "volume": ch.get("volumeName", ""),
                            "free": ch.get("isAuth", 1) == 0,
                        }
                        for ch in chapter_list
                        if ch.get("title")
                    ]

                # 可能的格式3: allItem（旧版卷列表）
                vol_list = inner.get("allItem", [])
                if vol_list:
                    chapters = []
                    for ch in vol_list:
                        chapters.append({
                            "chapter_id": str(ch.get("itemId", ch.get("chapterId", ""))),
                            "title": ch.get("title", ""),
                            "volume": ch.get("volumeName", ""),
                            "free": True,
                        })
                    if chapters:
                        return chapters
    except Exception as e:
        logger.warning(f"番茄目录 API 失败，尝试 HTML 降级: {e}")

    # 第二版：HTML 页面解析降级
    try:
        async with httpx.AsyncClient(timeout=15, headers={
            **MOBILE_HEADERS, "Referer": "https://fanqienovel.com/",
        }, follow_redirects=True) as client:
            resp = await client.get(f"https://fanqienovel.com/page/{book_id}")
            if resp.status_code != 200:
                return []

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")
            chapters = []

            # 尝试从 SSR 数据提取
            page_ctx = _extract_page_context(html)
            if page_ctx:
                try:
                    page_data = page_ctx.get("pageContext", {}).get("pageProps", {}).get("pageData", {})
                    all_item = page_data.get("allItem", [])
                    if all_item:
                        return [
                            {
                                "chapter_id": str(ch.get("itemId", "")),
                                "title": ch.get("title", ""),
                                "volume": ch.get("volumeName", ""),
                                "free": True,
                            }
                            for ch in all_item if ch.get("title")
                        ]
                except (KeyError, TypeError):
                    pass

            # HTML 列表解析
            for item in soup.select(".chapter-item, .chapter-list-item, li[class*='chapter'], [class*='catalog'] a"):
                link = item if item.name == "a" and item.get("href") else item.select_one("a")
                if not link:
                    continue
                href = link.get("href", "")
                ch_id_match = re.search(r"/reader/\d+/(\d+)", href)
                if not ch_id_match:
                    ch_id_match = re.search(r"itemId=(\d+)", href)
                if not ch_id_match:
                    continue

                chapters.append({
                    "chapter_id": ch_id_match.group(1),
                    "title": link.get_text(strip=True),
                    "volume": "",
                    "free": True,
                })

            return chapters
    except Exception as e:
        logger.error(f"番茄目录 HTML 降级失败: {e}")
        return []


async def get_fanqie_chapter(book_id: str, chapter_id: str) -> str | None:
    """获取番茄小说章节内容（优先 API，失败后 HTML 降级）"""
    # 第一版：API 快速获取
    try:
        async with httpx.AsyncClient(timeout=15, headers=MOBILE_HEADERS) as client:
            resp = await client.get(
                "https://fanqienovel.com/api/reader/full",
                params={"itemId": chapter_id},
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("data", {}).get("content", "")
                if content:
                    content = re.sub(r"<[^>]+>", "", content)
                    content = content.replace("&nbsp;", " ")
                    if content.strip():
                        return content.strip()
    except Exception as e:
        logger.warning(f"番茄章节 API 失败，尝试 HTML 降级: {e}")

    # 第二版：HTML 页面解析降级（优先 reader 页，其次 book page 的 SSR 数据）
    try:
        headers_h = {**MOBILE_HEADERS, "Referer": "https://fanqienovel.com/"}
        async with httpx.AsyncClient(timeout=15, headers=headers_h, follow_redirects=True) as client:
            # 方式 A: reader 页
            resp = await client.get(
                f"https://fanqienovel.com/reader/{book_id}/{chapter_id}"
            )
            if resp.status_code == 200:
                html = resp.text
                soup = BeautifulSoup(html, "html.parser")
                page_ctx = _extract_page_context(html)
                if page_ctx:
                    try:
                        reader_data = page_ctx.get("pageContext", {}).get("pageProps", {}).get("pageData", {}).get("reader", {})
                        content = reader_data.get("content", "")
                        if content:
                            content = re.sub(r"<[^>]+>", "", content)
                            return content.strip()
                    except (KeyError, TypeError):
                        pass
                content_el = soup.select_one(".content-area, .article-content, [class*='content'], .read-content, #content")
                if content_el:
                    return content_el.get_text("\n", strip=True)

    except Exception as e:
        logger.warning(f"番茄章节 reader 页降级失败: {e}")

    # 方式 B: book page 提取 __INITIAL_STATE__（可能包含内容预览）
    try:
        async with httpx.AsyncClient(timeout=15, headers=headers_h, follow_redirects=True) as client:
            resp = await client.get(f"https://fanqienovel.com/page/{book_id}")
            if resp.status_code == 200:
                m = re.search(r"__INITIAL_STATE__\s*=\s*(\{.+?\});", resp.text, re.DOTALL)
                if m:
                    state = json.loads(m.group(1))
                    reader_state = state.get("reader", {})
                    chapter_data = reader_state.get("chapterData", {})
                    if chapter_data and isinstance(chapter_data, dict):
                        content = chapter_data.get("content", "")
                        if content:
                            content = re.sub(r"<[^>]+>", "", content)
                            return content.strip()
                    preview_state = state.get("preview", {})
                    preview_data = preview_state.get("chapterData", {})
                    if preview_data and isinstance(preview_data, dict):
                        content = preview_data.get("content", "")
                        if content:
                            content = re.sub(r"<[^>]+>", "", content)
                            return content.strip()
    except Exception as e:
        logger.warning(f"番茄章节 page SSR 降级失败: {e}")

    return None


async def crawl_fanqie_novel_raw(
    book_id: str,
    max_chapters: int = 100,
    task_id: str | None = None,
    **kwargs,
) -> list[dict]:
    """爬取番茄小说章节（并行）"""
    logger.info(f"获取番茄小说 {book_id} 目录...")
    catalog = await get_fanqie_catalog(book_id)
    if not catalog:
        raise ValueError("无法获取番茄小说章节目录")

    free_chapters = catalog[:max_chapters]
    for i, ch in enumerate(free_chapters):
        ch["_index"] = i + 1

    total = len(free_chapters)
    sem = asyncio.Semaphore(5)
    completed = [0]

    async def fetch_one(ch):
        if task_id and asyncio.current_task() and asyncio.current_task().cancelled():
            return None
        async with sem:
            try:
                content = await get_fanqie_chapter(book_id, ch["chapter_id"])
                if not content:
                    logger.warning(f"番茄第{ch['_index']}章内容为空: {ch.get('title', '')}")
                    return None
                completed[0] += 1
                if completed[0] % 10 == 0:
                    logger.info(f"番茄并行爬取: {completed[0]}/{total} 章")
                return {
                    "chapter_number": ch["_index"],
                    "title": ch.get("title", ""),
                    "content": content,
                    "word_count": len(content),
                    "source_url": f"https://fanqienovel.com/reader/{book_id}/{ch['chapter_id']}",
                }
            except Exception as e:
                logger.error(f"番茄第{ch['_index']}章爬取失败: {e}")
                completed[0] += 1
                return None

    tasks = [fetch_one(ch) for ch in free_chapters]
    results = await asyncio.gather(*tasks)
    chapters_data = [r for r in results if r is not None]
    chapters_data.sort(key=lambda x: x["chapter_number"])

    logger.info(f"番茄爬取完成: {len(chapters_data)}/{total} 章")
    return chapters_data


# ════════════════════════════════════════════════════════
# 七猫（qimao.com）
# ════════════════════════════════════════════════════════

async def search_qimao(keyword: str, limit: int = 10) -> list[dict]:
    """搜索七猫
    注：七猫搜索页为 Nuxt SSR 客户端渲染，搜索结果通过 JS 异步加载，
    爬虫无法获取结果列表。
    """
    logger.info(f"七猫搜索「{keyword}」— 七猫使用客户端 JS 渲染搜索，爬虫不可用")
    try:
        async with httpx.AsyncClient(timeout=15, headers=MOBILE_HEADERS, follow_redirects=True) as client:
            resp = await client.get(
                QIMAO_SEARCH_URL,
                params={"keyword": keyword},
            )
            if resp.status_code != 200:
                logger.warning(f"七猫搜索返回 {resp.status_code}")
                return []

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")
            results = []

            # 尝试解析 SSR JSON 数据
            try:
                script = soup.find("script", {"id": "__NEXT_DATA__"})
                if not script:
                    script = soup.find("script", text=re.compile(r"window\.__NUXT__"))
                if script:
                    raw = script.string or script.text
                    if raw:
                        data = json.loads(raw)
                        books = data.get("props", {}).get("pageProps", {}).get("list", []) or \
                                data.get("state", {}).get("search", {}).get("list", [])
                        if books:
                            return [
                                {
                                    "book_id": str(b.get("bookId", b.get("id", ""))),
                                    "title": b.get("bookName", b.get("name", "")),
                                    "author": b.get("author", ""),
                                    "genre": b.get("categoryName", b.get("category", "")),
                                    "desc": (b.get("abstract", b.get("desc", "")) or "")[:200],
                                    "status": "已完结" if b.get("bookStatus") == 2 else "连载中",
                                    "platform": "qimao",
                                    "url": f"https://www.qimao.com/shuku/{b.get('bookId', b.get('id', ''))}/",
                                }
                                for b in books[:limit]
                                if b.get("bookName", b.get("name"))
                            ]
            except (KeyError, TypeError, json.JSONDecodeError):
                pass

            # HTML 卡片解析
            for item in soup.select("[class*='search'] li, .book-item, .item, [class*='result'] li")[:limit]:
                link = item.select_one("a[href*='/shuku/']")
                if not link:
                    continue
                href = link.get("href", "")
                book_id = ""
                id_match = re.search(r"/shuku/(\d+)", href)
                if id_match:
                    book_id = id_match.group(1)
                if not book_id:
                    continue

                title_el = item.select_one(".book-name, .book-title, .name, h3, h4")
                author_el = item.select_one(".author, .author-name, .writer")

                results.append({
                    "book_id": book_id,
                    "title": title_el.get_text(strip=True) if title_el else "",
                    "author": author_el.get_text(strip=True) if author_el else "",
                    "genre": "",
                    "desc": "",
                    "status": "未知",
                    "platform": "qimao",
                    "url": urljoin(QIMAO_BOOK_URL, href) if href else "",
                })

            return results
    except Exception as e:
        logger.error(f"七猫搜索失败: {e}")
        return []


async def get_qimao_catalog(book_id: str) -> list[dict]:
    """获取七猫小说目录"""
    try:
        async with httpx.AsyncClient(timeout=15, headers=MOBILE_HEADERS, follow_redirects=True) as client:
            resp = await client.get(QIMAO_CATALOG_URL.format(book_id=book_id))
            if resp.status_code != 200:
                return []

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")
            chapters = []

            for li in soup.select(".chapter-list li, .catalog-list li, ul.list li"):
                link = li.select_one("a")
                if not link:
                    continue
                href = link.get("href", "")
                ch_id_match = re.search(r"/(\d+)", href)
                if not ch_id_match:
                    continue
                chapters.append({
                    "chapter_id": ch_id_match.group(1),
                    "title": link.get_text(strip=True),
                    "volume": "",
                    "free": True,
                })

            return chapters
    except Exception as e:
        logger.error(f"七猫目录获取失败: {e}")
        return []


async def get_qimao_chapter(book_id: str, chapter_id: str) -> str | None:
    """获取七猫章节内容"""
    try:
        async with httpx.AsyncClient(timeout=15, headers=MOBILE_HEADERS, follow_redirects=True) as client:
            resp = await client.get(
                QIMAO_CHAPTER_URL.format(book_id=book_id, chapter_id=chapter_id)
            )
            if resp.status_code != 200:
                return None

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")
            content_el = soup.select_one(".read-content, .chapter-content, .content")
            if content_el:
                return content_el.get_text("\n", strip=True)
            return None
    except Exception as e:
        logger.error(f"七猫章节获取失败: {e}")
        return None


async def crawl_qimao_novel_raw(
    book_id: str,
    max_chapters: int = 100,
    task_id: str | None = None,
    **kwargs,
) -> list[dict]:
    """爬取七猫小说章节（并行）"""
    logger.info(f"获取七猫小说 {book_id} 目录...")
    catalog = await get_qimao_catalog(book_id)
    if not catalog:
        raise ValueError("无法获取七猫章节目录")

    free_chapters = catalog[:max_chapters]
    for i, ch in enumerate(free_chapters):
        ch["_index"] = i + 1

    total = len(free_chapters)
    sem = asyncio.Semaphore(5)
    completed = [0]

    async def fetch_one(ch):
        if task_id and asyncio.current_task() and asyncio.current_task().cancelled():
            return None
        async with sem:
            try:
                content = await get_qimao_chapter(book_id, ch["chapter_id"])
                if not content:
                    logger.warning(f"七猫第{ch['_index']}章内容为空: {ch.get('title', '')}")
                    return None
                completed[0] += 1
                if completed[0] % 10 == 0:
                    logger.info(f"七猫并行爬取: {completed[0]}/{total} 章")
                return {
                    "chapter_number": ch["_index"],
                    "title": ch.get("title", ""),
                    "content": content,
                    "word_count": len(content),
                    "source_url": QIMAO_CHAPTER_URL.format(book_id=book_id, chapter_id=ch["chapter_id"]),
                }
            except Exception as e:
                logger.error(f"七猫第{ch['_index']}章爬取失败: {e}")
                completed[0] += 1
                return None

    tasks = [fetch_one(ch) for ch in free_chapters]
    results = await asyncio.gather(*tasks)
    chapters_data = [r for r in results if r is not None]
    chapters_data.sort(key=lambda x: x["chapter_number"])

    logger.info(f"七猫爬取完成: {len(chapters_data)}/{total} 章")
    return chapters_data


# ════════════════════════════════════════════════════════
# 纵横中文网（zongheng.com）
# ════════════════════════════════════════════════════════

async def search_zongheng(keyword: str, limit: int = 10) -> list[dict]:
    """搜索纵横中文网
    注：纵横搜索页为 JS 客户端渲染，搜索结果通过异步加载生成，
    爬虫无法获取结果列表。
    """
    logger.info(f"纵横搜索「{keyword}」— 纵横使用客户端 JS 渲染搜索，爬虫不可用")
    try:
        async with httpx.AsyncClient(timeout=15, headers=MOBILE_HEADERS, follow_redirects=True) as client:
            resp = await client.get(
                ZONGHENG_SEARCH_URL,
                params={"keyword": keyword},
            )
            if resp.status_code != 200:
                return []

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")
            results = []

            for item in soup.select("li, .result-item, .search-item, table tr")[:limit]:
                link = item.select_one("a[href*='/book/'], a[href*='zongheng'], h3 a, h4 a")
                if not link:
                    continue
                href = link.get("href", "")
                book_id = ""
                id_match = re.search(r"/book/(\d+)", href)
                if not id_match:
                    continue
                book_id = id_match.group(1)

                title = link.get_text(strip=True)
                if not title or len(title) < 2:
                    continue

                author_el = item.select_one(".author, .book-author, .writer, td:nth-child(2)")
                results.append({
                    "book_id": book_id,
                    "title": title,
                    "author": author_el.get_text(strip=True) if author_el else "",
                    "genre": "",
                    "desc": "",
                    "status": "未知",
                    "platform": "zongheng",
                    "url": urljoin("http://book.zongheng.com/", href) if href else "",
                })

            return results
    except Exception as e:
        logger.error(f"纵横搜索失败: {e}")
        return []


async def get_zongheng_catalog(book_id: str) -> list[dict]:
    """获取纵横小说目录"""
    try:
        async with httpx.AsyncClient(timeout=15, headers=MOBILE_HEADERS, follow_redirects=True) as client:
            resp = await client.get(ZONGHENG_CATALOG_URL.format(book_id=book_id))
            if resp.status_code != 200:
                return []

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")
            chapters = []

            for li in soup.select(".chapter-list ul li, .catalog-list li, .volume-chapter li"):
                link = li.select_one("a")
                if not link:
                    continue
                href = link.get("href", "")
                ch_id_match = re.search(r"/chapter/\d+/(\d+)", href)
                if not ch_id_match:
                    continue
                chapters.append({
                    "chapter_id": ch_id_match.group(1),
                    "title": link.get_text(strip=True),
                    "volume": "",
                    "free": True,
                })

            return chapters
    except Exception as e:
        logger.error(f"纵横目录获取失败: {e}")
        return []


async def get_zongheng_chapter(book_id: str, chapter_id: str) -> str | None:
    """获取纵横章节内容"""
    try:
        async with httpx.AsyncClient(timeout=15, headers=MOBILE_HEADERS, follow_redirects=True) as client:
            resp = await client.get(
                ZONGHENG_CHAPTER_URL.format(book_id=book_id, chapter_id=chapter_id)
            )
            if resp.status_code != 200:
                return None

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")
            content_el = soup.select_one(".content, .read-content, #content")
            if content_el:
                return content_el.get_text("\n", strip=True)
            return None
    except Exception as e:
        logger.error(f"纵横章节获取失败: {e}")
        return None


async def crawl_zongheng_novel_raw(
    book_id: str,
    max_chapters: int = 100,
    task_id: str | None = None,
    **kwargs,
) -> list[dict]:
    """爬取纵横小说章节（并行）"""
    logger.info(f"获取纵横小说 {book_id} 目录...")
    catalog = await get_zongheng_catalog(book_id)
    if not catalog:
        raise ValueError("无法获取纵横章节目录")

    free_chapters = catalog[:max_chapters]
    for i, ch in enumerate(free_chapters):
        ch["_index"] = i + 1

    total = len(free_chapters)
    sem = asyncio.Semaphore(5)
    completed = [0]

    async def fetch_one(ch):
        if task_id and asyncio.current_task() and asyncio.current_task().cancelled():
            return None
        async with sem:
            try:
                content = await get_zongheng_chapter(book_id, ch["chapter_id"])
                if not content:
                    logger.warning(f"纵横第{ch['_index']}章内容为空: {ch.get('title', '')}")
                    return None
                completed[0] += 1
                if completed[0] % 10 == 0:
                    logger.info(f"纵横并行爬取: {completed[0]}/{total} 章")
                return {
                    "chapter_number": ch["_index"],
                    "title": ch.get("title", ""),
                    "content": content,
                    "word_count": len(content),
                    "source_url": ZONGHENG_CHAPTER_URL.format(book_id=book_id, chapter_id=ch["chapter_id"]),
                }
            except Exception as e:
                logger.error(f"纵横第{ch['_index']}章爬取失败: {e}")
                completed[0] += 1
                return None

    tasks = [fetch_one(ch) for ch in free_chapters]
    results = await asyncio.gather(*tasks)
    chapters_data = [r for r in results if r is not None]
    chapters_data.sort(key=lambda x: x["chapter_number"])

    logger.info(f"纵横爬取完成: {len(chapters_data)}/{total} 章")
    return chapters_data


# ════════════════════════════════════════════════════════
# 统一搜索入口
# ════════════════════════════════════════════════════════

PLATFORM_SEARCH_FUNCS: dict[str, Any] = {
    "qidian": search_qidian,
    "fanqie": search_fanqie,
    "qimao": search_qimao,
    "zongheng": search_zongheng,
}

PLATFORM_CRAWL_FUNCS: dict[str, Any] = {
    "qidian": crawl_qidian_novel_raw,
    "fanqie": crawl_fanqie_novel_raw,
    "qimao": crawl_qimao_novel_raw,
    "zongheng": crawl_zongheng_novel_raw,
}

PLATFORM_LABELS: dict[str, str] = {
    "qidian": "起点",
    "fanqie": "番茄小说",
    "qimao": "七猫",
    "zongheng": "纵横",
}


async def search_novels(keyword: str, platform: str = "all", limit: int = 10) -> list[dict]:
    """
    多平台搜索小说。

    Args:
        keyword: 搜索关键词
        platform: 平台标识，'all' 搜索所有平台
        limit: 每平台最多结果数
    """
    if platform == "all":
        # 并行搜索所有平台
        tasks = []
        for p, func in PLATFORM_SEARCH_FUNCS.items():
            tasks.append(func(keyword, limit))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        combined = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.warning(f"平台搜索失败: {list(PLATFORM_SEARCH_FUNCS.keys())[i]} - {r}")
            elif r:
                combined.extend(r)

        # 去重：按 book_id+platform 去重
        seen = set()
        deduped = []
        for item in combined:
            key = f"{item.get('platform', '')}_{item.get('book_id', '')}"
            if key not in seen:
                seen.add(key)
                deduped.append(item)

        return deduped

    func = PLATFORM_SEARCH_FUNCS.get(platform)
    if func:
        return await func(keyword, limit)
    logger.warning(f"未知平台: {platform}")
    return []


async def crawl_novel_raw(
    platform: str,
    book_id: str,
    max_chapters: int = 100,
    task_id: str | None = None,
    **kwargs,
) -> list[dict]:
    """
    通用小说爬取入口，自动路由到对应平台的爬取函数。

    Args:
        platform: 平台标识（qidian/fanqie/qimao/zongheng）
        book_id: 书籍 ID
        max_chapters: 最大爬取章数
        task_id: 后台任务 ID（用于取消检测）
    """
    func = PLATFORM_CRAWL_FUNCS.get(platform)
    if not func:
        raise ValueError(f"不支持的爬取平台: {platform}")
    return await func(book_id, max_chapters=max_chapters, task_id=task_id, **kwargs)
