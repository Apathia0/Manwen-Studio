<template>
  <!-- 视频卡片工作台 - 全屏弹窗 -->
  <view v-if="visible" class="vwb">
    <!-- 遮罩层 -->
    <view class="vwb__mask" @tap="handleClose" />

    <!-- 主体容器 -->
    <view class="vwb__container" @tap.stop>
      <!-- 顶部栏：镜头标题 + 关闭按钮 -->
      <view class="vwb__header">
        <view class="vwb__header-left">
          <text class="vwb__header-icon">🛠</text>
          <text class="vwb__header-title">镜头 {{ shotIndex }} 工作台</text>
        </view>
        <view class="vwb__header-close" @tap="handleClose">
          <text class="vwb__close-icon">✕</text>
        </view>
      </view>

      <!-- 4 类卡片导航标签栏 -->
      <scroll-view scroll-x class="vwb__tabs-scroll" show-scrollbar="false">
        <view class="vwb__tabs">
          <view
            v-for="tab in tabs"
            :key="tab.key"
            :class="['vwb__tab', { 'vwb__tab--active': currentType === tab.key }]"
            @tap="switchTab(tab.key)"
          >
            <text class="vwb__tab-icon">{{ tab.icon }}</text>
            <text class="vwb__tab-label">{{ tab.label }}</text>
          </view>
        </view>
      </scroll-view>

      <!-- 内容区域 - 按卡片类型显示完整内容 -->
      <scroll-view scroll-y class="vwb__content">
        <!-- ========== 角色卡片 (T12) ========== -->
        <view v-if="currentType === 'character'" class="vwb__card-content">
          <!-- 加载中 -->
          <view v-if="characterLoading" class="vwb__placeholder">
            <text class="vwb__placeholder-icon">⏳</text>
            <text class="vwb__placeholder-title">加载角色资产中…</text>
          </view>

          <!-- 空状态 -->
          <view v-else-if="characterAssets.length === 0" class="vwb__placeholder">
            <text class="vwb__placeholder-icon">👤</text>
            <text class="vwb__placeholder-title">暂无角色资产</text>
            <text class="vwb__placeholder-desc">请先生成角色参考图后再来管理</text>
          </view>

          <!-- 角色资产列表 -->
          <view v-else class="vwb__asset-list">
            <view
              v-for="asset in characterAssets"
              :key="asset.id"
              :class="['vwb__asset-card', { 'vwb__asset-card--selected': selectedCharacterAssetId === asset.id }]"
              @tap="selectCharacterAsset(asset.id)"
            >
              <image
                :src="characterAssetThumb(asset)"
                class="vwb__asset-thumb"
                mode="aspectFill"
                @error="onAssetThumbError(asset.id)"
              />
              <view class="vwb__asset-info">
                <text class="vwb__asset-name">{{ asset.name }}</text>
                <view :class="['vwb__badge', `vwb__badge--${assetStatusBadge(asset)}`]">
                  <text>{{ assetStatusLabel(asset) }}</text>
                </view>
              </view>
              <!-- 选中标记 -->
              <view v-if="selectedCharacterAssetId === asset.id" class="vwb__asset-check">
                <text>✓</text>
              </view>
            </view>
          </view>

          <!-- 重绘提示词输入区（inline） -->
          <view v-if="showRedrawPrompt" class="vwb__redraw-panel">
            <text class="vwb__redraw-panel-title">重绘提示词（可选）</text>
            <textarea
              v-model="redrawPromptText"
              class="vwb__redraw-textarea"
              placeholder="输入重绘提示词，留空则使用默认提示词"
              :maxlength="500"
              :auto-height="true"
            />
            <view class="vwb__redraw-panel-actions">
              <view class="vwb__action-btn vwb__action-btn--secondary" @tap="cancelRedraw">
                <text class="vwb__action-label">取消</text>
              </view>
              <view class="vwb__action-btn vwb__action-btn--primary" @tap="confirmRedraw">
                <text class="vwb__action-label">确认重绘</text>
              </view>
            </view>
          </view>
        </view>

        <!-- ========== 故事版卡片 (T13) ========== -->
        <view v-else-if="currentType === 'storyboard'" class="vwb__card-content">
          <!-- 当前故事版预览 -->
          <view v-if="shotData?.storyboard_image_url" class="vwb__preview-section">
            <image
              :src="assetUrl(shotData.storyboard_image_url)"
              class="vwb__preview-image"
              mode="aspectFit"
            />
          </view>

          <!-- 状态信息 -->
          <view class="vwb__info-section">
            <view class="vwb__info-row">
              <text class="vwb__info-label">状态</text>
              <view :class="['vwb__badge', `vwb__badge--${statusBadge(shotData)}`]">
                <text>{{ statusLabel(shotData) }}</text>
              </view>
            </view>
          </view>

          <!-- 镜头风格预设选择器（T21） -->
          <view class="vwb__style-preset-section">
            <view class="vwb__style-preset-header">
              <text class="vwb__section-title">镜头风格预设</text>
              <view
                v-if="stylePresetsLoading"
                class="vwb__versions-refresh vwb__versions-refresh--spin"
              >
                <text>⟳</text>
              </view>
            </view>
            <!-- 当前绑定 -->
            <view v-if="shotStylePresetName" class="vwb__style-current">
              <view class="vwb__style-current-badge">
                <text class="vwb__style-current-name">{{ shotStylePresetName }}</text>
              </view>
              <view
                :class="['vwb__style-clear', { 'vwb__style-clear--disabled': busy }]"
                @tap="handleClearShotStylePreset"
              >
                <text>清除风格预设</text>
              </view>
            </view>
            <view v-else class="vwb__style-current--empty">
              <text class="vwb__placeholder-desc">未绑定风格预设</text>
            </view>
            <!-- 预设选择列表 -->
            <view v-if="stylePresets.length > 0" class="vwb__style-chips-wrap">
              <view
                v-for="preset in stylePresets"
                :key="preset.id"
                :class="['vwb__style-chip', { 'vwb__style-chip--active': selectedStylePresetId === preset.id }]"
                @tap="handleSelectStylePreset(preset)"
              >
                <text class="vwb__style-chip-text">{{ preset.name }}</text>
              </view>
            </view>
          </view>

          <!-- 渲染故事版帧（T23） -->
          <view class="vwb__render-frame-section">
            <view class="vwb__render-frame-header">
              <text class="vwb__section-title">渲染故事版帧</text>
            </view>
            <!-- 渲染面板 -->
            <view v-if="showRenderFramePanel" class="vwb__redraw-panel">
              <text class="vwb__redraw-panel-title">提示词（可选，留空则使用镜头默认提示词）</text>
              <textarea
                v-model="renderFramePrompt"
                class="vwb__redraw-textarea"
                placeholder="输入自定义渲染提示词"
                :maxlength="2000"
                :auto-height="true"
              />
              <view class="vwb__redraw-panel-actions">
                <view class="vwb__action-btn vwb__action-btn--secondary" @tap="cancelRenderFrame">
                  <text class="vwb__action-label">取消</text>
                </view>
                <view
                  :class="['vwb__action-btn', 'vwb__action-btn--primary', { 'vwb__action-btn--disabled': busy === 'renderFrame' }]"
                  @tap="confirmRenderFrame"
                >
                  <text class="vwb__action-label">{{ busy === 'renderFrame' ? '渲染中…' : '确认渲染' }}</text>
                </view>
              </view>
            </view>
            <!-- 触发按钮 -->
            <view
              v-else
              :class="['vwb__action-btn', 'vwb__action-btn--secondary', { 'vwb__action-btn--disabled': busy || !shotId }]"
              style="flex: none"
              @tap="showRenderFramePanel = true"
            >
              <text class="vwb__action-icon">🖼</text>
              <text class="vwb__action-label">渲染故事版帧</text>
            </view>
          </view>

          <!-- 故事版提示词编辑区（T13） -->
          <view class="vwb__prompt-editor">
            <view class="vwb__prompt-editor-header">
              <text class="vwb__info-label">故事版提示词</text>
              <view v-if="promptEdited" class="vwb__prompt-dirty-badge">
                <text>已修改</text>
              </view>
            </view>
            <textarea
              v-model="editedStoryboardPrompt"
              class="vwb__prompt-textarea"
              placeholder="暂无故事版提示词"
              :maxlength="2000"
              :auto-height="true"
            />
          </view>

          <!-- 预览组装提示词（T13+T17） -->
          <view class="vwb__preview-section">
            <view class="vwb__preview-header">
              <text class="vwb__section-title">预览组装提示词</text>
              <view
                :class="['vwb__versions-refresh', { 'vwb__versions-refresh--spin': previewPromptLoading && currentType === 'storyboard' }]"
                @tap="handlePreviewPrompt"
              >
                <text>{{ (previewPromptLoading && currentType === 'storyboard') ? '⟳' : '🔍' }}</text>
                <text>{{ (previewPromptLoading && currentType === 'storyboard') ? '加载中…' : '获取' }}</text>
              </view>
            </view>

            <!-- 组装后三段式展示 -->
            <view v-if="previewPromptParts && previewPromptVisible && currentType === 'storyboard'" class="vwb__preview-parts">
              <view v-if="previewPromptParts.part1" class="vwb__preview-part">
                <text class="vwb__preview-part-label">Part 1 — 描述</text>
                <textarea
                  :value="previewPromptParts.part1"
                  class="vwb__preview-textarea"
                  disabled
                  :maxlength="-1"
                  :auto-height="true"
                />
              </view>
              <view v-if="previewPromptParts.part2" class="vwb__preview-part">
                <text class="vwb__preview-part-label">Part 2 — 运镜</text>
                <textarea
                  :value="previewPromptParts.part2"
                  class="vwb__preview-textarea"
                  disabled
                  :maxlength="-1"
                  :auto-height="true"
                />
              </view>
              <view v-if="previewPromptParts.part3" class="vwb__preview-part">
                <text class="vwb__preview-part-label">Part 3 — 质量/风格</text>
                <textarea
                  :value="previewPromptParts.part3"
                  class="vwb__preview-textarea"
                  disabled
                  :maxlength="-1"
                  :auto-height="true"
                />
              </view>

              <!-- 完整组装提示词 -->
              <view class="vwb__preview-part">
                <text class="vwb__preview-part-label">完整组装</text>
                <textarea
                  :value="previewPromptText"
                  class="vwb__preview-textarea vwb__preview-textarea--full"
                  disabled
                  :maxlength="-1"
                  :auto-height="true"
                />
              </view>

              <!-- 复制按钮 -->
              <view class="vwb__preview-actions">
                <view class="vwb__action-btn vwb__action-btn--secondary" @tap="copyPreviewPrompt">
                  <text class="vwb__action-icon">📋</text>
                  <text class="vwb__action-label">复制完整提示词</text>
                </view>
                <view class="vwb__action-btn vwb__action-btn--secondary" @tap="closePreviewPrompt">
                  <text class="vwb__action-label">收起</text>
                </view>
              </view>
            </view>

            <!-- 空状态 -->
            <view v-if="!previewPromptText && !previewPromptLoading && currentType === 'storyboard'" class="vwb__placeholder vwb__placeholder--compact">
              <text class="vwb__placeholder-desc">点击"获取"查看后端组装后的完整提示词</text>
            </view>
          </view>

          <!-- 故事版版本列表（T13） -->
          <view v-if="storyboardVersions.length > 0" class="vwb__versions">
            <view class="vwb__versions-header">
              <text class="vwb__section-title">历史版本（{{ storyboardVersions.length }}）</text>
              <view
                v-if="storyboardVersionsLoading"
                class="vwb__versions-refresh vwb__versions-refresh--spin"
                @tap="refreshStoryboardVersions"
              >
                <text>⟳</text>
              </view>
              <view v-else class="vwb__versions-refresh" @tap="refreshStoryboardVersions">
                <text>⟳ 刷新</text>
              </view>
            </view>

            <view
              v-for="ver in storyboardVersions"
              :key="ver.id"
              :class="['vwb__version-item', { 'vwb__version-item--master': ver.is_master }]"
            >
              <image
                :src="videoAssetUrl(ver.file_path)"
                class="vwb__version-thumb"
                mode="aspectFill"
                @error="onVersionThumbError(ver.id)"
              />
              <view class="vwb__version-info">
                <text class="vwb__version-name">{{ ver.name }}</text>
                <text class="vwb__version-meta">rev {{ ver.revision }}</text>
                <view v-if="ver.is_master" class="vwb__version-master-tag">
                  <text>当前主版</text>
                </view>
              </view>
              <view
                v-if="!ver.is_master"
                class="vwb__version-action"
                @tap="setAsMasterStoryboard(ver.id)"
              >
                <text>设为主版本</text>
              </view>
            </view>
          </view>

          <!-- 故事版空状态 -->
          <view v-if="!shotData?.storyboard_image_url && storyboardVersions.length === 0" class="vwb__placeholder">
            <text class="vwb__placeholder-icon">🎬</text>
            <text class="vwb__placeholder-title">暂无故事版</text>
            <text class="vwb__placeholder-desc">点击下方"重新生成"创建故事版图片</text>
          </view>
        </view>

        <!-- ========== 场景卡片（T15）========== -->
        <view v-else-if="currentType === 'scene'" class="vwb__card-content">
          <!-- 加载中 -->
          <view v-if="sceneLoading" class="vwb__placeholder">
            <text class="vwb__placeholder-icon">⏳</text>
            <text class="vwb__placeholder-title">加载场景资产中…</text>
          </view>

          <!-- 场景参考图预览 -->
          <view v-if="sceneAssets.length > 0 && !sceneLoading" class="vwb__preview-section">
            <image
              :src="videoAssetUrl(sceneAssets[0].file_path)"
              class="vwb__preview-image"
              mode="aspectFit"
            />
          </view>

          <!-- 场景资产列表（多选） -->
          <view v-if="sceneAssets.length > 0 && !sceneLoading" class="vwb__asset-list">
            <view
              v-for="asset in sceneAssets"
              :key="asset.id"
              :class="['vwb__asset-card', { 'vwb__asset-card--selected': selectedSceneAssetId === asset.id }]"
              @tap="selectSceneAsset(asset.id)"
            >
              <image
                :src="videoAssetUrl(asset.file_path)"
                class="vwb__asset-thumb"
                mode="aspectFill"
              />
              <view class="vwb__asset-info">
                <text class="vwb__asset-name">{{ asset.name || '场景资产' }}</text>
                <view :class="['vwb__badge', `vwb__badge--${assetStatusBadge(asset)}`]">
                  <text>{{ assetStatusLabel(asset) }}</text>
                </view>
              </view>
              <view v-if="selectedSceneAssetId === asset.id" class="vwb__asset-check">
                <text>✓</text>
              </view>
            </view>
          </view>

          <!-- 场景信息 -->
          <view v-if="!sceneLoading" class="vwb__info-section">
            <view v-if="shotData?.scene_location" class="vwb__info-row">
              <text class="vwb__info-label">场景位置</text>
              <text class="vwb__info-text">{{ shotData.scene_location }}</text>
            </view>
            <view v-if="shotData?.time_of_day" class="vwb__info-row">
              <text class="vwb__info-label">时间</text>
              <text class="vwb__info-text">{{ shotData.time_of_day }}</text>
            </view>
            <view v-if="shotData?.dialogue_or_narration" class="vwb__info-row">
              <text class="vwb__info-label">氛围/对白</text>
              <text class="vwb__info-text vwb__info-text--prompt">{{ shotData.dialogue_or_narration }}</text>
            </view>
          </view>

          <!-- 场景提示词编辑区（T15） -->
          <view v-if="!sceneLoading" class="vwb__prompt-editor">
            <view class="vwb__prompt-editor-header">
              <text class="vwb__info-label">场景提示词</text>
              <view v-if="scenePromptEdited" class="vwb__prompt-dirty-badge">
                <text>已修改</text>
              </view>
            </view>
            <textarea
              v-model="editedScenePrompt"
              class="vwb__prompt-textarea"
              placeholder="暂无场景提示词"
              :maxlength="2000"
              :auto-height="true"
            />
          </view>

          <!-- 场景重绘面板 -->
          <view v-if="showSceneRedrawPrompt && !sceneLoading" class="vwb__redraw-panel">
            <text class="vwb__redraw-panel-title">重绘提示词（可选）</text>
            <textarea
              v-model="redrawPromptText"
              class="vwb__redraw-textarea"
              placeholder="输入重绘提示词，留空则使用默认提示词"
              :maxlength="500"
              :auto-height="true"
            />
            <view class="vwb__redraw-panel-actions">
              <view class="vwb__action-btn vwb__action-btn--secondary" @tap="cancelSceneRedraw">
                <text class="vwb__action-label">取消</text>
              </view>
              <view class="vwb__action-btn vwb__action-btn--primary" @tap="confirmSceneRedraw">
                <text class="vwb__action-label">确认重绘</text>
              </view>
            </view>
          </view>

          <!-- 空状态 -->
          <view v-if="!sceneLoading && sceneAssets.length === 0 && !shotData?.scene_location" class="vwb__placeholder">
            <text class="vwb__placeholder-icon">🏞</text>
            <text class="vwb__placeholder-title">暂无场景详情</text>
            <text class="vwb__placeholder-desc">先生成镜头详情以获取场景信息，或点击下方"重新生成"创建场景参考图</text>
          </view>
        </view>

        <!-- ========== 视频卡片（T14）========== -->
        <view v-else-if="currentType === 'video'" class="vwb__card-content">
          <!-- 视频播放器 -->
          <view v-if="shotData?.video_url" class="vwb__preview-section">
            <!-- #ifdef MP-WEIXIN -->
            <view class="vwb__fallback">
              <text class="vwb__fallback-icon">▶</text>
              <text class="vwb__fallback-title">小程序内不支持播放视频</text>
              <text class="vwb__fallback-desc">视频为跨域资源，请复制链接在浏览器中打开</text>
              <button
                class="vwb__fallback-btn"
                open-type="launchApp"
                @tap="openVideoInBrowser"
              >
                请在浏览器中打开
              </button>
            </view>
            <!-- #endif -->
            <!-- #ifndef MP-WEIXIN -->
            <video
              :src="assetUrl(shotData.video_url)"
              class="vwb__preview-video"
              controls
            />
            <!-- #endif -->
          </view>

          <!-- 生成失败提示 + 重试 -->
          <view v-if="shotData?.status === 'failed'" class="vwb__error-section">
            <text class="vwb__error-icon">⚠</text>
            <view class="vwb__error-content">
              <text class="vwb__error-title">视频生成失败</text>
              <text v-if="shotData?.error_message" class="vwb__error-desc">{{ shotData.error_message }}</text>
            </view>
            <view
              :class="['vwb__action-btn', 'vwb__action-btn--primary', { 'vwb__action-btn--disabled': busy || !shotData }]"
              @tap="handleVideoRetry"
            >
              <text class="vwb__action-icon">⟳</text>
              <text class="vwb__action-label">重试</text>
            </view>
          </view>

          <!-- 视频元数据 -->
          <view class="vwb__info-section">
            <view class="vwb__info-row">
              <text class="vwb__info-label">状态</text>
              <view :class="['vwb__badge', `vwb__badge--${statusBadge(shotData)}`]">
                <text>{{ statusLabel(shotData) }}</text>
              </view>
            </view>
            <view v-if="videoMetaInfo" class="vwb__info-row">
              <text class="vwb__info-label">视频元信息</text>
              <text class="vwb__info-text">{{ videoMetaInfo }}</text>
            </view>
          </view>

          <!-- 视频片段管理（T22） -->
          <ClipTimeline
            :shot-id="shotId"
            @updated="emit('updated')"
          />

          <!-- 宽高比选择器（T14） -->
          <view class="vwb__param-section">
            <text class="vwb__section-title">宽高比</text>
            <view class="vwb__param-options">
              <view
                v-for="ratio in aspectRatioOptions"
                :key="ratio.value"
                :class="['vwb__param-chip', { 'vwb__param-chip--active': selectedAspectRatio === ratio.value }]"
                @tap="selectedAspectRatio = ratio.value"
              >
                <text>{{ ratio.label }}</text>
              </view>
            </view>
          </view>

          <!-- 渲染参数：时长选择（T14） -->
          <view class="vwb__param-section">
            <text class="vwb__section-title">视频时长</text>
            <view class="vwb__param-options">
              <view
                v-for="dur in durationOptions"
                :key="dur"
                :class="['vwb__param-chip', { 'vwb__param-chip--active': selectedDuration === dur }]"
                @tap="selectedDuration = dur"
              >
                <text>{{ dur }}s</text>
              </view>
            </view>
          </view>

          <!-- 渲染参数：尺寸 / 方向（T14） -->
          <view class="vwb__param-section">
            <text class="vwb__section-title">视频尺寸</text>
            <view class="vwb__param-options">
              <view
                v-for="size in sizeOptions"
                :key="size.value"
                :class="['vwb__param-chip', { 'vwb__param-chip--active': selectedSize === size.value }]"
                @tap="selectedSize = size.value"
              >
                <text>{{ size.label }}</text>
              </view>
            </view>
          </view>

          <view class="vwb__param-section">
            <text class="vwb__section-title">画面方向</text>
            <view class="vwb__param-options">
              <view
                v-for="ori in orientationOptions"
                :key="ori.value"
                :class="['vwb__param-chip', { 'vwb__param-chip--active': selectedOrientation === ori.value }]"
                @tap="selectedOrientation = ori.value"
              >
                <text>{{ ori.label }}</text>
              </view>
            </view>
          </view>

          <!-- 视频提示词编辑区（T14） -->
          <view class="vwb__prompt-editor">
            <view class="vwb__prompt-editor-header">
              <text class="vwb__info-label">视频提示词</text>
              <view v-if="videoPromptEdited" class="vwb__prompt-dirty-badge">
                <text>已修改</text>
              </view>
            </view>
            <textarea
              v-model="editedVideoPrompt"
              class="vwb__prompt-textarea"
              placeholder="暂无视频提示词"
              :maxlength="3000"
              :auto-height="true"
            />
          </view>

          <!-- 预览组装提示词（T14+T17） -->
          <view class="vwb__preview-section">
            <view class="vwb__preview-header">
              <text class="vwb__section-title">预览组装提示词</text>
              <view
                :class="['vwb__versions-refresh', { 'vwb__versions-refresh--spin': previewPromptLoading && currentType === 'video' }]"
                @tap="handlePreviewPrompt"
              >
                <text>{{ (previewPromptLoading && currentType === 'video') ? '⟳' : '🔍' }}</text>
                <text>{{ (previewPromptLoading && currentType === 'video') ? '加载中…' : '获取' }}</text>
              </view>
            </view>

            <!-- 组装后三段式展示 -->
            <view v-if="previewPromptParts && previewPromptVisible && currentType === 'video'" class="vwb__preview-parts">
              <view v-if="previewPromptParts.part1" class="vwb__preview-part">
                <text class="vwb__preview-part-label">Part 1 — 描述</text>
                <textarea
                  :value="previewPromptParts.part1"
                  class="vwb__preview-textarea"
                  disabled
                  :maxlength="-1"
                  :auto-height="true"
                />
              </view>
              <view v-if="previewPromptParts.part2" class="vwb__preview-part">
                <text class="vwb__preview-part-label">Part 2 — 运镜</text>
                <textarea
                  :value="previewPromptParts.part2"
                  class="vwb__preview-textarea"
                  disabled
                  :maxlength="-1"
                  :auto-height="true"
                />
              </view>
              <view v-if="previewPromptParts.part3" class="vwb__preview-part">
                <text class="vwb__preview-part-label">Part 3 — 质量/风格</text>
                <textarea
                  :value="previewPromptParts.part3"
                  class="vwb__preview-textarea"
                  disabled
                  :maxlength="-1"
                  :auto-height="true"
                />
              </view>

              <!-- 完整组装提示词 -->
              <view class="vwb__preview-part">
                <text class="vwb__preview-part-label">完整组装</text>
                <textarea
                  :value="previewPromptText"
                  class="vwb__preview-textarea vwb__preview-textarea--full"
                  disabled
                  :maxlength="-1"
                  :auto-height="true"
                />
              </view>

              <!-- 复制按钮 -->
              <view class="vwb__preview-actions">
                <view class="vwb__action-btn vwb__action-btn--secondary" @tap="copyPreviewPrompt">
                  <text class="vwb__action-icon">📋</text>
                  <text class="vwb__action-label">复制完整提示词</text>
                </view>
                <view class="vwb__action-btn vwb__action-btn--secondary" @tap="closePreviewPrompt">
                  <text class="vwb__action-label">收起</text>
                </view>
              </view>
            </view>

            <!-- 空状态 -->
            <view v-if="!previewPromptText && !previewPromptLoading && currentType === 'video'" class="vwb__placeholder vwb__placeholder--compact">
              <text class="vwb__placeholder-desc">点击"获取"查看后端组装后的完整提示词</text>
            </view>
          </view>

          <!-- 空状态 -->
          <view v-if="!shotData?.video_url && shotData?.status !== 'failed'" class="vwb__placeholder">
            <text class="vwb__placeholder-icon">▶</text>
            <text class="vwb__placeholder-title">暂无视频</text>
            <text class="vwb__placeholder-desc">点击下方"重新生成"生成视频</text>
          </view>
        </view>
      </scroll-view>

      <!-- 底部操作栏：6 个功能按钮 -->
      <view class="vwb__actions">
        <!-- 第一行：主要操作 -->
        <view class="vwb__actions-row">
          <view
            :class="['vwb__action-btn', 'vwb__action-btn--primary', { 'vwb__action-btn--disabled': busy || !currentResource }]"
            @tap="handleRegenerate"
          >
            <text v-if="busy === 'regenerate'" class="vwb__action-spinner">⟳</text>
            <text v-else class="vwb__action-icon">🔄</text>
            <text class="vwb__action-label">{{ busy === 'regenerate' ? '生成中...' : '重新生成' }}</text>
          </view>

          <view
            :class="['vwb__action-btn', 'vwb__action-btn--primary', { 'vwb__action-btn--disabled': busy || !currentResource }]"
            @tap="handleUploadReplace"
          >
            <text class="vwb__action-icon">📤</text>
            <text class="vwb__action-label">上传替换</text>
          </view>

          <view
            :class="['vwb__action-btn', 'vwb__action-btn--primary', { 'vwb__action-btn--disabled': busy || !currentResource }]"
            @tap="handleRedraw"
          >
            <text class="vwb__action-icon">🎨</text>
            <text class="vwb__action-label">重绘</text>
          </view>
        </view>

        <!-- 第二行：辅助操作 -->
        <view class="vwb__actions-row">
          <view
            :class="['vwb__action-btn', 'vwb__action-btn--secondary', { 'vwb__action-btn--disabled': busy || !currentResource }]"
            @tap="handleReanalyzePrompt"
          >
            <text class="vwb__action-icon">🔍</text>
            <text class="vwb__action-label">分析提示词</text>
          </view>

          <view
            :class="['vwb__action-btn', 'vwb__action-btn--secondary', { 'vwb__action-btn--disabled': busy || !currentResource }]"
            @tap="handlePromptSave"
          >
            <text class="vwb__action-icon">💾</text>
            <text class="vwb__action-label">保存提示词</text>
          </view>

          <view
            :class="['vwb__action-btn', 'vwb__action-btn--danger', { 'vwb__action-btn--disabled': busy }]"
            @tap="handleDelete"
          >
            <text class="vwb__action-icon">🗑</text>
            <text class="vwb__action-label">删除</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { videoApi } from '@/api'
