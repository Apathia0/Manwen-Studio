# 积分制 + 双轨凭据（平台 / 我的 Key）设计方案

> 状态：方案定稿  
> 日期：2026-07-15  
> 适用范围：StoryCanvas Web、移动端、FastAPI 后端、PostgreSQL、管理后台  
> 关联历史文档（计费路径将被本方案替代）：`2026-06-18-quota-purchase-design.md`、`2026-06-05-payment-gateway-design.md`、`2026-06-04-admin-revenue-dashboard-design.md`  
> 修订说明：放弃「纯 NewAPI 中转（本站零计费）」与「套餐 + 次数 + 创作点」混合体系，改为企业常见的 **积分钱包 + 按模型定价 + 平台账户 / 我的 Key 双轨**。

---

## 1. 文档目的

StoryCanvas 需要同时满足两类用户：

1. **普通创作者**：不想自己找上游、配 Key，充值积分后直接用平台模型。
2. **自带上游用户**：已有 NewAPI / 兼容网关 Key，希望走自己的额度，不花本站积分。

同时管理员需要：

- 配置上游渠道与模型目录（类似渠道管理，但产品侧用「积分」售卖平台能力）。
- 按模型配置积分价格。
- 查看积分充值与平台路径消耗，而不是维护复杂的套餐次数矩阵。

本文档定义积分制双轨架构、数据模型、接口、前后端交互、安全边界、旧计费下线与验收标准。

---

## 2. 产品决策（已确认）

| 决策项 | 结论 |
|--------|------|
| 总体方案 | **积分钱包 + 双轨凭据** |
| 平台路径 | 使用平台上游 Key；按模型积分价扣本站积分 |
| 我的 Key 路径 | 用户仅配置 API Key；URL 由管理员控制；模型从平台目录选择；**不扣本站积分** |
| 积分定价 | **按模型定价**（文本按次或按 token；图片按张；视频按次或按秒） |
| 模式切换 | 用户手动选择 `平台账户` / `我的 Key`，系统记住上次选择 |
| Base URL | **仅管理员配置**；用户不可填任意 URL |
| 模型选择 | 从管理员维护的模型目录点选，不手填裸模型字符串（默认） |
| 旧套餐 / 次数配额 | **作为 AI 门槛移除**；由积分替代 |
| 注册赠送 | 管理员可配置是否赠送积分及数量 |
| 平台 Key | 仅用于「平台账户」路径的真实调用，以及管理端测试/同步 |

---

## 3. 用户心智（统一文案）

> **用平台模型就花积分；切到「我的 Key」就花你自己上游的钱，本站不扣积分。**

| 用户看到的 | 含义 |
|------------|------|
| 积分余额 | 本站可消费额度 |
| 平台账户 | 用平台模型，扣积分 |
| 我的 Key | 用你的 API Key 调同一批平台目录模型，不扣积分 |
| 预计消耗 | 仅平台账户模式展示 |

禁止再并列「套餐次数 + 积分 + 创作点」多套货币。首期只有 **积分** 一种本站货币。

---

## 4. 现状问题与迁移原则

### 4.1 现状问题

- 单模型全局配置，无法多模型目录与差异定价。
- 模块级 `configure_runtime()` 导致并发串 Key/模型。
- 套餐 + 次数与真实模型成本脱节，运营与理解成本高。
- 用户本地填 URL/Key 存在 SSRF、跳过配额、平台 Key 误用风险。
- 纯中转模式无法服务「只想充值就用」的普通用户。

### 4.2 迁移原则

- AI 调用门槛改为：登录 +（平台模式积分足够 / 我的 Key 模式已配置 Key）+ 模型可用。
- 旧 `Plan` / 次数表 **保留历史数据**，不再作为 AI 扣费真相源。
- 支付能力保留，用于 **积分充值**（及未来非 AI 商品），不再绑定「月度功能次数包」作为主路径。
- 不删除用户作品、漫画、视频资源。

---

## 5. 设计目标

### 5.1 功能目标

