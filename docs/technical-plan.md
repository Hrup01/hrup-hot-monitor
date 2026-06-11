# 技术方案

## 总体架构

采用轻量本地 Web 应用：

- 后端：Python 标准库 HTTP 服务。
- 前端：原生 HTML / CSS / JavaScript。
- AI：OpenRouter Chat Completions。
- Twitter / X：TwitterAPI.io Advanced Search。
- 网页来源：通过搜索 URL 抓取 HTML 后抽取标题、链接、摘要类文本。
- 推送：Server-Sent Events + 浏览器 Notification API；邮箱使用 SMTP。

这样可以在空目录内快速落地 MVP，不引入复杂框架和依赖，后续也方便封装为 Agent Skill。

## MCP 查询结论

### OpenRouter

MCP 来源：Context7 `/llmstxt/openrouter_ai_llms-full_txt`

确认点：

- Chat Completions Endpoint：`POST https://openrouter.ai/api/v1/chat/completions`
- 必要请求头：
  - `Authorization: Bearer <OPENROUTER_API_KEY>`
  - `Content-Type: application/json`
- 可选请求头：
  - `HTTP-Referer`
  - `X-OpenRouter-Title`
- 支持 `response_format`：
  - `{ "type": "json_object" }`
  - 或 `{ "type": "json_schema", "json_schema": { ... } }`

采用方案：使用 `json_schema` 强制返回热点识别结构，降低 JSON 解析失败概率。

### TwitterAPI.io

MCP 来源：Context7 `/websites/twitterapi_io_api-reference`

确认点：

- Advanced Search Endpoint：`GET https://api.twitterapi.io/twitter/tweet/advanced_search`
- 认证请求头：`X-API-Key`
- 查询参数：
  - `query`：支持高级搜索语法
  - `queryType`：`Latest` 或 `Top`
- 文档提示不要依赖分页，建议用 `since_time` 与 `until_time` 控制单次请求结果规模。

采用方案：每次检查用关键词构造 `query`，附加最近 6 小时的 `since_time` / `until_time`，`queryType=Latest`。

### Browser Notification / EventSource

MCP 来源：Context7 `/websites/developer_mozilla_en-us`

确认点：

- `Notification.requestPermission()` 应由用户点击触发。
- `new Notification(title, options)` 可创建浏览器通知。
- `new EventSource(url)` 用于接收 Server-Sent Events。

采用方案：前端按钮触发通知授权；后端通过 `/api/events` 发送 SSE；热点达到阈值后前端创建通知。

## 数据流

1. 用户配置关键词和可选 SMTP。
2. 后端定时器每 30 分钟触发分析。
3. 后端同时采集 8 个来源：
   - Twitter 使用 TwitterAPI.io。
   - 其他来源通过搜索页 URL 抓取。
   - 用户可在页面补充各来源人工摘录。
4. 后端将多源信号交给 OpenRouter。
5. OpenRouter 返回结构化热点判断。
6. 后端保存结果和历史。
7. 达到阈值时：
   - 通过 SSE 发给浏览器。
   - 如果邮箱启用，则发送 SMTP 邮件。

## 接口设计

### `GET /api/state`

返回应用状态、来源列表、最近结果、是否已配置 OpenRouter / TwitterAPI。

### `POST /api/config`

保存关键词、人工来源输入、邮箱设置。

### `GET /api/run`

立即执行一次热点采集与分析。

### `GET /api/events`

SSE 事件流，用于浏览器推送。

## 风险与约束

- 搜索引擎页面可能因为反爬、地区、验证码、HTML 改版导致抓取失败。
- 默认低频抓取，每 30 分钟一次，减少被限制概率。
- TwitterAPI.io 需要用户提供 `TWITTERAPI_KEY`。
- OpenRouter 需要用户提供 `OPENROUTER_API_KEY`。
- 当前浏览器通知要求页面打开并授权；若需要页面关闭后仍推送，需要后续扩展 Service Worker + Push Subscription。

## 验收标准

- 本地服务可启动。
- 页面可访问。
- 可配置关键词并立即分析。
- 8 个来源均在页面中展示。
- 未配置 Key 时有明确状态和回退能力。
- 配置 Key 后可调用 OpenRouter / TwitterAPI.io。
- 浏览器授权后可接收热点通知。
- 邮箱配置完整并启用后可发送邮件。

