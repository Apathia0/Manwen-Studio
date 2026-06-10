# 视频工作流二级工作台重构设计

## 1. 背景与目标

### 1.1 当前问题
当前视频工作流（`VideoStoryboardLayout`）采用三栏布局，右侧有一个320px的内嵌工作区，包含4个tab（整章成片/故事版/视频/角色资产）。这种设计存在以下问题：
- 右侧工作区空间有限，无法完整展示重绘、上传替换等复杂功能
- 用户需要在小区域内进行精细操作，体验不佳
- 与漫画工作台的交互风格不一致

### 1.2 设计目标
- 移除右侧内嵌工作区，让分镜流水线面板占满可用宽度
- 点击角色资产卡片、故事版卡片、视频卡片时，进入全屏二级工作台
- 二级工作台参考漫画工作台的图片点击放大布局，提供完整的操作功能
- 统一视频工作流与漫画工作流的交互体验

## 2. 整体架构设计

### 2.1 布局变化

**当前布局**：
```
┌──────────┬─────────────────┬──────────────┐
│ 章节列表  │   分镜流水线     │  右侧工作台   │
│ (可折叠)  │   (主面板)      │  (320px)     │
│          │                 │  4个tab切换   │
└──────────┴─────────────────┴──────────────┘
```

**新布局**：
```
┌──────────┬─────────────────────────────────┐
│ 章节列表  │         分镜流水线               │
│ (可折叠)  │         (全宽)                  │
│          │                                 │
│          │  镜头1: [角色卡] [故事版卡] [视频卡]│
│          │  镜头2: [角色卡] [故事版卡] [视频卡]│
│          │  ...                            │
└──────────┴─────────────────────────────────┘
```

### 2.2 二级工作台触发机制

**触发方式**：点击整个卡片进入二级工作台

**实现方式**：
```tsx
// 在ChapterVideoWorkflowPanel中
const [workbenchState, setWorkbenchState] = useState<{
  type: 'character' | 'storyboard' | 'video';
  shotId: number;
  assetId?: number;
} | null>(null);

// 卡片点击处理
const handleCardClick = (type, shotId, assetId) => {
  setWorkbenchState({ type, shotId, assetId });
};

// 渲染二级工作台
{workbenchState && (
  <VideoCardWorkbench
    type={workbenchState.type}
    shotId={workbenchState.shotId}
    assetId={workbenchState.assetId}
    onClose={() => setWorkbenchState(null)}
  />
)}
```

## 3. 二级工作台详细设计

### 3.1 统一布局结构

所有三种卡片类型的二级工作台采用统一布局：

```
┌─────────────────────────────────────────────────────┐
│  [← 返回工作台]    镜头1·角色资产    [100%][135%][170%] [X] │
├─────────────────────────────────────────────────────┤
│                                                     │
│                   大图/视频预览区域                  │
│              （深色背景，支持左右导航）               │
│                                                     │
├─────────────────────────────────────────────────────┤
│  [重新生成] [上传替换] [删除] [重绘]                 │
│  提示词编辑区域（可展开/折叠）                       │
└─────────────────────────────────────────────────────┘
```

### 3.2 各类型卡片的功能差异

#### 角色资产卡片二级工作台
**预览区域**：显示角色参考图大图
**操作按钮**：
- 重新生成：调用`regenerateCharacterReference` API
- 上传替换：文件上传，替换现有参考图
- 删除：删除角色资产
- 重绘：打开`ImageRedrawModal`，支持局部/整图重绘
- 提示词编辑：编辑角色描述提示词

#### 故事版卡片二级工作台
**预览区域**：显示故事版图片大图
**操作按钮**：
- 重新生成：调用`regenerateStoryboard` API
- 上传替换：文件上传，替换现有故事版
- 删除：删除故事版
- 重绘：打开`ImageRedrawModal`
- 分析提示词：AI重新分析场景描述
- 提示词编辑：编辑场景描述提示词

#### 视频卡片二级工作台
**预览区域**：显示视频播放器
**操作按钮**：
- 重新生成：调用`regenerateVideo` API
- 删除：删除视频
- 提示词编辑：编辑视频生成参数

### 3.3 交互细节

**导航**：
- 左右箭头按钮切换同一类型下的不同资源（例如：角色资产卡片二级工作台中，左右切换不同镜头的角色资产）
- 键盘左右键导航
- ESC键关闭二级工作台