1. 管理员配置上游渠道（Base URL + 平台 API Key）。
2. 管理员维护模型目录（同步或手建），并按模型配置积分价。
3. 用户拥有积分账户：充值、赠送、消费、流水。
4. 用户可配置自己的 API Key，并在「平台账户 / 我的 Key」间切换。
5. 两种模式均从同一模型目录选择模型。
6. 平台模式：预扣 → 调用 → 按实际用量结算 → 多退少不欠费（预扣覆盖上限）。
7. 我的 Key 模式：不扣积分，错误透传上游（余额不足、Key 无效等）。
8. 所有调用使用请求级不可变上下文，禁止全局 runtime 串线。
9. 可选记录调用日志与积分流水，支持客服对账。

### 5.2 非功能目标

- 并发安全：积分扣减幂等、账户行锁、无负余额。
- Key 加密存储，日志脱敏，GET 不回说明文。
- 用户不能指定任意 Base URL。
- 价格变更不影响历史已结算流水（保存价格快照）。

### 5.3 非目标（首期）

- 复杂套餐权益矩阵（模型权限按套餐开关）。
- 月度功能次数配额。
- 用户自定义 Base URL。
- 积分提现、用户互转。
- 多渠道自动故障转移 / 竞价。
- 我的 Key 模式收取服务费（若以后要加，单独配置，默认 0）。

---

## 6. 核心原则

### 6.1 双轨凭据，单一模型目录

```text
模型目录（管理员）
        │
        ├─ 平台账户 ──► 平台 API Key + 扣积分
        │
        └─ 我的 Key ──► 用户 API Key + 不扣积分
```

URL 始终来自管理员渠道；模型始终来自目录（或目录允许的 key）。

### 6.2 权益极简

首期不设「能不能用这个模型」的套餐墙，只设：

- 模型是否上架（`enabled` + `user_visible`）
- 平台模式积分是否足够
- 我的 Key 模式 Key 是否有效

若某模型成本极高，用 **更高积分价** 调节，而不是再做一套权限表。

### 6.3 先预扣，后结算（仅平台模式）

- 调用前按「预估上限」锁定积分。
- 成功后按实际用量结算，多余释放。
- 失败全额释放。
- 不允许形成欠费；预扣不足则拒绝调用。

### 6.4 请求级上下文

```python
@dataclass(frozen=True)
class AIExecutionContext:
    request_id: str
    user_id: int
    task_type: str
    credential_mode: str      # "platform" | "user_key"
    channel_id: int
    model_id: int
    model_key: str
    modality: str
    base_url: str
    api_key: str              # platform key 或 user key（内存中）
    price_snapshot_json: dict | None  # 平台模式必填
    estimated_points: Decimal | None
    reservation_id: int | None
```

### 6.5 历史价格快照

每次平台模式成功结算写入当时积分价配置快照；管理员改价不影响已完成账单。

---

## 7. 目标架构

```text
┌──────────────────────────────────────────────────────────────┐
│ Web / Mobile                                                 │
│ 积分余额 · 充值 · 模式切换(平台/我的Key) · 模型选择 · 预计消耗 │
└────────────────────────────┬─────────────────────────────────┘
                             │ mode + model_id + 业务参数
┌────────────────────────────▼─────────────────────────────────┐
│ FastAPI                                                      │
│ 鉴权 · 解析模式 · 模型目录校验 · 积分预扣(仅平台) · 幂等键    │
└────────────────────────────┬─────────────────────────────────┘
                             │ AIExecutionContext
┌────────────────────────────▼─────────────────────────────────┐
│ AI 调度                                                      │
│ Resolver · Pricing · Reservation · Adapter · UsageLog        │
└──────────────┬─────────────────────────────┬─────────────────┘
               │                             │
┌──────────────▼──────────────┐   ┌──────────▼─────────────────┐
│ 上游 NewAPI / 兼容网关       │   │ 积分账本                    │
│ 平台 Key 或 用户 Key         │   │ 账户 · 预扣 · 结算 · 流水   │
└─────────────────────────────┘   └────────────────────────────┘
```

---

## 8. 积分产品设计

### 8.1 积分是什么

