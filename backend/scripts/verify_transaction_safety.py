import asyncio
import datetime
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import SessionLocal, engine, init_db  # noqa: E402
import main as app_main  # noqa: E402
from models import Chapter, ChatMessage, Story, User, UserSession, UserQuotaGrantMonthly, UserSubscription, UserUsageMonthly  # noqa: E402


def _now_token(prefix: str) -> str:
    stamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    return f"{prefix}_{stamp}"


def _create_user_fixture() -> dict[str, Any]:
    db = SessionLocal()
    try:
        app_main._ensure_platform_seed(db)
        user = User(
            email=f"{_now_token('txsafe')}@example.com",
            password_hash=app_main._password_hash("password123"),
            name="Tx Safety",
            role="user",
            status="active",
            email_verified=True,
        )
        db.add(user)
        db.flush()

        session = UserSession(
            user_id=user.id,
            token=_now_token("sess"),
        )
        db.add(session)

        story = Story(
            owner_user_id=user.id,
            title=_now_token("story"),
            description="事务安全测试故事",
            onboarding_completed=True,
        )
        db.add(story)
        db.flush()

        chapter = Chapter(
            story_id=story.id,
            chapter_number=1,
            title="第一章",
            novel_content="",
            content_source="chat",
            status="draft",
            word_count=0,
        )
        db.add(chapter)
        db.flush()
        db.add(ChatMessage(chapter_id=chapter.id, role="user", content="请生成一章测试正文"))

        db.commit()
        return {
            "user_id": user.id,
            "story_id": story.id,
            "chapter_id": chapter.id,
            "token": session.token,
        }
    finally:
        db.close()