import { BASE_URL } from '@/utils/constants'
import { videoAssetUrl } from '@/utils/url'
import ClipTimeline from '@/components/clip-timeline/clip-timeline.vue'
import type { ChapterVideoShot, VideoAsset, VideoStylePreset } from '@/api/types'

// ── 卡片类型定义 ──
type CardType = 'character' | 'storyboard' | 'scene' | 'video'

// ── Props ──
interface WorkbenchProps {
  /** 控制弹窗显隐 */
  visible: boolean
  /** 镜头 ID */
  shotId: number
  /** 镜头完整数据 */
  shotData: ChapterVideoShot | null
  /** 工作流 ID */
  workflowId: number
  /** 章节 ID */
  chapterId: number
  /** 初始激活的卡片类型 */
  initialType?: CardType
}

const props = withDefaults(defineProps<WorkbenchProps>(), {
  initialType: 'storyboard',
})

// ── Emits ──
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'updated', result?: unknown): void
}>()

// ── 状态 ──
/** 当前激活的卡片类型 */
const currentType = ref<CardType>(props.initialType || 'storyboard')
/** 忙碌标识：null = 空闲，字符串 = 当前操作名 */
const busy = ref<string | null>(null)

/** 监听 initialType 变化，同步到 currentType */
watch(
  () => props.initialType,
  (val) => {
    if (val) currentType.value = val
  }
)

