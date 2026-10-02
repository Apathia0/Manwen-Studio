"""共享画布运行产物复用。

This module contains the part of canvas-stage reuse that is useful to the
runtime as well as to future stage entry points.  A generated media output is
only reusable when the current node and all of its active upstream
configuration have the same definition fingerprint as a node in a previous
successful run of the same canvas.

The module deliberately does not mutate a canvas version while resolving
runtime outputs.  The runtime applies the returned snapshots to its current
``VideoCanvasRunNode`` rows, which keeps the immutable graph snapshot intact
and, importantly, avoids creating a billing event for a reused node.
"""

from __future__ import annotations

from copy import deepcopy
from collections import deque
import hashlib
import json
from typing import Any, Callable, Iterable, Mapping

from models import VideoCanvasRun, VideoCanvasRunNode, VideoCanvasVersion


IMAGE_OUTPUT_NODE_TYPES = frozenset({"image", "image_generation", "storyboard"})
VIDEO_OUTPUT_NODE_TYPES = frozenset({"video", "video_generation"})
REUSABLE_OUTPUT_NODE_TYPES = IMAGE_OUTPUT_NODE_TYPES | VIDEO_OUTPUT_NODE_TYPES


# The callback is intentionally small and duck-typed.  It lets the runtime
# perform application-specific ownership checks without making this module
# depend on the runtime's media helpers.
OutputValidator = Callable[[dict[str, Any], dict[str, Any], Any, Any], bool]


def _node_config(node: Mapping[str, Any]) -> dict[str, Any]:
    data = node.get("data") if isinstance(node.get("data"), Mapping) else {}
    config = data.get("config") if isinstance(data, Mapping) else {}
    return config if isinstance(config, dict) else {}


def _node_id(node: Mapping[str, Any]) -> str:
    return str(node.get("id") or "")


def _active_parent_map(graph: Mapping[str, Any]) -> dict[str, set[str]]:
    parents: dict[str, set[str]] = {}
    for edge in graph.get("edges") or []:
        if not isinstance(edge, Mapping):
            continue
        edge_data = edge.get("data")
        if isinstance(edge_data, Mapping) and edge_data.get("disabled"):
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source and target:
            parents.setdefault(target, set()).add(source)
    return parents


def scope_node_ids(graph: Mapping[str, Any], node_id: str) -> set[str]:
    """Return ``node_id`` and every active upstream dependency.

    This mirrors ``canvas_stage_gateway.api_scope`` without importing a
    router.  Disabled edges are not part of a node's executable definition.
    """

    target = str(node_id or "")
    if not target:
        return set()
    parents = _active_parent_map(graph)
    included = {target}
    pending: deque[str] = deque([target])
    while pending:
        current = pending.popleft()
        for parent in parents.get(current, set()):
            if parent not in included:
                included.add(parent)
                pending.append(parent)
    return included


# Useful compatibility spelling for callers that used the gateway's helper.
_run_scope_node_ids = scope_node_ids


from services.canvas_style import apply_canvas_style, canvas_style  # noqa: E402