def _cleanup_fixture(fixture: dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        db.query(UserUsageMonthly).filter(UserUsageMonthly.user_id == fixture["user_id"]).delete()
        db.query(UserQuotaGrantMonthly).filter(UserQuotaGrantMonthly.user_id == fixture["user_id"]).delete()
        db.query(UserSubscription).filter(UserSubscription.user_id == fixture["user_id"]).delete()
        story = db.get(Story, fixture["story_id"])
        if story:
            db.delete(story)
            db.flush()
        session = db.query(UserSession).filter(UserSession.user_id == fixture["user_id"]).first()
        if session:
            db.delete(session)
        user = db.get(User, fixture["user_id"])
        if user:
            db.delete(user)
        db.commit()
    finally:
        db.close()


def _idle_in_tx_count() -> int:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        row = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND state = 'idle in transaction'
                """
            )
        ).scalar_one()
    return int(row or 0)


async def _measure_idle_during_request(task_factory: Callable[[], Awaitable[httpx.Response]]) -> tuple[httpx.Response, int]:
    baseline = _idle_in_tx_count()
    peak = baseline
    task = asyncio.create_task(task_factory())
    while not task.done():
        await asyncio.sleep(0.1)
        peak = max(peak, _idle_in_tx_count())
    response = await task
    peak = max(peak, _idle_in_tx_count())
    return response, peak - baseline


@asynccontextmanager
async def _patched_generation() -> Any:
    original_generate_novel = app_main.generate_novel
    original_generate_framework = app_main.generate_framework
    original_split_scenes = app_main.split_scenes
    original_generate_manga_image = app_main.generate_manga_image
    original_ensure_continuity = app_main._ensure_generated_chapter_continuity
    original_refresh_memory = app_main._refresh_chapter_memory
    original_complete_framework_payload = app_main._complete_framework_payload
    original_framework_quality_issues = app_main._framework_launch_quality_issues
    original_background_quality_check = app_main._background_quality_check

    async def fake_generate_novel(*args, **kwargs):
        await asyncio.sleep(2.0)
        return "测试正文，模拟外部模型慢调用。"

    async def fake_generate_framework(*args, **kwargs):
        await asyncio.sleep(2.0)
        return {
            "description": "测试框架",
            "tags": {"genre": "科幻"},
            "characters": [{"name": "主角", "role": "主角"}],
            "outline": {
                "three_acts": [
                    {"act": "1", "title": "开端", "summary": "开局", "chapters": [{"chapter_number": 1, "title": "开篇", "summary": "开场"}]},
                    {"act": "2", "title": "发展", "summary": "发展", "chapters": [{"chapter_number": 2, "title": "推进", "summary": "推进"}]},
                ]
            },
            "chapters": [
                {"chapter_number": 1, "title": "开篇", "summary": "开场"},
                {"chapter_number": 2, "title": "推进", "summary": "推进"},
            ],
        }

    async def fake_split_scenes(*args, **kwargs):
        await asyncio.sleep(2.0)
        return ["镜头一", "镜头二", "镜头三", "镜头四"]

    async def fake_generate_manga_image(scene_prompt, chapter_id, image_number, **kwargs):
        await asyncio.sleep(1.0)
        chapter_dir = ROOT / "manga_outputs" / f"chapter_{chapter_id}"
        chapter_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"test_panel_{image_number:02d}.png"
        file_path = chapter_dir / file_name
        if not file_path.exists():
            file_path.write_bytes(b"\x89PNG\r\n\x1a\n")
        return app_main.image_service.ImageGenerationResult(
            image_path=f"manga_outputs/chapter_{chapter_id}/{file_name}",
            final_prompt=scene_prompt,
            prompt_sanitized=False,
        )

    async def fake_ensure_continuity(story_context, chapter_info, content, request):
        return content

    async def fake_refresh_memory(chapter, request, db):
        chapter.memory_summary = {
            "chapter_summary": {"summary": "测试摘要"},
            "chapter_handoff": {"opening_must_continue": "测试承接"},
        }

    async def fake_complete_framework_payload(framework, *args, **kwargs):
        return framework

    def fake_framework_quality_issues(framework):
        return []

    async def fake_background_quality_check(*args, **kwargs):
        return None

    app_main.generate_novel = fake_generate_novel
    app_main.generate_framework = fake_generate_framework
    app_main.split_scenes = fake_split_scenes
    app_main.generate_manga_image = fake_generate_manga_image
    app_main._ensure_generated_chapter_continuity = fake_ensure_continuity
    app_main._refresh_chapter_memory = fake_refresh_memory
    app_main._complete_framework_payload = fake_complete_framework_payload
    app_main._framework_launch_quality_issues = fake_framework_quality_issues
    app_main._background_quality_check = fake_background_quality_check
    try:
        yield
    finally:
        app_main.generate_novel = original_generate_novel
        app_main.generate_framework = original_generate_framework
        app_main.split_scenes = original_split_scenes
        app_main.generate_manga_image = original_generate_manga_image
        app_main._ensure_generated_chapter_continuity = original_ensure_continuity
        app_main._refresh_chapter_memory = original_refresh_memory
        app_main._complete_framework_payload = original_complete_framework_payload
        app_main._framework_launch_quality_issues = original_framework_quality_issues
        app_main._background_quality_check = original_background_quality_check


async def _run_api_checks() -> list[dict[str, Any]]:
    fixture = _create_user_fixture()
    headers = {"Authorization": f"Bearer {fixture['token']}"}
    transport = httpx.ASGITransport(app=app_main.app)
    results: list[dict[str, Any]] = []
    original_ready = app_main.SYSTEM_READY
    original_status = dict(app_main.INSTALL_STATUS)
    app_main.SYSTEM_READY = True
    app_main.INSTALL_STATUS = {
        "installed": True,
        "source": "transaction_safety_check",
        "database_reachable": True,
    }
    try:
        async with _patched_generation():
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response, idle_delta = await _measure_idle_during_request(
                    lambda: client.post(f"/api/chapters/{fixture['chapter_id']}/generate-novel", headers=headers)
                )
                results.append(
                    {
                        "name": "generate_novel",
                        "status": response.status_code,
                        "idle_delta": idle_delta,
                    }
                )

                response, idle_delta = await _measure_idle_during_request(
                    lambda: client.post(
                        f"/api/stories/{fixture['story_id']}/framework/generate",
                        headers=headers,
                        json={"description": "请生成一个两阶段测试框架"},
                    )
                )
                results.append(
                    {
                        "name": "framework_generate",
                        "status": response.status_code,
                        "idle_delta": idle_delta,
                    }
                )

                app_main._write_scenes_file(
                    fixture["chapter_id"],
                    ["镜头一", "镜头二", "镜头三", "镜头四", "镜头五", "镜头六"],
                    [],
                )

                response, idle_delta = await _measure_idle_during_request(
                    lambda: client.post(f"/api/chapters/{fixture['chapter_id']}/generate-manga-stream", headers=headers)
                )
                results.append(
                    {
                        "name": "generate_manga_stream",
                        "status": response.status_code,
                        "idle_delta": idle_delta,
                        "body_preview": response.text[:120],
                    }
                )
    finally:
        app_main.SYSTEM_READY = original_ready
        app_main.INSTALL_STATUS = original_status
        _cleanup_fixture(fixture)
    return results


def _run_startup_migration_check() -> dict[str, Any]:
    import database as database_module  # noqa: E402

    original_migrate = database_module._migrate
    original_assert_schema = database_module._assert_model_schema_present
    calls: list[dict[str, Any]] = []

    def fake_migrate(*_args, **kwargs):
        calls.append(kwargs)

    try:
        database_module._migrate = fake_migrate
        database_module._assert_model_schema_present = lambda *_args, **_kwargs: None
        init_db(run_migrations=False)
    finally:
        database_module._migrate = original_migrate
        database_module._assert_model_schema_present = original_assert_schema

    return {
        "lock_path_called": bool(calls),
        "migration_changes_disabled": bool(calls) and calls[0].get("run_changes") is False,
    }


async def main() -> None:
    api_results = await _run_api_checks()
    migration_result = _run_startup_migration_check()

    failures: list[str] = []
    for item in api_results:
        if item["status"] != 200:
            failures.append(f"{item['name']} returned {item['status']}")
        if item["idle_delta"] > 0:
            failures.append(f"{item['name']} observed idle-in-transaction delta {item['idle_delta']}")

    if not migration_result["lock_path_called"]:
        failures.append("init_db(run_migrations=False) did not enter the PostgreSQL lock path")
    if not migration_result["migration_changes_disabled"]:
        failures.append("init_db(run_migrations=False) enabled incremental migration changes")

    summary = {
        "api_results": api_results,
        "migration_result": migration_result,
        "ok": not failures,
        "failures": failures,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
