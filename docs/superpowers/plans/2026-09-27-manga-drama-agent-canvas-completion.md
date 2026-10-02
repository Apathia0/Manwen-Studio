# 漫剧 Agent 自动化画布完整性实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让漫剧画布支持从一句话或可信剧本来源开始，经过剧本、拆分、导演、资产、分镜图、视频和合片的可恢复自动化流程，同时保证多节点、多连线下的输入、参考图和版本传递正确。

**Architecture:** 保留现有画布 JSON 版本快照、`definition_revision` 乐观锁和 `VideoCanvasRun` 后台运行模型。将生成链统一为一个严格但可修复的导演质量入口；将边作为执行真源，并在每次图变更后从边重算引用快照；将 Agent 的跨阶段推进从前端重新发消息的隐式机制提升为后端持久化阶段状态机，前端只负责展示、审批和恢复。

**Tech Stack:** Python 3.10+、FastAPI、SQLAlchemy 2、pytest、React 19、TypeScript、Vite、Vitest、Tailwind CSS v4、现有 DeepSeek/Image2/视频 API 适配层。

## Global Constraints

- 所有文本文件以 UTF-8 无 BOM 编码创建或编辑；编辑前检查 BOM，发现 BOM 或疑似非 UTF-8 时停止。
- 不得使用 `as any`、`@ts-ignore`、`@ts-expect-error`。
- 用户生成图片的 React 回显统一使用 `frontend/src/components/shared/MediaImage.tsx`；必须绑定 ref 的场景补 `img.decode()` 门控。
- 视频图生视频参考图使用 `input_reference` 管道符格式；公网 URL 不可用时必须明确失败，不能静默退化为无参考图。
- 画布保存使用 `definition_revision` 乐观锁；任何阶段不能覆盖审批后用户的新版本。
- 不使用 `rsync --delete`、`git clean -fdx`、`docker compose down -v`，不删除 `backend/manga_outputs/` 或 `backend/video_outputs/`。
- 任何付费生成都必须通过现有 `VideoCanvasRun`、计费预留、幂等键和取消机制。
- Agent 的 `plan`/`ask`/`auto` 权限语义保持不变；模型不能自行提升权限。
- 每项任务先写失败测试，再写最小实现，再运行针对性测试；不要用删除测试或放宽断言来消除失败。
- 不在本计划执行期间提交 Git commit；执行阶段如用户明确要求提交，再按仓库 Git 流程单独处理。

## 当前基线与验收目标

已核验基线：直接执行 `pytest -k canvas` 会在收集阶段被仓库现有的 `backend/test-output.txt` 编码文件和缺失的 `prompts.video_analysis` 模块阻断；隔离运行核心画布测试通过（本次定点集合 173 passed，扩大到导演/运行时/图/恢复/剧本保真集合 191 passed）。在 `frontend/` 中执行 `npm run build` 的 `tsc -b` 失败 24 项，错误全部落在 `src/components/novel-autopilot/`，根因是该目录引用了 `api.ts` 中不存在的类型/API，画布和 AgentPanel 未产生同类类型错误。生产导演入口已核实为 `canvas_director_quality.direct`，旧的 `orchestrate_scene_video_units` 仅由测试调用；画布 Agent 现有 8 个阶段，但后台生成完成后的续接尚未由服务端 callback 创建下一阶段 action，当前仍主要由 `AgentPanel.tsx` 轮询后重新发送 `canvas_resume_run_id` 驱动。

在执行 Task 1 前先完成测试收集基线清理：确认 `backend/test-output.txt` 不再被 pytest 当作测试模块读取，并补齐或移除 `prompts.video_analysis` 的错误测试引用（不得通过忽略整个测试目录来伪造通过）。之后分别记录“全量测试”和“画布定点测试”的真实命令与结果；若全量基线仍有与本分支无关的失败，必须在验收报告中单列，不能继续使用未经说明的 `pytest -k canvas` 通过数。

完成后必须满足：

