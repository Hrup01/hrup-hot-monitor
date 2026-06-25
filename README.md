# Hot Monitor

一个面向热点追踪场景的本地 Web 监控工具。项目通过多源检索、证据聚合和 AI/启发式分析，生成可筛选、可追溯、可推送的热点看板，适合用于追踪 AI、产品、品牌、舆情或专题趋势。

## 功能概览

- 多源采集：聚合 TwitterAPI.io 与主流搜索/内容站点信号
- 热点识别：优先调用 OpenRouter 做结构化分析，无 Key 时自动回退为启发式评分
- 实时看板：展示热点等级、热度分、趋势变化、多源共振、证据明细
- 手动触发：支持立即扫描，方便调试和人工验收
- 定时轮询：默认每 30 分钟自动执行一次分析
- 通知能力：支持浏览器通知，满足阈值时可选发送 SMTP 邮件
- 本地持久化：配置、历史结果、通知记录保存在 `data/state.json`

## 当前支持的数据源

- Twitter
- Bing
- Google
- DuckDuckGo
- HackerNews
- Baidu
- 360Search
- Sogou
- Weixin
- Zhihu
- Bilibili
- Weibo
- Douyin
- Xiaohongshu
- Tieba

## 技术栈

- 后端：Python 标准库 `http.server`
- 前端：原生 HTML / CSS / JavaScript
- AI 分析：OpenRouter Chat Completions
- 推送：Server-Sent Events + Browser Notification API
- 邮件：SMTP

项目当前不依赖第三方 Python 包，默认使用系统自带 Python 3 即可启动。

## 快速开始

### 1. 准备环境

建议使用 Python 3.10 及以上版本。

```bash
python --version
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，按需填写：

```env
# OpenRouter
OPENROUTER_API_KEY=
OPENROUTER_MODEL=openai/gpt-5.2
OPENROUTER_SITE_URL=http://localhost:8000
OPENROUTER_SITE_NAME=Hot Monitor

# TwitterAPI.io
TWITTERAPI_KEY=

# Runtime
HOTMONITOR_POLL_SECONDS=1800
PORT=8000
```

说明：

- `OPENROUTER_API_KEY` 为空时，系统仍可运行，但会使用启发式分析结果
- `TWITTERAPI_KEY` 为空时，Twitter 数据源不可用，其余网页数据源仍可工作
- `HOTMONITOR_POLL_SECONDS` 默认值为 `1800`，即每 30 分钟轮询一次

### 3. 启动服务

```bash
python app.py
```

启动成功后访问：

[http://127.0.0.1:8000](http://127.0.0.1:8000)

## 使用说明

### 基本流程

1. 在页面中填写搜索主题，或维护监控词列表
2. 点击“立即扫描”触发一次采集与分析
3. 在热点看板中查看热度、来源覆盖、趋势和证据
4. 如需浏览器通知，首次进入页面后授权通知权限
5. 如需邮件通知，在配置中补充 SMTP 信息并启用邮件发送

### 分析模式

- `openrouter`：已配置 OpenRouter Key，返回 AI 结构化分析
- `heuristic`：未配置 OpenRouter Key，使用本地启发式评分
- `fallback`：调用 OpenRouter 失败后自动回退到启发式分析

### 阈值与通知

- 系统默认推送阈值为 `70`
- 当热点分数大于等于阈值时：
  - 通过 SSE 向前端广播通知事件
  - 浏览器已授权时弹出系统通知
  - 若启用邮件配置，则发送一封热点提醒邮件

## API 一览

### `GET /api/state`

返回：

- 数据源列表
- 当前配置与运行状态
- 聚合后的仪表盘数据
- OpenRouter / TwitterAPI 是否已就绪
- 当前轮询周期

### `POST /api/config`

保存配置，支持以下字段：

- `query`
- `watch_terms`
- `source_inputs`
- `settings`
- `manual_keywords`

### `GET /api/run`

立即执行一次采集和热点分析，返回本次分析结果。

### `GET /api/events`

SSE 事件流，用于前端接收：

- `notification`
- `result`
- `error`

## 目录结构

```text
hrup-hot-moniter/
├─ app.py                 # 服务入口与核心逻辑
├─ README.md
├─ .env.example           # 环境变量示例
├─ data/
│  └─ state.json          # 运行状态与历史结果
├─ docs/
│  ├─ requirements.md     # 需求说明
│  └─ technical-plan.md   # 技术方案
├─ web/
│  ├─ index.html          # 前端页面
│  ├─ styles.css          # 前端样式
│  └─ app.js              # 前端交互逻辑
└─ skills/
   └─ hot-monitor/        # 相关技能脚本与参考资料
```

## 状态持久化

系统会将以下信息写入 `data/state.json`：

- 当前查询词
- 监控词列表
- 手动补充的数据源文本
- 邮件与推送设置
- 最新一次分析结果
- 历史分析记录
- 通知记录
- 最近错误信息

## 已知限制

- 搜索引擎和内容站点页面结构可能变化，导致抓取结果波动
- 未配置 TwitterAPI Key 时，Twitter 源不会参与分析
- 浏览器通知依赖页面打开且用户已授权
- 邮件发送依赖有效 SMTP 配置
- 当前为本地单机运行形态，未包含用户鉴权、多租户和任务队列

## 适用场景

- AI 产品与模型热点追踪
- 品牌舆情与话题预警
- 竞品动态监控
- 垂直行业内容雷达
- 自定义关键词趋势观察

## 后续可扩展方向

- 增加更多数据源与更稳定的采集适配层
- 引入数据库和更完整的历史趋势分析
- 支持多主题、多订阅人、多阈值策略
- 补充导出报表、Webhook、企业微信/飞书通知
- 将当前能力封装为独立 Agent Skill 或服务化组件
