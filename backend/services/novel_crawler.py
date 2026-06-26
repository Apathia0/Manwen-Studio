"""
小说爬虫服务：支持起点中文网的小说搜索和章节爬取。

策略：
- 起点：优先移动端 SSR API（m.qidian.com），无需 CDP 浏览器
- 兜底：httpx + BeautifulSoup HTML 解析
"""

import asyncio
import json
import logging
import re
from typing import Any
from urllib.parse import urljoin

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

QIDIAN_SEARCH_URL = "https://m.qidian.com/search"
QIDIAN_BOOK_URL = "https://m.qidian.com/book/{book_id}/"
QIDIAN_CATALOG_URL = "https://m.qidian.com/book/{book_id}/catalog/"
QIDIAN_CHAPTER_URL = "https://m.qidian.com/book/{book_id}/{chapter_id}/"


async def search_qidian(keyword: str, limit: int = 10) -> list[dict]:
    """搜索起点小说"""
    async with httpx.AsyncClient(timeout=15, headers=MOBILE_HEADERS) as client:
        resp = await client.get(
            QIDIAN_SEARCH_URL,
            params={"kw": keyword},
        )
        resp.raise_for_status()
        html = resp.text

        # 尝试从 SSR pageContext 提取
        m = re.search(
            r'<script[^>]+id=["\']vite-plugin-ssr_pageContext["\'][^>]*>([\s\S]*?)</script>',
            html,
            re.IGNORECASE,
        )
        if m:
            try:
                page_ctx = json.loads(m[1])
                page_data = page_ctx.get("pageContext", {}).get("pageProps", {}).get("pageData", {})
                books = page_data.get("records", [])
                if books:
                    return [
                        {
                            "book_id": str(b.get("bid") or b.get("bookId", "")),
                            "title": b.get("bName") or b.get("bookName", ""),
                            "author": b.get("bAuth") or b.get("author", ""),
                            "genre": "·".join(filter(None, [b.get("cat", ""), b.get("subCat", "")])),
                            "desc": b.get("desc", ""),
                            "status": "连载中" if b.get("cnt") else "已完结",
                            "platform": "qidian",
                            "url": f"https://m.qidian.com/book/{b.get('bid') or b.get('bookId', '')}/",
                        }
                        for b in books[:limit]
                        if b.get("bName") or b.get("bookName")
                    ]
            except (json.JSONDecodeError, KeyError):
                pass

        # 兜底：HTML 解析
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
    """获取起点小说章节目录"""
    async with httpx.AsyncClient(timeout=15, headers=MOBILE_HEADERS) as client:
        resp = await client.get(QIDIAN_CATALOG_URL.format(book_id=book_id))
        resp.raise_for_status()
        html = resp.text

        m = re.search(
            r'<script[^>]+id=["\']vite-plugin-ssr_pageContext["\'][^>]*>([\s\S]*?)</script>',
            html,
            re.IGNORECASE,
        )
        if m:
            try:
                page_ctx = json.loads(m[1])
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
            except (json.JSONDecodeError, KeyError):
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
    """获取单章内容"""
    async with httpx.AsyncClient(timeout=15, headers=MOBILE_HEADERS) as client:
        resp = await client.get(
            QIDIAN_CHAPTER_URL.format(book_id=book_id, chapter_id=chapter_id)
        )
        resp.raise_for_status()
        html = resp.text

        m = re.search(
            r'<script[^>]+id=["\']vite-plugin-ssr_pageContext["\'][^>]*>([\s\S]*?)</script>',
            html,
            re.IGNORECASE,
        )
        if m:
            try:
                page_ctx = json.loads(m[1])
                chapter_data = page_ctx.get("pageContext", {}).get("pageProps", {}).get("pageData", {})
                content = chapter_data.get("content", "")
                if content:
                    content = re.sub(r"<[^>]+>", "", content)
                    content = re.sub(r"&nbsp;", " ", content)
                    return content.strip()
            except (json.JSONDecodeError, KeyError):
                pass

        soup = BeautifulSoup(html, "html.parser")
        content_el = soup.select_one(".read-content, .chapter-content, #chapter-content")
        if content_el:
            return content_el.get_text("\n", strip=True)
        return None


async def crawl_qidian_novel(
    book_id: str,
    story_id: int,
    max_chapters: int = 100,
    task_id: str | None = None,
    **kwargs,
) -> dict:
    """爬取起点小说完整内容并存入数据库"""
    db = next(SessionLocal())
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

        crawled = 0
        for i, ch in enumerate(free_chapters):
            if task_id and asyncio.current_task() and asyncio.current_task().cancelled():
                break

            try:
                content = await get_qidian_chapter(book_id, ch["chapter_id"])
                if not content:
                    logger.warning(f"第 {i+1} 章内容为空: {ch['title']}")
                    continue

                existing = db.query(Chapter).filter(
                    Chapter.story_id == story_id,
                    Chapter.chapter_number == i + 1,
                ).first()

                if existing:
                    existing.novel_content = content
                    existing.title = ch["title"]
                else:
                    new_chapter = Chapter(
                        story_id=story_id,
                        chapter_number=i + 1,
                        title=ch["title"],
                        novel_content=content,
                        status="completed",
                        word_count=len(content),
                    )
                    db.add(new_chapter)

                crawled += 1
                if crawled % 10 == 0:
                    db.commit()
                    logger.info(f"已爬取 {crawled}/{len(free_chapters)} 章")

                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"爬取第 {i+1} 章失败: {e}")
                continue

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


async def search_novels(keyword: str, platform: str = "qidian", limit: int = 10) -> list[dict]:
    """搜索小说（支持多平台路由）"""
    if platform == "qidian":
        return await search_qidian(keyword, limit)
    # 其他平台暂不支持
    return []