// ── 角色资产相关状态（T12）──
/** 角色资产列表 */
const characterAssets = ref<VideoAsset[]>([])
/** 资产加载中 */
const characterLoading = ref(false)
/** 当前选中的角色资产 ID */
const selectedCharacterAssetId = ref<number | null>(null)
/** 图片加载失败的资产 ID 集合 */
const assetImageErrors = ref<Set<number>>(new Set())

// ── 故事版相关状态（T13）──
/** 故事版历史版本列表 */
const storyboardVersions = ref<VideoAsset[]>([])
/** 版本加载中 */
const storyboardVersionsLoading = ref(false)
/** 编辑中的故事版提示词 */
const editedStoryboardPrompt = ref('')

// ── 重绘相关状态 ──
/** 是否显示重绘提示词面板 */
const showRedrawPrompt = ref(false)
/** 重绘提示词文本 */
const redrawPromptText = ref('')

// ── 视频相关状态（T14）──
/** 编辑中的视频提示词 */
const editedVideoPrompt = ref('')
/** 原始视频提示词 */
const originalVideoPrompt = ref('')
/** 选中的宽高比 */
const selectedAspectRatio = ref<'16:9' | '9:16' | '1:1' | '4:3' | '3:2' | '2:3'>('16:9')
/** 选中的视频时长（秒） */
const selectedDuration = ref<5 | 10 | 15>(15)
/** 选中的视频尺寸 */
const selectedSize = ref<'small' | 'medium' | 'large'>('large')
/** 选中的画面方向 */
const selectedOrientation = ref<'landscape' | 'portrait'>('landscape')

