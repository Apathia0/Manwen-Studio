# 分镜场景与道具卡片 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在分镜列表的展开区域中新增场景卡片和道具卡片，支持 AI 自动提取、资产生成、跨分镜继承，确保同场景同道具的视觉一致性。

**Architecture:** 
- 后端：扩展 `VideoShot` 模型增加 `scene_prompt` 和 `prop_prompts_json` 字段；修改 `parse_shot_asset_prompts` 让 AI 同时提取场景和道具描述；新增道具资产生成端点；实现场景/道具资产继承函数
- 前端：扩展 `ShotAssetPromptDraft` 类型；在 `ShotRow` 展开区新增场景和道具 `AssetCard3` 卡片；新增 API 函数调用后端生成端点

**Tech Stack:** Python/FastAPI/SQLAlchemy (后端), React/TypeScript (前端), DeepSeek API (AI 提取), Image2 API (图片生成)

---

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/models.py` | 修改 | `VideoShot` 增加 `scene_prompt`、`prop_prompts_json` 字段 |
| `backend/routers/video.py` | 修改 | 修改 `parse_shot_asset_prompts`；新增道具/场景资产生成端点；新增继承函数 |
| `frontend/src/api.ts` | 修改 | `ShotAssetPromptDraft` 增加 `scene_prompt`、`prop_prompts`；新增 API 函数 |
| `frontend/src/components/VideoStoryboardPanel.tsx` | 修改 | `ShotRow` 展开区新增场景和道具卡片 |

---

### Task 1: 后端模型扩展 — VideoShot 增加场景和道具字段

**Files:**
- Modify: `backend/models.py:517`

- [ ] **Step 1: 在 VideoShot 模型中增加 scene_prompt 和 prop_prompts_json 字段**

在 `backend/models.py` 的 `VideoShot` 类中，`character_prompts_json` 字段后面添加两个新字段：

```python
# 在 character_prompts_json 字段后面添加
scene_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
prop_prompts_json: Mapped[Any] = mapped_column(JSON, nullable=True)
```

- [ ] **Step 2: 验证模型变更**

```bash
cd backend
python -c "from models import VideoShot; print('scene_prompt' in [c.name for c in VideoShot.__table__.columns]); print('prop_prompts_json' in [c.name for c in VideoShot.__table__.columns])"
```

Expected: 两行都输出 `True`

- [ ] **Step 3: 提交**

```bash
git add backend/models.py
git commit -m "feat: add scene_prompt and prop_prompts_json fields to VideoShot model"
```

---

### Task 2: 后端 AI 提取 — 修改 parse_shot_asset_prompts 增加场景和道具提取

**Files:**
- Modify: `backend/routers/video.py:4877-4920` (AI prompt 部分)
- Modify: `backend/routers/video.py:4944-4982` (结果处理部分)
- Modify: `backend/routers/video.py:4991-5022` (fallback 部分)

- [ ] **Step 1: 修改 AI prompt 的 JSON schema 和规则**

在 `backend/routers/video.py` 中找到 `parse_shot_asset_prompts` 函数，修改 `prompt_text` 变量中的 JSON schema 和规则部分：

```python
# 找到 prompt_text = f"""Generate production-ready shot asset prompts as strict JSON only.
# 修改 JSON schema 部分
prompt_text = f"""Generate production-ready shot asset prompts as strict JSON only.

Return JSON schema:
{{
  "character_prompts": [{{"name":"...", "prompt":"..."}}],
  "scene_prompt": "...",
  "prop_prompts": [{{"name":"...", "prompt":"..."}}],
  "storyboard_prompt": "...",
  "first_frame_prompt": "...",
  "last_frame_prompt": "...",
  "video_prompt": "..."
}}

Rules:
1. Character prompts are CHARACTER DESIGN SHEETS ONLY. No scene events, no system UI text overlays, no chapter plot reenactment.
2. Character prompts must request one-page turnaround sheet with: front portrait, side portrait, full-body, expression set, outfit/accessory callouts.
3. Scene prompt must describe the ENVIRONMENT ONLY (location, architecture, lighting, atmosphere, color palette). No characters, no actions. Example: "A dimly lit medieval tavern with wooden beams, candlelight, stone walls, warm amber tones".
4. Prop prompts are OBJECT DESIGN SHEETS for key props appearing in this shot. Each prop needs: name, detailed visual description (material, size, color, condition, distinctive features). Only include props that are visually important or appear repeatedly. Example: [{"name": "Ancient Sword", "prompt": "A weathered double-edged sword with ornate golden hilt, leather-wrapped grip, blade shows battle scratches, 90cm overall length"}].
5. Storyboard prompt MUST be a time-segmented shot breakdown covering ALL content that will appear in the final video. Requirements:
   a. Divide the shot into 3-5 equal time segments with [X-Ys] timestamps.
   b. For EACH segment describe: exact camera framing and movement state, precise character positions (foreground/background/left/right), facial expressions, body language, lighting changes, any props or environment details visible.
   c. Each segment description must be 2-4 sentences with vivid visual detail (not just one line).
   d. Include all dialogue/exactly when it occurs, with speaker and tone.
   e. End with complete camera/director notes: lens choice, focus pull, lighting setup, color temperature, depth of field.
6. Video prompt must describe the COMPLETE continuous action of the shot from start to end, including all camera movement, character blocking, lighting progression, and sound design. It must be consistent with the storyboard segments.
7. First/last frame prompts must capture the exact visual state at the beginning and end of the shot.
8. Keep style consistency with selected style preset.
9. Output valid JSON object only.

Selected style: {style_name}
Shot grounding: {shot_grounding}
Inherited character constraints: {inherited_constraints}

Character seeds (keep and improve, do not add scene event):
{ai_character_json}

Scene location: {scene_location}
Scene mood: {scene_mood}

Base storyboard prompt:
{base_storyboard}

Base first frame prompt:
{base_first}

Base last frame prompt:
{base_last}

Base video prompt:
{base_video}
"""
```

- [ ] **Step 2: 修改结果处理部分，提取 scene_prompt 和 prop_prompts**

在 `parse_shot_asset_prompts` 函数中，找到 `cleaned_char_prompts` 处理后的位置，添加场景和道具的提取逻辑：

```python
# 在 cleaned_char_prompts 处理后（大约 line 4956 之后）添加
            final_scene_prompt = str(result.get("scene_prompt") or "").strip() or f"Scene at {scene_location}. Mood: {scene_mood}."

            ai_prop_prompts = result.get("prop_prompts", [])
            cleaned_prop_prompts: list[dict] = []
            if isinstance(ai_prop_prompts, list):
                for item in ai_prop_prompts:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    prompt = str(item.get("prompt") or "").strip()
                    if name and prompt:
                        cleaned_prop_prompts.append({"name": name, "prompt": prompt})
