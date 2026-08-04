"""诊断脚本：通过 TestClient 复现 DELETE /api/stories/18，捕获真实异常堆栈。

只读 + 事务回滚：delete_story 仅失败时抛异常（未 commit），成功后才是用户想要的删除。
用法：python diag_reproduce_delete.py
"""
import traceback
from types import SimpleNamespace

from fastapi.testclient import TestClient

import main

STORY_ID = 18


def main_run():
    with TestClient(main.app) as client:
        # 绕过 license 中间件（TestClient 的 host 为 testserver，非授权域名）
        original_check_domain = main.license_checker.check_domain
        main.license_checker.check_domain = lambda h: True
        # 注入假认证，让 delete_story 走真实删除逻辑
        original_require_user = main._require_user
        original_require_story = main._require_story_for_user

        def fake_require_user(request, db):
            return SimpleNamespace(id=1, role="admin")

        def fake_require_story(sid, user, db):
            story = db.get(main.Story, sid)
            if story is None:
                print(f"story {sid} 不存在")
            else:
                print(f"story {sid} 存在，title={story.title!r}")
            return story

        main._require_user = fake_require_user
        main._require_story_for_user = fake_require_story
        try:
            resp = client.delete(f"/api/stories/{STORY_ID}")
            print(f"HTTP {resp.status_code}: {resp.text[:500]}")
        finally:
            main._require_user = original_require_user
            main._require_story_for_user = original_require_story


if __name__ == "__main__":
    try:
        main_run()
    except Exception as exc:  # noqa: BLE001 - 诊断脚本需打印完整堆栈
        print("=" * 60)
        print(f"复现到真实异常: {type(exc).__name__}: {exc}")
        traceback.print_exc()