- 本站唯一 AI 消费货币，展示名：**积分**（管理员可改显示名，内部字段 `points`）。
- 使用 `NUMERIC` 存储，禁止用浮点做最终结算。
- 充值比例由管理员配置，例如默认 **1 元 = 10 积分**（可改，需写进配置而非写死代码）。

### 8.2 积分来源

| source_type | 说明 | 是否可过期 |
|-------------|------|------------|
| `purchase` | 用户充值购买 | 默认不过期 |
| `register_grant` | 注册赠送 | 可配 |
| `admin_grant` | 管理员发放 | 可配 |
| `promo` | 活动赠送 | 可配 |
| `refund` | 退款/失败释放入账 | 随原规则 |
| `adjust` | 管理员调账 | 按操作 |

首期可先实现 **单余额账户**（`available_points` + `reserved_points`），赠送过期用定时任务扫描流水标记；若需严格「先过期先扣」，二期再引入资金桶表。

**推荐首期**：单余额 + 流水明细足够；过期赠送用 `expires_at` 在发放时写入，扣费时优先扣即将过期部分（若首期排期紧，可先 FIFO 按流水扣减简化）。

### 8.3 按模型定价

每个模型一条生效中的价格配置：

| modality | 计费方式 `billing_type` | 配置示例 |
|----------|-------------------------|----------|
| text | `per_call` | 每次 2 积分 |
| text | `per_1k_tokens` | 输入 0.5 / 1K，输出 1.5 / 1K；可选最低每次 1 积分 |
| image | `per_image` | 每张 5 积分；可按质量档加价 |
| video | `per_call` | 每次 50 积分 |
| video | `per_second` | 每秒 3 积分 |

字段建议：

```json
{
  "billing_type": "per_1k_tokens",
  "input_points_per_1k": 0.5,
  "output_points_per_1k": 1.5,
  "min_points_per_call": 1,
  "estimate_default_output_tokens": 2000
}
```

管理员改价生成新版本；旧版本 `valid_to` 闭合。

### 8.4 预估与预扣

**平台模式**提交时：

1. 根据模型价格 + 请求参数计算 `estimated_points`。
2. 预扣额 = 预估 × 安全系数（默认 1.2）或文本用 `max_output` 上限估算，取合理上限。
3. `available >= reserve` 才继续，否则返回 `insufficient_points`。
4. 调用成功后：
   - 有实际 token/张数/秒数 → 按公式算 `actual_points`（不低于 `min_points_per_call`）
   - 无实际用量 → 用预估或请求参数结算，并标记 `usage_source=estimated`
5. `actual <= reserved`：结算 actual，释放差额。  
   若实际意外大于预扣（应尽量避免）：补扣仅当余额足够；否则记 `partial` 告警并冻结该用户继续调用直至管理员处理（首期应力保预扣上限盖住实际）。

**我的 Key 模式**：不做预扣；`estimated_points` 对用户显示为 0 或「上游计费」。

### 8.5 充值

- 复用现有支付网关创建「积分充值订单」。
- 支付回调幂等：同一支付事件只入账一次。
- 管理员可配置充值档位（金额 → 积分，可含赠送）。

### 8.6 注册赠送

- 平台设置：`points.register_grant_enabled`、`points.register_grant_amount`。
- 新用户注册成功且开启时入账一笔 `register_grant`。
- 已存在用户不补发（除非管理员手动发）。

---

## 9. 双轨凭据与模型选择

### 9.1 模式定义

| credential_mode | api_key 来源 | 是否扣积分 | 前置条件 |
|-----------------|--------------|------------|----------|
| `platform` | 渠道平台 Key | 是 | 积分预扣成功 |
| `user_key` | 用户保存的 Key | 否 | 用户已配置 Key |

用户可在用户中心设置默认模式；生成页可临时切换。

### 9.2 用户自定义范围（已确认）

允许：

- 保存 / 更新 / 清除 API Key
- 测试 Key（平台 URL + 用户 Key）
- 选择模型目录中的模型
- 切换 credential_mode

不允许：

- 自定义 Base URL
- 在普通路径手填未上架模型名
- 使用平台 Key 却声称 user_key 以逃费