```

- [ ] **Step 3: 修改持久化部分，保存 scene_prompt 和 prop_prompts_json**

在 `parse_shot_asset_prompts` 函数中，找到持久化到数据库的部分（AI 成功路径和 fallback 路径都需修改），添加：

```python
# AI 成功路径（大约 line 4964-4969）：
            shot.storyboard_prompt = final_storyboard
            shot.video_prompt = final_video
            shot.first_frame_prompt = final_first
            shot.last_frame_prompt = final_last
            shot.character_prompts_json = cleaned_char_prompts
            shot.scene_prompt = final_scene_prompt  # 新增
            shot.prop_prompts_json = cleaned_prop_prompts  # 新增
            db.commit()

# fallback 路径（大约 line 4999-5004）：
    shot.storyboard_prompt = fallback_storyboard
    shot.video_prompt = fallback_video
    shot.first_frame_prompt = fallback_first
    shot.last_frame_prompt = fallback_last
    shot.character_prompts_json = fallback_char
    shot.scene_prompt = f"Scene at {scene_location}. Mood: {scene_mood}."  # 新增
    shot.prop_prompts_json = []  # 新增（fallback 无道具）
    db.commit()
```

- [ ] **Step 4: 修改返回值，包含 scene_prompt 和 prop_prompts**

在 `parse_shot_asset_prompts` 函数的两个返回语句中（AI 成功和 fallback），添加新字段：

```python
# AI 成功路径返回值（大约 line 4974-4987）：
            return {
                "shot_id": shot_id,
                "style_preset": style_name,
                "character_prompts": cleaned_char_prompts,
                "scene_prompt": final_scene_prompt,  # 新增
                "prop_prompts": cleaned_prop_prompts,  # 新增
                "storyboard_prompt": final_storyboard,
                "first_frame_prompt": final_first,
                "last_frame_prompt": final_last,
                "video_prompt": final_video,
                "grounding_used": {
                    "shot": shot_grounding,
                    "inheritance_constraints_present": bool(inherited_constraints),
                    "character_count": len(default_character_prompts),
                },
            }

# fallback 路径返回值（大约 line 5009-5022）：
    return {
        "shot_id": shot_id,
        "style_preset": style_name,
        "character_prompts": fallback_char,
        "scene_prompt": f"Scene at {scene_location}. Mood: {scene_mood}.",  # 新增
        "prop_prompts": [],  # 新增
        "storyboard_prompt": fallback_storyboard,
        "first_frame_prompt": fallback_first,
        "last_frame_prompt": fallback_last,
        "video_prompt": fallback_video,
        "grounding_used": {
            "shot": shot_grounding,
            "inheritance_constraints_present": bool(inherited_constraints),
            "character_count": len(default_character_prompts),
        },
    }
