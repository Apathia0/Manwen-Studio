import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from database import get_db, init_db
from models import Chapter, ChatMessage, MangaImage, Story
from schemas import (
    ChapterContentUpdate,
    ChapterOut,
    ChatMessageIn,
    ChatMessageOut,
    MangaImageOut,
    OutlineChapterPlanUpdate,
    StoryCreate,
    StoryOut,
    StoryUpdate,
)
from services.deepseek import (
    adjust_chapter_content,
    adjust_framework_with_chat,
    chat_stream,
    continue_framework,
    expand_chapter_to_content,
    generate_character_profiles_from_framework,
    generate_framework,
    generate_novel,
    quality_assess,
    regenerate_characters,
    regenerate_outline,
    regenerate_tags,
    rewrite_selection,
    scenes_from_selection,
    split_scenes,
)
from services.errors import MangaImageGenerationError, MissingApiKeyError
from services.image2 import generate_manga_image, generate_reference_image
from services.scene_safety import sanitize_scene_list

load_dotenv()

logger = logging.getLogger("main")
ACTIVE_MANGA_GENERATIONS: set[int] = set()

app = FastAPI(title="Novel & Manga Generator")

DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
MAX_CHARACTER_PROFILE_CHARS = int(os.getenv("MAX_CHARACTER_PROFILE_CHARS", "20000"))
API_TOKEN = os.getenv("API_TOKEN", "").strip()

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(MissingApiKeyError)
async def _missing_api_key_handler(request: Request, exc: MissingApiKeyError):
    return JSONResponse(status_code=400, content={"detail": str(exc), "provider": exc.provider})

# Serve generated manga images as static files
manga_dir = Path(__file__).resolve().parent / "manga_outputs"
manga_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/manga", StaticFiles(directory=str(manga_dir)), name="manga")


@app.middleware("http")
async def require_api_token(request: Request, call_next):
    if API_TOKEN and request.url.path.startswith("/api") and request.method != "OPTIONS":
        supplied = request.headers.get("x-api-token", "")
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        if supplied != API_TOKEN:
            return JSONResponse({"detail": "Invalid or missing API token"}, status_code=401)
    return await call_next(request)


def _require_chapter(chapter_id: int, db: Session) -> Chapter:
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found")
    return chapter


def _user_deepseek_api_key(request: Request) -> str | None:
    return request.headers.get("x-deepseek-api-key") or None


def _user_image_api_key(request: Request) -> str | None:
    return request.headers.get("x-image-api-key") or None


def _character_profile_text(body: dict) -> str:
    raw = body.get("characters", "")
    if not isinstance(raw, str):
        raise HTTPException(400, "characters must be a string")
    text = raw.strip()
    if len(text) > MAX_CHARACTER_PROFILE_CHARS:
        raise HTTPException(413, f"Character profile is too long. Max length is {MAX_CHARACTER_PROFILE_CHARS} characters")
    return text


