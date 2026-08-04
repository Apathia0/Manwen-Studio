"""诊断脚本：找出本地库中数据最丰富的章节，验证 delete_chapter 修复。

只读查询 + 可选真实删除（--delete 参数）。用法：
  python diag_candidate_chapters.py            # 只列出候选章节
  python diag_candidate_chapters.py --delete   # 删除第一个候选章节（验证修复）
"""
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import text

import database
import main


def list_candidates():
    with database.engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT * FROM (
                SELECT c.id, c.story_id,
                  (SELECT count(*) FROM script_scenes s WHERE s.chapter_id=c.id) scenes,
                  (SELECT count(*) FROM ai_usage_events a WHERE a.chapter_id=c.id) ai,
                  (SELECT count(*) FROM video_assets v WHERE v.chapter_id=c.id) vas,
                  (SELECT count(*) FROM chapter_video_workflows w WHERE w.chapter_id=c.id) wf
                FROM chapters c
                WHERE EXISTS (SELECT 1 FROM ai_usage_events a WHERE a.chapter_id=c.id)
                   OR EXISTS (SELECT 1 FROM video_assets v WHERE v.chapter_id=c.id)
                   OR EXISTS (SELECT 1 FROM chapter_video_workflows w WHERE w.chapter_id=c.id)
            ) t
            ORDER BY (t.scenes + t.ai + t.vas + t.wf) DESC LIMIT 5
        """)).fetchall()
    return rows


def delete_chapter_e2e(chapter_id: int):
    with TestClient(main.app) as client:
        original_check = main.license_checker.check_domain
        main.license_checker.check_domain = lambda h: True
        original_require_user = main._require_user
        original_require_chapter = main._require_chapter_for_user
        try:
            main._require_user = lambda request, db: SimpleNamespace(id=1, role="admin")

            def fake_require_chapter(cid, user, db):
                chapter = db.get(main.Chapter, cid)
                if chapter is None:
                    print(f"chapter {cid} 不存在")
                return chapter

            main._require_chapter_for_user = fake_require_chapter
            resp = client.delete(f"/api/chapters/{chapter_id}")
            print(f"DELETE /api/chapters/{chapter_id} -> HTTP {resp.status_code}: {resp.text[:300]}")
        finally:
            main.license_checker.check_domain = original_check
            main._require_user = original_require_user
            main._require_chapter_for_user = original_require_chapter


if __name__ == "__main__":
    rows = list_candidates()
    if not rows:
        print("没有数据丰富的候选章节")
        sys.exit(0)
    print("候选章节 (id, story_id, scenes, ai_usage, video_assets, workflows):")
    for r in rows:
        print("  ", tuple(r))
    if "--delete" in sys.argv:
        target = rows[0]
        print(f"删除候选章节 id={target[0]} ...")
        delete_chapter_e2e(int(target[0]))