1. `frontend` 的 `npm run build` 和 `npm run lint` 通过。
2. 画布端到端模拟测试覆盖：一句话剧本 → 拆分 → 导演 → 资产分析 → 资产出图 → 编译 → 分镜出图 → 视频 → 合片；外部模型和 OSS 使用 fake adapter，不产生真实费用。
3. 删除边、替换上游图片、删除节点、重新生成和复制节点后，运行时不会使用过期或已断开的引用；复制配置与复制已生成结果的语义必须明确区分。
4. 多父、多子、容器展开、菱形依赖和 concat 顺序在前后端结果一致；冻结版本在 runtime 执行前仍会校验端口和输出能力，不会把缺失上游静默当成空输入。
5. 视频节点实际收到角色/场景/道具/风格/分镜参考图的受控集合，超过模型能力或平台上限时在计费和提交前失败并说明原因；seed 和 `input_mode` 的支持/忽略状态可追溯。
6. Agent 在 `auto` 模式可由后端持久化状态推进后台阶段；进程重启、浏览器关闭或 SSE 断开后可从 `VideoCanvasRun` 恢复，不重复扣费或提交上游任务。SSE 和前端轮询只能展示/触发幂等恢复，不能是唯一状态机。
7. Agent 能在没有预先打开画布时创建漫剧项目和画布；已有项目仍遵循所有权与幂等校验。
8. 生成结果在产品层明确标为技术完成、待创作审阅；无法把技术成功描述成质量已通过。

### 评审复核结论（执行依据）

| 评审判断 | 复核结论 | 计划中的处理 |
| --- | --- | --- |
| `novel-autopilot` 阻断生产构建 | 确认。`frontend/npm run build` 的 24 条 `tsc` 错误均在该目录，根因是缺失 `api.ts` 合约；不是画布/AgentPanel 类型错误 | Task 1 先恢复真实 API 合约，不用占位导出掩盖问题 |
| 参考图删除/替换后仍残留 | 确认。`canvasReferenceSync.ts` 只追加，删除节点/边路径没有 reconcile | Task 3 改为按当前有效边重算，并区分边派生引用与手动引用 |
| 复制节点连同连线一起复制 | 不完全成立。单节点 Duplicate 不复制边，多节点粘贴只保留选区内部边；但复制已生成节点会原样带 `asset_id`，runtime 可能复用旧结果 | Task 3 明确“复制配置”与“复制结果”，默认清除生成结果/运行元数据，结果复用必须显式操作 |
| runtime 不区分端口、无产出静默跳过 | 部分成立。图保存校验已有端口规则，但 runtime `_node_inputs` 未再次按端口校验，缺失 output 会 `continue`；legacy 无输出节点也缺少执行语义 | Task 3 在冻结图执行前增加端口/输出校验和可见 blocked 错误 |
| 角色资产只按名字绑定 | 部分成立。角色有名字匹配，但场景/道具也可能按 `scene_ids` 过宽绑定；真正风险是绑定泛化和参考图泛滥 | Task 4 按角色/场景/beat/道具引用建立确定性选择策略 |
| 画布没有最多 9 张参考图保护 | 确认。传统路径有校验，画布 `_configured_reference_inputs`/`_external_video_reference_urls` 没有统一平台上限 | Task 3/4 在计费前按 `min(9, model_limit)` 拒绝超限 |
| 生产导演走旧 `orchestrate_scene_video_units` | 不成立。生产 `/director-plan` 调用 `canvas_director_quality.direct`；旧函数目前仅测试调用 | Task 2 不做无依据的入口替换，改为保护生产入口、收敛单帧规则、隔离 legacy 并补路由级测试 |
| Agent 完全没有阶段工具 | 不成立。8 个 `canvas_stage` 阶段均已接通；真正缺口是后台 callback 不创建下一阶段 action，当前依赖前端轮询+resume 消息 | Task 5 把续接提升为服务端持久化状态机，并补项目创建工具 |
| 合片有自动画质评估 | 未发现。当前只输出 `technical_pass_needs_creative_review` | Task 6/7 保持“技术完成/待创作审阅”边界，后续另建质量评估能力 |

---

## Task 1: 修复当前前端构建基线

