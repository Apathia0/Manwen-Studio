# 积分双轨制 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 落地「积分钱包 + 平台账户/我的 Key 双轨 + 按模型定价」，替换 AI 调用对套餐次数的依赖。

**Architecture:** 新增 `ai_channels`/`ai_models`/`ai_model_prices`/`points_*`/`user_ai_*` 表与服务层；请求级解析 `credential_mode`；平台模式预扣积分后用平台 Key 调上游，user_key 模式用用户 Key 不扣积分；旧配额在开关打开时短路。

**Tech Stack:** FastAPI / SQLAlchemy 2 / PostgreSQL / React / 现有支付网关

## Global Constraints

- 用户不可提交任意 Base URL
- 积分用 NUMERIC，禁止 float 结算
- Key 加密存储，GET 只回掩码
- `credential_mode=platform` 禁止用用户 Key；`user_key` 禁止回落平台 Key 替用户付费
- 旧 Plan/次数表不 DROP，仅短路 AI 门槛
- 代码注释使用中文
- UTF-8 无 BOM

---

### Task 1: 数据模型与迁移

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/database.py`（`_migrate` 如需补索引）
- Test: `backend/tests/test_points_models.py`

- [ ] 新增模型：AiChannel, AiModel, AiModelPrice, UserAiCredential, UserAiPreference, PointsAccount, PointsLedgerEntry, AiUsageEvent, PointsProduct
- [ ] create_all 可创建新表
- [ ] 单元测试导入模型成功

### Task 2: 密钥加解密与积分账本服务

**Files:**
- Create: `backend/services/ai/crypto_secrets.py`
- Create: `backend/services/points/accounts.py`
- Create: `backend/services/points/reservation.py`
- Create: `backend/services/points/pricing.py`
- Test: `backend/tests/test_points_ledger.py`

- [ ] Fernet/派生密钥加解密
- [ ] ensure_account / credit / reserve / settle / release
- [ ] 幂等键
- [ ] 定价计算 per_call / per_1k_tokens / per_image / per_second

### Task 3: 渠道/目录/解析器

**Files:**
- Create: `backend/services/ai/context.py`
- Create: `backend/services/ai/channels.py`
- Create: `backend/services/ai/catalog.py`
- Create: `backend/services/ai/credentials.py`
- Create: `backend/services/ai/resolver.py`
- Create: `backend/services/ai/bootstrap.py`（从 PlatformSetting 迁移默认渠道）
- Test: `backend/tests/test_ai_resolver.py`

- [ ] 解析 platform / user_key
- [ ] 禁止 URL 覆盖
- [ ] bootstrap 旧配置

### Task 4: API 路由

**Files:**
- Create: `backend/routers/points_ai.py`
- Modify: `backend/main.py` 注册路由 + 短路配额
- Test: `backend/tests/test_points_ai_api.py`

用户：credential / preferences / models / estimate / points account/ledger/products/purchase  
管理：channels / models / prices / points settings / adjust

### Task 5: 接入 AI 调用路径

**Files:**
- Modify: `backend/main.py`（`_user_deepseek_api_key`、`_user_image_api_key`、`_check_and_consume_feature_quota`）
- Modify: 关键生成入口预扣/结算（文本主路径优先）
- Test: 集成测试

- [ ] 开关 `points.dual_track_enabled` 或默认启用新路径
- [ ] 平台模式预扣，失败释放
- [ ] user_key 跳过积分与旧配额

### Task 6: 前端用户侧

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/UserAccountUsagePage.tsx` 或新建 Points 页
- Modify: 生成入口附近模型/模式选择（至少 Workspace 文本路径）
- 清理 apiHeaders 长期 Key（逐步）

### Task 7: 前端管理侧

**Files:**
- Create/Modify admin 组件：渠道、模型、积分价、积分设置
- Modify: `frontend/src/App.tsx` 导航

### Task 8: 支付入账积分 + 注册赠送

**Files:**
- Modify: `_mark_order_paid` 支持 `source=points_purchase`
- 注册成功钩子赠送

---

执行时按 Task 1→8 顺序，可在 1–3 后端并行后合并。