def _parse_character_profile_cards(text: str) -> list[dict]:
    normalized = (text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return []

    blocks = [block.strip() for block in re.split(r"(?=^角色名[:：])", normalized, flags=re.MULTILINE) if block.strip()]
    cards: list[dict] = []
    for index, block in enumerate(blocks, start=1):
        name = f"角色 {index}"
        fields: list[dict[str, str]] = []
        for raw_line in block.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            match = re.match(r"^([^:：]{1,20})[:：]\s*(.+)$", line)
            if match:
                label, value = match.groups()
                label = label.strip()
                value = value.strip()
                if not value:
                    continue
                if label == "角色名":
                    name = value
                fields.append({"label": label, "value": value})
            elif fields:
                fields[-1]["value"] = f"{fields[-1]['value']}\n{line}"
            else:
                fields.append({"label": "描述", "value": line})
        cards.append({"name": name, "raw": block, "fields": fields})
    return cards


def _build_framework_context(story: Story | None, chapter: Chapter | None = None) -> str:
    """Assemble framework constraints from story tags, characters, outline and chapter metadata."""
    if not story:
        return ""
    parts = []
    if story.tags:
        parts.append(f"故事标签: {json.dumps(story.tags, ensure_ascii=False)}")
    if story.characters:
        parts.append(f"角色设定: {json.dumps(story.characters, ensure_ascii=False)}")
    if story.outline:
        parts.append(f"故事大纲: {json.dumps(story.outline, ensure_ascii=False)}")
    if chapter:
        if chapter.act:
            parts.append(f"当前章节所属幕: {chapter.act}")
        if chapter.key_events:
            parts.append(f"本章关键事件: {json.dumps(chapter.key_events, ensure_ascii=False)}")
    return "\n".join(parts)


def _count_words(text: str | None) -> int | None:
    if not text:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    return len("".join(stripped.split()))


def _normalize_key_events(raw) -> list[str] | None:
    if not raw:
        return None
    if isinstance(raw, list):
        items = [str(item).strip() for item in raw if str(item).strip()]
        return items or None
    if isinstance(raw, str):
        text = raw.strip()
        return [text] if text else None
    return [str(raw).strip()] if str(raw).strip() else None


def _normalize_framework_outline(outline: dict | None, chapters: list | None) -> dict:
    normalized = dict(outline or {})
    acts = normalized.get("three_acts")
    if not isinstance(acts, list):
        acts = []

    chapter_groups: dict[str, list[dict]] = {}
    if isinstance(chapters, list):
        for item in chapters:
            if not isinstance(item, dict):
                continue
            act_key = str(item.get("act") or "").strip()
            chapter_number = item.get("chapter_number")
            title = str(item.get("title") or "").strip()
            if not isinstance(chapter_number, int) or chapter_number < 1 or not title:
                continue
            chapter_entry = {
                "chapter_number": chapter_number,
                "title": title,
            }
            key_events = _normalize_key_events(item.get("key_events"))
            if key_events:
                chapter_entry["key_events"] = key_events
            summary = item.get("summary")
            if isinstance(summary, str) and summary.strip():
                chapter_entry["summary"] = summary.strip()
            chapter_groups.setdefault(act_key, []).append(chapter_entry)

    next_unassigned: list[dict] = chapter_groups.pop("", [])
    merged_acts: list[dict] = []
    for index, act in enumerate(acts, start=1):
        if isinstance(act, dict):
            act_entry = dict(act)
        else:
            act_entry = {"title": str(act)}
        act_label = act_entry.get("act", index)
        act_entry["act"] = act_label
        candidates = chapter_groups.pop(str(act_label), None) or chapter_groups.pop(str(index), None)
        if not candidates and next_unassigned:
            candidates = next_unassigned
            next_unassigned = []
        act_entry["chapters"] = sorted(candidates or [], key=lambda item: item["chapter_number"])
        merged_acts.append(act_entry)

    leftover = []
    for items in chapter_groups.values():
        leftover.extend(items)
    leftover.extend(next_unassigned)
    if leftover:
        merged_acts.append({
            "act": len(merged_acts) + 1,
            "title": "章节规划",
            "summary": "",
            "chapters": sorted(leftover, key=lambda item: item["chapter_number"]),
        })

    normalized["three_acts"] = merged_acts
    return normalized


def _extract_outline_chapters(outline: dict | None) -> list[dict]:
    if not isinstance(outline, dict):
        return []
    acts = outline.get("three_acts")
    if not isinstance(acts, list):
        return []
    extracted: list[dict] = []
    for index, act in enumerate(acts, start=1):
        if not isinstance(act, dict):
            continue
        act_label = act.get("act", index)
        chapters = act.get("chapters")
        if not isinstance(chapters, list):
            continue
        for item in chapters:
            if not isinstance(item, dict):
                continue
            chapter_number = item.get("chapter_number")
            title = str(item.get("title") or "").strip()
            if not isinstance(chapter_number, int) or chapter_number < 1 or not title:
                continue
            chapter_entry = dict(item)
            chapter_entry["chapter_number"] = chapter_number
            chapter_entry["title"] = title
            chapter_entry["act"] = item.get("act", act_label)
            extracted.append(chapter_entry)
    return extracted


def _merge_chapter_plans(existing: list[dict] | None, incoming: list[dict] | None) -> list[dict]:
    merged: dict[int, dict] = {}

    def _ingest(items: list[dict] | None, *, prefer_existing: bool) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            chapter_number = item.get("chapter_number")
            title = str(item.get("title") or "").strip()
            if not isinstance(chapter_number, int) or chapter_number < 1 or not title:
                continue
            normalized = dict(item)
            normalized["chapter_number"] = chapter_number
            normalized["title"] = title
            if prefer_existing and chapter_number in merged:
                current = dict(merged[chapter_number])
                current.update({k: v for k, v in normalized.items() if v not in (None, "", [], {})})
                merged[chapter_number] = current
            else:
                current = dict(merged.get(chapter_number, {}))
                current.update(normalized)
                merged[chapter_number] = current

    _ingest(existing, prefer_existing=False)
    _ingest(incoming, prefer_existing=True)
    return [merged[key] for key in sorted(merged)]


def _merge_framework_outline(existing_outline: dict | None, incoming_outline: dict | None, incoming_chapters: list | None) -> dict:
    existing_outline = existing_outline if isinstance(existing_outline, dict) else {}
    incoming_outline = incoming_outline if isinstance(incoming_outline, dict) else {}

    existing_chapters = _extract_outline_chapters(existing_outline)
    incoming_outline_chapters = _extract_outline_chapters(incoming_outline)
    combined_incoming = _merge_chapter_plans(incoming_outline_chapters, incoming_chapters)
    merged_chapters = _merge_chapter_plans(existing_chapters, combined_incoming)

    existing_acts = existing_outline.get("three_acts") if isinstance(existing_outline.get("three_acts"), list) else []
    incoming_acts = incoming_outline.get("three_acts") if isinstance(incoming_outline.get("three_acts"), list) else []

    merged_acts: list[dict] = []
    act_index: dict[str, int] = {}

    def _push_act(raw_act, fallback_index: int, *, prefer_incoming: bool) -> None:
        if isinstance(raw_act, dict):
            act_entry = dict(raw_act)
        else:
            act_entry = {"title": str(raw_act)}
        act_label = str(act_entry.get("act", fallback_index))
        act_entry["act"] = act_entry.get("act", fallback_index)
        act_entry.pop("chapters", None)
        if act_label in act_index:
            idx = act_index[act_label]
            current = dict(merged_acts[idx])
            update_data = {k: v for k, v in act_entry.items() if v not in (None, "", [], {})}
            if prefer_incoming:
                current.update(update_data)
            else:
                for key, value in update_data.items():
                    current.setdefault(key, value)
            merged_acts[idx] = current
            return
        act_index[act_label] = len(merged_acts)
        merged_acts.append(act_entry)

    for idx, act in enumerate(existing_acts, start=1):
        _push_act(act, idx, prefer_incoming=False)
    for idx, act in enumerate(incoming_acts, start=1):
        _push_act(act, idx, prefer_incoming=True)

    base_outline = dict(existing_outline)
    base_outline.update({k: v for k, v in incoming_outline.items() if k != "three_acts"})
    base_outline["three_acts"] = merged_acts
    return _normalize_framework_outline(base_outline, merged_chapters)


def _has_complete_tags(tags: dict | None) -> bool:
    if not isinstance(tags, dict):
        return False
    return all(str(tags.get(key) or "").strip() for key in ("type", "theme", "style", "audience"))


def _has_complete_big_five(scores) -> bool:
    if not isinstance(scores, dict):
        return False
    alias_map = {
        "openness": ("openness", "O"),
        "conscientiousness": ("conscientiousness", "C"),
        "extraversion": ("extraversion", "E"),
        "agreeableness": ("agreeableness", "A"),
        "neuroticism": ("neuroticism", "N"),
    }
    for aliases in alias_map.values():
        value = None
        for key in aliases:
            if scores.get(key) not in (None, ""):
                value = scores.get(key)
                break
        if value in (None, ""):
            return False
    return True


def _has_complete_characters(characters) -> bool:
    if not isinstance(characters, list) or len(characters) == 0:
        return False
    for item in characters:
        if not isinstance(item, dict):
            return False
        if not str(item.get("name") or "").strip():
            return False
        if not str(item.get("role") or "").strip():
            return False
        if not _has_complete_big_five(item.get("big_five")):
            return False
    return True


def _has_complete_outline(outline: dict | None) -> bool:
    if not isinstance(outline, dict):
        return False
    acts = outline.get("three_acts")
    if not isinstance(acts, list) or len(acts) < 3:
        return False
    if not _extract_outline_chapters(outline):
        return False
    for act in acts:
        if not isinstance(act, dict):
            return False
        if not str(act.get("title") or "").strip():
            return False
        if not str(act.get("summary") or "").strip():
            return False
        chapters = act.get("chapters")
        if not isinstance(chapters, list) or len(chapters) == 0:
            return False
    return True


async def _complete_framework_payload(framework: dict | None, description: str, api_key: str | None = None) -> dict:
    payload = dict(framework or {})
    payload["tags"] = payload.get("tags") if isinstance(payload.get("tags"), dict) else {}
    payload["characters"] = _normalize_characters_payload(payload.get("characters") if isinstance(payload.get("characters"), list) else [])
    payload["outline"] = _merge_framework_outline({}, payload.get("outline"), payload.get("chapters"))
    payload["chapters"] = _extract_outline_chapters(payload["outline"])

    story_context = {
        "description": description,
        "tags": payload["tags"],
        "characters": payload["characters"],
        "outline": payload["outline"],
    }

    if not _has_complete_tags(payload["tags"]):
        try:
            payload["tags"] = _merge_tags(payload["tags"], await regenerate_tags(story_context, api_key=api_key))
            story_context["tags"] = payload["tags"]
        except Exception as exc:
            logger.warning("Failed to backfill framework tags: %s", exc)

    if not _has_complete_characters(payload["characters"]):
        try:
            payload["characters"] = _merge_characters_payload(
                payload["characters"],
                await regenerate_characters(story_context, api_key=api_key),
            )
            story_context["characters"] = payload["characters"]
        except Exception as exc:
            logger.warning("Failed to backfill framework characters: %s", exc)

    if not _has_complete_outline(payload["outline"]):
        try:
            incoming_outline = await regenerate_outline(story_context, api_key=api_key)
            payload["outline"] = _merge_framework_outline(
                payload["outline"],
                incoming_outline,
                _extract_outline_chapters(incoming_outline),
            )
            story_context["outline"] = payload["outline"]
        except Exception as exc:
            logger.warning("Failed to backfill framework outline: %s", exc)

    payload["chapters"] = _extract_outline_chapters(payload["outline"])
    return payload


def _sort_story_chapters_for_shift(story: Story, start_number: int, delta: int) -> list[Chapter]:
    if delta == 0:
        return []
    candidates = [chapter for chapter in story.chapters if chapter.chapter_number >= start_number]
    return sorted(candidates, key=lambda chapter: chapter.chapter_number, reverse=delta > 0)


def _shift_story_chapter_numbers(story: Story, start_number: int, delta: int) -> None:
    for chapter in _sort_story_chapters_for_shift(story, start_number, delta):
        chapter.chapter_number += delta


def _normalize_outline_plan_payload(raw: dict | None, *, fallback_title: str, fallback_act: str) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    title = str(raw.get("title") or "").strip() or fallback_title
    summary = str(raw.get("summary") or "").strip()
    key_events = _normalize_key_events(raw.get("key_events"))
    act = str(raw.get("act") or fallback_act or "").strip() or fallback_act

    payload = {
        "title": title,
        "act": act,
    }
    if summary:
        payload["summary"] = summary
    if key_events:
        payload["key_events"] = key_events
    return payload


def _infer_manual_plan_act(chapters: list[dict], *, after_chapter_number: int | None = None, target_chapter_number: int | None = None) -> str:
    if isinstance(target_chapter_number, int):
        for item in chapters:
            if item.get("chapter_number") == target_chapter_number:
                return str(item.get("act") or "").strip() or "1"

    if isinstance(after_chapter_number, int):
        for item in chapters:
            if item.get("chapter_number") == after_chapter_number:
                return str(item.get("act") or "").strip() or "1"
        for item in chapters:
            if item.get("chapter_number") == after_chapter_number + 1:
                return str(item.get("act") or "").strip() or "1"

    if chapters:
        return str(chapters[-1].get("act") or "").strip() or "1"
    return "1"


def _apply_chapter_content(chapter: Chapter, content: str, *, status: str | None = None) -> None:
    chapter.novel_content = content
    chapter.word_count = _count_words(content)
    if status:
        chapter.status = status


def _normalize_big_five_scores(raw):
    if not isinstance(raw, dict):
        return raw
    key_map = {
        "O": "O",
        "C": "C",
        "E": "E",
        "A": "A",
        "N": "N",
        "openness": "O",
        "conscientiousness": "C",
        "extraversion": "E",
        "agreeableness": "A",
        "neuroticism": "N",
    }
    normalized = {}
    for key, value in raw.items():
        target = key_map.get(str(key))
        if not target:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric <= 10:
            numeric *= 10
        normalized[target] = max(0, min(100, int(round(numeric))))
    return normalized or raw


def _normalize_characters_payload(raw):
    if not isinstance(raw, list):
        return raw
    normalized = []
    for item in raw:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        character = dict(item)
        if "big_five" in character:
            character["big_five"] = _normalize_big_five_scores(character.get("big_five"))
        normalized.append(character)
    return normalized


def _merge_tags(existing, incoming):
    existing = existing if isinstance(existing, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}
    merged = dict(existing)
    for key, value in incoming.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged or existing or incoming


def _merge_characters_payload(existing, incoming):
    existing_list = _normalize_characters_payload(existing if isinstance(existing, list) else [])
    incoming_list = _normalize_characters_payload(incoming if isinstance(incoming, list) else [])
    merged: list[dict] = []
    index_by_name: dict[str, int] = {}

    for item in existing_list:
        if isinstance(item, dict):
            record = dict(item)
            merged.append(record)
            name = str(record.get("name") or "").strip().lower()
            if name:
                index_by_name[name] = len(merged) - 1
        else:
            merged.append(item)

    for item in incoming_list:
        if not isinstance(item, dict):
            merged.append(item)
            continue
        record = dict(item)
        name = str(record.get("name") or "").strip().lower()
        if name and name in index_by_name:
            idx = index_by_name[name]
            current = dict(merged[idx]) if isinstance(merged[idx], dict) else {}
            current.update({k: v for k, v in record.items() if v not in (None, "", [], {})})
            merged[idx] = current
        else:
            merged.append(record)
            if name:
                index_by_name[name] = len(merged) - 1

    return merged


def _story_framework_context(story: Story) -> dict:
    return {
        "description": story.description or "",
        "tags": story.tags,
        "characters": story.characters,
        "outline": story.outline,
    }


def _unlink_file(path: Path, label: str) -> None:
    if not path.exists():
        return
    try:
        path.unlink()
    except OSError as exc:
        logger.warning("Failed to delete %s %s: %s", label, path, exc)
        raise HTTPException(409, f"{label} file is currently in use. Try again later")


def _rmtree_best_effort(path: Path, label: str) -> None:
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError as exc:
        logger.warning("Failed to delete %s %s: %s", label, path, exc)


def _write_bytes_or_conflict(path: Path, data: bytes, label: str) -> None:
    try:
        path.write_bytes(data)
    except OSError as exc:
        logger.warning("Failed to write %s %s: %s", label, path, exc)
        raise HTTPException(409, f"{label} file is currently in use. Try again later")


def _chapter_dir(chapter_id: int) -> Path:
    return Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}"