```

- [ ] **Step 5: 提交**

```bash
git add backend/routers/video.py
git commit -m "feat: extend parse_shot_asset_prompts to extract scene and prop prompts"
```

---

### Task 3: 后端 API — 新增道具资产生成端点

**Files:**
- Modify: `backend/routers/video.py` (在 `generate_shot_character_asset` 端点后添加)

- [ ] **Step 1: 添加道具资产生成端点**

在 `backend/routers/video.py` 中，找到 `generate_shot_character_asset` 函数的结束位置（大约 line 5104），在其后添加：

```python
@router.post("/api/shots/{shot_id}/prop-assets/generate")
async def generate_shot_prop_asset(
    shot_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """Generate a prop reference asset for a shot."""
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    prop_name = str(body.get("prop_name") or "Prop").strip() or "Prop"
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "Prop prompt is required")

    style_ctx = _resolve_effective_style_for_shot(shot, db, body.get("style_preset"))
    style_name = style_ctx.get("name") or ""
    image_style_params = style_ctx.get("image_style_params") or {}

    chapter_id = shot.scene.chapter_id
    prop_dir = _VIDEO_OUTPUTS_DIR / "prop_refs" / f"chapter_{chapter_id}" / f"shot_{shot_id}"
    prop_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", prop_name)
    file_name = f"{safe_name}_{uuid.uuid4().hex[:8]}.png"
    full_path = prop_dir / file_name

    final_prompt = _merge_style_prompt(prompt, style_ctx.get("prompt_template"), style_name)
    api_key = _user_image_api_key(request)
    _configure_image_service(request, db)

    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=False)

    try:
        await image2_service.generate_reference_image(
            prompt=final_prompt,
            output_path=full_path,
            api_key=api_key or None,
            size=image_style_params.get("size", "1792x1024"),
        )
    except Exception as e:
        logger.warning("Prop reference generation failed (shot=%s, name=%s): %s", shot_id, prop_name, e)
        raise HTTPException(502, f"道具参考图生成失败: {e}")

    relative_path = f"prop_refs/chapter_{chapter_id}/shot_{shot_id}/{file_name}"
    source_asset_ids = body.get("source_asset_ids")
    if not isinstance(source_asset_ids, list):
        source_asset_ids = None

    asset = VideoAsset(
        story_id=shot.scene.chapter.story_id if shot.scene.chapter else None,
        chapter_id=shot.scene.chapter_id,
        scene_id=shot.scene_id,
        shot_id=shot_id,
        asset_type="prop_reference",
        name=f"Prop - {prop_name}",
        file_path=relative_path,
        provider="image2",
        prompt=final_prompt,
        source_asset_ids_json=source_asset_ids,
        style_preset=style_name or None,
    )
    db.add(asset)
    db.commit()
    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=True)
    db.refresh(asset)

    return {
        "shot_id": shot_id,
        "asset": {
            "id": asset.id,
            "name": asset.name,
            "file_path": _to_video_url(asset.file_path),
            "asset_type": asset.asset_type,
            "prompt": asset.prompt,
            "style_preset": asset.style_preset,
            "created_at": _serialize_datetime(asset.created_at),
        },
    }
