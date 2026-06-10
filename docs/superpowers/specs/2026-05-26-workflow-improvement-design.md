# 漫画工作流改进设计方案

## 概述

本设计方案旨在解决用户在使用漫画工作流时遇到的三个核心问题：
1. 新建作品必须走完AI引导流程，无法跳过
2. 右上角+号按钮无法添加新章节
3. 手动编辑正文后保存失败

## 设计目标

- 保留现有完整流程，但提供跳过选项
- 修复手动增加章节功能
- 修复手动编辑保存功能
- 提升用户体验，减少不必要的操作步骤

## 详细设计

### 1. 引导页跳过按钮

#### 1.1 修改位置
- 文件：`frontend/src/components/OnboardingPage.tsx`
- 在引导页底部添加"跳过引导"按钮

#### 1.2 实现逻辑
```typescript
// 在OnboardingPage组件中添加跳过按钮
const handleSkipOnboarding = async () => {
  try {
    // 调用API标记引导已完成
    await api.completeOnboarding(storyId);
    // 直接进入工作台
    onComplete();
  } catch (error) {
    console.error('跳过引导失败:', error);
  }
};
```

#### 1.3 UI设计
- 按钮位置：引导页底部，与"下一步"按钮并列
- 按钮样式：次要按钮样式（灰色或边框）
- 按钮文字："跳过引导，直接开始"

### 2. 手动增加章节功能

#### 2.1 修复右上角+号按钮
- 文件：`frontend/src/components/EditorPanel.tsx`
- 修改`handleNewChapter`函数

```typescript
// 修改前：只是导航到最后一章
const handleNewChapter = useCallback(() => {
  if (chapters.length > 0) {
    onChapterChange(chapters[chapters.length - 1]);
  }
}, [chapters, onChapterChange]);

// 修改后：创建新章节并导航
const handleNewChapter = useCallback(async () => {
  try {
    // 调用API创建新章节
    const newChapter = await api.createNextChapter(storyId);
    // 刷新章节列表
    await onContentUpdated();
    // 导航到新章节
    onChapterChange(newChapter);
  } catch (error) {
    console.error('创建章节失败:', error);
  }
}, [storyId, onContentUpdated, onChapterChange]);
```

#### 2.2 在编辑区域添加新建章节按钮
- 文件：`frontend/src/components/EditorPanel.tsx`
- 在编辑区域顶部添加"新建章节"按钮

```typescript
// 在编辑区域顶部添加按钮
<Button 
  onClick={handleNewChapter}
  variant="outline"
  size="sm"
>
  <Plus className="w-4 h-4 mr-2" />
  新建章节
</Button>
```

### 3. 手动编辑保存功能

#### 3.1 修复竞态条件
- 文件：`frontend/src/components/EditorPanel.tsx`
- 修改`useEffect`依赖项，避免编辑状态丢失

```typescript
// 修改前：依赖currentChapter?.id和currentChapter?.novel_content
useEffect(() => {
  setIsEditing(false);
  setDraftContent(currentChapter?.novel_content ?? '');
  // ...
}, [currentChapter?.id, currentChapter?.novel_content]);

// 修改后：只依赖currentChapter?.id
useEffect(() => {
  setIsEditing(false);
  setDraftContent(currentChapter?.novel_content ?? '');
  // ...
}, [currentChapter?.id]);
```

#### 3.2 添加保存确认提示
- 文件：`frontend/src/components/EditorPanel.tsx`
- 修改`handleSaveDraft`函数，添加保存成功提示

```typescript
const handleSaveDraft = async () => {
  try {
    await saveChapterContent(currentChapter.id, draftContent);
    await onContentUpdated();
    setIsEditing(false);
    // 添加保存成功提示
    toast.success('正文保存成功');
  } catch (error) {
    console.error('保存失败:', error);
    toast.error('保存失败，请重试');
  }
};
```

### 4. 后端API支持

#### 4.1 创建章节API
- 文件：`backend/main.py`
- 确保`create_next_chapter`API正常工作

#### 4.2 保存内容API
- 文件：`backend/main.py`
- 确保`update_chapter_content`API正常工作
- 添加`content_source`字段支持

```python
@app.put("/api/chapters/{chapter_id}/content", response_model=ChapterOut)
async def update_chapter_content(chapter_id, body, request, db):
    chapter = _require_chapter(chapter_id, db)
    text = body.content.strip()
    # 设置content_source为manual
    _apply_chapter_content(chapter, text, status="draft", content_source="manual")
    await _refresh_chapter_memory(chapter, request, db)
    db.commit()
    return chapter
```

## 实施计划

### 阶段1：引导页跳过按钮
1. 修改`OnboardingPage.tsx`，添加跳过按钮
2. 修改`App.tsx`，处理跳过逻辑
3. 测试跳过功能

### 阶段2：手动增加章节功能
1. 修改`EditorPanel.tsx`，修复`handleNewChapter`函数
2. 添加新建章节按钮
3. 测试章节创建功能

### 阶段3：手动编辑保存功能
1. 修改`EditorPanel.tsx`，修复`useEffect`依赖
2. 添加保存确认提示
3. 测试保存功能

## 预期效果

1. 用户可以选择跳过引导，直接进入工作台
2. 右上角+号按钮能够正常创建新章节
3. 手动编辑的正文能够正确保存
4. 用户体验得到提升，操作更加流畅

## 风险评估

- **低风险**：跳过引导功能，只是添加一个按钮，不影响现有流程
- **中风险**：章节创建功能，需要确保API调用正确
- **低风险**：保存功能修复，只是修改依赖项和添加提示

## 测试计划

1. **跳过引导测试**：验证跳过按钮功能，确保能正常进入工作台
2. **章节创建测试**：验证右上角+号按钮和新建章节按钮功能
3. **保存功能测试**：验证手动编辑后保存功能，确保内容正确保存
4. **回归测试**：验证现有功能未受影响