// ── 场景相关状态（T15）──
/** 场景资产列表 */
const sceneAssets = ref<VideoAsset[]>([])
/** 场景资产加载中 */
const sceneLoading = ref(false)
/** 当前选中的场景资产 ID */
const selectedSceneAssetId = ref<number | null>(null)
/** 编辑中的场景提示词 */
const editedScenePrompt = ref('')
/** 原始场景提示词 */
const originalScenePrompt = ref('')
/** 是否显示场景重绘面板 */
const showSceneRedrawPrompt = ref(false)

// ── 渲染故事版帧相关状态（T23）──
/** 是否显示渲染帧面板 */
const showRenderFramePanel = ref(false)
/** 渲染帧提示词 */
const renderFramePrompt = ref('')

// ── 镜头风格预设相关状态（T21）──
/** 风格预设列表 */
const stylePresets = ref<VideoStylePreset[]>([])
/** 风格预设加载中 */
const stylePresetsLoading = ref(false)
/** 当前镜头绑定的风格预设名称 */
const shotStylePresetName = ref('')
/** 当前选中的预设 ID */
const selectedStylePresetId = ref<number | null>(null)

// ── 预览组装提示词（T17）──
/** 预览面板是否可见 */
const previewPromptVisible = ref(false)
/** 组装后的完整提示词文本 */
const previewPromptText = ref('')
/** 提示词三段式分解 */
const previewPromptParts = ref<{ part1: string; part2: string; part3: string | null } | null>(null)
/** 预览加载中 */
const previewPromptLoading = ref(false)

// ── 提示词编辑追踪 ──
/** 原始故事版提示词（用于判断是否修改） */
const originalStoryboardPrompt = ref('')
/** 提示词是否被修改 */
const promptEdited = computed(() => {
  return editedStoryboardPrompt.value !== originalStoryboardPrompt.value
})

/** 视频提示词是否被修改（T14） */
const videoPromptEdited = computed(() => {
  return editedVideoPrompt.value !== originalVideoPrompt.value
})

/** 场景提示词是否被修改（T15） */
const scenePromptEdited = computed(() => {
  return editedScenePrompt.value !== originalScenePrompt.value
})

/** 视频元信息（时长、分辨率等展示文本）（T14） */
const videoMetaInfo = computed(() => {
  const parts: string[] = []
  if (selectedDuration.value) {
    parts.push(`时长 ${selectedDuration.value}s`)
  }
  if (selectedAspectRatio.value) {
    parts.push(`宽高比 ${selectedAspectRatio.value}`)
  }
  if (selectedSize.value) {
    parts.push(`尺寸 ${selectedSize.value === 'large' ? '大' : selectedSize.value === 'medium' ? '中' : '小'}`)
  }
  parts.push(`方向 ${selectedOrientation.value === 'landscape' ? '横屏' : '竖屏'}`)
  return parts.length > 0 ? parts.join(' · ') : ''
})

/** 标签栏配置 */
interface TabConfig {
  key: CardType
  label: string
  icon: string
}

const tabs: TabConfig[] = [
  { key: 'character', label: '角色', icon: '👤' },
  { key: 'storyboard', label: '故事版', icon: '🎬' },
  { key: 'scene', label: '场景', icon: '🏞' },
  { key: 'video', label: '视频', icon: '▶' },
]

// ── 选项常量（T14）──

/** 宽高比选项 */
const aspectRatioOptions: Array<{ value: '16:9' | '9:16' | '1:1' | '4:3' | '3:2' | '2:3'; label: string }> = [
  { value: '16:9', label: '16:9' },
  { value: '9:16', label: '9:16' },
  { value: '1:1', label: '1:1' },
  { value: '4:3', label: '4:3' },
  { value: '3:2', label: '3:2' },
  { value: '2:3', label: '2:3' },
]

/** 视频时长选项 */
const durationOptions: Array<5 | 10 | 15> = [5, 10, 15]

/** 视频尺寸选项 */
const sizeOptions: Array<{ value: 'small' | 'medium' | 'large'; label: string }> = [
  { value: 'small', label: '小' },
  { value: 'medium', label: '中' },
  { value: 'large', label: '大' },
]

/** 画面方向选项 */
const orientationOptions: Array<{ value: 'landscape' | 'portrait'; label: string }> = [
  { value: 'landscape', label: '横屏' },
  { value: 'portrait', label: '竖屏' },
]

/** 镜头序号（从 shotData 中读取） */
const shotIndex = computed(() => props.shotData?.shot_index ?? props.shotId)

/** 当前资源（根据卡片类型从 shotData 派生） */
const currentResource = computed(() => {
  if (!props.shotData) return null
  const shot = props.shotData

  switch (currentType.value) {
    case 'character':
      // 角色资源：从 shot.characters 和 character_prompts 派生，附加选中资产
      return {
        id: shot.id,
        type: 'character' as const,
        characters: shot.characters || [],
        prompts: shot.character_prompts || [],
        selectedAssetId: selectedCharacterAssetId.value,
      }
    case 'storyboard':
      // 故事版资源：图片 URL + 提示词
      return {
        id: shot.id,
        type: 'storyboard' as const,
        url: shot.storyboard_image_url ?? null,
        prompt: shot.storyboard_prompt ?? null,
        hasAsset: !!shot.storyboard_image_url,
      }
    case 'scene':
      // 场景资源：位置 + 时间 + 场景提示词
      return {
        id: shot.id,
        type: 'scene' as const,
        location: shot.scene_location ?? null,
        timeOfDay: shot.time_of_day ?? null,
        prompt: shot.scene_prompt ?? null,
      }
    case 'video':
      // 视频资源：URL + 提示词
      return {
        id: shot.id,
        type: 'video' as const,
        url: shot.video_url ?? null,
        prompt: shot.video_prompt ?? null,
        hasAsset: !!shot.video_url,
      }
    default:
      return null
  }
})

// ── 工具方法 ──

/** 生成静态资源完整 URL */
function assetUrl(path?: string | null): string {
  if (!path) return ''
  if (path.startsWith('http://') || path.startsWith('https://') || path.startsWith('/static/')) return path
  return `${BASE_URL}/static/video/${path.replace(/^video_outputs[/\\]/, '')}`
}

/** 角色资产缩略图 URL */
function characterAssetThumb(asset: VideoAsset): string {
  // 如果该资产之前加载失败，返回占位图
  if (assetImageErrors.value.has(asset.id)) {
    return ''
  }
  // 使用统一的 videoAssetUrl 处理远程/本地路径
  return videoAssetUrl(asset.file_path) || ''
}

/** 资产缩略图加载失败回调 */
function onAssetThumbError(assetId: number) {
  assetImageErrors.value.add(assetId)
}

/** 版本缩略图加载失败回调（降级处理，不阻塞） */
function onVersionThumbError(_versionId: number) {
  // 静默处理，图片组件会显示默认占位
}

/** 状态徽标样式类名 */
function statusBadge(shot: ChapterVideoShot | null): string {
  if (!shot) return 'pending'
  if (shot.status === 'failed') return 'failed'
  if (shot.status === 'video_ready') return 'success'
  if (shot.status === 'storyboard_ready') return 'info'
  return 'pending'
}

/** 状态文本标签 */
function statusLabel(shot: ChapterVideoShot | null): string {
  if (!shot) return '未知'
  const labels: Record<string, string> = {
    pending: '待处理',
    storyboard_generating: '故事版生成中',
    storyboard_ready: '故事版已完成',
    video_generating: '视频生成中',
    video_ready: '视频已完成',
    failed: '失败',
  }
  return labels[shot.status] || shot.status
}

/** 资产状态徽标样式 */
function assetStatusBadge(asset: VideoAsset): string {
  if (asset.status === 'ready' || asset.status === 'completed') return 'success'
  if (asset.status === 'failed') return 'failed'
  if (asset.status === 'processing' || asset.status === 'generating') return 'info'
  return 'pending'
}

/** 资产状态文本 */
function assetStatusLabel(asset: VideoAsset): string {
  const labels: Record<string, string> = {
    ready: '已完成',
    completed: '已完成',
    failed: '失败',
    processing: '处理中',
    generating: '生成中',
    pending: '待处理',
    draft: '草稿',
  }
  return labels[asset.status] || asset.status
}

// ── 标签切换 ──

/** 切换当前激活的卡片类型 */
function switchTab(type: CardType) {
  currentType.value = type
  // 切换标签时取消重绘面板
  showRedrawPrompt.value = false
  showSceneRedrawPrompt.value = false
  showRenderFramePanel.value = false
  renderFramePrompt.value = ''
  // 重置预览提示词状态
  previewPromptVisible.value = false
  previewPromptText.value = ''
  previewPromptParts.value = null
}

// ── 加载数据 ──

/** 加载角色资产列表 */
async function loadCharacterAssets() {
  if (!props.chapterId) return
  characterLoading.value = true
  try {
    const result = await videoApi.listVideoAssets(props.chapterId, 'character')
    characterAssets.value = result.assets || []
    // 首次加载时清除错误记录
    assetImageErrors.value = new Set()
  } catch (e: any) {
    uni.showToast({ title: e?.message || '加载角色资产失败', icon: 'none' })
    characterAssets.value = []
  } finally {
    characterLoading.value = false
  }
}

/** 加载故事版版本列表 */
async function loadStoryboardVersions() {
  if (!props.shotId) return
  storyboardVersionsLoading.value = true
  try {
    const result = await videoApi.getShotStoryboards(props.shotId)
    storyboardVersions.value = result.assets || []
  } catch (e: any) {
    uni.showToast({ title: e?.message || '加载故事版版本失败', icon: 'none' })
    storyboardVersions.value = []
  } finally {
    storyboardVersionsLoading.value = false
  }
}

/** 刷新故事版版本列表 */
async function refreshStoryboardVersions() {
  await loadStoryboardVersions()
}

