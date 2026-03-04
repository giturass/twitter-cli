# Twitter CLI

Twitter/X 命令行工具 — 读取 Timeline、管理推文。

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

### 读取

```bash
# 抓取首页 timeline
twitter feed

# 自定义抓取条数
twitter feed --max 50

# 跳过筛选
twitter feed --no-filter

# JSON 输出
twitter feed --json > tweets.json

# 从已有数据加载
twitter feed --input tweets.json


# 抓取收藏
twitter favorite
twitter favorite --max 30 --json
```

### 用户

```bash
# 查看用户资料
twitter user elonmusk

# 列出用户推文
twitter user-posts elonmusk --max 20

# 查看粉丝
twitter followers elonmusk --max 30

# 查看关注
twitter following elonmusk --max 30
```

### 发推

```bash
# 发新推文
twitter post "Hello World"

# 回复推文
twitter reply <tweet_id> "这是回复内容"

# 引用转推（传 URL 或 ID 均可）
twitter quote <tweet_url_or_id> "这是引用内容"

# 删除推文（会有确认提示）
twitter delete <tweet_id>

# 跳过删除确认
twitter delete <tweet_id> --yes
```

## Pipeline

```
抓取 (GraphQL API)  →  筛选 (Engagement Score)
      50 条               top 20
```

### 筛选算法

加权评分公式，收藏权重最高（代表"值得回看"）：

```
score = 1.0 × likes + 3.0 × retweets + 2.0 × replies
      + 5.0 × bookmarks + 0.5 × log10(views)
```

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
```

### Cookie 配置

**方式 1：自动提取**（推荐） — 确保浏览器已登录 x.com，程序自动通过 `browser-cookie3` 按 Chrome → Edge → Firefox → Brave 顺序尝试读取。

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
├── client.py       # Twitter GraphQL API Client (GET + POST)
├── auth.py         # Cookie 提取 (env / browser-cookie3)
├── filter.py       # Engagement scoring + 筛选
├── formatter.py    # Rich 终端输出 + JSON
├── config.py       # YAML 配置加载
└── models.py       # 数据模型 (dataclass)
```

## 注意事项

- 使用 Cookie 登录存在被平台检测的风险，建议使用**专用小号**
- Cookie 只存在本地，不上传不外传
- GraphQL `queryId` 会从 Twitter 前端 JS 自动检测，无需手动维护