### 9.3 模型目录

与渠道绑定：

- 管理员同步 `GET {base_url}/models`（用平台探测/平台 Key）或手动录入。
- 字段：`model_key`、`display_name`、`modality`、`enabled`、`user_visible`、`sort_order`、价格版本。
- 用户列表接口同时返回：显示名、模态、积分价摘要、是否推荐。

### 9.4 解析顺序（模型）

1. 请求显式 `model_id`
2. 用户该 modality 默认模型
3. 管理员任务默认模型
4. 该 modality 排序第一的可见模型

每步校验模型启用且用户可见。

### 9.5 前端交互要点

**用户中心**

- 积分余额、充值入口、流水分页
- API Key 配置（掩码）
- 默认模式：平台账户 / 我的 Key
- 默认模型（按 text/image/video）

**生成入口**

- 模式切换控件
- 模型下拉
- 平台模式：`预计消耗约 X 积分 · 余额 Y`
- 我的 Key：`使用你的 API Key · 本站不扣积分`
- 积分不足：引导充值；有 Key 时可一键切到「我的 Key」

---

## 10. 数据模型

### 10.1 `ai_channels`

| 字段 | 说明 |
|------|------|
| `id` | PK |
| `code` / `name` | 编码与显示名 |
| `adapter_type` | openai_compatible / video 适配器等 |
| `base_url` | 上游地址 |
| `modality` | text / image / video / multi |
| `platform_secret_ciphertext` | 平台调用 Key 密文 |
| `key_version` / `last_four` | 加密版本与掩码 |
| `enabled` / `timeout_seconds` | |
| `extra_config_json` | |

### 10.2 `ai_models`

| 字段 | 说明 |
|------|------|
| `id` | PK |
| `channel_id` | FK |
| `model_key` | 上游模型名 |
| `display_name` | 用户可见名 |
| `modality` | |
| `enabled` / `user_visible` / `sort_order` | |
| `capabilities_json` | 可选 |

唯一约束：`(channel_id, model_key)`。

### 10.3 `ai_model_prices`

| 字段 | 说明 |
|------|------|
| `id` | 价格版本 ID |
| `model_id` | FK |
| `billing_type` | per_call / per_1k_tokens / per_image / per_second |
| `price_config_json` | 具体单价与下限 |
| `valid_from` / `valid_to` | 生效窗口 |
| `created_by` | 管理员 |

同一模型同一时间仅一条生效价。

### 10.4 `user_ai_credentials`

| 字段 | 说明 |
|------|------|
| `user_id` | unique |
| `secret_ciphertext` / `key_version` / `last_four` | |
| `status` | active / invalid / empty |
| `last_validated_at` | |

### 10.5 `user_ai_preferences`

| 字段 | 说明 |
|------|------|
| `user_id` | |
| `credential_mode` | platform / user_key |
| `default_text_model_id` | nullable |
| `default_image_model_id` | nullable |
| `default_video_model_id` | nullable |

### 10.6 `points_accounts`

| 字段 | 说明 |
|------|------|
| `user_id` | unique |
| `available_points` | NUMERIC |
| `reserved_points` | NUMERIC |
| `version` | 乐观锁可选 |
| `updated_at` | |

约束：`available_points >= 0`，`reserved_points >= 0`。

### 10.7 `points_ledger_entries`

| 字段 | 说明 |
|------|------|
| `id` | PK |
| `account_id` | FK |
| `entry_type` | purchase / grant / reserve / settle / release / refund / adjust |
| `amount` | 正为入账，负为出账（或按 type 约定方向，需统一） |
| `balance_after` | 可选便于展示 |
| `idempotency_key` | unique |
| `usage_event_id` | nullable |
| `order_id` | nullable |
| `metadata_json` | 快照、备注 |
| `created_at` | |

### 10.8 `ai_usage_events`

一次用户可感知的 AI 请求：