/** 加载场景资产列表（T15） */
async function loadSceneAssets() {
  if (!props.chapterId) return
  sceneLoading.value = true
  try {
    const result = await videoApi.listVideoAssets(props.chapterId, 'scene')
    sceneAssets.value = (result.assets || []).filter(
      // 只显示属于当前镜头的场景资产（如果有 shot_id 则过滤）
      (a) => a.shot_id == null || a.shot_id === props.shotId
    )
  } catch (e: any) {
    uni.showToast({ title: e?.message || '加载场景资产失败', icon: 'none' })
    sceneAssets.value = []
  } finally {
    sceneLoading.value = false
  }
}

/** 选择场景资产（T15） */
function selectSceneAsset(assetId: number) {
  selectedSceneAssetId.value = assetId === selectedSceneAssetId.value ? null : assetId
}

/** 视频重试（T14） */
async function handleVideoRetry() {
  if (busy.value || !props.shotId) return
  busy.value = 'retryVideo'
  try {
    await videoApi.regenerateChapterWorkflowVideo(props.shotId, undefined, undefined, selectedAspectRatio.value as '16:9' | '9:16')
    uni.showToast({ title: '视频重新生成已提交', icon: 'success' })
    emit('updated')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '重试视频生成失败', icon: 'none' })
  } finally {
    busy.value = null
  }
}

/** 小程序视频兜底：在浏览器中打开（T14） */
function openVideoInBrowser() {
  const url = props.shotData?.video_url
  if (!url) return
  const fullUrl = assetUrl(url)
  // uni-app 复制链接到剪贴板
  uni.setClipboardData({
    data: fullUrl,
    success() {
      uni.showToast({ title: '链接已复制，请在浏览器中粘贴打开', icon: 'none', duration: 2500 })
    },
    fail() {
      // H5 环境兜底
      uni.showModal({
        title: '请在浏览器中打开',
        content: fullUrl,
        showCancel: false,
      })
    },
  })
}

/** 取消场景重绘（T15） */
function cancelSceneRedraw() {
  showSceneRedrawPrompt.value = false
  redrawPromptText.value = ''
}

/** 确认场景重绘（T15） */
async function confirmSceneRedraw() {
  if (busy.value || !selectedSceneAssetId.value) return
  showSceneRedrawPrompt.value = false
  busy.value = 'redraw'
  try {
    const assetId = selectedSceneAssetId.value
    await videoApi.regenerateVideoAsset(assetId, {
      prompt: redrawPromptText.value || undefined,
    })
    uni.showToast({ title: '已提交场景重绘', icon: 'success' })
    await loadSceneAssets()
    emit('updated')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '场景重绘失败', icon: 'none' })
  } finally {
    busy.value = null
    redrawPromptText.value = ''
  }
}

/** 选择角色资产 */
function selectCharacterAsset(assetId: number) {
  selectedCharacterAssetId.value = assetId === selectedCharacterAssetId.value ? null : assetId
}

/** 设置故事版主版本 */
async function setAsMasterStoryboard(assetId: number) {
  if (busy.value) return
  busy.value = 'setMaster'
  try {
    await videoApi.setMasterStoryboard(props.shotId, assetId)
    uni.showToast({ title: '已设为主版本', icon: 'success' })
    // 刷新版本列表和镜头数据
    await loadStoryboardVersions()
    emit('updated')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '设置主版本失败', icon: 'none' })
  } finally {
    busy.value = null
  }
}

// ── 监听：标签切换时加载对应数据 ──

/** 监听 currentType 变化，加载对应数据 */
watch(currentType, (type) => {
  if (type === 'character') {
    loadCharacterAssets()
  } else if (type === 'storyboard') {
    loadStoryboardVersions()
    loadStylePresets()
    // 同步提示词编辑区
    editedStoryboardPrompt.value = props.shotData?.storyboard_prompt || ''
    originalStoryboardPrompt.value = props.shotData?.storyboard_prompt || ''
  } else if (type === 'scene') {
    // T15：加载场景资产 + 同步场景提示词
    loadSceneAssets()
    editedScenePrompt.value = props.shotData?.scene_prompt || ''
    originalScenePrompt.value = props.shotData?.scene_prompt || ''
  } else if (type === 'video') {
    // T14：同步视频提示词
    editedVideoPrompt.value = props.shotData?.video_prompt || ''
    originalVideoPrompt.value = props.shotData?.video_prompt || ''
  }
})

/** 监听 shotData 变化，刷新提示词编辑区 */
watch(
  () => props.shotData?.storyboard_prompt,
  (newPrompt) => {
    if (currentType.value === 'storyboard') {
      editedStoryboardPrompt.value = newPrompt || ''
      originalStoryboardPrompt.value = newPrompt || ''
    }
  }
)

/** 监听 shotData 视频提示词变化（T14） */
watch(
  () => props.shotData?.video_prompt,
  (newPrompt) => {
    if (currentType.value === 'video') {
      editedVideoPrompt.value = newPrompt || ''
      originalVideoPrompt.value = newPrompt || ''
    }
  }
)

/** 监听 shotData 场景提示词变化（T15） */
watch(
  () => props.shotData?.scene_prompt,
  (newPrompt) => {
    if (currentType.value === 'scene') {
      editedScenePrompt.value = newPrompt || ''
      originalScenePrompt.value = newPrompt || ''
    }
  }
)

/** 监听弹窗打开，加载初始数据 */
watch(
  () => props.visible,
  (vis) => {
    if (vis) {
      nextTick(() => {
        if (currentType.value === 'character') {
          loadCharacterAssets()
        } else if (currentType.value === 'storyboard') {
          loadStoryboardVersions()
          loadStylePresets()
          editedStoryboardPrompt.value = props.shotData?.storyboard_prompt || ''
          originalStoryboardPrompt.value = props.shotData?.storyboard_prompt || ''
        } else if (currentType.value === 'scene') {
          // T15：初始加载场景数据
          loadSceneAssets()
          editedScenePrompt.value = props.shotData?.scene_prompt || ''
          originalScenePrompt.value = props.shotData?.scene_prompt || ''
        } else if (currentType.value === 'video') {
          // T14：初始同步视频提示词
          editedVideoPrompt.value = props.shotData?.video_prompt || ''
          originalVideoPrompt.value = props.shotData?.video_prompt || ''
        }
      })
    } else {
      // 关闭时重置状态
      showRedrawPrompt.value = false
      showSceneRedrawPrompt.value = false
      showRenderFramePanel.value = false
      renderFramePrompt.value = ''
      redrawPromptText.value = ''
    }
  }
)

// ── 关闭弹窗 ──

/** 关闭工作台 */
function handleClose() {
  busy.value = null
  showRedrawPrompt.value = false
  showSceneRedrawPrompt.value = false
  showRenderFramePanel.value = false
  renderFramePrompt.value = ''
  previewPromptVisible.value = false
  previewPromptText.value = ''
  previewPromptParts.value = null
  emit('close')
}

// ── 6 个操作 Handler ──

/**
 * 1. 重新生成
 * 根据 currentType 调用对应的重新生成 API
 */
async function handleRegenerate() {
  if (busy.value || !currentResource.value) return

  // 角色类型需要先选中资产
  if (currentType.value === 'character' && !selectedCharacterAssetId.value) {
    uni.showToast({ title: '请先选择要重新生成的角色资产', icon: 'none' })
    return
  }

  busy.value = 'regenerate'
  try {
    switch (currentType.value) {
      case 'character': {
        // T12：重新生成角色参考图
        const assetId = selectedCharacterAssetId.value!
        const selectedAsset = characterAssets.value.find((a) => a.id === assetId)
        await videoApi.regenerateVideoAsset(assetId, {
          prompt: selectedAsset?.prompt || undefined,
        })
        uni.showToast({ title: '已提交重新生成', icon: 'success' })
        // 刷新资产列表
        await loadCharacterAssets()
        break
      }
      case 'storyboard':
        // T13：重新生成故事版
        await videoApi.regenerateChapterWorkflowStoryboard(props.shotId)
        uni.showToast({ title: '已提交重新生成', icon: 'success' })
        await loadStoryboardVersions()
        break
      case 'video':
        // T14：重新生成视频（传递渲染参数）
        await videoApi.regenerateChapterWorkflowVideo(
          props.shotId,
          editedVideoPrompt.value || undefined,
          undefined, // reference_asset_ids 由后端按工作流配置取
          selectedAspectRatio.value as '16:9' | '9:16'
        )
        uni.showToast({ title: '已提交重新生成', icon: 'success' })
        break
      case 'scene':
        // T15：重新生成场景参考图
        if (!selectedSceneAssetId.value) {
          uni.showToast({ title: '请先选择场景资产，或先生成场景参考图', icon: 'none' })
          return
        }
        await videoApi.regenerateVideoAsset(selectedSceneAssetId.value, {
          prompt: editedScenePrompt.value || undefined,
        })
        uni.showToast({ title: '已提交场景重新生成', icon: 'success' })
        await loadSceneAssets()
        break
      default:
        uni.showToast({ title: `${getTypeLabel(currentType.value)} 重新生成即将实现`, icon: 'none' })
        break
    }
    emit('updated')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '操作失败', icon: 'none' })
  } finally {
    busy.value = null
  }
}

/**
 * 2. 上传替换
 * 根据 currentType 上传文件替换当前资源
 */
