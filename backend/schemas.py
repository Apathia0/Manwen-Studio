class VideoCanvasContainerCreateRequest(BaseModel):
    """创建资产容器请求。"""
    name: str = Field(default="资产容器", min_length=1, max_length=64)
    node_ids: list[str] = Field(min_length=1, max_length=50)
    expected_definition_revision: int | None = Field(default=None, ge=1)


class VideoCanvasContainerOut(BaseModel):
    """容器节点输出结构（运行时读取）。"""
    container_id: str
    label: str
    tabs: list[dict[str, Any]]
    matrix_layout: bool
    nodes: list[dict[str, Any]]  # 包含所有子节点的完整信息