def _scene_meta_path(chapter_id: int) -> Path:
    return _chapter_dir(chapter_id) / "scenes_meta.json"


def _write_scenes_file(chapter_id: int, scenes: list[str], sanitized_indices: list[int] | None = None) -> None:
    prompts_dir = _chapter_dir(chapter_id)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    prompts_file = prompts_dir / "scenes.txt"
    with open(prompts_file, "w", encoding="utf-8") as f:
        for idx, scene in enumerate(scenes, start=1):
            f.write(f"=== 第{idx}格 ===\n{scene.strip()}\n\n")
    meta_path = _scene_meta_path(chapter_id)
    payload = {"sanitized_indices": sorted(set(sanitized_indices or []))}
    meta_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _parse_scenes_text(raw: str) -> list[str]:
    import re

    parts = [p.strip() for p in re.split(r"(?m)^=== .*? ===\n", raw) if p.strip()]
    return parts


def _load_scene_meta(chapter_id: int) -> dict:
    meta_path = _scene_meta_path(chapter_id)
    if not meta_path.exists():
        return {"sanitized_indices": []}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {"sanitized_indices": []}


def _clear_chapter_manga_state(chapter: Chapter, db: Session) -> None:
    chapter_dir = _chapter_dir(chapter.id)
    if chapter_dir.exists():
        for filename in ("scenes.txt",):
            path = chapter_dir / filename
            if path.exists():
                _unlink_file(path, filename)
        for img in list(chapter.images):
            img_path = Path(__file__).resolve().parent / img.image_path
            if img_path.exists():
                _unlink_file(img_path, "manga image")
            db.delete(img)


def _clear_chapter_images_only(chapter: Chapter, db: Session) -> None:
    for img in list(chapter.images):
        img_path = Path(__file__).resolve().parent / img.image_path
        if img_path.exists():
            _unlink_file(img_path, "manga image")
        db.delete(img)


def _decode_png_upload(b64: str) -> bytes:
    if not b64:
        raise HTTPException(400, "No image provided")
    if "," in b64 and b64.lstrip().startswith("data:"):
        b64 = b64.split(",", 1)[1]
    try:
        import base64
        import binascii
        import io

        from PIL import Image, UnidentifiedImageError

        img_bytes = base64.b64decode(b64, validate=True)
        if len(img_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"Image is too large. Max size is {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")
        with Image.open(io.BytesIO(img_bytes)) as img:
            img.verify()
        with Image.open(io.BytesIO(img_bytes)) as img:
            output = io.BytesIO()
            img.convert("RGBA").save(output, format="PNG", optimize=True)
            png_bytes = output.getvalue()
        if len(png_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"Image is too large after processing. Max size is {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")
        return png_bytes
    except HTTPException:
        raise
    except (binascii.Error, ValueError):
        raise HTTPException(400, "Invalid base64 image data")
    except UnidentifiedImageError:
        raise HTTPException(400, "Uploaded file is not a valid image")


@app.on_event("startup")
def on_startup():
    init_db()
    # One-time: rename default stories
    from database import SessionLocal
    db = SessionLocal()
    try:
        for s in db.query(Story).filter(Story.title.in_(["我的第一个故事", "未命名故事"])).all():
            if s.chapters and any(ch.messages for ch in s.chapters):
                s.title = "转生成为暗恋公主的女仆故事"
                s.description = "百合女仆与公主的奇幻冒险"
            # else: leave as-is for empty stories
        db.commit()
    finally:
        db.close()


# ─── Story CRUD ─────────────────────────────────────────────

@app.post("/api/stories", response_model=StoryOut)
def create_story(body: StoryCreate, db: Session = Depends(get_db)):
    story = Story(title=body.title, description=body.description)
    db.add(story)
    db.flush()
    # Auto-create first chapter
    chapter = Chapter(story_id=story.id, chapter_number=1)
    db.add(chapter)
    db.commit()
    db.refresh(story)
    return story


@app.get("/api/stories", response_model=list[StoryOut])
def list_stories(db: Session = Depends(get_db)):
    return db.query(Story).order_by(Story.created_at.desc()).all()