async function handleUploadReplace() {
  if (busy.value || !currentResource.value) return

  // 角色类型需要先选中资产
  if (currentType.value === 'character' && !selectedCharacterAssetId.value) {
    uni.showToast({ title: '请先选择要替换的角色资产', icon: 'none' })
    return
  }

  busy.value = 'upload'
  try {
    const type = currentType.value

    if (type === 'character') {
      // T12：选择图片后调用 replaceVideoAsset 替换角色资产
      const res = await uni.chooseImage({ count: 1, sizeType: ['compressed'] })
      if (res.tempFilePaths.length > 0) {
        const assetId = selectedCharacterAssetId.value!
        await videoApi.replaceVideoAsset(assetId, res.tempFilePaths[0])
        uni.showToast({ title: '角色资产已替换', icon: 'success' })
        await loadCharacterAssets()
        emit('updated')
      }
    } else if (type === 'storyboard') {
      // T13：选择图片后上传故事版
      const res = await uni.chooseImage({ count: 1, sizeType: ['compressed'] })
      if (res.tempFilePaths.length > 0) {
        await videoApi.uploadShotStoryboard(props.shotId, res.tempFilePaths[0])
        uni.showToast({ title: '故事版已上传', icon: 'success' })
        await loadStoryboardVersions()
        emit('updated')
      }
    } else if (type === 'video') {
      // T14：选择视频后上传
      const res = await uni.chooseVideo({ sourceType: ['album'] })
      if (res.tempFilePath) {
        await videoApi.uploadShotVideo(props.shotId, res.tempFilePath)
        uni.showToast({ title: '视频已上传', icon: 'success' })
        emit('updated')
      }
    } else if (type === 'scene') {
      // T15：选择图片后替换场景资产
      if (!selectedSceneAssetId.value) {
        uni.showToast({ title: '请先选择要替换的场景资产', icon: 'none' })
        return
      }
      const res = await uni.chooseImage({ count: 1, sizeType: ['compressed'] })
      if (res.tempFilePaths.length > 0) {
        await videoApi.replaceVideoAsset(selectedSceneAssetId.value, res.tempFilePaths[0])
        uni.showToast({ title: '场景资产已替换', icon: 'success' })
        await loadSceneAssets()
        emit('updated')
      }
    } else {
      uni.showToast({ title: '场景类型暂不支持上传', icon: 'none' })
    }
  } catch (e: any) {
    uni.showToast({ title: e?.message || '上传替换失败', icon: 'none' })
  } finally {
    busy.value = null
  }
}

/**
 * 3. 重绘
 * 根据 currentType 调用对应的重绘 API
 */
async function handleRedraw() {
  if (busy.value || !currentResource.value) return

  // 角色类型需要先选中资产
  if (currentType.value === 'character' && !selectedCharacterAssetId.value) {
    uni.showToast({ title: '请先选择要重绘的角色资产', icon: 'none' })
    return
  }

  // 角色类型显示重绘提示词面板（inline）
  if (currentType.value === 'character') {
    showRedrawPrompt.value = true
    redrawPromptText.value = ''
    return
  }

  // 非角色类型直接执行重绘
  busy.value = 'redraw'
  try {
    switch (currentType.value) {
      case 'storyboard':
        // T13：重新生成故事版
        await videoApi.regenerateChapterWorkflowStoryboard(props.shotId)
        uni.showToast({ title: '已提交重新生成', icon: 'success' })
        await loadStoryboardVersions()
        break
      case 'video':
        // T14：视频类型不支持蒙版重绘
        uni.showToast({ title: '视频类型不支持蒙版重绘，请使用"重新生成"', icon: 'none' })
        break
      case 'scene':
        // T15：场景重绘（需先选中场景资产）
        if (!selectedSceneAssetId.value) {
          uni.showToast({ title: '请先选择要重绘的场景资产', icon: 'none' })
          return
        }
        showSceneRedrawPrompt.value = true
        redrawPromptText.value = ''
        return // 退出函数，等待用户在面板中确认
      default:
        uni.showToast({ title: `${getTypeLabel(currentType.value)} 重绘即将实现`, icon: 'none' })
        break
    }
    emit('updated')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '重绘失败', icon: 'none' })
  } finally {
    busy.value = null
  }
}

/** 取消重绘 */
function cancelRedraw() {
  showRedrawPrompt.value = false
  redrawPromptText.value = ''
}

/** 确认重绘（角色类型） */
async function confirmRedraw() {
  if (busy.value || !selectedCharacterAssetId.value) return
  showRedrawPrompt.value = false
  busy.value = 'redraw'
  try {
    const assetId = selectedCharacterAssetId.value
    await videoApi.regenerateVideoAsset(assetId, {
      prompt: redrawPromptText.value || undefined,
    })
    uni.showToast({ title: '已提交重绘', icon: 'success' })
    await loadCharacterAssets()
    emit('updated')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '重绘失败', icon: 'none' })
  } finally {
    busy.value = null
    redrawPromptText.value = ''
  }
}

/**
 * 4. 删除
 * 删除当前卡片资源（需确认）
 */
async function handleDelete() {
  if (busy.value) return

  // 角色类型需要先选中资产
  if (currentType.value === 'character' && !selectedCharacterAssetId.value) {
    uni.showToast({ title: '请先选择要删除的角色资产', icon: 'none' })
    return
  }

  // 构建确认消息
  let confirmContent: string
  if (currentType.value === 'character') {
    const asset = characterAssets.value.find((a) => a.id === selectedCharacterAssetId.value)
    confirmContent = `确定要删除角色资产「${asset?.name || '未知'}」吗？此操作不可撤销。`
  } else {
    confirmContent = `确定要删除当前${getTypeLabel(currentType.value)}资源吗？此操作不可撤销。`
  }

  const confirmRes = await uni.showModal({
    title: '确认删除',
    content: confirmContent,
  })
  if (!confirmRes.confirm) return

  busy.value = 'delete'
  try {
    switch (currentType.value) {
      case 'character': {
        // T12：删除角色资产
        const assetId = selectedCharacterAssetId.value!
        await videoApi.deleteVideoAsset(assetId)
        uni.showToast({ title: '角色资产已删除', icon: 'success' })
        selectedCharacterAssetId.value = null
        await loadCharacterAssets()
        break
      }
      case 'storyboard':
        // T13：清除故事版
        await videoApi.clearShotStoryboard(props.shotId)
        uni.showToast({ title: '故事版已清除', icon: 'success' })
        storyboardVersions.value = []
        break
      case 'video':
        // T14：清除视频
        await videoApi.clearShotVideo(props.shotId)
        uni.showToast({ title: '视频已清除', icon: 'success' })
        break
      case 'scene':
        // T15：删除场景资产
        if (!selectedSceneAssetId.value) {
          uni.showToast({ title: '请先选择要删除的场景资产', icon: 'none' })
          return
        }
        await videoApi.deleteVideoAsset(selectedSceneAssetId.value)
        uni.showToast({ title: '场景资产已删除', icon: 'success' })
        selectedSceneAssetId.value = null
        await loadSceneAssets()
        break
      default:
        uni.showToast({ title: `${getTypeLabel(currentType.value)} 类型不支持删除`, icon: 'none' })
        break
    }
    emit('updated')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '删除失败', icon: 'none' })
  } finally {
    busy.value = null
  }
}

/**
 * 5. 重新分析提示词
 * 调用 AI 重新分析并生成当前镜头提示词
 */
async function handleReanalyzePrompt() {
  if (busy.value || !currentResource.value) return
  busy.value = 'reanalyze'
  try {
    // 所有类型统一调用镜头提示词重新分析
    await videoApi.reanalyzeChapterShotPrompts(props.shotId)
    uni.showToast({ title: '提示词分析已提交', icon: 'success' })
    emit('updated')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '分析提示词失败', icon: 'none' })
  } finally {
    busy.value = null
  }
}

/**
 * 6. 保存提示词
 * 保存当前编辑的提示词到后端
 */
async function handlePromptSave() {
  if (busy.value || !currentResource.value) return

  // 角色类型不支持提示词编辑
  if (currentType.value === 'character') {
    uni.showToast({ title: '角色类型不支持提示词编辑', icon: 'none' })
    return
  }

  busy.value = 'savePrompt'
  try {
    const prompts: Record<string, string | null> = {}
    if (currentType.value === 'storyboard') {
      prompts.storyboard_prompt = editedStoryboardPrompt.value || null
    }
    if (currentType.value === 'video') {
      prompts.video_prompt = editedVideoPrompt.value || null
    }
    if (currentType.value === 'scene') {
      prompts.scene_prompt = editedScenePrompt.value || null
    }

    if (Object.keys(prompts).length > 0) {
      await videoApi.saveChapterShotPrompts(props.shotId, prompts)
      // 更新原始提示词记录
      if (currentType.value === 'storyboard') {
        originalStoryboardPrompt.value = editedStoryboardPrompt.value
      } else if (currentType.value === 'video') {
        originalVideoPrompt.value = editedVideoPrompt.value
      } else if (currentType.value === 'scene') {
        originalScenePrompt.value = editedScenePrompt.value
      }
      uni.showToast({ title: '提示词已保存', icon: 'success' })
    } else {
      uni.showToast({ title: '暂无提示词可保存', icon: 'none' })
    }
    emit('updated')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '保存失败', icon: 'none' })
  } finally {
    busy.value = null
  }
}

/**
 * 7. 预览组装提示词（T17）
 * 从后端获取组装后的完整提示词，在面板中展示三段式分解和完整文本
 */
async function handlePreviewPrompt() {
  if (previewPromptLoading.value || !props.shotId) return
  // 仅 storyboard 和 video 类型支持
  if (currentType.value !== 'storyboard' && currentType.value !== 'video') {
    uni.showToast({ title: '仅故事版和视频支持预览提示词', icon: 'none' })
    return
  }
  previewPromptLoading.value = true
  try {
    const result = await videoApi.previewVideoPrompt(props.shotId)
    previewPromptText.value = result.assembled_prompt || ''
    previewPromptParts.value = result.parts || null
    previewPromptVisible.value = true
  } catch (e: any) {
    uni.showToast({ title: e?.message || '获取组装提示词失败', icon: 'none' })
    previewPromptText.value = ''
    previewPromptParts.value = null
    previewPromptVisible.value = false
  } finally {
    previewPromptLoading.value = false
  }
}

/** 复制完整提示词到剪贴板 */
function copyPreviewPrompt() {
  if (!previewPromptText.value) {
    uni.showToast({ title: '暂无提示词可复制', icon: 'none' })
    return
  }
  uni.setClipboardData({
    data: previewPromptText.value,
    success() {
      uni.showToast({ title: '已复制到剪贴板', icon: 'success' })
    },
    fail() {
      uni.showToast({ title: '复制失败', icon: 'none' })
    },
  })
}

/** 关闭预览面板 */
function closePreviewPrompt() {
  previewPromptVisible.value = false
  previewPromptText.value = ''
  previewPromptParts.value = null
}

/** 获取卡片类型中文标签 */
function getTypeLabel(type: CardType): string {
  const labels: Record<CardType, string> = {
    character: '角色',
    storyboard: '故事版',
    scene: '场景',
    video: '视频',
  }
  return labels[type] || type
}

// ── T21：镜头风格预设 ──

