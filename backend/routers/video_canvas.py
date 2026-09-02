@router.post("/api/video-canvas/canvases/{canvas_id}/containers/create")
async def create_node_container(canvas_id: int, body: VideoCanvasContainerCreateRequest, request: Request, db: Session = Depends(get_db)):
    """从给定节点列表创建资产容器节点（带自动 Tab 分类）。"""
    user = _require_user(request, db)
    canvas = _require_canvas(canvas_id, user, db)
    if body.expected_definition_revision is not None and canvas.definition_revision != body.expected_definition_revision:
        raise HTTPException(409, {"message": "画布定义已更新", "definition_revision": canvas.definition_revision})
    
    graph = _latest_version(canvas.id, db).graph_json or {}
    node_map = {str(node.get("id")) for node in graph.get("nodes") or []}
    invalid_ids = [nid for nid in body.node_ids if nid not in node_map]
    if invalid_ids:
        raise HTTPException(422, f"节点不存在：{', '.join(invalid_ids)}")
    
    # 按 asset_role 分组
    assets_by_role: dict[str, list[dict]] = defaultdict(list)
    for node in graph["nodes"]:
        if str(node.get("id")) in body.node_ids:
            config = (node.get("data") or {}).get("config") or {}
            role = str(config.get("asset_role") or "other")
            assets_by_role.setdefault(role, []).append(node)
    
    tabs = []
    position_map: dict[str, tuple[int, int]] = {}
    
    for role in ["character", "scene", "prop", "other"]:
        nodes = assets_by_role.get(role, [])
        if nodes:
            tab_title = {"character": "角色", "scene": "场景", "prop": "道具"}.get(role, role)
            tab_color = {"character": "#73a7ff", "scene": "#34d399", "prop": "#f59e0b", "other": "#6b7280"}.get(role, "#6b7280")
            tab_nodes = [n["id"] for n in nodes]
            tabs.append({"title": tab_title, "color": tab_color, "nodes": tab_nodes})
            
            # 计算矩阵布局
            width, height = 280, 180
            gap_x, gap_y = 30, 25
            cols_per_row = 3
            rows = (len(nodes) + cols_per_row - 1) // cols_per_row
            for idx, node in enumerate(nodes):
                row, col = divmod(idx, cols_per_row)
                x = col * (width + gap_x)
                y = row * (height + gap_y)
                position_map[node["id"]] = (x + 20, y + 20)  # 加 padding
    
    container_node_id = f"container-{uuid.uuid4().hex[:16]}"
    base_x = min(p[0] for p in position_map.values()) if position_map else 0
    base_y = min(p[1] for p in position_map.values()) if position_map else 0
    
    # 为容器本身找一个空闲位置
    all_positions = set()
    for pid in body.node_ids:
        if pid in position_map:
            px, py = position_map[pid]
            all_positions.add((px, py))
    
    def find_free_position(start_y: int):
        for offset in range(1, 100):
            y = start_y + offset * 250
            # 检查是否有冲突
            has_conflict = False
            for pos in all_positions:
                if abs(pos[0] - base_x) < 100 and abs(pos[1] - y) < 200:
                    has_conflict = True
                    break
            if not has_conflict:
                return (base_x, y)
        return (base_x, start_y + 300)
    
    container_pos = find_free_position(base_y)
    
    container_config = {
        "node_role": "container",
        "node_label": body.name or "资产容器",
        "tabs": tabs,
        "matrix_layout": True,
        "expected_revision": canvas.definition_revision,
    }
    
    # 更新所有节点的相对坐标（容器内绝对位置）
    updated_nodes = []
    for node in graph["nodes"]:
        nid = str(node.get("id"))
        if nid in position_map:
            rel_x, rel_y = position_map[nid]
            absolute_x = container_pos[0] + rel_x
            absolute_y = container_pos[1] + rel_y
            updated_nodes.append({
                **node,
                "position": {"x": absolute_x, "y": absolute_y},
            })
        else:
            updated_nodes.append(node)
    
    graph["nodes"] = updated_nodes
    graph["nodes"].append({
        "id": container_node_id,
        "type": "container",
        "position": {"x": container_pos[0], "y": container_pos[1]},
        "data": {"label": container_config["node_label"], "config": container_config},
    })
    
    version = VideoCanvasVersion(
        canvas_id=canvas.id,
        version_no=canvas.definition_revision + 1,
        graph_json=graph,
        source="manual",
        change_summary=f"创建资产容器 '{body.name}'（含{len(body.node_ids)}个节点）",
        created_by_user_id=user.id,
    )
    db.add(version)
    canvas.definition_revision += 1
    db.commit()
    db.refresh(canvas)
    
    return {"ok": True, "container_id": container_node_id, "tab_count": len(tabs), "node_count": len(body.node_ids)}


def _compute_matrix_layout(nodes: list[dict], width: int = 280, height: int = 180, gap_x: int = 30, gap_y: int = 25, cols_per_row: int = 3) -> dict[str, tuple[int, int]]:
    """计算节点矩阵布局坐标（按 row-major 顺序填充，每行固定列数）。"""
    position_map: dict[str, tuple[int, int]] = {}
    rows = (len(nodes) + cols_per_row - 1) // cols_per_row
    for idx, node in enumerate(nodes):
        row, col = divmod(idx, cols_per_row)
        x = col * (width + gap_x)
        y = row * (height + gap_y)
        position_map[node["id"]] = (x, y)
    return position_map