def definition_hash(graph: Mapping[str, Any], node_id: str) -> str:
    """Hash the meaningful definition of a node and its active ancestors.

    ``asset_id`` is execution state when it is accompanied by the reuse
    marker.  Removing both values in that case means a reused output does not
    make an otherwise identical definition look changed.  An unmarked
    ``asset_id`` remains part of the definition because it may be an explicit
    user-selected asset.
    """

    scope = scope_node_ids(graph, node_id)
    style = canvas_style(graph)
    values: list[tuple[str, Any, dict[str, Any]]] = []
    for raw_node in graph.get("nodes") or []:
        if not isinstance(raw_node, Mapping):
            continue
        current_id = _node_id(raw_node)
        if current_id not in scope:
            continue
        # 画布风格会在运行时补入没有自带风格的生成节点，指纹必须按同样的有效配置计算。
        config = apply_canvas_style(str(raw_node.get("type") or ""), deepcopy(_node_config(raw_node)), style)
        marker = config.pop("_reused_definition_hash", None)
        if marker:
            config.pop("asset_id", None)
        values.append((current_id, raw_node.get("type"), config))

    edges = [
        deepcopy(edge)
        for edge in (graph.get("edges") or [])
        if isinstance(edge, Mapping)
        and str(edge.get("source") or "") in scope
        and str(edge.get("target") or "") in scope
    ]
    raw = json.dumps(
        [
            sorted(values, key=lambda item: item[0]),
            sorted(edges, key=lambda item: str(item.get("id") or "")),
        ],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# Keep the gateway's private spelling available to tests and callers while
# using one implementation for runtime reuse.
_definition_hash = definition_hash


def normalize_node_ids(value: Any) -> set[str]:
    """Normalize a list/set/string of node ids without treating a string as chars."""

    if value is None:
        return set()
    if isinstance(value, str):
        value = [value]
    try:
        values = list(value)
    except TypeError:
        return set()
    return {str(item).strip() for item in values if isinstance(item, (str, int)) and str(item).strip()}


def resolve_rerun_node_ids(
    run: Any,
    explicit: Iterable[str] | None = None,
    task_context: Mapping[str, Any] | None = None,
) -> set[str]:
    """Read rerun ids from the optional runtime argument or frozen run plan.

    The HTTP router can evolve independently of the worker: current callers
    may pass ``rerun_node_ids`` as a task kwarg, while older/newer callers can
    persist it in ``plan_json`` or ``scope_json``.  Values are unioned so an
    explicit worker request can never accidentally weaken a persisted rerun.
    """

    result = normalize_node_ids(explicit)
    context = task_context if isinstance(task_context, Mapping) else {}
    for key in ("rerun_node_ids", "rerun_ids"):
        result.update(normalize_node_ids(context.get(key)))

    for container_name in ("plan_json", "scope_json"):
        container = getattr(run, container_name, None)
        if not isinstance(container, Mapping):
            continue
        for key in ("rerun_node_ids", "rerun_ids"):
            result.update(normalize_node_ids(container.get(key)))
    return result


def _query_successful_runs(db: Any, canvas_id: int, limit: int) -> list[Any]:
    """Fetch recent successful runs, failing closed if a legacy DB/mock lacks a query feature."""

    try:
        query = db.query(VideoCanvasRun).filter(
            VideoCanvasRun.canvas_id == canvas_id,
            VideoCanvasRun.status == "succeeded",
        )
        query = query.order_by(VideoCanvasRun.id.desc()).limit(limit)
        rows = query.all()
    except Exception:
        # Reuse is an optimization.  A schema/mock mismatch must never stop a
        # fresh generation from running.
        try:
            rows = db.query(VideoCanvasRun).all()
        except Exception:
            return []

    successful = [
        row for row in rows
        if getattr(row, "status", "succeeded") in {None, "succeeded"}
        and getattr(row, "canvas_id", canvas_id) == canvas_id
    ]
    successful.sort(key=lambda row: getattr(row, "id", 0) or 0, reverse=True)
    return successful[:limit]


def _successful_run_nodes(db: Any, run: Any) -> list[Any]:
    try:
        query = db.query(VideoCanvasRunNode).filter(
            VideoCanvasRunNode.run_id == run.id,
            VideoCanvasRunNode.status == "succeeded",
        )
        # A retry can leave multiple attempts.  We group below as a second
        # line of defence for DB adapters that do not preserve this ordering.
        query = query.order_by(VideoCanvasRunNode.attempt.desc())
        rows = query.all()
    except Exception:
        try:
            rows = db.query(VideoCanvasRunNode).all()
        except Exception:
            return []

    latest: dict[str, Any] = {}
    for row in rows:
        if getattr(row, "run_id", run.id) != run.id:
            continue
        if getattr(row, "status", "succeeded") not in {None, "succeeded"}:
            continue
        node_id = str(getattr(row, "node_id", "") or "")
        if not node_id:
            continue
        previous = latest.get(node_id)
        if previous is None or (getattr(row, "attempt", 1) or 1) > (getattr(previous, "attempt", 1) or 1):
            latest[node_id] = row
    return list(latest.values())


def _snapshot_has_media(snapshot: Any) -> bool:
    """Require a persisted asset reference for cross-run reuse.

    URL-only snapshots are intentionally excluded here.  Imported media has
    its own origin/ownership validation path in the runtime, while generated
    shared outputs are represented by a ``VideoAsset`` id.  Requiring that id
    prevents a stale or user-supplied URL from becoming a trusted output just
    because it appeared in an old run snapshot.
    """

    if not isinstance(snapshot, Mapping):
        return False
    asset_id = snapshot.get("asset_id")
    return isinstance(asset_id, int) and not isinstance(asset_id, bool) and asset_id > 0


def _is_reusable_node(node: Mapping[str, Any]) -> bool:
    return str(node.get("type") or "") in REUSABLE_OUTPUT_NODE_TYPES


def invalidated_node_ids(
    graph: Mapping[str, Any],
    rerun_node_ids: Iterable[str] | None = None,
) -> set[str]:
    """Return generation nodes that must not use an old output.

    Rerunning an upstream text/asset node invalidates every downstream media
    node whose definition includes it.  The rerun target itself is included so
    an explicitly requested media node is always generated again.
    """

    rerun_ids = normalize_node_ids(rerun_node_ids)
    if not rerun_ids:
        return set()
    return {
        node_id
        for node_id, node in (
            (_node_id(node), node)
            for node in (graph.get("nodes") or [])
            if isinstance(node, Mapping) and _node_id(node)
        )
        if _is_reusable_node(node) and scope_node_ids(graph, node_id).intersection(rerun_ids)
    }


def clear_invalid_reuse_markers(
    graph: dict[str, Any],
    rerun_node_ids: Iterable[str] | None = None,
) -> set[str]:
    """Drop stale gateway markers without changing explicit user assets.

    The graph passed to this function is expected to be a worker-local copy of
    an immutable version snapshot.  It returns the media nodes whose marker
    was cleared, allowing the runtime to force those nodes through generation.
    """

    original = deepcopy(graph)
    rerun_ids = normalize_node_ids(rerun_node_ids)
    cleared: set[str] = set()
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_id = _node_id(node)
        config = _node_config(node)
        marker = config.get("_reused_definition_hash")
        if not marker:
            continue
        try:
            invalid = str(marker) != definition_hash(original, node_id) or bool(
                rerun_ids.intersection(scope_node_ids(original, node_id))
            )
        except (TypeError, ValueError, KeyError):
            invalid = True
        if invalid:
            config.pop("asset_id", None)
            config.pop("_reused_definition_hash", None)
            cleared.add(node_id)
    return cleared


def find_reusable_outputs(
    graph: Mapping[str, Any],
    canvas_id: int,
    db: Any,
    rerun_node_ids: Iterable[str] | None = None,
    *,
    current_run_id: int | None = None,
    limit: int = 30,
    protected_node_ids: Iterable[str] | None = None,
    output_validator: OutputValidator | None = None,
) -> dict[str, dict[str, Any]]:
    """Find reusable media snapshots from the newest matching successful runs.

    The returned mapping is ``current_node_id -> copied output snapshot``.
    Nodes are resolved newest-run-first.  A rerun target invalidates itself
    and all of its downstream media nodes only when the target is upstream of
    that media node; rerunning a downstream node still permits independent
    upstream outputs to be reused.
    """

    if not isinstance(graph, Mapping):
        return {}
    current_nodes = {
        _node_id(node): node
        for node in (graph.get("nodes") or [])
        if isinstance(node, Mapping) and _node_id(node)
    }
    if not current_nodes:
        return {}

    rerun_ids = normalize_node_ids(rerun_node_ids)
    resolved = set(rerun_ids)
    protected = normalize_node_ids(protected_node_ids)
    original = deepcopy(dict(graph))
    current_hashes: dict[str, str] = {}
    current_scopes: dict[str, set[str]] = {}
    for node_id, node in current_nodes.items():
        if not _is_reusable_node(node):
            continue
        config = _node_config(node)
        # Explicitly selected/imported media already has a safe reuse path in
        # the runtime; do not replace it with an older run's snapshot.
        if isinstance(config.get("asset_id"), int) or str(config.get("trusted_import_media_url") or "").strip():
            resolved.add(node_id)
            continue
        if config.get("stale"):
            resolved.add(node_id)
            continue
        current_hashes[node_id] = definition_hash(original, node_id)
        current_scopes[node_id] = scope_node_ids(original, node_id)

    result: dict[str, dict[str, Any]] = {}
    if not current_hashes:
        return result

    for run in _query_successful_runs(db, canvas_id, max(1, int(limit))):
        run_id = getattr(run, "id", None)
        if current_run_id is not None and run_id == current_run_id:
            continue
        version_id = getattr(run, "canvas_version_id", None)
        if version_id is None:
            continue
        try:
            version = db.get(VideoCanvasVersion, version_id)
        except Exception:
            continue
        previous_graph = getattr(version, "graph_json", None) if version else None
        if not isinstance(previous_graph, Mapping):
            continue
        previous_nodes = {
            _node_id(node): node
            for node in (previous_graph.get("nodes") or [])
            if isinstance(node, Mapping) and _node_id(node)
        }

        for run_node in _successful_run_nodes(db, run):
            node_id = str(getattr(run_node, "node_id", "") or "")
            if node_id not in current_hashes or node_id in resolved:
                continue
            if node_id in protected:
                continue
            target = current_nodes[node_id]
            source = previous_nodes.get(node_id)
            if not source or str(source.get("type") or "") != str(target.get("type") or ""):
                continue
            if rerun_ids.intersection(current_scopes.get(node_id, set())):
                continue
            try:
                if definition_hash(previous_graph, node_id) != current_hashes[node_id]:
                    continue
            except (TypeError, ValueError, KeyError):
                continue
            snapshot = getattr(run_node, "output_snapshot_json", None)
            if not _snapshot_has_media(snapshot):
                continue
            copied = deepcopy(dict(snapshot))
            if output_validator is not None:
                try:
                    if not output_validator(copied, target, run, run_node):
                        continue
                except Exception:
                    # Validation is fail-closed for a candidate, not for the
                    # whole fresh run.
                    continue
            result[node_id] = copied
            resolved.add(node_id)

    return result


# A descriptive alias for callers that prefer "resolve" terminology.
resolve_reusable_outputs = find_reusable_outputs
get_reusable_outputs = find_reusable_outputs


def apply_reusable_outputs(
    graph: dict[str, Any],
    outputs: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Apply gateway-compatible reuse markers to a mutable graph.

    Runtime execution normally does not need this helper; it copies output
    snapshots directly to run nodes.  It is provided so stage callers can use
    the same hash semantics without importing the gateway implementation.
    """

    applied: dict[str, dict[str, Any]] = {}
    nodes = {
        _node_id(node): node
        for node in (graph.get("nodes") or [])
        if isinstance(node, dict) and _node_id(node)
    }
    for node_id, snapshot in outputs.items():
        node = nodes.get(str(node_id))
        if not node or not isinstance(snapshot, Mapping):
            continue
        config = _node_config(node)
        asset_id = snapshot.get("asset_id")
        if isinstance(asset_id, int) and not isinstance(asset_id, bool):
            fingerprint = definition_hash(graph, str(node_id))
            config["asset_id"] = asset_id
            config["_reused_definition_hash"] = fingerprint
        applied[str(node_id)] = deepcopy(dict(snapshot))
    return applied


def _reusable_outputs(
    graph: dict[str, Any],
    canvas_id: int,
    db: Any,
    rerun_ids: Iterable[str] | None = None,
) -> None:
    """Gateway-compatible mutating facade (the runtime uses the pure API)."""

    clear_invalid_reuse_markers(graph, rerun_ids)
    outputs = find_reusable_outputs(graph, canvas_id, db, rerun_ids)
    apply_reusable_outputs(graph, outputs)


__all__ = [
    "IMAGE_OUTPUT_NODE_TYPES",
    "VIDEO_OUTPUT_NODE_TYPES",
    "REUSABLE_OUTPUT_NODE_TYPES",
    "apply_reusable_outputs",
    "definition_hash",
    "find_reusable_outputs",
    "get_reusable_outputs",
    "normalize_node_ids",
    "resolve_rerun_node_ids",
    "resolve_reusable_outputs",
    "scope_node_ids",
    "_definition_hash",
    "_reusable_outputs",
]