/** 加载风格预设列表（T21） */
async function loadStylePresets() {
  stylePresetsLoading.value = true
  try {
    const result = await videoApi.listStylePresets()
    stylePresets.value = result.presets || []
  } catch (e: any) {
    uni.showToast({ title: e?.message || '加载风格预设失败', icon: 'none' })
  } finally {
    stylePresetsLoading.value = false
  }
}

/** 选择镜头风格预设（T21） */
async function handleSelectStylePreset(preset: VideoStylePreset) {
  if (busy.value || !props.shotId) return
  busy.value = 'stylePreset'
  try {
    await videoApi.setShotVideoStylePreset(props.shotId, preset.name)
    shotStylePresetName.value = preset.name
    selectedStylePresetId.value = preset.id
    uni.showToast({ title: `已绑定风格「${preset.name}」`, icon: 'success' })
    emit('updated')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '设置风格预设失败', icon: 'none' })
  } finally {
    busy.value = null
  }
}

/** 清除镜头风格预设（T21） */
async function handleClearShotStylePreset() {
  if (busy.value || !props.shotId) return
  if (!shotStylePresetName.value) return
  const confirmRes = await uni.showModal({
    title: '清除风格预设',
    content: `确定要清除当前镜头的风格预设「${shotStylePresetName.value}」吗？`,
  })
  if (!confirmRes.confirm) return
  busy.value = 'clearStylePreset'
  try {
    await videoApi.deleteShotVideoStylePreset(props.shotId)
    shotStylePresetName.value = ''
    selectedStylePresetId.value = null
    uni.showToast({ title: '已清除风格预设', icon: 'success' })
    emit('updated')
  } catch (e: any) {
    uni.showToast({ title: e?.message || '清除风格预设失败', icon: 'none' })
  } finally {
    busy.value = null
  }
}

// ── T23：渲染故事版帧 ──

/** 取消渲染帧 */
function cancelRenderFrame() {
  showRenderFramePanel.value = false
  renderFramePrompt.value = ''
}

/** 确认渲染故事版帧（T23） */
async function confirmRenderFrame() {
  if (busy.value || !props.shotId) return
  busy.value = 'renderFrame'
  showRenderFramePanel.value = false
  try {
    const payload: {
      provider?: string
      aspect_ratio?: string
      overwrite?: boolean
      style_preset?: string
      prompt?: string
      reference_asset_ids?: number[]
    } = {}
    if (renderFramePrompt.value) {
      payload.prompt = renderFramePrompt.value
    }
    if (shotStylePresetName.value) {
      payload.style_preset = shotStylePresetName.value
    }
    const result = await videoApi.renderStoryboardFrame(props.shotId, payload)
    uni.showToast({ title: `故事版帧已提交渲染（状态: ${result.shot_status}）`, icon: 'success' })
    await loadStoryboardVersions()
    emit('updated', result)
  } catch (e: any) {
    uni.showToast({ title: e?.message || '渲染故事版帧失败', icon: 'none' })
  } finally {
    busy.value = null
    renderFramePrompt.value = ''
  }
}
</script>

<style lang="scss" scoped>

// ── 工作台全屏弹窗 ──
.vwb {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 1100;
  display: flex;
  flex-direction: column;
}

// ── 遮罩 ──
.vwb__mask {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(15, 23, 42, 0.6);
}

// ── 主体容器 ──
.vwb__container {
  position: relative;
  flex: 1;
  display: flex;
  flex-direction: column;
  background: $lv-surface-solid;
  border-radius: $lv-radius-lg $lv-radius-lg 0 0;
  box-shadow: $lv-shadow-xl;
  margin-top: env(safe-area-inset-top);
  overflow: hidden;
  animation: vwb-slide-up 0.3s ease;
}