```

- [ ] **Step 2: 添加场景资产生成端点（shot 级别）**

在道具端点后添加场景资产生成端点：

```python
@router.post("/api/shots/{shot_id}/scene-assets/generate")
async def generate_shot_scene_asset(
    shot_id: int,
    body: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    """Generate a scene reference asset for a shot (shot-level scene, not scene-level concept art)."""
    user = _require_user(request, db)
    shot = db.get(VideoShot, shot_id)
    if not shot:
        raise HTTPException(404, "Shot not found")
    if not shot.scene:
        raise HTTPException(404, "Scene not found")
    _require_chapter_for_user(shot.scene.chapter_id, user, db)

    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        # 使用 shot 上保存的 scene_prompt 作为 fallback
        prompt = shot.scene_prompt or f"Scene at {shot.scene.location or 'unknown'}. Mood: {shot.scene.mood or 'neutral'}."

    style_ctx = _resolve_effective_style_for_shot(shot, db, body.get("style_preset"))
    style_name = style_ctx.get("name") or ""
    image_style_params = style_ctx.get("image_style_params") or {}

    chapter_id = shot.scene.chapter_id
    scene_dir = _VIDEO_OUTPUTS_DIR / "scene_refs" / f"chapter_{chapter_id}" / f"shot_{shot_id}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"scene_{uuid.uuid4().hex[:8]}.png"
    full_path = scene_dir / file_name

    final_prompt = _merge_style_prompt(prompt, style_ctx.get("prompt_template"), style_name)
    api_key = _user_image_api_key(request)
    _configure_image_service(request, db)

    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=False)

    try:
        await image2_service.generate_reference_image(
            prompt=final_prompt,
            output_path=full_path,
            api_key=api_key or None,
            size=image_style_params.get("size", "1792x1024"),
        )
    except Exception as e:
        logger.warning("Scene reference generation failed (shot=%s): %s", shot_id, e)
        raise HTTPException(502, f"场景参考图生成失败: {e}")

    relative_path = f"scene_refs/chapter_{chapter_id}/shot_{shot_id}/{file_name}"
    source_asset_ids = body.get("source_asset_ids")
    if not isinstance(source_asset_ids, list):
        source_asset_ids = None

    asset = VideoAsset(
        story_id=shot.scene.chapter.story_id if shot.scene.chapter else None,
        chapter_id=shot.scene.chapter_id,
        scene_id=shot.scene_id,
        shot_id=shot_id,
        asset_type="scene_reference",
        name=f"Scene - {shot.scene.title or f'Scene {shot.scene.scene_number}'}",
        file_path=relative_path,
        provider="image2",
        prompt=final_prompt,
        source_asset_ids_json=source_asset_ids,
        style_preset=style_name or None,
    )
    db.add(asset)
    db.commit()
    _check_and_consume_quota_wrapper(user.id, "manga.image.monthly_limit", 1, db, deduct=True)
    db.refresh(asset)

    return {
        "shot_id": shot_id,
        "asset": {
            "id": asset.id,
            "name": asset.name,
            "file_path": _to_video_url(asset.file_path),
            "asset_type": asset.asset_type,
            "prompt": asset.prompt,
            "style_preset": asset.style_preset,
            "created_at": _serialize_datetime(asset.created_at),
        },
    }
```

- [ ] **Step 3: 提交**

```bash
git add backend/routers/video.py
git commit -m "feat: add prop and scene asset generation endpoints for shots"
```

---

### Task 4: 后端继承 — 实现场景和道具资产继承函数

**Files:**
- Modify: `backend/routers/video.py` (在 `_select_character_reference_assets_for_scene` 函数后添加)

- [ ] **Step 1: 添加场景资产继承函数**

在 `_select_character_reference_assets_for_scene` 函数后（大约 line 647）添加：

```python
def _select_scene_reference_assets_for_shot(shot: VideoShot, db: Session, limit: int = 3) -> list[VideoAsset]:
    """选择当前 shot 可用的场景参考图资产（继承逻辑）。
    
    优先级：
    1. 当前 shot 自己的 scene_reference 资产
    2. 同 scene_id 下其他 shot 的 scene_reference 资产（最近创建的优先）
    3. Scene 级别的 concept_art_asset_id
    """
    matched: list[VideoAsset] = []
    used_ids: set[int] = set()

    # 第一级：当前 shot 的 scene_reference 资产
    current_assets = (
        db.query(VideoAsset)
        .filter(
            VideoAsset.shot_id == shot.id,
            VideoAsset.asset_type == "scene_reference",
            VideoAsset.status == "active",
        )
        .order_by(VideoAsset.created_at.desc())
        .all()
    )
    for a in current_assets:
        if a.id not in used_ids:
            matched.append(a)
            used_ids.add(a.id)
            if len(matched) >= limit:
                return matched[:limit]

    # 第二级：同 scene_id 下其他 shot 的 scene_reference 资产
    if shot.scene_id:
        sibling_assets = (
            db.query(VideoAsset)
            .filter(
                VideoAsset.scene_id == shot.scene_id,
                VideoAsset.asset_type == "scene_reference",
                VideoAsset.shot_id != shot.id,
                VideoAsset.status == "active",
            )
            .order_by(VideoAsset.created_at.desc())
            .all()
        )
        for a in sibling_assets:
            if a.id not in used_ids:
                matched.append(a)
                used_ids.add(a.id)
                if len(matched) >= limit:
                    return matched[:limit]

    # 第三级：Scene 级别的 concept_art
    if shot.scene and shot.scene.concept_art_asset_id:
        concept_id = shot.scene.concept_art_asset_id
        if concept_id not in used_ids:
            asset = db.get(VideoAsset, concept_id)
            if asset and asset.status == "active":
                matched.append(asset)
                used_ids.add(concept_id)

    return matched[:limit]