| 字段 | 说明 |
|------|------|
| `request_id` | unique 幂等 |
| `user_id` / `story_id` / … | |
| `task_type` | |
| `credential_mode` | platform / user_key |
| `model_id` / `model_key` | |
| `status` | reserved / running / succeeded / failed / released |
| `input_tokens` / `output_tokens` / `image_count` / `video_seconds` | |
| `usage_source` | provider / estimated |
| `estimated_points` / `reserved_points` / `settled_points` | |
| `price_snapshot_json` | 平台模式 |
| `error_code` | |
| `created_at` / `completed_at` | |

我的 Key 模式：`settled_points = 0`，仍记 usage 便于统计。

### 10.9 支付幂等

复用或新建 `billing_payment_events`：

- `(provider, event_id)` unique
- 支付成功回调内：锁订单 → 写 event → 入账积分 → 提交

### 10.10 废弃作为 AI 门槛的表

只读保留，AI 路径不再扣减：

- `plans` / `plan_features` / `plan_quota_rules`（AI 次数相关）
- `user_subscriptions`（作为 AI 门槛时）
- `user_usage_monthly` / `user_quota_grant_monthly`

---

## 11. API 设计

### 11.1 用户积分

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/points/account` | 余额、预扣中 |
| GET | `/api/points/ledger` | 流水 |
| GET | `/api/points/products` | 充值档位 |
| POST | `/api/points/purchase` | 创建充值订单 |

### 11.2 用户凭据与模型

| 方法 | 路径 | 用途 |
|------|------|------|
| GET/PUT/DELETE | `/api/ai/credential` | 我的 Key |
| POST | `/api/ai/credential/test` | 测试 Key |
| GET/PUT | `/api/ai/preferences` | 默认模式与默认模型 |
| GET | `/api/ai/models` | 可见模型 + 积分价摘要 |
| POST | `/api/ai/estimate` | 平台模式费用预估 |

### 11.3 生成接口

请求体扩展：

```json
{
  "credential_mode": "platform",
  "model_id": 12,
  "request_id": "5d1543b8-4eb4-4fce-9f1f-301d7777259d"
}
```

规则：

- `credential_mode` 可省略，默认用用户偏好。
- `request_id` 前端生成，防重复提交与重复预扣。
- 忽略普通用户提交的 `base_url`。
- 平台模式：预扣失败不发起上游调用。
- 我的 Key：无 Key 返回 `user_api_key_required`。

### 11.4 管理员

| 方法 | 路径 | 用途 |
|------|------|------|
| CRUD | `/api/admin/ai/channels` | 渠道 |
| POST | `.../test` · `.../sync-models` | 测试与同步 |
| CRUD | `/api/admin/ai/models` | 模型 |
| GET/POST | `/api/admin/ai/models/{id}/prices` | 价格版本 |
| GET/PUT | `/api/admin/ai/task-defaults` | 任务默认模型 |
| GET/PUT | `/api/admin/points/settings` | 充值比例、注册赠送 |
| CRUD | `/api/admin/points/products` | 充值档位 |
| POST | `/api/admin/points/adjust` | 调账 |
| GET | `/api/admin/ai/usage` | 用量 |
| GET | `/api/admin/points/metrics` | 充值与消耗统计 |

### 11.5 前端清理

- `apiHeaders()` 不再附带长期 Key / 自定义 URL / 模型名到所有请求。
- Key 仅用户中心写入服务端；生成只带登录态 + body。

---

## 12. 管理后台

1. **上游渠道**：URL、平台 Key（掩码）、超时、测试连接  
2. **模型目录**：同步、显示名、上下架、排序  
3. **模型积分价**：计费类型、单价、预估参数、历史版本  
4. **积分设置**：充值比例、注册赠送、充值档位  
5. **用户调账**：发放/扣减积分（写流水）  
6. **用量与积分看板**：平台路径消耗、充值额、我的 Key 调用占比（无本站金额）  
7. **下线**：AI 次数套餐售卖、配额规则运营入口  

---

## 13. 核心流程

### 13.1 平台模式

```text
用户提交（mode=platform, model_id, request_id）
  → 校验登录与模型可见
  → 若 request_id 已存在：返回原状态/结果
  → 计算预估积分与预扣额
  → 事务：锁账户 → 预扣 → 写 ledger(reserve) → 写 usage_event(reserved)
  → 用平台 Key 调上游
  → 成功：算实际积分 → settle + release 差额 → usage succeeded
  → 失败：release 全部预扣 → usage failed