@keyframes vwb-slide-up {
  from {
    opacity: 0;
    transform: translateY(120rpx);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

// ── 顶部栏 ──
.vwb__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: $lv-card-padding;
  border-bottom: 1rpx solid $lv-border-light;
  background: linear-gradient(135deg, $lv-primary-lighter, $lv-bg-end);
  flex-shrink: 0;
}

.vwb__header-left {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.vwb__header-icon {
  font-size: $lv-font-xl;
}

.vwb__header-title {
  font-size: $lv-font-lg;
  font-weight: 600;
  color: $lv-text-primary;
}

.vwb__header-close {
  width: 64rpx;
  height: 64rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: $lv-radius-full;
  background: rgba(0, 0, 0, 0.06);
  transition: background 0.2s;

  &:active {
    background: rgba(0, 0, 0, 0.12);
  }
}

.vwb__close-icon {
  font-size: 32rpx;
  color: $lv-text-secondary;
  font-weight: 600;
}

// ── 标签栏 ──
.vwb__tabs-scroll {
  flex-shrink: 0;
  background: $lv-surface-solid;
  border-bottom: 1rpx solid $lv-border-light;
}

.vwb__tabs {
  display: flex;
  padding: 16rpx $lv-page-padding;
  gap: 12rpx;
}

.vwb__tab {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 16rpx 28rpx;
  border-radius: $lv-radius-xl;
  background: $lv-bg-end;
  border: 1rpx solid $lv-border-light;
  transition: all 0.25s;
  white-space: nowrap;
  flex-shrink: 0;

  &--active {
    background: $lv-primary;
    border-color: $lv-primary;
    box-shadow: $lv-shadow-sm;

    .vwb__tab-label {
      color: $lv-text-on-primary;
      font-weight: 600;
    }
  }

  &:active {
    transform: scale(0.96);
  }
}

.vwb__tab-icon {
  font-size: $lv-font-base;
}

.vwb__tab-label {
  font-size: $lv-font-sm;
  color: $lv-text-secondary;
  transition: color 0.25s;
}

// ── 内容区 ──
.vwb__content {
  flex: 1;
  overflow-y: auto;
  padding: $lv-card-padding;
  background: $lv-bg-end;
}

.vwb__card-content {
  display: flex;
  flex-direction: column;
  gap: $lv-section-gap;
}

// ── 预览区 ──
.vwb__preview-section {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 360rpx;
  background: $lv-surface-solid;
  border-radius: $lv-radius-md;
  border: 1rpx solid $lv-border-light;
  overflow: hidden;
}

.vwb__preview-image {
  width: 100%;
  height: 480rpx;
  border-radius: $lv-radius-md;
}

.vwb__preview-video {
  width: 100%;
  height: 480rpx;
  border-radius: $lv-radius-md;
}

// ── 信息区 ──
.vwb__info-section {
  display: flex;
  flex-direction: column;
  gap: $lv-item-gap;
}

.vwb__info-row {
  display: flex;
  flex-direction: column;
  gap: 6rpx;
  padding: 16rpx 20rpx;
  background: $lv-surface-solid;
  border-radius: $lv-radius-sm;
  border: 1rpx solid $lv-border-light;
}

.vwb__info-label {
  font-size: $lv-font-xs;
  color: $lv-text-muted;
  font-weight: 500;
}

.vwb__info-text {
  font-size: $lv-font-base;
  color: $lv-text-primary;

  &--prompt {
    font-size: $lv-font-sm;
    color: $lv-text-secondary;
    line-height: 1.6;
  }
}

// ── 状态徽标 ──
.vwb__badge {
  display: inline-flex;
  align-self: flex-start;
  padding: 4rpx 16rpx;
  border-radius: $lv-radius-full;
  font-size: $lv-font-xs;

  &--pending {
    background: $lv-warning-bg;
    color: $lv-warning;
  }

  &--info {
    background: $lv-primary-light;
    color: $lv-primary;
  }

  &--success {
    background: $lv-success-bg;
    color: $lv-success;
  }

  &--failed {
    background: $lv-error-bg;
    color: $lv-error;
  }
}

// ── 占位区 ──
.vwb__placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60rpx 40rpx;
  background: $lv-surface-solid;
  border-radius: $lv-radius-md;
  border: 2rpx dashed $lv-border-light;
  gap: 16rpx;
}

.vwb__placeholder-icon {
  font-size: 72rpx;
  opacity: 0.5;
}

.vwb__placeholder-title {
  font-size: $lv-font-lg;
  font-weight: 600;
  color: $lv-text-secondary;
}

.vwb__placeholder-desc {
  font-size: $lv-font-sm;
  color: $lv-text-muted;
  text-align: center;
}

// ── 角色资产列表（T12）──
.vwb__asset-list {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.vwb__asset-card {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 16rpx;
  background: $lv-surface-solid;
  border-radius: $lv-radius-sm;
  border: 2rpx solid $lv-border-light;
  transition: all 0.2s;
  position: relative;

  &--selected {
    border-color: $lv-primary;
    background: $lv-primary-lighter;
    box-shadow: 0 0 0 2rpx $lv-primary-light;
  }

  &:active {
    transform: scale(0.98);
  }
}

.vwb__asset-thumb {
  width: 120rpx;
  height: 120rpx;
  border-radius: $lv-radius-xs;
  background: $lv-bg-end;
  flex-shrink: 0;
}

.vwb__asset-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
  min-width: 0;
}

.vwb__asset-name {
  font-size: $lv-font-base;
  font-weight: 500;
  color: $lv-text-primary;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vwb__asset-check {
  position: absolute;
  top: 8rpx;
  right: 8rpx;
  width: 40rpx;
  height: 40rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: $lv-radius-full;
  background: $lv-primary;
  color: $lv-text-on-primary;
  font-size: $lv-font-sm;
  font-weight: 700;
}

// ── 重绘面板（T12）──
.vwb__redraw-panel {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
  padding: 20rpx;
  background: $lv-surface-solid;
  border-radius: $lv-radius-sm;
  border: 1rpx solid $lv-border-light;
}

.vwb__redraw-panel-title {
  font-size: $lv-font-sm;
  font-weight: 600;
  color: $lv-text-primary;
}

.vwb__redraw-textarea {
  width: 100%;
  min-height: 120rpx;
  padding: 16rpx;
  font-size: $lv-font-sm;
  color: $lv-text-primary;
  background: $lv-bg-end;
  border-radius: $lv-radius-xs;
  border: 1rpx solid $lv-border-light;
  box-sizing: border-box;

  &:focus {
    border-color: $lv-border-focus;
  }
}

.vwb__redraw-panel-actions {
  display: flex;
  gap: 12rpx;
}

// ── 提示词编辑区（T13）──
.vwb__prompt-editor {
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}

.vwb__prompt-editor-header {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.vwb__prompt-dirty-badge {
  padding: 2rpx 12rpx;
  border-radius: $lv-radius-full;
  background: $lv-warning-bg;
  font-size: $lv-font-xs;
  color: $lv-warning;
}

.vwb__prompt-textarea {
  width: 100%;
  min-height: 160rpx;
  padding: 16rpx 20rpx;
  font-size: $lv-font-sm;
  color: $lv-text-primary;
  background: $lv-surface-solid;
  border-radius: $lv-radius-sm;
  border: 1rpx solid $lv-border-light;
  box-sizing: border-box;
  line-height: 1.6;

  &:focus {
    border-color: $lv-border-focus;
  }
}

// ── 故事版版本列表（T13）──
.vwb__versions {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.vwb__versions-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.vwb__section-title {
  font-size: $lv-font-base;
  font-weight: 600;
  color: $lv-text-primary;
}

.vwb__versions-refresh {
  display: flex;
  align-items: center;
  gap: 4rpx;
  padding: 6rpx 16rpx;
  border-radius: $lv-radius-full;
  background: $lv-primary-lighter;
  font-size: $lv-font-xs;
  color: $lv-primary;
  transition: all 0.2s;

  &:active {
    background: $lv-primary;
    color: $lv-text-on-primary;
  }

  &--spin {
    opacity: 0.6;
    pointer-events: none;
    animation: vwb-spin 0.8s linear infinite;
  }
}

.vwb__version-item {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 16rpx;
  background: $lv-surface-solid;
  border-radius: $lv-radius-sm;
  border: 1rpx solid $lv-border-light;
  transition: all 0.2s;

  &--master {
    border-color: $lv-primary;
    background: $lv-primary-lighter;
  }
}

.vwb__version-thumb {
  width: 100rpx;
  height: 100rpx;
  border-radius: $lv-radius-xs;
  background: $lv-bg-end;
  flex-shrink: 0;
}

.vwb__version-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
  min-width: 0;
}

.vwb__version-name {
  font-size: $lv-font-sm;
  font-weight: 500;
  color: $lv-text-primary;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vwb__version-meta {
  font-size: $lv-font-xs;
  color: $lv-text-muted;
}

.vwb__version-master-tag {
  align-self: flex-start;
  padding: 2rpx 10rpx;
  border-radius: $lv-radius-full;
  background: $lv-primary;
  font-size: $lv-font-xs;
  color: $lv-text-on-primary;
}

.vwb__version-action {
  flex-shrink: 0;
  padding: 10rpx 20rpx;
  border-radius: $lv-radius-sm;
  background: $lv-primary;
  font-size: $lv-font-xs;
  color: $lv-text-on-primary;
  font-weight: 500;
  transition: all 0.2s;

  &:active {
    background: $lv-primary-dark;
    transform: scale(0.96);
  }
}

// ── 小程序视频兜底（T14）──
.vwb__fallback {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16rpx;
  padding: 40rpx 32rpx;
  text-align: center;
}

.vwb__fallback-icon {
  font-size: 64rpx;
  opacity: 0.4;
}

.vwb__fallback-title {
  font-size: $lv-font-base;
  font-weight: 600;
  color: $lv-text-secondary;
}

.vwb__fallback-desc {
  font-size: $lv-font-sm;
  color: $lv-text-muted;
  line-height: 1.5;
}

.vwb__fallback-btn {
  margin-top: 8rpx;
  padding: 16rpx 40rpx;
  font-size: $lv-font-base;
  color: $lv-text-on-primary;
  background: $lv-primary;
  border-radius: $lv-radius-sm;
  border: none;
  line-height: 1.4;

  &::after {
    border: none;
  }
}

// ── 错误/重试区（T14）──
.vwb__error-section {
  display: flex;
  align-items: flex-start;
  gap: 16rpx;
  padding: 20rpx;
  background: $lv-error-bg;
  border-radius: $lv-radius-sm;
  border: 1rpx solid #f5c6cb;
}

.vwb__error-icon {
  font-size: 36rpx;
  flex-shrink: 0;
  margin-top: 2rpx;
}

.vwb__error-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
  min-width: 0;
}

.vwb__error-title {
  font-size: $lv-font-sm;
  font-weight: 600;
  color: $lv-error;
}

.vwb__error-desc {
  font-size: $lv-font-xs;
  color: $lv-text-secondary;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}

// ── 参数选择区（T14）──
.vwb__param-section {
  display: flex;
  flex-direction: column;
  gap: 10rpx;
}

.vwb__param-options {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
}

.vwb__param-chip {
  padding: 10rpx 22rpx;
  border-radius: $lv-radius-full;
  background: $lv-surface-solid;
  border: 1rpx solid $lv-border-light;
  font-size: $lv-font-xs;
  color: $lv-text-secondary;
  transition: all 0.2s;

  &--active {
    background: $lv-primary-lighter;
    border-color: $lv-primary;
    color: $lv-primary;
    font-weight: 600;
  }

  &:active {
    transform: scale(0.96);
  }
}

// ── 底部操作栏 ──
.vwb__actions {
  flex-shrink: 0;
  padding: $lv-card-padding;
  padding-bottom: calc($lv-card-padding + env(safe-area-inset-bottom));
  background: $lv-surface-solid;
  border-top: 1rpx solid $lv-border-light;
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.vwb__actions-row {
  display: flex;
  gap: 10rpx;
}

.vwb__action-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  padding: 18rpx 12rpx;
  border-radius: $lv-radius-sm;
  border: 1rpx solid transparent;
  transition: all 0.2s;
  min-height: $lv-touch-min;

  &:active:not(&--disabled) {
    transform: scale(0.97);
  }

  // 主要操作（蓝色）
  &--primary {
    background: $lv-primary;
    border-color: $lv-primary;

    .vwb__action-label {
      color: $lv-text-on-primary;
      font-weight: 500;
    }

    &:active:not(&--disabled) {
      background: $lv-primary-dark;
    }
  }

  // 次要操作（浅色背景）
  &--secondary {
    background: $lv-bg-end;
    border-color: $lv-border-light;

    .vwb__action-label {
      color: $lv-text-secondary;
    }

    &:active:not(&--disabled) {
      background: $lv-primary-light;
    }
  }

  // 危险操作（红色）
  &--danger {
    background: $lv-error-bg;
    border-color: $lv-error-bg;

    .vwb__action-label {
      color: $lv-error;
    }

    &:active:not(&--disabled) {
      background: #fde2e7;
    }
  }

  // 禁用态
  &--disabled {
    opacity: 0.45;
    pointer-events: none;
  }
}

.vwb__action-icon {
  font-size: $lv-font-xl;
}

.vwb__action-spinner {
  font-size: $lv-font-xl;
  animation: vwb-spin 0.8s linear infinite;
}

@keyframes vwb-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.vwb__action-label {
  font-size: $lv-font-sm;
  white-space: nowrap;
}

// ── 预览组装提示词（T17）──
.vwb__preview-section {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.vwb__preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.vwb__preview-parts {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.vwb__preview-part {
  display: flex;
  flex-direction: column;
  gap: 6rpx;
}

.vwb__preview-part-label {
  font-size: $lv-font-xs;
  color: $lv-text-muted;
  font-weight: 500;
  padding-left: 4rpx;
}

.vwb__preview-textarea {
  width: 100%;
  min-height: 100rpx;
  padding: 16rpx 20rpx;
  font-size: $lv-font-sm;
  color: $lv-text-primary;
  background: $lv-surface-solid;
  border-radius: $lv-radius-sm;
  border: 1rpx solid $lv-border-light;
  box-sizing: border-box;
  line-height: 1.6;

  &--full {
    min-height: 160rpx;
    background: $lv-primary-lighter;
    border-color: $lv-primary;
  }
}

.vwb__preview-actions {
  display: flex;
  gap: 12rpx;
}

.vwb__placeholder--compact {
  padding: 24rpx 20rpx;
}

.vwb__placeholder--compact .vwb__placeholder-desc {
  font-size: $lv-font-xs;
}

// ── 镜头风格预设（T21）──
.vwb__style-preset-section {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
  padding: 20rpx;
  background: $lv-surface-solid;
  border-radius: $lv-radius-sm;
  border: 1rpx solid $lv-border-light;
}

.vwb__style-preset-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.vwb__style-current {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12rpx;

  &--empty {
    padding: 8rpx 0;
  }
}

.vwb__style-current-badge {
  padding: 6rpx 16rpx;
  border-radius: $lv-radius-full;
  background: $lv-primary-lighter;
}

.vwb__style-current-name {
  font-size: $lv-font-sm;
  color: $lv-primary;
  font-weight: 600;
}

.vwb__style-clear {
  padding: 8rpx 20rpx;
  border-radius: $lv-radius-sm;
  background: $lv-error-bg;
  font-size: $lv-font-xs;
  color: $lv-error;
  font-weight: 500;
  transition: all 0.2s;

  &:active:not(&--disabled) {
    background: #fde2e7;
    transform: scale(0.96);
  }

  &--disabled {
    opacity: 0.45;
    pointer-events: none;
  }
}

.vwb__style-chips-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
}

.vwb__style-chip {
  padding: 10rpx 22rpx;
  border-radius: $lv-radius-full;
  background: $lv-bg-end;
  border: 1rpx solid $lv-border-light;
  transition: all 0.2s;

  &--active {
    background: $lv-primary-lighter;
    border-color: $lv-primary;
  }

  &:active {
    transform: scale(0.96);
  }
}

.vwb__style-chip-text {
  font-size: $lv-font-xs;
  color: $lv-text-secondary;
  font-weight: 500;

  .vwb__style-chip--active & {
    color: $lv-primary;
    font-weight: 600;
  }
}

.vwb__style-loading {
  display: flex;
  justify-content: center;
  padding: 16rpx 0;
  font-size: $lv-font-xs;
  color: $lv-text-muted;
}

// ── 渲染故事版帧（T23）──
.vwb__render-frame-section {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
  padding: 20rpx;
  background: $lv-surface-solid;
  border-radius: $lv-radius-sm;
  border: 1rpx solid $lv-border-light;
}

.vwb__render-frame-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
