# Twitter CLI

从你的 Twitter/X 首页抓取推文，智能筛选高价值内容，AI 自动生成摘要。

**零 API Key** — 使用浏览器 Cookie 认证，免费访问 Twitter。

## Quick Start

```bash
# 安装
cd twitter-cli
uv sync

# 运行（自动从 Chrome 提取 Cookie）
twitter feed
```

首次运行确保 Chrome 已登录 x.com。

## 使用方式

```bash
# 完整 pipeline：抓取 50 条 → 筛选 top 20 → AI 总结
twitter feed

# 自定义抓取条数
twitter feed --count 50

# 只抓取 + 筛选，跳过 AI 总结
twitter feed --no-summary

# JSON 输出（可重定向到文件）
twitter feed --json > tweets.json

# 对已有数据做筛选 + 总结
twitter feed --input tweets.json

# 跳过筛选
twitter feed --no-filter

# 指定浏览器
twitter feed --browser firefox

# 抓取收藏
twitter bookmarks
twitter bookmarks --count 30 --json
```

## Pipeline

```
抓取 (GraphQL API)  →  筛选 (Engagement Score)  →  AI 总结
      50 条               top 20                  按主题分组
```

### 筛选算法

加权评分公式，收藏权重最高（代表"值得回看"）：

```
score = 1.0 × likes + 3.0 × retweets + 2.0 × replies
      + 5.0 × bookmarks + 0.5 × log10(views)
```

### AI 总结

支持 **OpenAI-compatible**（doubao / deepseek / openai）和 **Anthropic**（Claude）两种 API 格式。

## 配置

编辑 `config.yaml`：

```yaml
fetch:
  count: 50

filter:
  mode: "topN"          # "topN" | "score" | "all"
  topN: 20
  weights:
    likes: 1.0
    retweets: 3.0
    replies: 2.0
    bookmarks: 5.0
    views_log: 0.5

ai:
  provider: "openai"    # "openai" or "anthropic"
  api_key: ""           # 或设置环境变量 AI_API_KEY
  model: "doubao-seed-2.0-code"
  base_url: "https://ark.cn-beijing.volces.com/api/coding"
  language: "zh-CN"
```

### Cookie 配置

**方式 1：自动提取**（推荐） — 确保 Chrome 已登录 x.com，程序自动通过 `browser-cookie3` 读取。

**方式 2：环境变量** — 设置：

```bash
export TWITTER_AUTH_TOKEN=your_auth_token
export TWITTER_CT0=your_ct0
```

可通过 [Cookie-Editor](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm) 浏览器插件导出。

## 项目结构

```
twitter_cli/
├── __init__.py     # 版本信息
├── cli.py          # CLI 入口 (click)
├── client.py       # Twitter GraphQL API Client
├── auth.py         # Cookie 提取 (env / browser-cookie3)
├── filter.py       # Engagement scoring + 筛选
├── summarizer.py   # AI 总结 (OpenAI + Anthropic)
├── formatter.py    # Rich 终端输出 + JSON
├── config.py       # YAML 配置加载
└── models.py       # 数据模型 (dataclass)
```

## 注意事项

- 使用 Cookie 登录存在被平台检测的风险，建议使用**专用小号**
- Cookie 只存在本地，不上传不外传
- GraphQL `queryId` 会从 Twitter 前端 JS 自动检测，无需手动维护