**缩放**：
- 三级缩放按钮（100%/135%/170%）
- 图片支持滚轮缩放

**状态管理**：
- 使用React状态管理当前预览的资源
- 关闭二级工作台时恢复主界面滚动位置

## 4. 技术实现细节

### 4.1 文件结构变化

**新建文件**：
- `frontend/src/components/VideoCardWorkbench.tsx` — 统一的二级工作台组件

**修改文件**：
- `frontend/src/components/ChapterVideoWorkflowPanel.tsx` — 移除右侧工作台，添加二级工作台触发逻辑
- `frontend/src/components/VideoStoryboardLayout.tsx` — 调整布局，移除右侧工作台容器

**复用文件**：
- `frontend/src/components/shared/ImageRedrawModal.tsx` — 重绘功能
- `frontend/src/components/MangaPanel.tsx` — 参考深色背景样式

### 4.2 组件接口设计

```typescript
// VideoCardWorkbench.tsx
interface VideoCardWorkbenchProps {
  type: 'character' | 'storyboard' | 'video';
  shotId: number;
  assetId?: number;
  onClose: () => void;
}

// 状态管理
interface WorkbenchState {
  currentIndex: number;  // 当前预览的资源索引
  zoomLevel: 1 | 1.35 | 1.7;  // 缩放级别
  isRedrawModalOpen: boolean;  // 重绘弹窗状态
  editingPrompt: string;  // 正在编辑的提示词
}
```

### 4.3 API调用映射

| 卡片类型 | 重新生成API | 删除API | 上传替换API |
|---------|------------|--------|------------|
| 角色资产 | `regenerateCharacterReference` | `deleteCharacterAsset` | `uploadCharacterReference` |
| 故事版 | `regenerateStoryboard` | `deleteStoryboard` | `uploadStoryboard` |
| 视频 | `regenerateVideo` | `deleteVideo` | 无（视频不支持上传替换） |

### 4.4 样式规范

**深色背景**：复用`MangaPanel.tsx`的样式
```css
bg-[linear-gradient(180deg,_#0b1220_0%,_#111827_100%)]
```

**圆角**：`rounded-[28px]`

**边框**：`border border-[#d7e3f4]`

**文字颜色**：`text-white`

### 4.5 键盘快捷键

- `←` / `→`：切换上/下一个资源
- `ESC`：关闭二级工作台
- `+` / `-`：缩放控制
- `R`：打开重绘弹窗
- `Delete`：删除当前资源（需确认）

### 4.6 错误处理

- API调用失败时显示Toast错误提示
- 上传文件时显示进度条
- 删除操作需要二次确认

## 5. 实现步骤

### 5.1 第一阶段：基础框架
1. 创建`VideoCardWorkbench.tsx`组件基础结构
2. 实现深色背景布局和导航功能
3. 集成缩放控制

### 5.2 第二阶段：功能实现
1. 实现角色资产卡片的二级工作台功能
2. 实现故事版卡片的二级工作台功能
3. 实现视频卡片的二级工作台功能

### 5.3 第三阶段：集成与优化
1. 修改`ChapterVideoWorkflowPanel.tsx`，移除右侧工作台
2. 添加卡片点击触发二级工作台的逻辑
3. 优化键盘快捷键和交互细节
4. 测试和修复问题

## 6. 测试计划

### 6.1 功能测试
- 测试三种卡片类型的二级工作台打开/关闭
- 测试重新生成、上传替换、删除、重绘功能
- 测试提示词编辑功能
- 测试键盘快捷键

### 6.2 兼容性测试
- 测试不同屏幕尺寸下的布局表现
- 测试与现有功能的兼容性

### 6.3 用户体验测试
- 测试操作流程的顺畅度
- 测试视觉效果的一致性

## 7. 风险与缓解

### 7.1 技术风险
- **风险**：二级工作台与现有状态管理冲突
- **缓解**：使用独立的状态管理，避免全局状态污染

### 7.2 用户体验风险
- **风险**：用户不适应新的交互方式
- **缓解**：提供清晰的视觉指引和操作提示

### 7.3 性能风险
- **风险**：全屏二级工作台影响页面性能
- **缓解**：使用React.lazy懒加载，优化渲染性能