def _select_prop_reference_assets_for_shot(shot: VideoShot, db: Session, limit: int = 6) -> list[VideoAsset]:
    """选择当前 shot 可用的道具参考图资产（继承逻辑）。
    
    优先级：
    1. 当前 shot 自己的 prop_reference 资产
    2. 同 scene_id 下其他 shot 的同名 prop_reference 资产
    3. 同 chapter 下其他 shot 的同名 prop_reference 资产
    """
    matched: list[VideoAsset] = []
    used_ids: set[int] = set()

    # 获取当前 shot 的道具名称列表
    prop_names: list[str] = []
    if shot.prop_prompts_json:
        for item in shot.prop_prompts_json:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if name:
                    prop_names.append(name)

    # 第一级：当前 shot 的 prop_reference 资产
    current_assets = (
        db.query(VideoAsset)
        .filter(
            VideoAsset.shot_id == shot.id,
            VideoAsset.asset_type == "prop_reference",
            VideoAsset.status == "active",
        )
        .order_by(VideoAsset.created_at.desc())
        .all()
    )
    for a in current_assets:
        if a.id not in used_ids:
            matched.append(a)
            used_ids.add(a.id)
            if len(matched) >= limit:
                return matched[:limit]

    # 第二级：同 scene_id 下其他 shot 的同名 prop_reference 资产
    if shot.scene_id and prop_names:
        sibling_assets = (
            db.query(VideoAsset)
            .filter(
                VideoAsset.scene_id == shot.scene_id,
                VideoAsset.asset_type == "prop_reference",
                VideoAsset.shot_id != shot.id,
                VideoAsset.status == "active",
            )
            .order_by(VideoAsset.created_at.desc())
            .all()
        )
        for name in prop_names:
            for a in sibling_assets:
                if a.id in used_ids:
                    continue
                if name in (a.name or ""):
                    matched.append(a)
                    used_ids.add(a.id)
                    break
            if len(matched) >= limit:
                return matched[:limit]

    # 第三级：同 chapter 下其他 shot 的同名 prop_reference 资产（兜底）
    chapter_id = shot.scene.chapter_id if shot.scene else None
    if chapter_id and prop_names:
        chapter_assets = (
            db.query(VideoAsset)
            .filter(
                VideoAsset.chapter_id == chapter_id,
                VideoAsset.asset_type == "prop_reference",
                VideoAsset.status == "active",
            )
            .order_by(VideoAsset.created_at.desc())
            .all()
        )
        for name in prop_names:
            for a in chapter_assets:
                if a.id in used_ids:
                    continue
                if name in (a.name or ""):
                    matched.append(a)
                    used_ids.add(a.id)
                    break
            if len(matched) >= limit:
                return matched[:limit]

    return matched[:limit]