@app.get("/api/stories/{story_id}", response_model=StoryOut)
def get_story(story_id: int, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    return story


@app.put("/api/stories/{story_id}", response_model=StoryOut)
def update_story(story_id: int, body: StoryUpdate, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    if body.title is not None:
        story.title = body.title
    if body.description is not None:
        story.description = body.description
    if body.tags is not None:
        story.tags = body.tags
    if body.outline is not None:
        story.outline = body.outline
    if body.characters is not None:
        story.characters = _normalize_characters_payload(body.characters)
    db.commit()
    db.refresh(story)
    return story


@app.delete("/api/stories/{story_id}")
def delete_story(story_id: int, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    # Delete all chapters and their data
    for chapter in story.chapters:
        chapter_dir = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter.id}"
        _rmtree_best_effort(chapter_dir, "chapter directory")
        for img in chapter.images:
            db.delete(img)
        for msg in chapter.messages:
            db.delete(msg)
        db.delete(chapter)
    if story.cover_image:
        cover_path = Path(__file__).resolve().parent / story.cover_image
        try:
            _unlink_file(cover_path, "story cover")
        except HTTPException:
            logger.warning("Story cover remained after story deletion: %s", cover_path)
    story_dir = Path(__file__).resolve().parent / "manga_outputs" / f"story_{story_id}"
    _rmtree_best_effort(story_dir, "story asset directory")
    db.delete(story)
    db.commit()
    return {"ok": True}


@app.post("/api/stories/{story_id}/upload-cover")
async def upload_story_cover(story_id: int, request: Request, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    body = await request.json()
    b64 = body.get("image", "")
    import uuid
    img_bytes = _decode_png_upload(b64)
    covers_dir = manga_dir / "covers"
    covers_dir.mkdir(parents=True, exist_ok=True)
    filename = f"cover_{story_id}_{uuid.uuid4().hex[:8]}.png"
    _write_bytes_or_conflict(covers_dir / filename, img_bytes, "story cover")
    # Delete old cover file if exists
    if story.cover_image:
        old = Path(__file__).resolve().parent / story.cover_image
        try:
            _unlink_file(old, "old story cover")
        except HTTPException:
            logger.warning("Old story cover remained after replacement: %s", old)
    story.cover_image = f"manga_outputs/covers/{filename}"
    db.commit()
    db.refresh(story)
    return {"cover_image": story.cover_image}


# ─── Chapter CRUD ───────────────────────────────────────────

@app.get("/api/stories/{story_id}/chapters", response_model=list[ChapterOut])
def list_chapters(story_id: int, db: Session = Depends(get_db)):
    if not db.get(Story, story_id):
        raise HTTPException(404, "Story not found")
    return (
        db.query(Chapter)
        .filter(Chapter.story_id == story_id)
        .order_by(Chapter.chapter_number)
        .all()
    )


@app.get("/api/chapters/{chapter_id}", response_model=ChapterOut)
def get_chapter(chapter_id: int, db: Session = Depends(get_db)):
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found")
    return chapter


@app.post("/api/stories/{story_id}/chapters", response_model=ChapterOut)
def create_next_chapter(story_id: int, db: Session = Depends(get_db)):
    story = (
        db.query(Story)
        .filter(Story.id == story_id)
        .with_for_update()
        .first()
    )
    if not story:
        raise HTTPException(404, "Story not found")
    max_num = (
        db.query(Chapter.chapter_number)
        .filter(Chapter.story_id == story_id)
        .order_by(Chapter.chapter_number.desc())
        .first()
    )
    next_num = (max_num[0] + 1) if max_num else 1
    chapter = Chapter(story_id=story_id, chapter_number=next_num, title=f"第{next_num}话", status="pending")
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


@app.delete("/api/chapters/{chapter_id}")
def delete_chapter(chapter_id: int, db: Session = Depends(get_db)):
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found")

    # Delete image files from disk
    chapter_dir = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}"
    _rmtree_best_effort(chapter_dir, "chapter directory")

    # Delete DB records (messages + images cascade via relationship, or manually)
    for img in chapter.images:
        db.delete(img)
    for msg in chapter.messages:
        db.delete(msg)
    db.delete(chapter)
    db.commit()
    return {"ok": True}


# ─── Chat (SSE streaming) ──────────────────────────────────

@app.post("/api/chapters/{chapter_id}/chat")
async def chat(chapter_id: int, body: ChatMessageIn, request: Request, db: Session = Depends(get_db)):
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found")
    if chapter.content_source == "import":
        raise HTTPException(409, "This chapter was imported from existing novel text and cannot use AI chat")

    # Save user message
    chapter.content_source = "chat"
    user_msg = ChatMessage(chapter_id=chapter_id, role="user", content=body.content)
    db.add(user_msg)
    db.commit()

    # Build message history including all previous chapters in same story
    all_chapters = (
        db.query(Chapter)
        .filter(Chapter.story_id == chapter.story_id, Chapter.chapter_number <= chapter.chapter_number)
        .order_by(Chapter.chapter_number)
        .all()
    )
    history = []
    for ch in all_chapters:
        for m in ch.messages:
            history.append({"role": m.role, "content": m.content})

    framework_context = _build_framework_context(chapter.story, chapter)

    collected: list[str] = []

    def save_interrupted_assistant() -> None:
        full_content = "".join(collected).strip()
        if not full_content:
            return
        assistant_msg = ChatMessage(
            chapter_id=chapter_id,
            role="assistant",
            content=f"{full_content}\n\n[已中止]",
        )
        db.add(assistant_msg)
        db.commit()

    async def event_generator():
        try:
            async for token in chat_stream(history, api_key=_user_deepseek_api_key(request), framework_context=framework_context):
                collected.append(token)
                yield {"event": "token", "data": json.dumps({"content": token}, ensure_ascii=False)}
            # Save assistant message
            full_content = "".join(collected)
            assistant_msg = ChatMessage(chapter_id=chapter_id, role="assistant", content=full_content)
            db.add(assistant_msg)
            db.commit()
            yield {"event": "done", "data": json.dumps({"content": full_content}, ensure_ascii=False)}
        except asyncio.CancelledError:
            db.rollback()
            save_interrupted_assistant()
            raise
        except Exception as e:
            db.rollback()
            persisted_user_msg = db.get(ChatMessage, user_msg.id)
            if persisted_user_msg:
                db.delete(persisted_user_msg)
                db.commit()
            yield {"event": "error", "data": json.dumps({"error": str(e)}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


# ─── Generate Novel ─────────────────────────────────────────

@app.post("/api/chapters/{chapter_id}/generate-novel", response_model=ChapterOut)
async def generate_novel_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found")
    if chapter.content_source == "import":
        raise HTTPException(409, "This chapter was imported from existing novel text and cannot generate AI novel text")

    history = [{"role": m.role, "content": m.content} for m in chapter.messages]
    if not history:
        raise HTTPException(400, "No chat history to generate novel from")

    # Build framework context from story outline, characters, tags and chapter metadata
    framework_context = _build_framework_context(chapter.story, chapter)

    novel_content = await generate_novel(
        history,
        api_key=_user_deepseek_api_key(request),
        framework_context=framework_context,
    )
    _apply_chapter_content(chapter, novel_content, status="completed")
    chapter.content_source = "chat"

    # Also save as assistant message
    msg = ChatMessage(chapter_id=chapter_id, role="assistant", content=novel_content)
    db.add(msg)
    db.commit()
    db.refresh(chapter)
    return chapter


MAX_IMPORTED_NOVEL_CHARS = int(os.getenv("MAX_IMPORTED_NOVEL_CHARS", "50000"))


@app.post("/api/chapters/{chapter_id}/import-novel", response_model=ChapterOut)
async def import_novel_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    """Replace chapter chat history with a single user-imported novel text.

    The imported text is saved both as a single chat message (so the existing
    `generate-scenes` flow works unchanged) and as `chapter.novel_content`.
    """
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found")

    body = await request.json()
    raw = body.get("content", "")
    if not isinstance(raw, str):
        raise HTTPException(400, "content must be a string")
    text = raw.strip()
    if not text:
        raise HTTPException(400, "content is empty")
    if len(text) > MAX_IMPORTED_NOVEL_CHARS:
        raise HTTPException(413, f"Novel is too long. Max length is {MAX_IMPORTED_NOVEL_CHARS} characters")
    if chapter.content_source == "chat" or chapter.messages:
        raise HTTPException(409, "This chapter already uses AI chat. Create a new chapter to import existing novel text.")
    if chapter.images:
        raise HTTPException(409, "This chapter already has manga images. Create a new chapter to import existing novel text.")

    _clear_chapter_manga_state(chapter, db)
    db.query(ChatMessage).filter(ChatMessage.chapter_id == chapter_id).delete()
    db.add(ChatMessage(chapter_id=chapter_id, role="user", content=text))
    _apply_chapter_content(chapter, text, status="draft")
    chapter.content_source = "import"
    db.commit()
    db.refresh(chapter)
    return chapter


@app.put("/api/chapters/{chapter_id}/content", response_model=ChapterOut)
def update_chapter_content(chapter_id: int, body: ChapterContentUpdate, db: Session = Depends(get_db)):
    chapter = _require_chapter(chapter_id, db)
    text = body.content.strip()
    if not text:
        raise HTTPException(400, "content is empty")
    _apply_chapter_content(chapter, text, status="draft")
    db.commit()
    db.refresh(chapter)
    return chapter


# ─── Character Profiles ───────────────────────────────────

def _characters_path(chapter_id: int) -> Path:
    return Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "characters.txt"


def _load_characters(chapter_id: int, db: Session | None = None) -> str:
    """Load character profiles: chapter-level file first, then fallback to story-level."""
    p = _characters_path(chapter_id)
    if p.exists():
        text = p.read_text(encoding="utf-8").strip()
        if text:
            return text
    # Fallback to story-level
    if db:
        chapter = db.get(Chapter, chapter_id)
        if chapter and chapter.story and chapter.story.character_profiles:
            return chapter.story.character_profiles.strip()
    return ""


def _has_chapter_characters(chapter_id: int) -> bool:
    """Check if chapter has its own character file (not inherited)."""
    p = _characters_path(chapter_id)
    return p.exists() and bool(p.read_text(encoding="utf-8").strip())


# Story-level character profiles
@app.get("/api/stories/{story_id}/characters")
async def get_story_characters(story_id: int, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    return {"characters": (story.character_profiles or "").strip()}


@app.put("/api/stories/{story_id}/characters")
async def save_story_characters(story_id: int, body: dict, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    story.character_profiles = _character_profile_text(body)
    db.commit()
    return {"ok": True}


@app.post("/api/stories/{story_id}/characters/generate")
async def generate_story_characters_from_framework(story_id: int, request: Request, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    if not isinstance(story.characters, list) or len(story.characters) == 0:
        raise HTTPException(400, "Story has no framework characters to convert")

    generated = await generate_character_profiles_from_framework(
        _story_framework_context(story),
        api_key=_user_deepseek_api_key(request),
    )
    story.character_profiles = _character_profile_text({"characters": generated})
    db.commit()
    return {"characters": story.character_profiles.strip()}


# Chapter-level character profiles (with fallback info)
@app.get("/api/chapters/{chapter_id}/characters")
async def get_characters(chapter_id: int, db: Session = Depends(get_db)):
    chapter = _require_chapter(chapter_id, db)
    has_own = _has_chapter_characters(chapter_id)
    if has_own:
        text = _characters_path(chapter_id).read_text(encoding="utf-8").strip()
    else:
        text = (chapter.story.character_profiles or "").strip() if chapter.story else ""
    return {"characters": text, "source": "chapter" if has_own else ("story" if text else "none")}


@app.put("/api/chapters/{chapter_id}/characters")
async def save_characters(chapter_id: int, body: dict, db: Session = Depends(get_db)):
    _require_chapter(chapter_id, db)
    text = _character_profile_text(body)
    p = _characters_path(chapter_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return {"ok": True}


@app.delete("/api/chapters/{chapter_id}/characters")
async def reset_chapter_characters(chapter_id: int, db: Session = Depends(get_db)):
    """Delete chapter-level override so it falls back to story-level."""
    _require_chapter(chapter_id, db)
    p = _characters_path(chapter_id)
    _unlink_file(p, "character profile")
    return {"ok": True}


# ─── Reference Image (垫图，支持多图) ──────────────────────────

MAX_REF_IMAGES_PER_LEVEL = int(os.getenv("MAX_REF_IMAGES_PER_LEVEL", "4"))


def _story_ref_dir(story_id: int) -> Path:
    return Path(__file__).resolve().parent / "manga_outputs" / f"story_{story_id}" / "ref_images"


def _chapter_ref_dir(chapter_id: int) -> Path:
    return Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "ref_images"


def _ref_meta_path(ref_dir: Path) -> Path:
    return ref_dir / "ref_meta.json"


def _legacy_story_ref_image(story_id: int) -> Path:
    """Old single-file location, kept for backward compat / lazy migration."""
    return Path(__file__).resolve().parent / "manga_outputs" / f"story_{story_id}" / "ref_image.png"


def _legacy_chapter_ref_image(chapter_id: int) -> Path:
    return Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "ref_image.png"


def _migrate_legacy_ref(legacy: Path, ref_dir: Path) -> None:
    """Move legacy single ref_image.png into ref_images/ as ref_legacy.png on demand."""
    if not legacy.exists():
        return
    try:
        ref_dir.mkdir(parents=True, exist_ok=True)
        target = ref_dir / "ref_legacy.png"
        if target.exists():
            target = ref_dir / f"ref_legacy_{uuid.uuid4().hex[:8]}.png"
        legacy.rename(target)
        logger.info("Migrated legacy ref image %s -> %s", legacy, target)
    except OSError as exc:
        logger.warning("Failed to migrate legacy ref image %s: %s", legacy, exc)


def _list_ref_files(ref_dir: Path) -> list[Path]:
    if not ref_dir.exists():
        return []
    return sorted([p for p in ref_dir.iterdir() if p.is_file() and p.suffix.lower() == ".png"])


def _load_ref_meta(ref_dir: Path) -> dict[str, dict]:
    meta_path = _ref_meta_path(ref_dir)
    if not meta_path.exists():
        return {}
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save_ref_meta(ref_dir: Path, meta: dict[str, dict]) -> None:
    ref_dir.mkdir(parents=True, exist_ok=True)
    _ref_meta_path(ref_dir).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _ref_static_path(ref_dir: Path, filename: str, kind: str, owner_id: int) -> str:
    """Build the static URL-relative path for a ref image."""
    if kind == "story":
        return f"manga_outputs/story_{owner_id}/ref_images/{filename}"
    return f"manga_outputs/chapter_{owner_id}/ref_images/{filename}"


def _serialize_refs(ref_dir: Path, kind: str, owner_id: int) -> list[dict]:
    meta = _load_ref_meta(ref_dir)
    out = []
    for p in _list_ref_files(ref_dir):
        item = {
            "filename": p.name,
            "image_path": _ref_static_path(ref_dir, p.name, kind, owner_id),
            "size_kb": round(p.stat().st_size / 1024),
        }
        extra = meta.get(p.name)
        if isinstance(extra, dict):
            if isinstance(extra.get("label"), str) and extra["label"].strip():
                item["label"] = extra["label"].strip()
            if isinstance(extra.get("kind"), str) and extra["kind"].strip():
                item["kind"] = extra["kind"].strip()
        out.append(item)
    return out


def _build_ref_entries(ref_dir: Path, kind: str, owner_id: int) -> list[dict]:
    meta = _load_ref_meta(ref_dir)
    entries: list[dict] = []
    for p in _list_ref_files(ref_dir):
        item = {
            "filename": p.name,
            "path": p,
            "image_path": _ref_static_path(ref_dir, p.name, kind, owner_id),
            "kind": "",
            "label": "",
        }
        extra = meta.get(p.name)
        if isinstance(extra, dict):
            if isinstance(extra.get("label"), str):
                item["label"] = extra["label"].strip()
            if isinstance(extra.get("kind"), str):
                item["kind"] = extra["kind"].strip()
        entries.append(item)
    return entries


def _effective_ref_entries(chapter_id: int, db: Session) -> list[dict]:
    chapter_dir = _chapter_ref_dir(chapter_id)
    _migrate_legacy_ref(_legacy_chapter_ref_image(chapter_id), chapter_dir)
    chapter_refs = _build_ref_entries(chapter_dir, "chapter", chapter_id)
    if chapter_refs:
        return chapter_refs
    chapter = db.get(Chapter, chapter_id)
    if chapter:
        story_dir = _story_ref_dir(chapter.story_id)
        _migrate_legacy_ref(_legacy_story_ref_image(chapter.story_id), story_dir)
        return _build_ref_entries(story_dir, "story", chapter.story_id)
    return []


def _effective_ref_image_paths(chapter_id: int, db: Session) -> list[Path]:
    """Return the effective ref image list: chapter-level first, else story-level fallback."""
    return [entry["path"] for entry in _effective_ref_entries(chapter_id, db)]


def _select_ref_image_paths_for_scene(scene_prompt: str, ref_entries: list[dict]) -> list[Path]:
    if not ref_entries:
        return []

    scene_text = (scene_prompt or "").strip()
    unlabeled = [entry["path"] for entry in ref_entries if not entry.get("label")]
    labeled_matches = [
        entry["path"]
        for entry in ref_entries
        if entry.get("label") and entry["label"] in scene_text
    ]
    if labeled_matches:
        seen: set[str] = set()
        selected: list[Path] = []
        for path in [*unlabeled, *labeled_matches]:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            selected.append(path)
        return selected
    return unlabeled or [entry["path"] for entry in ref_entries]


def _save_uploaded_ref(ref_dir: Path, img_bytes: bytes, label: str) -> str:
    if len(_list_ref_files(ref_dir)) >= MAX_REF_IMAGES_PER_LEVEL:
        raise HTTPException(409, f"Maximum {MAX_REF_IMAGES_PER_LEVEL} reference images allowed")
    ref_dir.mkdir(parents=True, exist_ok=True)
    filename = f"ref_{uuid.uuid4().hex[:8]}.png"
    _write_bytes_or_conflict(ref_dir / filename, img_bytes, label)
    return filename


def _slugify_ref_label(label: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", (label or "").strip())
    slug = slug.strip("_")
    return slug[:40] or "character"


def _build_character_ref_prompt(story: Story, card: dict) -> str:
    tags = json.dumps(story.tags, ensure_ascii=False) if story.tags else "漫画角色设定"
    return (
        "请生成一张单人漫画角色参考图，用于后续固定角色形象。\n"
        f"题材标签：{tags}\n"
        f"角色名：{card['name']}\n"
        f"角色外貌卡：\n{card['raw']}\n\n"
        "要求：只出现该角色一人；突出稳定五官、发型、服装和体型特征；"
        "采用角色设定图或干净半身立绘构图；背景简洁；不要对话框、不要文字、不要分镜、不要多人物。"
    )


# ─── Story-level multi ref images ───────────────────────────

@app.post("/api/stories/{story_id}/character-ref-images/generate")
async def generate_story_character_ref_images(story_id: int, request: Request, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")

    cards = _parse_character_profile_cards(story.character_profiles or "")
    if not cards:
        raise HTTPException(400, "Story has no character appearance cards to convert")

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    target_name = (body.get("character_name") or "").strip() if isinstance(body, dict) else ""
    overwrite = bool(body.get("overwrite")) if isinstance(body, dict) else False

    targets = [card for card in cards if not target_name or card["name"] == target_name]
    if not targets:
        raise HTTPException(404, f"Character '{target_name}' not found in appearance cards")

    ref_dir = _story_ref_dir(story_id)
    _migrate_legacy_ref(_legacy_story_ref_image(story_id), ref_dir)
    ref_dir.mkdir(parents=True, exist_ok=True)
    meta = _load_ref_meta(ref_dir)
    generated: list[str] = []
    skipped: list[str] = []

    for card in targets:
        existing = [
            filename
            for filename, item in meta.items()
            if isinstance(item, dict)
            and item.get("kind") == "character_generated"
            and item.get("label") == card["name"]
        ]
        if existing and not overwrite:
            skipped.append(card["name"])
            continue

        for filename in existing:
            path = ref_dir / filename
            if path.exists():
                _unlink_file(path, "story character ref image")
            meta.pop(filename, None)

        if len(_list_ref_files(ref_dir)) >= MAX_REF_IMAGES_PER_LEVEL:
            raise HTTPException(409, f"Maximum {MAX_REF_IMAGES_PER_LEVEL} reference images allowed")

        filename = f"char_{_slugify_ref_label(card['name'])}_{uuid.uuid4().hex[:8]}.png"
        await generate_reference_image(
            _build_character_ref_prompt(story, card),
            ref_dir / filename,
            api_key=_user_image_api_key(request),
        )
        meta[filename] = {"label": card["name"], "kind": "character_generated"}
        generated.append(card["name"])

    _save_ref_meta(ref_dir, meta)
    return {
        "images": _serialize_refs(ref_dir, "story", story_id),
        "max": MAX_REF_IMAGES_PER_LEVEL,
        "generated": generated,
        "skipped": skipped,
    }


@app.get("/api/stories/{story_id}/ref-images")
async def list_story_ref_images(story_id: int, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    ref_dir = _story_ref_dir(story_id)
    _migrate_legacy_ref(_legacy_story_ref_image(story_id), ref_dir)
    return {"images": _serialize_refs(ref_dir, "story", story_id), "max": MAX_REF_IMAGES_PER_LEVEL}


@app.post("/api/stories/{story_id}/ref-images")
async def add_story_ref_image(story_id: int, request: Request, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    body = await request.json()
    img_bytes = _decode_png_upload(body.get("image", ""))
    ref_dir = _story_ref_dir(story_id)
    _migrate_legacy_ref(_legacy_story_ref_image(story_id), ref_dir)
    _save_uploaded_ref(ref_dir, img_bytes, "story ref image")
    return {"images": _serialize_refs(ref_dir, "story", story_id), "max": MAX_REF_IMAGES_PER_LEVEL}


@app.delete("/api/stories/{story_id}/ref-images/{filename}")
async def delete_story_ref_image(story_id: int, filename: str, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "invalid filename")
    p = _story_ref_dir(story_id) / filename
    _unlink_file(p, "story ref image")
    meta = _load_ref_meta(_story_ref_dir(story_id))
    if filename in meta:
        meta.pop(filename, None)
        _save_ref_meta(_story_ref_dir(story_id), meta)
    return {"images": _serialize_refs(_story_ref_dir(story_id), "story", story_id), "max": MAX_REF_IMAGES_PER_LEVEL}


# ─── Chapter-level multi ref images (with story fallback) ───

@app.get("/api/chapters/{chapter_id}/ref-images")
async def list_chapter_ref_images(chapter_id: int, db: Session = Depends(get_db)):
    chapter = _require_chapter(chapter_id, db)
    ref_dir = _chapter_ref_dir(chapter_id)
    _migrate_legacy_ref(_legacy_chapter_ref_image(chapter_id), ref_dir)
    chapter_refs = _serialize_refs(ref_dir, "chapter", chapter_id)
    if chapter_refs:
        return {"images": chapter_refs, "source": "chapter", "max": MAX_REF_IMAGES_PER_LEVEL}
    story_dir = _story_ref_dir(chapter.story_id)
    _migrate_legacy_ref(_legacy_story_ref_image(chapter.story_id), story_dir)
    story_refs = _serialize_refs(story_dir, "story", chapter.story_id)
    if story_refs:
        return {"images": story_refs, "source": "story", "max": MAX_REF_IMAGES_PER_LEVEL}
    return {"images": [], "source": "none", "max": MAX_REF_IMAGES_PER_LEVEL}


@app.post("/api/chapters/{chapter_id}/ref-images")
async def add_chapter_ref_image(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    _require_chapter(chapter_id, db)
    body = await request.json()
    img_bytes = _decode_png_upload(body.get("image", ""))
    ref_dir = _chapter_ref_dir(chapter_id)
    _migrate_legacy_ref(_legacy_chapter_ref_image(chapter_id), ref_dir)
    _save_uploaded_ref(ref_dir, img_bytes, "chapter ref image")
    return {"images": _serialize_refs(ref_dir, "chapter", chapter_id), "source": "chapter", "max": MAX_REF_IMAGES_PER_LEVEL}


@app.delete("/api/chapters/{chapter_id}/ref-images/{filename}")
async def delete_chapter_ref_image(chapter_id: int, filename: str, db: Session = Depends(get_db)):
    _require_chapter(chapter_id, db)
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "invalid filename")
    p = _chapter_ref_dir(chapter_id) / filename
    _unlink_file(p, "chapter ref image")
    meta = _load_ref_meta(_chapter_ref_dir(chapter_id))
    if filename in meta:
        meta.pop(filename, None)
        _save_ref_meta(_chapter_ref_dir(chapter_id), meta)
    return {"images": _serialize_refs(_chapter_ref_dir(chapter_id), "chapter", chapter_id), "source": "chapter", "max": MAX_REF_IMAGES_PER_LEVEL}


# ─── Color Mode ─────────────────────────────────────────────

def _color_mode_path(chapter_id: int) -> Path:
    return Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "color_mode.txt"


def _load_color_mode(chapter_id: int) -> str:
    p = _color_mode_path(chapter_id)
    if p.exists():
        return p.read_text(encoding="utf-8").strip() or "bw"
    return "bw"


def _save_color_mode(chapter_id: int, mode: str):
    p = _color_mode_path(chapter_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(mode, encoding="utf-8")


@app.get("/api/chapters/{chapter_id}/color-mode")
async def get_color_mode(chapter_id: int, db: Session = Depends(get_db)):
    _require_chapter(chapter_id, db)
    return {"color_mode": _load_color_mode(chapter_id)}


@app.put("/api/chapters/{chapter_id}/color-mode")
async def set_color_mode(chapter_id: int, body: dict, db: Session = Depends(get_db)):
    _require_chapter(chapter_id, db)
    mode = body.get("color_mode", "bw")
    if mode not in ("bw", "color"):
        raise HTTPException(400, "color_mode must be 'bw' or 'color'")
    _save_color_mode(chapter_id, mode)
    return {"ok": True}


# ─── Image Count ───────────────────────────────────────────

DEFAULT_IMAGE_COUNT = 10
ALLOWED_IMAGE_COUNTS = [4, 6, 8, 10, 12, 15, 20]


def _image_count_path(chapter_id: int) -> Path:
    return Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "image_count.txt"


def _load_image_count(chapter_id: int) -> int:
    p = _image_count_path(chapter_id)
    if p.exists():
        try:
            v = int(p.read_text(encoding="utf-8").strip())
            if v in ALLOWED_IMAGE_COUNTS:
                return v
        except (ValueError, OSError):
            pass
    return DEFAULT_IMAGE_COUNT


def _chapter_has_scene_file(chapter_id: int) -> bool:
    prompts_file = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "scenes.txt"
    if not prompts_file.exists():
        return False
    try:
        return bool(prompts_file.read_text(encoding="utf-8").strip())
    except OSError:
        return True


@app.get("/api/chapters/{chapter_id}/image-count")
async def get_image_count(chapter_id: int, db: Session = Depends(get_db)):
    _require_chapter(chapter_id, db)
    return {"image_count": _load_image_count(chapter_id)}


@app.put("/api/chapters/{chapter_id}/image-count")
async def set_image_count(chapter_id: int, body: dict, db: Session = Depends(get_db)):
    chapter = _require_chapter(chapter_id, db)
    if chapter.images or _chapter_has_scene_file(chapter_id):
        raise HTTPException(409, "Cannot change image count after scenes or images have been created")
    count = body.get("image_count", DEFAULT_IMAGE_COUNT)
    if count not in ALLOWED_IMAGE_COUNTS:
        raise HTTPException(400, f"image_count must be one of {ALLOWED_IMAGE_COUNTS}")
    p = _image_count_path(chapter_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(count), encoding="utf-8")
    return {"ok": True}


# ─── Scene generation & management ───────────────────────

@app.post("/api/chapters/{chapter_id}/generate-scenes")
async def generate_scenes_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    """Generate scene prompts from chat history. Returns them for user review."""
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found")
    if not chapter.messages:
        raise HTTPException(400, "No chat messages yet")

    image_count = _load_image_count(chapter_id)
    chat_history = [{"role": m.role, "content": m.content} for m in chapter.messages]
    split_task = asyncio.create_task(
        split_scenes(
            chat_history,
            character_profiles=_load_characters(chapter_id, db),
            page_count=image_count,
            api_key=_user_deepseek_api_key(request),
        )
    )
    try:
        while not split_task.done():
            if await request.is_disconnected():
                split_task.cancel()
                raise HTTPException(499, "Scene generation was cancelled")
            await asyncio.sleep(0.25)
        scenes = await split_task
        if await request.is_disconnected():
            raise HTTPException(499, "Scene generation was cancelled")
    except ValueError as exc:
        logger.warning("Failed to parse scene split response for chapter %s: %s", chapter_id, exc)
        raise HTTPException(502, "AI returned invalid scene JSON. Please retry generating scenes.")
    except asyncio.CancelledError:
        raise HTTPException(499, "Scene generation was cancelled")
    finally:
        if not split_task.done():
            split_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await split_task
    sanitized_scenes, sanitized_indices = sanitize_scene_list(scenes)
    _write_scenes_file(chapter_id, sanitized_scenes, sanitized_indices)
    return {"scenes": sanitized_scenes, "sanitized_indices": sanitized_indices}


@app.get("/api/chapters/{chapter_id}/scenes")
async def get_scenes_endpoint(chapter_id: int, db: Session = Depends(get_db)):
    """Load saved scene prompts from file."""
    _require_chapter(chapter_id, db)
    prompts_file = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "scenes.txt"
    if not prompts_file.exists():
        return {"scenes": [], "sanitized_indices": []}
    try:
        raw = prompts_file.read_text(encoding="utf-8")
        parts = _parse_scenes_text(raw)
        meta = _load_scene_meta(chapter_id)
        if parts:
            _write_scenes_file(chapter_id, parts, meta.get("sanitized_indices", []))
        return {"scenes": parts, "sanitized_indices": meta.get("sanitized_indices", [])}
    except Exception:
        return {"scenes": [], "sanitized_indices": []}


@app.put("/api/chapters/{chapter_id}/scenes")
async def update_scenes_endpoint(chapter_id: int, body: dict, db: Session = Depends(get_db)):
    """Save user-edited scene prompts."""
    _require_chapter(chapter_id, db)
    scenes = body.get("scenes", [])
    image_count = _load_image_count(chapter_id)
    if not isinstance(scenes, list) or len(scenes) != image_count or not all(isinstance(s, str) and s.strip() for s in scenes):
        raise HTTPException(400, f"Must provide exactly {image_count} scenes")

    _write_scenes_file(chapter_id, scenes, [])
    return {"ok": True}


# ─── SSE for manga image generation ─────────────────────

@app.delete("/api/chapters/{chapter_id}/manga-images")
async def reset_manga_images(chapter_id: int, db: Session = Depends(get_db)):
    chapter = _require_chapter(chapter_id, db)
    if chapter_id in ACTIVE_MANGA_GENERATIONS:
        raise HTTPException(409, "Manga generation is already running for this chapter")
    _clear_chapter_images_only(chapter, db)
    db.commit()
    return {"ok": True}


@app.post("/api/chapters/{chapter_id}/generate-manga-stream")
async def generate_manga_stream(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found")

    # Load scenes from file (must exist - user should generate/confirm scenes first)
    prompts_file = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "scenes.txt"
    if not prompts_file.exists():
        raise HTTPException(400, "No scene prompts found. Generate scenes first.")
    image_count = _load_image_count(chapter_id)

    raw = prompts_file.read_text(encoding="utf-8")
    scenes = _parse_scenes_text(raw)
    if len(scenes) != image_count:
        raise HTTPException(400, f"Expected {image_count} scenes, found {len(scenes)}")
    if chapter_id in ACTIVE_MANGA_GENERATIONS:
        raise HTTPException(409, "Manga generation is already running for this chapter")
    ACTIVE_MANGA_GENERATIONS.add(chapter_id)

    # Check which images already exist
    existing_images = {img.image_number: img for img in chapter.images}

    async def event_generator():
        try:
            yield {"event": "scenes", "data": json.dumps({"scenes": scenes}, ensure_ascii=False)}

            for i, scene_prompt in enumerate(scenes, start=1):
                # Skip already generated images
                if i in existing_images:
                    img = existing_images[i]
                    yield {
                        "event": "image",
                        "data": json.dumps({
                            "id": img.id,
                            "image_number": i,
                            "image_path": img.image_path,
                            "prompt": img.prompt or scene_prompt,
                        }, ensure_ascii=False),
                    }
                    continue

                yield {
                    "event": "progress",
                    "data": json.dumps({"current": i, "total": image_count, "prompt": scene_prompt}, ensure_ascii=False),
                }
                try:
                    ref_entries = _effective_ref_entries(chapter_id, db)
                    ref_imgs = _select_ref_image_paths_for_scene(scene_prompt, ref_entries)
                    image_result = await generate_manga_image(
                        scene_prompt,
                        chapter_id,
                        i,
                        all_scenes=scenes,
                        character_profiles=_load_characters(chapter_id, db),
                        ref_image_paths=[str(p) for p in ref_imgs] if ref_imgs else None,
                        color_mode=_load_color_mode(chapter_id),
                        api_key=_user_image_api_key(request),
                    )
                    if image_result.prompt_sanitized and image_result.final_prompt != scene_prompt:
                        scenes[i - 1] = image_result.final_prompt
                        meta = _load_scene_meta(chapter_id)
                        sanitized_indices = sorted(set((meta.get("sanitized_indices", []) or []) + [i - 1]))
                        _write_scenes_file(chapter_id, scenes, sanitized_indices)
                        scene_prompt = image_result.final_prompt
                except MangaImageGenerationError as img_err:
                    payload = img_err.to_payload()
                    payload["error"] = f"第{i}张生成失败: {payload['error']}"
                    payload["image_number"] = i
                    yield {"event": "error", "data": json.dumps(payload, ensure_ascii=False)}
                    return
                except Exception as img_err:
                    yield {
                        "event": "error",
                        "data": json.dumps({"error": f"第{i}张生成失败: {str(img_err) or repr(img_err)}", "code": "unknown_error", "image_number": i}, ensure_ascii=False),
                    }
                    return

                manga = MangaImage(
                    chapter_id=chapter_id,
                    image_number=i,
                    image_path=image_result.image_path,
                    prompt=scene_prompt,
                )
                db.add(manga)
                db.commit()
                db.refresh(manga)
                yield {
                    "event": "image",
                    "data": json.dumps({
                        "id": manga.id,
                        "image_number": i,
                        "image_path": image_result.image_path,
                        "prompt": scene_prompt,
                    }, ensure_ascii=False),
                }

            yield {"event": "done", "data": json.dumps({"message": "漫画生成完成！"}, ensure_ascii=False)}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)}, ensure_ascii=False)}
        finally:
            ACTIVE_MANGA_GENERATIONS.discard(chapter_id)

    return EventSourceResponse(event_generator(), ping=10)


# ─── Regenerate single image ─────────────────────────────

@app.post("/api/chapters/{chapter_id}/regenerate-image/{image_number}")
async def regenerate_single_image(chapter_id: int, image_number: int, body: dict, request: Request, db: Session = Depends(get_db)):
    """Regenerate a single panel image with an updated prompt."""
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(404, "Chapter not found")
    image_count = _load_image_count(chapter_id)
    if image_number < 1 or image_number > image_count:
        raise HTTPException(400, f"image_number must be 1-{image_count}")

    prompt = body.get("prompt", "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")

    # Load all scenes for context
    prompts_file = Path(__file__).resolve().parent / "manga_outputs" / f"chapter_{chapter_id}" / "scenes.txt"
    all_scenes = None
    if prompts_file.exists():
        raw = prompts_file.read_text(encoding="utf-8")
        parts = _parse_scenes_text(raw)
        if len(parts) == image_count:
            # Update the scene in file
            parts[image_number - 1] = prompt
            all_scenes = parts
            _write_scenes_file(chapter_id, parts, _load_scene_meta(chapter_id).get("sanitized_indices", []))

    # Keep old DB/file intact until the new image is generated successfully.
    old_img = db.query(MangaImage).filter(
        MangaImage.chapter_id == chapter_id,
        MangaImage.image_number == image_number,
    ).first()
    old_path = Path(__file__).resolve().parent / old_img.image_path if old_img else None

    # Generate new image
    ref_entries = _effective_ref_entries(chapter_id, db)
    ref_imgs = _select_ref_image_paths_for_scene(prompt, ref_entries)
    try:
        image_result = await generate_manga_image(
            prompt,
            chapter_id,
            image_number,
            all_scenes=all_scenes,
            character_profiles=_load_characters(chapter_id, db),
            ref_image_paths=[str(p) for p in ref_imgs] if ref_imgs else None,
            color_mode=_load_color_mode(chapter_id),
            api_key=_user_image_api_key(request),
        )
    except MangaImageGenerationError as exc:
        raise HTTPException(502, exc.to_payload()) from exc
    if image_result.prompt_sanitized and image_result.final_prompt != prompt and all_scenes and len(all_scenes) == image_count:
        all_scenes[image_number - 1] = image_result.final_prompt
        meta = _load_scene_meta(chapter_id)
        sanitized_indices = sorted(set((meta.get("sanitized_indices", []) or []) + [image_number - 1]))
        _write_scenes_file(chapter_id, all_scenes, sanitized_indices)
        prompt = image_result.final_prompt

    if old_img:
        manga = old_img
        manga.image_path = image_result.image_path
        manga.prompt = prompt
    else:
        manga = MangaImage(
            chapter_id=chapter_id,
            image_number=image_number,
            image_path=image_result.image_path,
            prompt=prompt,
        )
        db.add(manga)
    db.commit()
    db.refresh(manga)

    if old_path and old_path.exists() and old_path != Path(__file__).resolve().parent / image_result.image_path:
        try:
            old_path.unlink()
        except OSError as exc:
            logger.warning("Failed to delete old regenerated image %s: %s", old_path, exc)

    return {
        "id": manga.id,
        "image_number": image_number,
                        "image_path": image_result.image_path,
        "prompt": prompt,
    }


# ─── Framework (InkAI) ─────────────────────────────────────

@app.post("/api/stories/{story_id}/framework/generate")
async def generate_framework_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    body = await request.json()
    description = body.get("description", "")
    if not isinstance(description, str) or not description.strip():
        description = story.description or ""
    if not description.strip():
        raise HTTPException(400, "description is required")

    framework = await generate_framework(description.strip(), api_key=_user_deepseek_api_key(request))
    framework = await _complete_framework_payload(
        framework,
        description.strip(),
        api_key=_user_deepseek_api_key(request),
    )

    story.description = description.strip()
    story.tags = framework.get("tags")
    story.characters = _normalize_characters_payload(framework.get("characters"))
    story.outline = _merge_framework_outline(story.outline, framework.get("outline"), framework.get("chapters"))
    db.commit()
    db.refresh(story)
    return {
        "tags": story.tags,
        "characters": story.characters,
        "outline": story.outline,
        "chapters": framework.get("chapters"),
    }


@app.post("/api/stories/{story_id}/framework/tags")
async def regenerate_tags_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")

    story_context = {
        "description": story.description or "",
        "tags": story.tags,
        "characters": story.characters,
        "outline": story.outline,
    }
    result = await regenerate_tags(story_context, api_key=_user_deepseek_api_key(request))

    tags = result if isinstance(result, dict) and "type" in result else result
    story.tags = tags
    db.commit()
    db.refresh(story)
    return {"tags": story.tags}


@app.post("/api/stories/{story_id}/framework/characters")
async def regenerate_characters_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")

    story_context = {
        "description": story.description or "",
        "tags": story.tags,
        "characters": story.characters,
        "outline": story.outline,
    }
    result = await regenerate_characters(story_context, api_key=_user_deepseek_api_key(request))

    characters = _normalize_characters_payload(result if isinstance(result, list) else result)
    story.characters = characters
    db.commit()
    db.refresh(story)
    return {"characters": story.characters}


@app.post("/api/stories/{story_id}/framework/outline")
async def regenerate_outline_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")

    story_context = {
        "description": story.description or "",
        "tags": story.tags,
        "characters": story.characters,
        "outline": story.outline,
    }
    result = await regenerate_outline(story_context, api_key=_user_deepseek_api_key(request))

    outline = result if isinstance(result, dict) and "three_acts" in result else result
    story.outline = _merge_framework_outline(story.outline, outline, _extract_outline_chapters(outline))
    db.commit()
    db.refresh(story)
    return {"outline": story.outline}


@app.post("/api/stories/{story_id}/framework/chapters/manual")
def update_outline_chapter_plan(story_id: int, body: OutlineChapterPlanUpdate, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")

    mode = (body.mode or "").strip().lower()
    if mode not in {"append", "insert_after", "update"}:
        raise HTTPException(400, "Invalid mode")

    chapters = _extract_outline_chapters(story.outline)
    plan_map = {item["chapter_number"]: dict(item) for item in chapters}

    if mode == "update":
        target_number = body.target_chapter_number
        if not isinstance(target_number, int) or target_number < 1:
            raise HTTPException(400, "target_chapter_number is required for update")
        existing = plan_map.get(target_number)
        if not existing:
            raise HTTPException(404, "Planned chapter not found")
        fallback_title = existing.get("title") or f"Chapter {target_number}"
        fallback_act = str(existing.get("act") or _infer_manual_plan_act(chapters, target_chapter_number=target_number))
        normalized = _normalize_outline_plan_payload(body.chapter.model_dump(), fallback_title=fallback_title, fallback_act=fallback_act)
        existing.update(normalized)
        existing["chapter_number"] = target_number
        plan_map[target_number] = existing
        next_plans = [plan_map[key] for key in sorted(plan_map)]
    else:
        if mode == "append":
            after_number = max((item["chapter_number"] for item in chapters), default=0)
        else:
            after_number = body.after_chapter_number
            if not isinstance(after_number, int) or after_number < 1:
                raise HTTPException(400, "after_chapter_number is required for insert_after")
            if after_number not in plan_map:
                raise HTTPException(404, "Insert anchor chapter not found")

        new_number = after_number + 1
        fallback_act = _infer_manual_plan_act(chapters, after_chapter_number=after_number)
        normalized = _normalize_outline_plan_payload(
            body.chapter.model_dump(),
            fallback_title=f"Chapter {new_number}",
            fallback_act=fallback_act,
        )

        shifted_plans: list[dict] = []
        for item in chapters:
            current = dict(item)
            if current["chapter_number"] >= new_number:
                current["chapter_number"] += 1
            shifted_plans.append(current)

        _shift_story_chapter_numbers(story, new_number, 1)

        normalized["chapter_number"] = new_number
        shifted_plans.append(normalized)
        next_plans = sorted(shifted_plans, key=lambda item: item["chapter_number"])

    story.outline = _normalize_framework_outline(story.outline, next_plans)
    db.commit()
    db.refresh(story)
    return {"outline": story.outline}


@app.post("/api/stories/{story_id}/framework/adjust")
async def adjust_framework_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")

    body = await request.json()
    messages = body.get("messages", [])
    if not isinstance(messages, list) or not messages:
        raise HTTPException(400, "messages is required")

    result = await adjust_framework_with_chat(
        _story_framework_context(story),
        messages,
        api_key=_user_deepseek_api_key(request),
    )

    framework = result.get("framework", {})
    description = str(framework.get("description") or story.description or "").strip()
    story.description = description
    story.tags = _merge_tags(story.tags, framework.get("tags"))
    story.characters = _merge_characters_payload(story.characters, framework.get("characters"))
    story.outline = _merge_framework_outline(story.outline, framework.get("outline"), framework.get("chapters"))
    db.commit()
    db.refresh(story)
    return {
        "reply": result.get("reply", ""),
        "story": {
            "description": story.description,
            "tags": story.tags,
            "characters": story.characters,
            "outline": story.outline,
        },
        "chapters": framework.get("chapters"),
    }


@app.post("/api/stories/{story_id}/framework/continue")
async def continue_framework_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")

    result = await continue_framework(
        _story_framework_context(story),
        api_key=_user_deepseek_api_key(request),
    )
    framework = result.get("framework", {})
    story.description = str(framework.get("description") or story.description or "").strip()
    story.tags = _merge_tags(story.tags, framework.get("tags"))
    story.characters = _merge_characters_payload(story.characters, framework.get("characters"))
    story.outline = _merge_framework_outline(story.outline, framework.get("outline"), framework.get("chapters"))
    db.commit()
    db.refresh(story)
    return {
        "reply": result.get("reply", ""),
        "story": {
            "description": story.description,
            "tags": story.tags,
            "characters": story.characters,
            "outline": story.outline,
        },
        "chapters": framework.get("chapters"),
    }


@app.post("/api/stories/{story_id}/expand-chapter", response_model=ChapterOut)
async def expand_chapter_endpoint(story_id: int, request: Request, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if not story:
        raise HTTPException(404, "Story not found")
    body = await request.json()
    act = body.get("act", "")
    chapter_title = body.get("chapter_title", "")
    chapter_number_val = body.get("chapter_number")

    if not chapter_title or not isinstance(chapter_title, str) or not chapter_title.strip():
        raise HTTPException(400, "chapter_title is required")

    story_context = {
        "description": story.description or "",
        "tags": story.tags,
        "characters": story.characters,
        "outline": story.outline,
    }
    chapter_info = {
        "title": chapter_title.strip(),
        "act": act if isinstance(act, str) else "",
        "chapter_number": chapter_number_val,
    }

    novel_content = await expand_chapter_to_content(
        story_context,
        chapter_info,
        api_key=_user_deepseek_api_key(request),
    )

    # Determine chapter number
    if isinstance(chapter_number_val, int) and chapter_number_val > 0:
        chapter_num = chapter_number_val
    else:
        max_num = (
            db.query(Chapter.chapter_number)
            .filter(Chapter.story_id == story_id)
            .order_by(Chapter.chapter_number.desc())
            .first()
        )
        chapter_num = (max_num[0] + 1) if max_num else 1

    existing = (
        db.query(Chapter)
        .filter(Chapter.story_id == story_id, Chapter.chapter_number == chapter_num)
        .first()
    )
    chapter = existing or Chapter(story_id=story_id, chapter_number=chapter_num)
    chapter.title = chapter_title.strip()
    chapter.content_source = "chat"
    chapter.act = act if isinstance(act, str) else None
    chapter.key_events = _normalize_key_events(body.get("key_events"))
    _apply_chapter_content(chapter, novel_content, status="completed")
    if existing is None:
        db.add(chapter)
        db.flush()
    db.add(ChatMessage(chapter_id=chapter.id, role="assistant", content=novel_content))
    db.commit()
    db.refresh(chapter)
    return chapter


@app.post("/api/chapters/{chapter_id}/rewrite-selection")
async def rewrite_selection_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    chapter = _require_chapter(chapter_id, db)
    body = await request.json()
    selected_text = body.get("selected_text", "")
    chapter_context = body.get("chapter_context", body.get("context", ""))

    if not isinstance(selected_text, str) or not selected_text.strip():
        raise HTTPException(400, "selected_text is required")
    if not isinstance(chapter_context, str):
        chapter_context = ""

    rewritten = await rewrite_selection(
        selected_text.strip(),
        chapter_context.strip() or (chapter.novel_content or "")[:4000],
        api_key=_user_deepseek_api_key(request),
    )
    return {"rewritten_text": rewritten}


@app.post("/api/chapters/{chapter_id}/adjust-content", response_model=ChapterOut)
async def adjust_chapter_content_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    chapter = _require_chapter(chapter_id, db)
    body = await request.json()
    instruction = body.get("instruction", "")

    if not isinstance(instruction, str) or not instruction.strip():
        raise HTTPException(400, "instruction is required")
    if not chapter.novel_content or not chapter.novel_content.strip():
        raise HTTPException(400, "Chapter has no novel content to adjust")

    chapter_info = {
        "title": chapter.title or f"第{chapter.chapter_number}话",
        "act": chapter.act or "",
        "chapter_number": chapter.chapter_number,
        "key_events": chapter.key_events or [],
    }
    updated_content = await adjust_chapter_content(
        _story_framework_context(chapter.story),
        chapter_info,
        chapter.novel_content,
        instruction.strip(),
        api_key=_user_deepseek_api_key(request),
    )
    _apply_chapter_content(chapter, updated_content, status="completed")
    db.commit()
    db.refresh(chapter)
    return chapter


@app.post("/api/chapters/{chapter_id}/quality-assess")
async def quality_assess_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    chapter = _require_chapter(chapter_id, db)
    content = chapter.novel_content or ""
    if not content.strip():
        raise HTTPException(400, "Chapter has no novel content to assess")

    assessment = await quality_assess(content, api_key=_user_deepseek_api_key(request))

    chapter.quality_score = assessment.get("scores", assessment)
    if chapter.novel_content and chapter.novel_content.strip():
        chapter.status = "reviewed"
    db.commit()
    db.refresh(chapter)
    return assessment


@app.post("/api/chapters/{chapter_id}/scenes-from-selection")
async def scenes_from_selection_endpoint(chapter_id: int, request: Request, db: Session = Depends(get_db)):
    _require_chapter(chapter_id, db)
    body = await request.json()
    selected_text = body.get("selected_text", "")
    character_profiles = body.get("character_profiles", body.get("characters", ""))
    page_count = body.get("page_count", 4)

    if not isinstance(selected_text, str) or not selected_text.strip():
        raise HTTPException(400, "selected_text is required")
    if not isinstance(character_profiles, str):
        character_profiles = str(character_profiles) if character_profiles else ""
    if not isinstance(page_count, int) or page_count < 1:
        page_count = 4
    if page_count > 20:
        page_count = 20

    scenes = await scenes_from_selection(
        selected_text.strip(),
        character_profiles=character_profiles,
        page_count=page_count,
        api_key=_user_deepseek_api_key(request),
    )
    sanitized_scenes, sanitized_indices = sanitize_scene_list(scenes)
    return {"scenes": sanitized_scenes, "page_count": page_count, "sanitized_indices": sanitized_indices}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "true").lower() == "true",
    )
