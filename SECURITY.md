# Security Policy

## 支持的版本

| 版本 | 安全更新 |
|---|---|
| v1.2.x | ✅ 支持 |
| < v1.2 | ❌ 不再维护 |

## 报告安全漏洞

**请不要通过公开 Issue 报告安全问题。**

请通过以下任一私下渠道联系我们，并在标题中标注 `[SECURITY]`：

- 发送邮件至项目维护者（见仓库 `git log` 中的提交者邮箱）
- 通过 GitHub 的 [Private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) 功能提交

请在报告中包含：

1. 漏洞类型与影响范围
2. 复现步骤（最小可复现示例）
3. 受影响的版本 / commit
4. 可选：修复建议

我们会在 **3 个工作日内**确认收到，并在修复发布后致谢（如你愿意署名）。

---

## 部署安全基线

本项目默认配置面向**本地开发**。部署到公网前请逐项确认：

### 凭据管理

- [ ] `backend/.env` 未被提交（已在 `.gitignore` 屏蔽，含 `*.env.bak*` 变体）
- [ ] 仓库中不存在真实 API Key、数据库密码、私钥
- [ ] 数据库密码已从默认 `postgres/postgres` 更改为强密码
- [ ] `auth/config/database.php` 未提交（仅提交 `database.php.example`）

### 访问控制

- [ ] 设置 `API_TOKEN`，并在前端配置匹配的 `VITE_API_TOKEN`
- [ ] `CORS_ORIGINS` 收敛为实际域名，不要使用 `*`
- [ ] 后端 `HOST` 绑定 `127.0.0.1`，由反向代理对外暴露
- [ ] 授权服务默认管理员 `admin / admin123` 已修改
- [ ] 管理后台入口增加 IP 白名单或额外认证

### 传输与基础设施

- [ ] 全站启用 HTTPS（Nginx / Caddy 反代 + 自动证书）
- [ ] 上传大小限制 `MAX_UPLOAD_BYTES` 按需调低
- [ ] 关闭调试模式，生产环境不暴露 `/docs` 与堆栈信息
- [ ] 定期备份数据库，备份文件不置于 Web 根目录

### 第三方服务

- [ ] API Key 遵循最小权限原则，单独申请、单独吊销
- [ ] 定期轮换 Key，泄露后立即在服务商后台作废
- [ ] 不将 Key 写入前端构建产物（`VITE_` 前缀会打包进客户端）

---

## 已知的安全设计

- **API Key 存储于浏览器 localStorage**，不上传服务端持久化。
  这意味着 XSS 可读取 Key —— 请谨慎引入第三方脚本。
- **后端 `.env` 中的 Key 仅作兜底**，前端未填写时才会使用。
- **授权校验为离线式**，客户端可被绕过；其定位是防误用而非强 DRM。

---

## 致谢

感谢所有负责任地披露问题的安全研究者。