```

### 13.2 我的 Key 模式

```text
用户提交（mode=user_key, model_id, request_id）
  → 校验已配置 Key、模型可见
  → 写 usage_event（settled_points=0）
  → 用用户 Key + 管理员 base_url 调上游
  → 映射上游错误（余额不足/Key 无效等）
```

### 13.3 充值

```text
创建订单 → 支付 → 回调
  → 支付事件幂等
  → 订单 paid
  → 积分入账 + ledger(purchase)
```

---

## 14. 安全设计

### 14.1 Key

- 平台 Key 与用户 Key 均加密存储。
- GET 只返回掩码与状态。
- 日志与 SSE 禁止完整 Key。
- `credential_mode=platform` 时 **禁止** 使用用户 Key 替换以造成计费混乱；反之 user_key 模式禁止回落平台 Key 替用户付上游费用。

### 14.2 SSRF

- 用户不可提交 Base URL。
- 管理员 base_url 校验协议与网段；内网需白名单。

### 14.3 积分并发

- 预扣/结算/释放在事务中 `SELECT FOR UPDATE` 账户。
- 所有账变带 `idempotency_key`。
- 数据库约束防止 available/reserved 为负。

### 14.4 逃费防护

- 仅声明 user_key 但未配置 Key → 拒绝。
- 不得因请求头带自定义 URL 就跳过积分。
- 平台模式必须走预扣，无预扣不得调上游。

---

## 15. 服务改造范围

### 15.1 新增模块（建议）

```text
backend/services/ai/
  context.py, channels.py, catalog.py, resolver.py
  credentials.py, pricing.py, adapters/...

backend/services/points/
  accounts.py, ledger.py, reservation.py, products.py
