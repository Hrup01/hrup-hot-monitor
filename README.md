# Hot Monitor

一个轻量热点监测网页版，默认聚合 8 个来源：
Twitter、Bing、Google、DuckDuckGo、HackerNews、搜狗、B站、微博。

## 启动

```bash
python app.py
```

默认访问：
`http://127.0.0.1:8000`

## .env 配置

项目启动时会自动读取根目录 `.env`：

```env
OPENROUTER_API_KEY=
OPENROUTER_MODEL=openai/gpt-5.2
OPENROUTER_SITE_URL=http://localhost:8000
OPENROUTER_SITE_NAME=Hot Monitor
TWITTERAPI_KEY=
HOTMONITOR_POLL_SECONDS=1800
PORT=8000
```

也可以参考 `.env.example`。

## 推送

- 浏览器推送：打开页面后授权 Notification
- 邮件推送：在页面里填写 SMTP 配置并启用

## 说明

当前版本会：

- 对多源进行抓取/聚合
- 优先用 OpenRouter 做热点识别
- 无 Key 时自动回退为启发式评分
- 每 30 分钟自动检查一次
