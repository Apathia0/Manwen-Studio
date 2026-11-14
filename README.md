# StoryCanvas（漫文工坊）

> 写小说、做漫画、拍漫剧 —— 一个平台，一站式完成。
>
> 同一个故事、同一套角色设定，从第一行文字一路做到漫画成图，再到视频成片。

<p align="left">  
  <img alt="license" src="https://img.shields.io/badge/license-Apache%202.0-blue" />  
  <img alt="python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB" />  
  <img alt="fastapi" src="https://img.shields.io/badge/FastAPI-0.115%2B-009688" />  
  <img alt="react" src="https://img.shields.io/badge/React-19-61DAFB" />  
</p>

![StoryCanvas 首页](docs/screenshots/01-hero.png)

---

## 目录

- [为什么是 StoryCanvas](#为什么是-storycanvas)
- [核心创作能力](#核心创作能力)
- [SaaS 平台能力](#saas-平台能力)
- [适用人群](#适用人群)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [配置 API Key](#配置-api-key)
- [项目结构](#项目结构)
- [完整截图](#完整截图)
- [安全说明](#安全说明)
- [常见问题](#常见问题)
- [License](#license)

---

## 为什么是 StoryCanvas

市面上的工具大多只覆盖单点：写作软件不管分镜，绘图工具不懂剧情，视频工具要你重新喂一遍设定。

StoryCanvas 把**小说剧本 → 漫画 → 漫剧**串成一条完整链路。三个阶段共用同一个项目与同一套设定：小说是底稿，分镜是桥梁，漫画与视频是成品，**前一步的结果直接成为下一步的输入**，不必在多个工具之间来回搬运。

![三大创作链路](docs/screenshots/02-three-stages.png)

---

## 核心创作能力

### 一、小说与剧本创作

从一句灵感到可连载的长篇，再改成可拍的剧本。

- **一句灵感生成框架** —— 自动产出题材、世界观、三幕式大纲与章节规划
- **角色与设定统一管理** —— 角色小传、关系线、外观描述、参考图集中在角色库
- **章节扩写** —— 保持节奏与风格续写，AI 助手随时介入改写、润色、调整
- **正文转剧本** —— 小说内容一键转为剧本格式，直接作为漫画与漫剧的底稿
- **风格参考** —— 上传参考文本，让 AI 对齐文风
- **连续性保障** —— 自动摘要前文要点，降低章节之间的设定冲突

![小说作品库](docs/screenshots/09-stories.png)

![小说创作工作台：左侧故事框架与设定，中间章节编辑器，右侧 AI 写作助手](docs/screenshots/13-novel-workspace.png)

工作台是三栏结构：左边是**故事框架 / 标签设定 / 角色设定**，中间是可切章的正文编辑器，右边是能直接改写正文的 **AI 写作助手**。

### 二、漫画创作

小说一键转分镜，分镜直接出漫画。

- **自动拆分镜** —— 自动拆分场景、镜头与对白，生成分镜脚本
- **分镜可编辑** —— 逐条修改镜头描述、景别、构图与情绪
- **角色一致性参考** —— 锁定人物外貌，减少画风与形象漂移
- **批量出图** —— 漫画批量生成，关键画面支持单图重绘与修正
- **成图留在项目里** —— 方便复盘与连载迭代，不会散落在本地文件夹

![漫画创作工作台：分镜总览、逐格生成与角色参考，左侧按章切换](docs/screenshots/14-manga-studio.png)

一次生成 **4 格一页**的分镜，每格可单独重绘；右上角统一控制彩色/黑白、画幅比例、画风与资产自动匹配，整章出图不用一格格手工拼。

### 三、漫剧创作（无限画布）

在无限画布上把剧本做成视频，合成完整漫剧。

![漫剧无限画布](docs/screenshots/03-manga-canvas.png)

![漫剧画布实景：剧本、拆分、导演、资产、分镜、出图逐段点亮，节点之间自动连线](docs/screenshots/15-manga-drama-canvas.png)

图中是一个真实项目的画布（56 个节点、203 条连线）：顶部状态条按 **剧本 → 拆分 → 导演 → 资产 → 分镜 → 出图** 逐段亮起，每一段通过才解锁下一段；右侧 AI 助手可以读整张画布，支持自动模式与"先给方案再执行"的询问模式。

- **节点化工作台** —— 剧本、场景、角色、故事版、视频都是画布上的节点，上下游关系一目了然
- **改稿即失效** —— 剧本一改，旧的拆分结果自动标记为过期，不会悄悄带着旧内容往下走
- **逐场景审核** —— 只有**批准**的场景才会被编译生成，没批准的不消耗额度
- **生成视频** —— 时长自动对齐模型支持的档位，再提交生成
- **合片导出** —— 各场景在画布上汇合，合成完整成片
- **版本可回退** —— 画布每次改动留存版本，可对比、可恢复

### 四、贯穿全流程的三件套

![AI 助手、创作台与模型广场](docs/screenshots/04-assistant.png)

| 能力          | 说明                             |
| ----------- | ------------------------------ |
| **AI 创作助手** | 小说工作台与漫剧画布都内置助手，对话即可读取、改写、生成内容 |
| **创作台**     | 不绑定作品的临时创作区，灵感来了随时独立出图、出视频     |
| **模型广场**    | 文本 / 图片 / 视频模型的能力参数与积分单价全部公开可查 |

助手的核心设计是 **改动先预览、确认才落地**：读出画布、按选中节点精确定位、上传参考图先做风格分析，每次改动都留存版本可回退。

![创作台](docs/screenshots/10-studio.png)

创作台支持图片与视频双模式：图片可调质量与比例，视频可选模型、画幅、清晰度与时长，都能挂参考图与排除词。

---

## SaaS 平台能力

除创作功能外，本项目内置了一套可直接运营的 SaaS 商业化底座，开箱即可售卖积分、管理用户。

![模型定价](docs/screenshots/05-model-billing.png)

### 账户与权限

- 邮箱注册 / 登录、邮箱验证码校验、会话管理
- 角色区分（普通用户 / 管理员），按角色展示可用菜单
- 管理员可代管用户、查看其作品与权益

### 积分计费体系

- **平台积分**：文本 / 图片按模型定价扣减，视频按秒计费
- **预扣机制**：长任务先预扣、完成后结算，避免超额消耗
- **用量台账**：每次调用记录积分流水，可追溯到具体模型与任务
- **月度用量统计**：按月汇总，配合配额规则做限流

### 套餐与订阅

数据模型已完整落地：`Plan` / `PlanFeature` / `PlanQuotaRule` / `UserSubscription` / `UserUsageMonthly` / `UserQuotaGrantMonthly`。

- 套餐管理（增删改、功能开关、配额规则）
- 订阅与到期处理
- 管理员手动发放额度（quota grant）

### 支付与订单

- **支付宝当面付**（`backend/services/alipay_f2f.py`，RSA2 签名 + 验签）
- 异步回调 `/api/payments/alipay/notify` 对账
- 订单状态流转、超时取消、主动查询同步

### 我的 Key（BYOK）

用户可在账户页配置自己的上游 API Key，走自己的额度，**不扣本站积分**。平台 Key 与用户 Key 双轨并存。

### 模型广场与定价

![模型广场](docs/screenshots/07-model-plaza.png)

- 模型能力参数与积分单价公开可查，**无需注册即可浏览**
- 文本 / 图片 / 视频模型分类展示
- 后台可上架、下架、调价（`/api/admin/...`）

### 套餐与充值

![积分套餐](docs/screenshots/08-pricing.png)

- 体验包、档位套餐、赠送积分规则
- 积分充值后即时可用于平台模型调用
- 也支持「同平台项目搭建授权」等一次性商品

### 运营后台

![用户管理](docs/screenshots/11-admin-users.png)

- 用户管理：增删改查、角色与账号状态控制、代发积分与配额
- 订单管理、收入看板与支付转化统计
- 套餐管理、平台公告与全局设置
- **审计日志**（`AuditLog`），关键操作全程留痕

![积分与 AI 渠道配置](docs/screenshots/12-admin-config.png)

积分规则（兑换比例、注册赠送）、充值套餐、上游 AI 渠道与模型目录计价，均在后台统一配置，改价无需改代码。

### 授权码服务（`auth/`）

`auth/` 是一套独立的 PHP 授权码系统（**独立仓库，未包含在主仓库中**），可用于域名授权、授权码发放与验证，适合做私有部署授权。

---

## 适用人群

![面向长期创作者](docs/screenshots/06-for-creators.png)

- **网文作者** —— 快速搭建长篇框架，稳定日更连载，再扩写成漫画与漫剧
- **漫画工作室** —— 把剧本、分镜和角色参考整合在同一工作流里，减少沟通成本
- **漫剧与短视频创作者** —— 从剧本到视频合片都在画布上完成，用助手加速反复调整
- **内容创业团队** —— 适合做 IP 孵化、短篇试水、爆款验证和图文视频矩阵扩展

---

## 技术栈

| 层    | 技术                                             |
| ---- | ---------------------------------------------- |
| 前端   | React 19 · TypeScript · Vite 8 · TailwindCSS 4 |
| 后端   | Python 3.10+ · FastAPI · SQLAlchemy            |
| 数据库  | PostgreSQL 16（也可用 SQLite）                      |
| AI   | DeepSeek / GPT / GLM 等文本模型 · 图片模型 · 视频模型（可插拔）  |
| 视频   | 云端视频 API，或本地 ComfyUI 工作流                       |
| 支付   | 支付宝当面付（RSA2）                                   |
| 授权服务 | PHP 8 · MySQL（可选，独立部署）                         |

后端单文件路由共 **109 个接口**，覆盖认证、创作、计费、支付、后台管理。

---

## 快速开始

### 前置要求

- **Python 3.10+**
- **Node.js 18+**
- **PostgreSQL 16**（或使用 SQLite，见下文）

### 1. 克隆仓库

```bash
git clone https://github.com/dream619/Manwen-Studio.git
cd Manwen-Studio
```

### 2. 准备数据库

```sql
CREATE DATABASE manga_novel;
```

默认连接串：

```text
postgresql://postgres:postgres@localhost:5432/manga_novel
```

> 若使用 SQLite，把 `.env` 中的 `DATABASE_URL` 改为  
> `sqlite:///./storycanvas.db` 即可，无需安装 PostgreSQL。

### 3. 配置环境变量

```bash
cd backend
cp .env.example .env      # Windows: copy .env.example .env
```

编辑 `backend/.env`：

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/manga_novel
HOST=127.0.0.1
PORT=8000
```

> ⚠️ **API Key 不要写进 `.env` 后提交。** 推荐在网页端「API Key」设置里填写，  
> 密钥只保存在浏览器本地存储中。详见 [安全说明](#安全说明)。

### 4. 安装依赖

**方式一（推荐，Windows 用户）**：双击根目录 `install.bat`，自动检查环境并安装前后端依赖。

**方式二（手动）**：

```bash
# 后端
cd backend && pip install -r requirements.txt && cd ..

# 前端
cd frontend && npm install && cd ..
```

### 5. 启动

**方式一**：双击根目录 `start.bat`（自动启动前后端并打开浏览器）。

**方式二**：两个终端分别启动：

```bash
# 终端 1
cd backend && python main.py

# 终端 2
cd frontend && npm run dev
```

访问 <http://localhost:5173>

---

## 配置 API Key

打开网页后点击右上角 **API Key**，分别配置：

| Key                  | 用途                 | 获取地址                           |
| -------------------- | ------------------ | ------------------------------ |
| **DeepSeek API Key** | 小说生成、分镜拆解、Agent 对话 | <https://newapi.aifusion6.cn/> |
| **Image2 API Key**   | 漫画 / 插画生成          | <https://newapi.aifusion6.cn/> |

填入后保存即可，无需重启服务。

若启用 SaaS 计费模式，则由后台「模型广场」统一配置平台 Key，用户走积分扣费或自备 Key。

---

## 项目结构

```text
Manwen-Studio/
├── backend/                 # FastAPI 后端
│   ├── main.py              # 应用入口与主路由（109 个接口）
│   ├── models.py            # SQLAlchemy 数据模型（含套餐/订单/配额/审计）
│   ├── database.py          # 数据库连接与会话
│   ├── routers/             # 路由模块（agent / video）
│   ├── services/            # 业务服务
│   │   ├── deepseek.py      # 文本模型
│   │   ├── image2.py        # 图片模型
│   │   ├── storyboard.py    # 分镜拆解
│   │   ├── screenplay.py    # 剧本转换
│   │   ├── agent_service.py # Agent 工具调用
│   │   ├── alipay_f2f.py    # 支付宝当面付
│   │   └── video_*.py       # 视频生成链路（含 ComfyUI）
│   ├── workflows/           # ComfyUI 工作流模板
│   ├── tests/               # pytest 测试套件（61 个测试文件）
│   └── .env.example         # 环境变量模板
├── frontend/                # React + TypeScript 前端
│   └── src/
│       ├── components/      # UI 组件
│       ├── prompts/         # 提示词工程模块
│       ├── api.ts           # 后端接口封装
│       └── genStore.ts      # 生成任务状态管理
├── auth/                    # 独立授权码服务（PHP，未纳入本仓库）
├── docs/screenshots/        # README 截图
├── install.bat / start.bat  # Windows 一键安装 / 启动
├── NOTICE
└── LICENSE
```

---

## 完整截图

**创作工作台（核心）**

| 小说创作工作台 | 漫画创作工作台 |
| --- | --- |
| ![小说创作工作台](docs/screenshots/13-novel-workspace.png) | ![漫画创作工作台](docs/screenshots/14-manga-studio.png) |

| 漫剧无限画布（真实项目速览） |
| --- |
| ![漫剧无限画布](docs/screenshots/15-manga-drama-canvas.png) |

**产品与计费**

| 首页 | 三大创作链路 |
| --- | --- |
| ![首页](docs/screenshots/01-hero.png) | ![三大创作链路](docs/screenshots/02-three-stages.png) |

| 漫剧无限画布（演示态） | AI 助手与创作台 |
| --- | --- |
| ![漫剧无限画布演示](docs/screenshots/03-manga-canvas.png) | ![AI 助手与创作台](docs/screenshots/04-assistant.png) |

| 模型定价 | 模型广场 |
| --- | --- |
| ![模型定价](docs/screenshots/05-model-billing.png) | ![模型广场](docs/screenshots/07-model-plaza.png) |

| 积分套餐 | 适用人群 |
| --- | --- |
| ![积分套餐](docs/screenshots/08-pricing.png) | ![适用人群](docs/screenshots/06-for-creators.png) |

**个人中心与运营后台**

| 小说作品库 | 创作台 |
| --- | --- |
| ![小说作品库](docs/screenshots/09-stories.png) | ![创作台](docs/screenshots/10-studio.png) |

| 用户管理 | 积分与 AI 渠道配置 |
| --- | --- |
| ![用户管理](docs/screenshots/11-admin-users.png) | ![积分与 AI 渠道配置](docs/screenshots/12-admin-config.png) |

---

## 安全说明

本项目在开源前已完成密钥扫描，仓库中**不含任何真实凭据**。部署时请注意：

- **不要提交 `.env`** —— 已在 `.gitignore` 中屏蔽，包含 `*.env.bak*` 等备份文件变体
- **API Key 优先走前端输入** —— 后端 `.env` 中的 Key 仅作为兜底
- **修改默认配置** —— PostgreSQL 默认 `postgres/postgres` 仅用于本地开发，生产环境务必更改
- **授权服务** —— `auth/` 下默认管理员为 `admin / admin123`，**首次登录必须修改**
- **公网部署** —— 建议置于 Nginx 之后并启用 HTTPS，同时设置 `API_TOKEN` 与严格的 `CORS_ORIGINS`
- **支付回调** —— 支付宝 notify 接口必须开启验签，并在服务端二次校验金额与订单状态

发现安全问题请参阅 [SECURITY.md](SECURITY.md)，请勿直接开公开 Issue。

---

## 常见问题

<details>

<summary><b>生成图片失败 / 超时？</b></summary>

确认图片模型 Key 有效且余额充足；单张生成通常需要 20–60 秒。

</details>

<details>

<summary><b>不想装 PostgreSQL？</b></summary>

使用 SQLite：把 `DATABASE_URL` 设为 `sqlite:///./storycanvas.db`，首次启动会自动建表。

</details>

<details>

<summary><b>视频生成怎么配置？</b></summary>

默认走云端视频 API。如需本地生成，安装 ComfyUI 后设置：

```env
VIDEO_PROVIDER=comfyui
COMFYUI_BASE_URL=http://127.0.0.1:8188
```

</details>

<details>

<summary><b>如何开启积分计费？</b></summary>

在管理后台配置套餐与模型定价后，用户调用将按积分扣费。  
若只想自用，可不启用计费，直接使用前端填写的 API Key。

</details>

<details>

<summary><b>端口被占用？</b></summary>

改 `backend/.env` 的 `PORT`；前端端口改 `frontend/vite.config.ts` 中的 `server.port`。

</details>

---

## 贡献

欢迎 Issue 与 PR。提交前请确保：

1. 不包含任何密钥、令牌、真实域名或服务器信息
2. 新增代码附带相应测试（`cd backend && pytest`）
3. 遵循现有代码风格

---

## License

本项目采用 [Apache License 2.0](LICENSE) 授权，Copyright 2026 libohan-ha。

你可以自由地使用、修改、分发本项目（包括商业用途），但需遵守以下条件：

- 保留版权声明、许可声明与 [`NOTICE`](NOTICE) 文件
- 修改过的文件需标注「已修改」
- 若发起专利诉讼指控本项目侵权，你获得的相关专利授权将自动终止

> Apache-2.0 相比 MIT 额外提供了**明确的专利授权**与**商标保护**条款，  
> 更适合可能被企业采用的项目。详见 [LICENSE](LICENSE) 全文。