```

### 15.2 改造重点

| 区域 | 要点 |
|------|------|
| deepseek / image2 / video_* | 接收 AIExecutionContext，去掉全局 configure 串线 |
| main / routers | AI 入口接入双轨与预扣；移除次数配额门槛 |
| 支付回调 | 支持积分充值入账幂等 |
| 前端账户页 | 积分 + Key + 模式；下线次数套餐墙 |
| 生成入口 | 模式切换、模型选择、预计积分 |

### 15.3 旧配置迁移

1. `PlatformSetting` 的 base_url / api_key / model → 默认渠道 + 初始模型。  
2. 为初始模型写入一条默认积分价（管理员可随后调整）。  
3. 浏览器 localStorage 旧 Key → 引导导入用户中心后清除本地明文。  
4. 旧订阅用户：可用管理员批量赠送积分作为补偿（运营策略，代码提供调账工具即可）。

---

## 16. 旧套餐 / 次数下线清单

### 产品

- [ ] AI 生成不再校验套餐是否有效、次数是否用尽  
- [ ] 前台去掉剩余次数、次数包购买  
- [ ] 定价页改为积分充值档位（可保留会员包装为「充值优惠」，但真相是积分）  
- [ ] 管理端隐藏 AI 次数配额配置  

### 代码

- [ ] 短路 AI 路径上的 `check_quota` / 扣次  
- [ ] 删除「自定义 Key 跳过配额」分支，改为明确的 `credential_mode`  
- [ ] 平台模式强制积分预扣  

### 数据

- [ ] 不 DROP 历史表  
- [ ] 标注 deprecated，禁止新逻辑依赖  

---

## 17. 分阶段实施

### 阶段 0：安全与开关

- 功能开关 `AI_BILLING_MODE=points_dual_track`。
- 禁止用户请求覆盖 base_url。
- 开关打开时跳过旧次数配额校验。

### 阶段 1：渠道 + 模型目录 + 请求级上下文

- 渠道/模型表，迁移旧 PlatformSetting。
- 文本链路请求级上下文（可先只支持平台 Key）。

### 阶段 2：积分账户与平台扣费

- 账户、流水、预扣结算。
- 模型积分价。
- 充值档位与支付入账。
- 注册赠送配置。

### 阶段 3：我的 Key 双轨 + 前台选择

- 用户 Key 存储与测试。
- 模式切换、模型选择、费用预估。
- 图片/视频接入同一套模式。

### 阶段 4：旧计费入口下线与运营看板

- 下线次数/套餐 AI 门槛 UI。
- 用量与积分统计。
- 清理死代码。

---

## 18. 测试方案

### 单元 / 集成

- 平台模式积分不足拒绝调用且无上游请求。
- 平台模式成功：预扣 → 实扣 → 释放差额正确。
- 平台模式失败：预扣全释放。
- 同一 request_id 不重复预扣。
- 我的 Key：不扣积分，Authorization 为用户 Key。
- 我的 Key 无 Key：拒绝。
- 用户无法覆盖 base_url。
- 两用户并发不同模式/模型不串线。
- 支付回调积分只入账一次。
- 改价后新请求用新价，旧流水快照不变。

### 前端

- 模式切换文案与预计消耗正确。
- 积分不足引导充值，并可切换我的 Key。
- Key 掩码展示；模型列表按 modality 过滤。

---

## 19. 验收标准

### 双轨

- 平台账户调用扣积分；我的 Key 调用不扣积分。
- 两种模式均使用管理员 base_url 与目录内模型。
- 平台 Key 从不用于 user_key 模式创作请求。

### 积分

- 充值到账、流水可查。
- 预扣/结算/失败释放正确。
- 按模型不同价格扣费正确（至少覆盖 per_call 与一种按量类型）。

### 安全

- 无明文 Key 回传与日志泄漏。
- 无任意 URL 中转。
- 无逃费路径（假 BYOK）。

### 兼容

- 作品与已生成媒体不受损。
- 历史订单数据保留。
- 旧单模型配置可迁移为默认渠道+模型+初始积分价。

---

## 20. 推荐默认配置

| 项 | 默认 |
|----|------|
| 充值比例 | 1 元 = 10 积分（可配） |
| 注册赠送 | 关闭；管理员可开并设数量 |
| 默认模式 | `platform` |
| 文本默认计费 | 可先 `per_call` 降低实现难度；上线后按需改 `per_1k_tokens` |
| 图片 | `per_image` |
| 视频 | `per_second` 或 `per_call`（按现有产品主路径选一个默认） |
| 预扣安全系数 | 1.2 |
| 目录模式 | 白名单上架 |
| 我的 Key 服务费 | 0 |
| 购买积分 | 不过期 |

---

## 21. 与其它方案的关系

| 方案 | 本定稿 |
|------|--------|
| 套餐 + 次数 + 创作点 | 废弃作为 AI 主计费 |
| 纯 NewAPI 中转（本站零计费） | 不采用；无法服务纯充值用户 |
| 积分 + 双轨 | **采用** |

未来若要做「会员每月送积分」，应建成 **积分发放规则**，而不是复活次数配额矩阵。

---

## 22. 结论

采用企业常见形态：

1. **积分** 作为本站唯一 AI 货币，按模型定价。  
2. **平台账户** 用平台 Key，预扣并结算积分。  
3. **我的 Key** 仅配 Key，URL 平台控，模型目录点选，不扣本站积分。  
4. 去掉套餐/次数作为 AI 门槛，换取灵活上架模型与清晰心智。  
5. 请求级上下文保证并发正确；支付与积分子系统保证账务正确。

实施顺序：开关与 URL 锁定 → 渠道模型目录 → 积分账本与平台扣费 → 双轨 Key 与前台选择 → 下线旧配额入口。

---

## 23. 评审确认点

请确认本文档后进入实现计划。若需微调，优先拍板：

1. 文本首期用 `per_call` 还是直接 `per_1k_tokens`。  
2. 充值比例默认 1 元 = ? 积分。  
3. 旧付费套餐用户是否批量补偿积分（运营策略）。  
4. 积分显示名是否就叫「积分」还是「创作点」等（建议统一叫积分，避免与旧文档混淆）。