**目的：** 先恢复可构建状态，避免后续画布改动被无关的未接入 novel-autopilot 组件阻断。

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/novel-autopilot/ChapterGoalCardDrawer.tsx`
- Modify: `frontend/src/components/novel-autopilot/ConsistencyCheckPanel.tsx`
- Modify: `frontend/src/components/novel-autopilot/CreativeModePanel.tsx`
- Modify: `frontend/src/components/novel-autopilot/OpeningPlanPanel.tsx`
- Modify: `frontend/src/components/novel-autopilot/PublishingPanel.tsx`
- Modify: `frontend/src/components/novel-autopilot/VolumePanel.tsx`
- Modify or create: the corresponding backend API routes only if the component contract is intended to be live; do not add fake exports that return invented data.
- Test: `frontend` TypeScript build and focused Vitest tests for serialization helpers.

**Interfaces:**
- `api.ts` must export the exact response types and functions imported by the six components, or the components must be changed to the existing API contract.
- No component may use an untyped `any` escape hatch.

- [ ] **Step 1: Record every missing symbol and its intended backend endpoint.**

  Run:

  ```powershell
  cd frontend
  npx tsc -b --pretty false
  ```

  Capture the 24 diagnostics, then locate the corresponding route definitions in `backend/main.py`, `backend/routers`, and `frontend/src/api.ts`. For each symbol choose one evidence-based path: connect it to an existing endpoint, or remove the unreachable UI import and route from the active bundle.

- [ ] **Step 2: Add focused type/API tests before implementation.**

  Test the request/response shape for each connected endpoint with a mocked `fetch`, including non-2xx error parsing. Assert that no function returns an untyped object.

- [ ] **Step 3: Implement the smallest contract-aligned changes.**

  Keep API functions beside the existing API client conventions. If an autopilot component has no registered backend route, hide it from active rendering until a real route exists; do not create a placeholder function that reports success.

- [ ] **Step 4: Verify the baseline.**

  Run:

  ```powershell
  npm run build
  npm run lint
  npm run test -- --run
  ```

  Expected: all commands exit 0. If unrelated pre-existing diagnostics remain, stop and resolve them before proceeding to canvas work.

---

## Task 2: Establish one authoritative canvas director pipeline

**目的：** 消除严格导演与旧的自动修复导演两套规则冲突，统一分镜图为干净单帧起始画面、视频为连续时间轴，并让可修复错误自动修复、不可修复错误明确返回。

**Files:**
- Modify: `backend/services/canvas_director_quality.py`
- Modify: `backend/services/video_canvas_director.py`
- Modify: `backend/routers/video_canvas.py:1693-1744`
- Modify: `backend/services/screenplay_adapt.py:277-370`
- Modify: `backend/services/agent_service.py:5974-6008`
- Test: `backend/tests/test_canvas_director_quality.py`
- Test: `backend/tests/test_video_canvas_director.py`
- Create: `backend/tests/test_canvas_director_end_to_end.py`

**Interfaces:**
- Keep `canvas_director_quality.direct(scenes, policy, *, api_key=None, user_constraints=None, **source_meta) -> dict` as the only production director entry.
- Keep `validate_plan(...) -> list[str]` pure: it reports errors and does not mutate the caller's input.
- Keep `compile_video_prompt(unit) -> str` as the sole video prompt compiler.
- The plan must contain `plan_version=2`, `storyboard_prompt`, `storyboard_json.segments`, `duration_seconds`, `beat_ids`, source hashes and continuity fields.

- [ ] **Step 1: Add failing regression tests for the rule conflict.**

  Add tests asserting:

  ```python
  def test_canvas_storyboard_is_clean_single_frame():
      result = asyncio.run(direct(SCENES, POLICY))
      assert result["production_policy"]["reference_mode"] == "clean_single_frame"
      assert "多格" not in result["units"][0]["storyboard_prompt"]
      assert "时间标注" not in result["units"][0]["storyboard_prompt"]

  def test_director_repairs_missing_prompt_but_rejects_unrepresentable_dialogue():
      ...
  ```

  The second test must use a fake DeepSeek response and assert that one recoverable missing field becomes a warning, while dialogue that cannot fit the model's maximum duration returns `UpstreamServiceError` with `code="canvas_director_quality_failed"` and diagnostics.

- [ ] **Step 2: Remove the old multi-grid production requirement from the active canvas path.**

  The production prompt and quality validator must agree: the storyboard image is one clean starting frame; the time axis stays in `storyboard_json` and `video_prompt`. Keep old `video_canvas_director.py` multi-grid helpers only for legacy callers if they are still referenced, but ensure `create_director_plan` cannot select them.

- [ ] **Step 3: Make the director repair loop deterministic and able to request re-splitting.**

  The production director may retry the model at most twice for locally repairable schema errors. Normalize duplicate IDs or missing prompts only when source beats, source dialogue, order and duration remain intact; never invent a new beat or silently drop original dialogue. When `minimum_seconds(beats) > max(policy.duration_options)`, return a structured `canvas_director_quality_failed` diagnostic containing the offending `scene_id`, `beat_ids`, required duration and suggested split boundary. Add a bounded re-split loop at the stage boundary: it may return the long beat to screenplay split once, persist the revised source hash, invalidate the old scene/director/compile descendants, and require approval again. It must not silently shorten dialogue or mutate the source screenplay.

- [ ] **Step 4: Enforce the scene approval contract.**

  `split` must persist `approved=false` and return `awaiting_scene_approval`. `director`, `assets` and `compile` must reject an unapproved scene with a structured approval-required error. If `auto` mode is allowed to approve automatically, that approval must be an explicit, persisted authorization event shown in the Agent/UI audit trail; it must not be an implicit `config["approved"] = True` side effect of entering a later stage.

- [ ] **Step 5: Add screenplay quality checks before stage submission.**

  `draft_screenplay` must validate scene headers, action, dialogue and minimum content without claiming the screenplay is production-ready. `screenplay_split` must preserve `content_hash`, source spans and all source dialogue. Return a non-destructive quality report (missing scene purpose, unclear actor, long dialogue, spatial discontinuity, over-capacity action) so the Agent can ask for clarification instead of proceeding with an incomplete script. The report must never rewrite the preserved source text.

- [ ] **Step 6: Run focused backend verification.**

  ```powershell
  cd backend
  python -m pytest tests/test_canvas_director_quality.py tests/test_video_canvas_director.py tests/test_canvas_stage_gateway.py -q
  ```

  Expected: all existing and new tests pass, including the two previously conflicting storyboard semantics.

---

## Task 3: Make graph inputs and reference assets edge-correct

**目的：** 让边真正决定输入；避免删线残留引用、重复旧图、端口混流、静默跳过和参考图超过上限。

**Files:**
- Modify: `backend/services/video_canvas_runtime.py:138-163,296-423,724-727`
- Modify: `backend/routers/video_canvas.py` graph validation and run planning sections
- Modify: `backend/services/canvas_stage_gateway.py:80-98,234-249`
- Modify: `frontend/src/components/video-canvas/canvasReferenceSync.ts`
- Modify: `frontend/src/components/VideoCanvasPanel.tsx:876-923`
- Modify: `frontend/src/components/video-canvas/CanvasEditorSurface.tsx`
- Modify: `frontend/src/components/shared/MediaImage.tsx` only if the shared contract needs an additional prop; otherwise leave it unchanged.
- Test: `backend/tests/test_video_canvas_graph.py`
- Test: `backend/tests/test_video_canvas_runtime.py`
- Test: `backend/tests/test_canvas_stage_gateway.py`
- Test: `frontend/src/components/video-canvas/canvasReferenceSync.test.ts`
- Create: `backend/tests/test_canvas_reference_propagation.py`

**Interfaces:**
- Introduce a pure backend helper with an explicit port-aware result, for example:

  ```python
  def resolve_node_inputs(
      graph: dict[str, Any],
      node_id: str,
      outputs: dict[str, dict[str, Any]],
  ) -> dict[str, list[dict[str, Any]]]:
      ...
  ```

  It must group values by `targetHandle`, expand containers recursively with cycle protection, preserve `sequence`, and reject an active incoming edge whose upstream output is unavailable.

- Introduce a pure frontend helper with replacement semantics:

  ```ts
  export function syncCanvasMediaReferences(
    nodes: CanvasReferenceNode[],
    edges: CanvasReferenceEdge[],
    assets: CanvasReferenceAsset[],
  ): CanvasReferenceNode[];
  ```

  Its output must recompute `reference_asset_ids`, previews and revisions from active incoming edges, while retaining only explicit manually selected references that are still valid.

- [ ] **Step 1: Add failing propagation tests.**

  Cover these exact cases:

  ```python
  def test_deleted_edge_removes_reference_from_target(): ...
  def test_replaced_upstream_output_does_not_keep_old_asset(): ...
  def test_port_inputs_do_not_mix_prompt_and_image_values(): ...
  def test_missing_active_upstream_output_blocks_target(): ...
  def test_container_and_nested_container_expand_once(): ...
  def test_more_than_nine_video_references_is_rejected_before_submission(): ...
  ```

  In TypeScript add equivalent tests for deletion, replacement, duplicate edges and disabled edges.

- [ ] **Step 2: Implement port-aware input resolution.**

  Replace the current single flat list behavior with a result grouped by `targetHandle`. `prompt`/`text` values may feed prompt consumers; `image`/`references` values may feed image consumers; concat consumes only `videos`. Validate the frozen graph again immediately before execution, including source output declaration, source/target handle compatibility, executable status and disabled edges. An active edge whose upstream output is absent must produce a blocked/failed node with source and target IDs; it may not be silently omitted. Preserve fan-out by reading the same immutable upstream output for each child, and expand containers recursively with cycle protection while retaining edge sequence.

- [ ] **Step 3: Recompute frontend reference snapshots after every graph mutation.**

  On create, delete, replace, duplicate, import, container membership change and load, call the pure synchronizer with the complete current `nodes`, `edges` and asset list. Do not append references incrementally. Track provenance for `edge-derived` versus explicit manual references; reconcile only edge-derived entries that are no longer reachable and retain manual entries that still pass ownership/asset validation. When duplicating a generated media node, default to a clean configuration: clear `result`, `asset_id`, output URL, provider job, billing and run-specific metadata. If the UI offers “reuse result”, it must be a separate explicit action with an ownership-checked asset reference and a visible reused marker.

- [ ] **Step 4: Enforce reference limits and useful errors.**

  Resolve model capability `max_reference_images`, apply the platform maximum of 9, de-duplicate by asset ID/URL, and fail before billing, OSS upload or upstream submission. Include target node ID, count, allowed limit, selected references and discarded/reason reasons in the error payload and run snapshot. Missing active outputs must become a blocked node with a reason visible in run status; a missing asset name/role match must be actionable rather than silently ignored.

- [ ] **Step 5: Verify media rendering compliance.**

  Replace the raw generated-media `<img>` in `VideoCanvasPanel.tsx:175` and the canvas surface generated-media preview in `CanvasEditorSurface.tsx:273` with `MediaImage`, unless a ref requirement makes that impossible. If a ref is required, retain explicit `decode()` gating and a failure placeholder. Add a source search assertion or lint rule for raw `<img>` in canvas-generated-media paths.

- [ ] **Step 6: Run focused verification.**

  ```powershell
  cd backend
  python -m pytest tests/test_video_canvas_graph.py tests/test_video_canvas_runtime.py tests/test_canvas_stage_gateway.py tests/test_canvas_reference_propagation.py -q
  cd ..\frontend
  npm run test -- --run src/components/video-canvas/canvasReferenceSync.test.ts
  npm run build
  ```

---

## Task 4: Complete asset-to-video consistency propagation

**目的：** 角色、场景、道具、风格和分镜参考图在图像生成和视频提交中保持同一组可验证来源。

**Files:**
- Modify: `backend/services/video_canvas_runtime.py:839-916`
- Modify: `backend/services/video_generation.py:61-98`
- Modify: `backend/services/video_provider_router.py`
- Modify: `backend/services/video_adapter.py`
- Modify: `backend/services/video_api.py:182-234,355-397,619-630`
- Modify: `backend/services/visual_asset_generation.py` only if the role contract needs explicit metadata.
- Modify: `backend/models.py` only if a persisted reference snapshot or seed field is required by the existing schema; prefer `input_snapshot_json` when sufficient.
- Test: `backend/tests/test_video_canvas_runtime.py`
- Test: `backend/tests/test_canvas_director_quality.py`
- Create: `backend/tests/test_canvas_video_reference_contract.py`

**Interfaces:**
- `submit_video_job` and every provider adapter must accept and forward `input_mode`, `reference_images`, `seed` where the provider supports them.
- Canvas runtime must call the provider with `input_mode="image_to_video"` whenever the resolved reference list is non-empty; otherwise use `text_to_video`.
- Persist the exact submitted reference URLs/asset IDs in `VideoCanvasRunNode.input_snapshot_json` before upstream submission.

- [ ] **Step 1: Add failing provider contract tests.**

  Assert the fake provider receives:

  ```python
  {
      "input_mode": "image_to_video",
      "reference_images": ["https://oss.example/a.png", "https://oss.example/b.png"],
      "seed": 123,
  }
  ```

  Also assert an empty reference list produces `text_to_video`, and ComfyUI receives the same mode rather than relying on a default.

- [ ] **Step 2: Wire explicit input mode and seed through all layers.**

  Keep backward-compatible defaults in public functions, but pass explicit values from canvas runtime. Freeze `seed` in the node config and `input_snapshot_json` before submission; pass it through `submit_video_job`, every provider adapter and the final upstream payload where supported. Do not invent seed semantics for providers that do not support it: record `seed_requested`, `seed_forwarded`, `seed_supported` and a warning in the output snapshot. Whenever references are non-empty, pass `input_mode="image_to_video"`; otherwise pass `text_to_video` explicitly, including to ComfyUI/provider-router paths.

- [ ] **Step 3: Build a deterministic reference selection policy.**

  For a storyboard image: bind character references by stable character identity/explicit beat mention, scene references by source scene, and props only when the beat/action identifies them; then apply explicit user-selected references and style snapshot, de-duplicated and capped. For a video: storyboard first frame plus the same relevant character/scene/prop/style references, subject to `min(9, model_limit)`. Never use a failed exact-name match as a reason to silently drop the asset: emit a binding warning with candidate names. Store the selected list, roles, revisions, provenance and discarded items/reasons in the run-node input snapshot.

- [ ] **Step 4: Make OSS failures actionable.**

  Any local-to-public conversion failure must fail the video node before submission and identify the media asset. Image generation may not silently downgrade when references were required by the node config; return a structured failure instead.

- [ ] **Step 5: Add consistency assertions.**

  Test that an asset bound to a storyboard and its downstream video appears in the video payload, that stale revisions are rejected, and that a video/audio asset cannot enter an image reference port. Test seed and input mode through the actual canvas runtime fake provider.

- [ ] **Step 6: Run verification.**

  ```powershell
  cd backend
  python -m pytest tests/test_video_canvas_runtime.py tests/test_canvas_video_reference_contract.py tests/test_canvas_director_quality.py -q
  ```

---

## Task 5: Add durable Agent project creation and backend stage continuation

**目的：** 消除“必须先打开项目”和“浏览器关闭后自动化链断掉”两个核心限制。

**Files:**
- Modify: `backend/services/agent_service.py` tool registry and canvas workflow prompt
- Modify: `backend/routers/agent_router.py` Agent context parsing and SSE payloads
- Modify: `backend/services/canvas_agent_actions.py`
- Modify: `backend/services/canvas_stage_gateway.py`
- Modify: `backend/routers/video_canvas.py` project creation endpoint reuse
- Modify: `backend/models.py` only if a durable continuation record cannot be represented by `CanvasAgentAction` + `VideoCanvasRun`
- Modify: `frontend/src/components/AgentPanel/AgentPanel.tsx`
- Modify: `frontend/src/components/AgentPanel/canvasAgentMode.ts`
- Modify: `frontend/src/api.ts`
- Test: `backend/tests/test_canvas_agent_actions.py`
- Test: `backend/tests/test_canvas_stage_gateway.py`
- Test: `backend/tests/test_agent_canvas_snapshot.py`
- Create: `backend/tests/test_canvas_agent_continuation.py`
- Test: frontend AgentPanel API/event tests if existing test harness supports them.

**Interfaces:**
- Add a real Agent tool `create_manga_drama_project` returning `{canvas_id, story_id, definition_revision}` with server-side ownership, idempotency and title validation.
- Add a durable continuation function, for example:

  ```python
  async def continue_canvas_stage_after_run(
      *, canvas_id: int, run_id: int, action_id: int, db: Session
  ) -> dict[str, Any]:
      ...
  ```

  It must atomically claim a succeeded run, verify action mode/revision, inspect the latest graph, and create exactly one next-stage action.

- `CanvasAgentAction` remains the authorization record. `VideoCanvasRun` remains the execution record. No natural-language approval may claim an action.

- [ ] **Step 1: Add failing tests for project creation.**

  Test same user + same idempotency key returns the existing story/canvas, a different user cannot reuse it, invalid story ownership is rejected, and the returned canvas is immediately usable by `get_canvas_graph`.

- [ ] **Step 2: Add failing tests for durable continuation.**

  Cover success, failed/cancelled run, revision conflict, process restart simulation, duplicate callback, changed permission mode, and duplicate upstream provider job. Assert only one next action and no second charge/submission.

- [ ] **Step 3: Implement the project creation tool.**

  Reuse the existing `POST /api/manga-drama/projects` service behavior rather than duplicating database creation. Use the Agent conversation and user as the idempotency scope. Return the canvas binding needed by subsequent tool calls.

- [ ] **Step 4: Implement backend continuation.**

  Add one transactional continuation transition invoked from the `VideoCanvasRun` completion callback, not from SSE or a browser poll. It must lock/claim the succeeded run and source `CanvasAgentAction`, verify owner/conversation/canvas, mode and current `definition_revision`, derive the next stage from a server allowlist, and atomically create one continuation record/next action using a unique key such as `(source_action_id, succeeded_run_id, next_stage)`. `auto` creates and dispatches the next stage; `ask` persists `waiting_for_approval`; `plan` persists a proposal without execution. Failed/cancelled runs and stale revisions do not advance. On startup/recovery, scan only durable queued/running/waiting continuations and replay the same idempotent transition. Do not write a completed `agent_stage_actions` marker before the graph version save succeeds.

- [ ] **Step 5: Keep SSE as a view, not the state machine.**

  Emit `stage_pending`, `waiting`, `canvas_updated`, `done` and a durable `continuation_id`, `stage`, `next_stage` and `run_id`. The frontend may poll/display status, but closing the browser must not delete the continuation. Replace natural-language `"生成任务已完成，请观察实际结果并继续后续制作阶段。"` as the control path with a typed idempotent resume/approve endpoint. Keep the existing frontend polling only as a compatibility/status view until the backend path is proven, then remove duplicate client-driven auto-resume. `GET canvas-actions` must return all recoverable waiting tasks (not only the first one), scoped by user, conversation and canvas.

- [ ] **Step 6: Verify Agent chaining.**

  Use a fake LLM that requests the eight stages in order and fake generation runs. Assert `auto` progresses after each completed run without SSE/browser participation, `ask` pauses, `plan` proposes, failed/cancelled runs stop with an actionable error, a resumed process does not repeat completed stages, and duplicate callbacks/resume/approval requests produce one continuation, one next action, one run, one provider job and one usage event.

---

## Task 6: Improve manual canvas UX and explicit stage visibility

**目的：** 让用户无需理解后端内部状态即可知道下一步、为什么被阻塞、哪些资产会进入视频，以及何时需要审批。

**Files:**
- Modify: `frontend/src/components/VideoCanvasPanel.tsx`
- Modify: `frontend/src/components/MangaDramaWorkspacePage.tsx`
- Modify: `frontend/src/components/video-canvas/CanvasNodeView.tsx`
- Modify: `frontend/src/components/video-canvas/CanvasNodePropertyPanel.tsx`
- Modify: `frontend/src/components/video-canvas/CanvasBottomToolbar.tsx`
- Modify: `frontend/src/components/video-canvas/CanvasContextMenu.tsx`
- Modify: `frontend/src/components/video-canvas/CanvasEditorSurface.tsx`
- Modify: `frontend/src/components/video-canvas/useCanvasInteractions.ts`
- Modify: `frontend/src/api.ts`
- Test: `frontend/src/components/video-canvas/canvasReferenceSync.test.ts`
- Create: `frontend/src/components/video-canvas/canvasStageState.test.ts` or the repository's established equivalent.

**Interfaces:**
- Add a typed stage status model: `draft`, `split`, `review`, `assets`, `images`, `videos`, `concat`, `blocked`, `succeeded`, `failed`.
- Every blocked node must expose `error_message`, upstream node ID and next action when available.

- [ ] **Step 1: Add UI state tests.**

  Test that pending/running/succeeded/failed/blocked states render distinct labels; failed reference upload names the asset; a stale scene points to重新拆分/重新编排; and a video node lists the references that will be submitted.

- [ ] **Step 2: Add a visible stage rail.**

  Render the eight stages and mark each as complete, waiting for approval, running, blocked or stale. Clicking a stage focuses the responsible node and opens the relevant property panel.

- [ ] **Step 3: Expose reference provenance.**

  In image/video node details, show each reference's asset name, role, revision, source node and whether it was manually selected or edge-derived. Removing an edge must immediately remove the derived item from this view.

- [ ] **Step 4: Make run actions explicit.**

  Separate “保存图定义”, “验证图”, “运行选中节点及上游”, “确认并开始生成”, “取消运行” and “合片”. Disable actions with an explanatory reason, not only a disabled button.

- [ ] **Step 5: Verify generated media rendering.**

  Use `MediaImage` for all generated image nodes and previews. Keep native `<img>` only for local upload previews, QR codes or branding assets covered by project rules.

- [ ] **Step 6: Run frontend checks.**

  ```powershell
  cd frontend
  npm run test -- --run
  npm run lint
  npm run build
  ```

---

## Task 7: Add full graph end-to-end verification and operational observability

**目的：** 用一条可重复的 fake-provider 流程证明系统真的能完成全链路，而不是只证明单个函数通过。

**Files:**
- Create: `backend/tests/test_manga_drama_canvas_e2e.py`
- Create: `backend/tests/fakes/canvas_generation_provider.py` if the existing test fixtures cannot be reused
- Modify: `backend/tests/conftest.py` only for isolated transactional fixtures
- Modify: `backend/services/video_canvas_runtime.py` logging/input snapshot fields
- Modify: `backend/services/canvas_stage_gateway.py` result diagnostics
- Modify: `frontend/src/api.ts` only for typed run diagnostics needed by the UI
- Test: all existing canvas tests and frontend test suite.

**Interfaces:**
- Fake provider records image prompts, image references, video prompts, video references, input mode, seed, run ID and node ID.
- E2E result returns a report containing node statuses, output asset IDs, selected references, definition revisions and billing event IDs.

- [ ] **Step 1: Build a deterministic test graph.**

  Include screenplay → scene → asset container → three asset image nodes → storyboard image nodes → video nodes → concat, with one fan-out and one diamond dependency. Include a disabled edge and a deliberately stale node.

- [ ] **Step 2: Run the graph through the public service boundaries.**

  Exercise project creation, screenplay stage, split, director, assets, asset images, compile, storyboard images, videos and concat. Do not call private helpers as a substitute for the stage gateway.

- [ ] **Step 3: Assert content and media provenance.**

  Assert source dialogue and beat IDs survive, every generated storyboard has the correct character/scene/prop roles, every video has its storyboard and allowed asset refs, concat follows sequence, and stale/deleted references stop the run before billing.

- [ ] **Step 4: Assert recovery and idempotency.**

  Interrupt after provider job creation, resume, and assert no duplicate provider job. Replay the same Agent action and callback; assert one graph version, one usage event and one output.

- [ ] **Step 5: Add structured diagnostics.**

  Include stage, canvas ID, run ID, node ID, dependency IDs, reference asset IDs, source revision, provider job ID and failure code in server logs and run snapshots. Redact API keys and tokens.

- [ ] **Step 6: Run the complete verification matrix.**

  ```powershell
  cd backend
  python -m pytest tests -q
  cd ..\frontend
  npm run test -- --run
  npm run lint
  npm run build
  ```

  Expected: all backend tests, frontend tests, lint and production build pass. Record counts and any external-service tests intentionally excluded because they require credentials.

---

## Delivery checkpoints

1. **Checkpoint A:** Task 1 complete; repository builds and lint passes.
2. **Checkpoint B:** Tasks 2–4 complete; director contract, edge propagation and reference payload tests pass.
3. **Checkpoint C:** Task 5 complete; Agent can create a project and recover autonomous stages without the browser.
4. **Checkpoint D:** Task 6 complete; manual UX exposes every blocking state and reference provenance.
5. **Checkpoint E:** Task 7 complete; full fake-provider E2E and complete verification matrix pass.

At each checkpoint run `git diff --stat`, inspect modified files, run the relevant focused tests and `lsp_diagnostics` on every modified source file. Do not declare completion until the final verification matrix passes.

## Self-review against the requested outcome

- 画布功能是否完整：Tasks 2, 3, 6, 7 cover stage semantics, graph operations, UX and E2E.
- 手动节点、多节点、多连线内容传递：Task 3 covers ports, fan-in/fan-out, containers, stale output, deletion and replacement.
- 图片任务、视频任务、参考图一致性：Task 4 covers Image2, OSS, `input_reference`, provider mode and seed propagation.
- Agent 一句话到成片：Tasks 2, 5 and 7 cover screenplay quality, project creation, durable stage continuation and end-to-end execution.
- 构建阻断：Task 1 explicitly resolves the current TypeScript errors before feature work.
- 质量与可恢复性：Tasks 2, 5 and 7 cover strict quality diagnostics, idempotency, billing safety, cancellation and restart recovery.

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-27-manga-drama-agent-canvas-completion.md`. Two execution options:

1. **Subagent-Driven（推荐）** — 按任务逐项派发新子代理，每项之间进行代码审查和验证。
2. **Inline Execution** — 在当前会话按 checkpoint 批量执行，使用 executing-plans skill。