```

- [ ] **Step 2: 修改 listVideoAssets 端点，支持 prop_reference 类型**

在 `backend/routers/video.py` 中找到 `list_video_assets` 函数（或类似功能的端点），确保 `prop_reference` 和 `scene_reference` 类型在查询时被包含。

查找函数位置：

```bash
Select-String -Path "backend\routers\video.py" -Pattern "list.*video.*assets|video_assets.*list" -Context 0,5
```

- [ ] **Step 3: 提交**

```bash
git add backend/routers/video.py
git commit -m "feat: add scene and prop asset inheritance functions"
```

---

### Task 5: 前端类型 — 扩展 ShotAssetPromptDraft 和 API 函数

**Files:**
- Modify: `frontend/src/api.ts:2826-2834` (ShotAssetPromptDraft 类型)
- Modify: `frontend/src/api.ts:2851-2865` (添加新 API 函数)

- [ ] **Step 1: 扩展 ShotAssetPromptDraft 类型**

在 `frontend/src/api.ts` 中找到 `ShotAssetPromptDraft` 接口，添加 `scene_prompt` 和 `prop_prompts` 字段：

```typescript
export interface ShotAssetPromptDraft {
  shot_id: number;
  style_preset: string;
  character_prompts: Array<{ name: string; prompt: string }>;
  scene_prompt: string;  // 新增
  prop_prompts: Array<{ name: string; prompt: string }>;  // 新增
  storyboard_prompt: string;
  first_frame_prompt: string;
  last_frame_prompt: string;
  video_prompt: string;
}
```

- [ ] **Step 2: 添加道具资产生成 API 函数**

在 `generateShotCharacterAsset` 函数后添加：

```typescript
export async function generateShotPropAsset(shotId: number, payload: {
  prop_name: string;
  prompt: string;
  style_preset?: string;
  reference_asset_ids?: number[];
  source_asset_ids?: number[];
}): Promise<VideoAsset> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/prop-assets/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
```

- [ ] **Step 3: 添加场景资产生成 API 函数**

在道具函数后添加：

```typescript
export async function generateShotSceneAsset(shotId: number, payload: {
  prompt: string;
  style_preset?: string;
  reference_asset_ids?: number[];
  source_asset_ids?: number[];
}): Promise<VideoAsset> {
  const res = await fetch(`${BASE}/api/shots/${shotId}/scene-assets/generate`, {
    method: 'POST',
    headers: apiHeaders(true),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
```

- [ ] **Step 4: 提交**

```bash
git add frontend/src/api.ts
git commit -m "feat: extend ShotAssetPromptDraft and add scene/prop asset API functions"
```

---

### Task 6: 前端组件 — 在 ShotRow 中新增场景和道具卡片

**Files:**
- Modify: `frontend/src/components/VideoStoryboardPanel.tsx:637-909` (ShotRow 组件)

- [ ] **Step 1: 在 ShotRow 组件中添加场景和道具相关的 props**

在 `ShotRow` 组件的 props 接口中添加新的回调函数：

```typescript
function ShotRow({
  shot,
  checked,
  chapterAssets,
  onCheckToggle,
  onViewAsset,
  onRedrawAsset,
  onDeleteAsset,
  onReplaceAsset,
  onGenerateVideo,
  onAnalyzeSingleShot,
  onGenerateCharacterAsset,
  onGenerateShotStoryboard,
  onOpenAssetWorkbench,
  onDirectDeleteAsset,
  deletingAssetId,
  onGenerateSceneAsset,    // 新增
  onGeneratePropAsset,     // 新增
}: {
  shot: EnrichedShot;
  checked: boolean;
  chapterAssets: VideoAsset[];
  onCheckToggle: (id: number) => void;
  onViewAsset: (asset: VideoAsset) => void;
  onRedrawAsset: (asset: VideoAsset) => void;
  onDeleteAsset: (shotId: number, assetId: number) => void;
  onReplaceAsset: (shotId: number, assetId: number) => void;
  onGenerateVideo: (shotId: number, referenceAssetIds: number[]) => void;
  onAnalyzeSingleShot: (shotId: number) => void;
  onGenerateCharacterAsset: (shotId: number, characterName: string, prompt: string) => Promise<void>;
  onGenerateShotStoryboard: (shotId: number, referenceAssetIds?: number[]) => Promise<void>;
  onOpenAssetWorkbench?: (items: WorkbenchItem[], title: string, refAssets?: VideoAsset[], refIds?: number[], onRefChange?: (ids: number[]) => void, shotId?: number) => void;
  onDirectDeleteAsset?: (shotId: number, assetId: number) => void;
  deletingAssetId?: number | null;
  onGenerateSceneAsset?: (shotId: number, prompt: string) => Promise<void>;    // 新增
  onGeneratePropAsset?: (shotId: number, propName: string, prompt: string) => Promise<void>;  // 新增
}) {
```

- [ ] **Step 2: 在 ShotRow 中添加场景资产的 useMemo 计算**

在 `charAssets` 的 useMemo 后添加场景和道具资产的计算：

```typescript
  // 场景资产（当前 shot + 同 scene 继承）
  const sceneAssets = useMemo(() => {
    const isSceneAsset = (a: any) => a.asset_type === 'scene_reference';
    const currentShotScenes = chapterAssets.filter(a => a.shot_id === shotId && isSceneAsset(a));
    // 继承同 scene_id 的其他 shot 的场景资产
    const sceneId = shot.scene_id;
    const inheritedScenes = sceneId
      ? chapterAssets.filter(a => a.shot_id !== shotId && a.scene_id === sceneId && isSceneAsset(a))
      : [];
    // 去重
    const seen = new Set(currentShotScenes.map(a => a.id));
    const result = [...currentShotScenes];
    for (const a of inheritedScenes) {
      if (!seen.has(a.id)) {
        result.push(a);
        seen.add(a.id);
      }
    }
    return result;
  }, [chapterAssets, shotId, shot.scene_id]);

  // 道具资产（当前 shot + 同名继承）
  const propAssets = useMemo(() => {
    const isPropAsset = (a: any) => a.asset_type === 'prop_reference';
    const currentShotProps = chapterAssets.filter(a => a.shot_id === shotId && isPropAsset(a));
    // 获取当前 shot 的道具名称
    const propNames = (shot.promptDraft?.prop_prompts || []).map(p => p.name);
    if (propNames.length === 0) return currentShotProps;
    // 继承同 chapter 下其他 shot 的同名道具资产
    const normalizedNames = new Set(propNames.map(n => n.trim().toLowerCase()));
    const inheritedProps = chapterAssets.filter(a =>
      a.shot_id !== shotId && isPropAsset(a) &&
      normalizedNames.has((a.name || '').replace(/^Prop\s*-\s*/i, '').trim().toLowerCase())
    );
    // 去重
    const seen = new Set(currentShotProps.map(a => a.id));
    const result = [...currentShotProps];
    for (const a of inheritedProps) {
      if (!seen.has(a.id)) {
        result.push(a);
        seen.add(a.id);
      }
    }
    return result;
  }, [chapterAssets, shotId, shot.promptDraft?.prop_prompts]);
```

- [ ] **Step 3: 在展开区的 grid 布局中添加场景和道具卡片**

在 `ShotRow` 的展开区（`{expanded && (...)}` 部分），找到现有的两个 `AssetCard3` 组件（角色资产和故事版），在其后添加场景和道具卡片：

```typescript
            {/* ③ 场景资产 */}
            <AssetCard3
              title="🏠 场景资产"
              assets={sceneAssets}
              placeholders={
                hasPromptDraft && shot.promptDraft?.scene_prompt
                  ? [{
                      key: 'scene',
                      label: '场景环境',
                      prompt: shot.promptDraft.scene_prompt,
                      hasAsset: sceneAssets.some(a => a.asset_type === 'scene_reference'),
                      isGenerating: false, // 可以后续扩展
                      onGenerate: onGenerateSceneAsset
                        ? async (p: string) => { await onGenerateSceneAsset(shotId, p); }
                        : undefined,
                    }]
                  : [{ key: 'no_scene', label: '待分析场景', prompt: '', hasAsset: false, isGenerating: false }]
              }
              onViewAsset={onViewAsset}
              onRedrawAsset={onRedrawAsset}
              onDeleteAsset={(aid: number) => onDeleteAsset(shotId, aid)}
              onReplaceAsset={(aid: number) => onReplaceAsset(shotId, aid)}
              onOpenWorkbench={onOpenAssetWorkbench}
              _refAssets={chapterAssets}
              _refIds={selectedRefIds}
              _onRefChange={setSelectedRefIds}
              _shotId={shotId}
              onDirectDeleteAsset={onDirectDeleteAsset ? (aid: number) => onDirectDeleteAsset(shotId, aid) : undefined}
              deletingAssetId={deletingAssetId}
            />

            {/* ④ 道具资产 */}
            <AssetCard3
              title="🎒 道具资产"
              assets={propAssets}
              placeholders={
                hasPromptDraft && shot.promptDraft?.prop_prompts && shot.promptDraft.prop_prompts.length > 0
                  ? shot.promptDraft.prop_prompts.map(pp => ({
                      key: pp.name,
                      label: pp.name,
                      prompt: pp.prompt,
                      hasAsset: propAssets.some(a => {
                        const assetPropName = (a.name || '').replace(/^Prop\s*-\s*/i, '').trim().toLowerCase();
                        return assetPropName === pp.name.trim().toLowerCase();
                      }),
                      isGenerating: false, // 可以后续扩展
                      onGenerate: onGeneratePropAsset
                        ? async (p: string) => { await onGeneratePropAsset(shotId, pp.name, p); }
                        : undefined,
                    }))
                  : [{ key: 'no_props', label: '待分析道具', prompt: '', hasAsset: false, isGenerating: false }]
              }
              onViewAsset={onViewAsset}
              onRedrawAsset={onRedrawAsset}
              onDeleteAsset={(aid: number) => onDeleteAsset(shotId, aid)}
              onReplaceAsset={(aid: number) => onReplaceAsset(shotId, aid)}
              onOpenWorkbench={onOpenAssetWorkbench}
              _refAssets={chapterAssets}
              _refIds={selectedRefIds}
              _onRefChange={setSelectedRefIds}
              _shotId={shotId}
              onDirectDeleteAsset={onDirectDeleteAsset ? (aid: number) => onDirectDeleteAsset(shotId, aid) : undefined}
              deletingAssetId={deletingAssetId}
            />
```

- [ ] **Step 4: 修改 grid 布局为 2 列以容纳 4 个卡片**

将展开区的 grid 布局从 `grid-cols-1 md:grid-cols-2` 改为支持更多卡片：

```typescript
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
```

这个布局已经支持 2 列，4 个卡片会自动换行，无需修改。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/VideoStoryboardPanel.tsx
git commit -m "feat: add scene and prop asset cards in ShotRow expanded view"
```

---

### Task 7: 前端集成 — 传递新增的回调函数

**Files:**
- Modify: `frontend/src/components/VideoStoryboardPanel.tsx:915-939` (主面板组件)
- Modify: `frontend/src/components/VideoStoryboardLayout.tsx` (布局组件，传递回调)

- [ ] **Step 1: 在 VideoStoryboardPanelProps 中添加新的回调**

在 `VideoStoryboardPanelProps` 接口中添加：

```typescript
interface VideoStoryboardPanelProps {
  // ... 现有 props ...
  onGenerateSceneAsset?: (shotId: number, prompt: string) => Promise<void>;    // 新增
  onGeneratePropAsset?: (shotId: number, propName: string, prompt: string) => Promise<void>;  // 新增
}
```

- [ ] **Step 2: 在主面板组件中传递新 props 到 ShotRow**

在 `VideoStoryboardPanel` 组件的 `ShotRow` 调用处添加新 props：

```typescript
<ShotRow
  // ... 现有 props ...
  onGenerateSceneAsset={onGenerateSceneAsset}
  onGeneratePropAsset={onGeneratePropAsset}
/>
```

- [ ] **Step 3: 在 VideoStoryboardLayout 中实现回调函数并传递**

在 `VideoStoryboardLayout.tsx` 中找到调用 `VideoStoryboardPanel` 的位置，添加场景和道具资产生成的实现：

```typescript
const handleGenerateSceneAsset = useCallback(async (shotId: number, prompt: string) => {
  try {
    await generateShotSceneAsset(shotId, { prompt });
    toast.success('场景参考图已生成');
    await loadChapterAssets(); // 刷新资产列表
  } catch (err: any) {
    toast.error(`场景图生成失败: ${err.message}`);
  }
}, [loadChapterAssets]);

const handleGeneratePropAsset = useCallback(async (shotId: number, propName: string, prompt: string) => {
  try {
    await generateShotPropAsset(shotId, { prop_name: propName, prompt });
    toast.success(`道具「${propName}」参考图已生成`);
    await loadChapterAssets(); // 刷新资产列表
  } catch (err: any) {
    toast.error(`道具图生成失败: ${err.message}`);
  }
}, [loadChapterAssets]);

// 在 VideoStoryboardPanel 调用处传递
<VideoStoryboardPanel
  // ... 现有 props ...
  onGenerateSceneAsset={handleGenerateSceneAsset}
  onGeneratePropAsset={handleGeneratePropAsset}
/>
```

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/VideoStoryboardPanel.tsx frontend/src/components/VideoStoryboardLayout.tsx
git commit -m "feat: wire up scene and prop asset generation callbacks"
```

---

### Task 8: 验证与测试

- [ ] **Step 1: 启动后端，验证模型迁移**

```bash
cd backend
python main.py
```

检查日志中是否有 `_migrate()` 相关的 DDL 执行信息，确认 `scene_prompt` 和 `prop_prompts_json` 字段已添加到 `video_shots` 表。

- [ ] **Step 2: 测试 AI 提取端点**

```bash
# 替换 {shot_id} 为实际的 shot ID
curl -X POST http://localhost:8000/api/shots/{shot_id}/asset-prompts/parse \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {token}" \
  -d '{"style_preset": "日式动漫风"}'
```

验证返回结果中包含 `scene_prompt` 和 `prop_prompts` 字段。

- [ ] **Step 3: 测试道具资产生成端点**

```bash
curl -X POST http://localhost:8000/api/shots/{shot_id}/prop-assets/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {token}" \
  -d '{"prop_name": "Ancient Sword", "prompt": "A weathered double-edged sword with ornate golden hilt"}'
```

- [ ] **Step 4: 测试场景资产生成端点**

```bash
curl -X POST http://localhost:8000/api/shots/{shot_id}/scene-assets/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer {token}" \
  -d '{"prompt": "A dimly lit medieval tavern with wooden beams and candlelight"}'
```

- [ ] **Step 5: 启动前端，验证 UI**

```bash
cd frontend
npm run dev
```

1. 进入视频工作区
2. 生成分镜后展开任意分镜
3. 验证展开区显示 4 个卡片：👤 角色资产、🎬 故事版、🏠 场景资产、🎒 道具资产
4. 点击「分析提示词」后，场景和道具卡片应显示占位符
5. 点击占位符的生成按钮，应成功生成参考图

- [ ] **Step 6: 验证继承机制**

1. 为某个分镜生成场景图
2. 展开同一场景下的另一个分镜
3. 验证该分镜的场景卡片中显示了继承的场景图

- [ ] **Step 7: 最终提交**

```bash
git add -A
git commit -m "feat: complete scene and prop cards for storyboard consistency"
```

---

## 注意事项

1. **数据库迁移**：新增字段通过 `_migrate()` 自动执行 ALTER TABLE，无需手动迁移
2. **资产类型**：道具使用 `prop_reference`，场景使用 `scene_reference`（与现有概念图共用类型，但通过 `shot_id` 区分来源）
3. **继承逻辑**：场景继承同 `scene_id`，道具继承同名（忽略 `Prop - ` 前缀）
4. **配额扣减**：道具和场景生成都走 `manga.image.monthly_limit` 配额
5. **故事版引用**：按用户选择，故事版渲染不自动引用场景/道具，用户通过「参考资产」按钮手动选择
