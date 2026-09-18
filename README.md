# YouTube 数据看板 · 每日自动采集

架构：**GitHub Actions（每天自动跑 Python）→ Google Sheets（存历史）→ Looker Studio（看板）＋ Python（深度分析）**

```
GitHub Actions 定时(每天 10:00 北京) ──► YouTube Data API(全部视频累计值)
                                      ──► YouTube Analytics API(前天日明细)
                                              │
                                              ▼
                                     Google Sheets（免费 · 历史永久追加）
                                              │
                        ┌─────────────────────┴─────────────────────┐
                        ▼                                           ▼
              Looker Studio 看板（日常看）                Python 深度分析（年龄对齐/增长/相关性）
```

- **免费**：GitHub Actions 私有仓库 2000 分钟/月（每天 3 分钟，用不到 5%）；Sheets 免费；Looker Studio 免费
- **不用开电脑**：脚本跑在 GitHub 服务器上，采集全程在 Google 云端内部完成，无需翻墙
- **历史永久可回溯**：每天追加一行，不覆盖；查任意一天 = 筛选 snapshot_date

---

## 一、你只需要做一次的准备（约 30 分钟）

### 第 1 步：Google Cloud 开启两个 API（约 10 分钟）
1. 打开 https://console.cloud.google.com/ ，登录你的 Google 账号
2. 顶部选择或新建一个项目（名字随意，如 `youtube-dashboard`）
3. 左侧菜单 → **APIs & Services → Library**
4. 搜索并依次启用这两个 API：
   - **YouTube Analytics API**
   - **Google Sheets API**
5. 左侧 **APIs & Services → OAuth consent screen**：
   - User Type 选 **External** → Create
   - App name 随意填（如 `yt-dashboard`），邮箱填你的 Gmail
   - Scopes 页可以跳过直接保存（脚本会请求需要的权限）
   - Test users → **Add users → 填你自己的 Gmail**（重要！否则授权会失败）
6. 左侧 **APIs & Services → Credentials → Create credentials → OAuth client ID**：
   - Application type 选 **Desktop app**
   - 创建后点 **Download JSON** → 得到一个 `client_secret.json`

### 第 2 步：本机授权一次，拿 refresh token（约 5 分钟）
1. 把 `client_secret.json` 放到本项目文件夹（和 `get_token.py` 同目录）
2. 在**能访问 Google 的环境**里（你的代理环境）打开终端，进入项目目录：
   ```bash
   pip install -r requirements.txt
   python get_token.py
   ```
3. 浏览器会弹出 Google 授权页 → 登录你的 Google → 点 **Allow**
4. 授权完成后目录里会生成 **`credentials.json`**（含长期有效的 refresh_token）

### 第 3 步：上传到 GitHub 并配置 Secrets（约 10 分钟）
1. 登录 https://github.com → New repository → 名字随意（如 `youtube-dashboard`）→ **Private** → Create
2. 把本项目文件上传（网页 Upload files 或 git push）：
   - `fetch_yt_data.py`
   - `requirements.txt`
   - `get_token.py`
   - `.github/workflows/youtube_dashboard.yml`（注意保留 .github/workflows 目录结构）
3. 打开仓库 → **Settings → Secrets and variables → Actions → New repository secret**，添加两个：
   - **GOOGLE_CREDENTIALS_JSON** ← 粘贴 `credentials.json` 的**完整内容**
   - **SPREADSHEET_ID** ← 留空也行；第一次运行后脚本会打印表格 ID，想固定就再补

### 第 4 步：触发第一次采集（约 2 分钟）
1. 仓库页面 → **Actions** 标签 → 左侧选 **YouTube 数据每日采集** → 右侧 **Run workflow** → 点绿色按钮
2. 等待 1-2 分钟，看到 ✅ 绿色对勾 = 成功
3. 到 Google Sheets 查看：脚本自动新建了「YouTube数据看板」表格，内含两张表：
   - **视频快照**：每个视频一行（当天累计播放/点赞/评论 + 视频年龄）
   - **日聚合**：当天频道级新增数据

> 之后每天北京时间 10:00 自动运行，不用你再管。

---

## 二、表结构（历史回溯的核心）

### 表 1：视频快照（video_snapshot）— 每个视频 × 每天一行
| 字段 | 含义 |
|---|---|
| snapshot_date | 采集日期（回溯的关键：查某天 = 筛这个字段） |
| video_id | YouTube 视频 ID |
| title | 标题 |
| publish_date | 发布日期 |
| age_days | 视频年龄（采集日 − 发布日）→ 用于 24h/48h/30d/60d 对齐分析 |
| total_views / total_likes / total_comments | 当天该视频累计值 |

### 表 2：日聚合（daily_stats）— 每天一行
| 字段 | 含义 |
|---|---|
| date | 数据日期（前天） |
| views | 当日新增播放 |
| watch_time_minutes | 当日观看时长（分钟） |
| subs_gained / subs_lost | 当日涨粉 / 掉粉 |
| likes / shares / comments | 当日互动 |
| avg_view_duration_seconds | 当日平均观看时长 |

---

## 三、Looker Studio 看板（第二次再做，约 30 分钟）

1. 打开 https://lookerstudio.google.com/ → **+ 创建 → 数据源**
2. 选择 **Google Sheets** → 授权 → 选择「YouTube数据看板」表格
3. 分别添加两个数据源：「视频快照」和「日聚合」
4. **+ 创建 → 报告**，添加图表：
   - 顶部概览卡：总播放、订阅者趋势（日聚合：views / subs_gained 求和）
   - 折线图：日播放量趋势（日聚合.date → views）
   - 条形图：单视频转粉量 TOP10（需视频级 subs_gained，见下方"深度分析"）
   - 组合图：播放量 vs 订阅增量（日聚合）
   - 表格：视频快照按 snapshot_date 筛选 → 看任意一天各视频情况
5. 加一个日期范围筛选器（控件 → 日期范围），就能"回到任意一天"

---

## 四、深度分析（按需跑，免费）

```python
# 示例：读 Sheets 后做「发布后第 7 天」对齐分析（pandas）
import gspread, pandas as pd
from google.oauth2.credentials import Credentials

creds = Credentials.from_authorized_user_info(json.loads(open("credentials.json").read()))
sh = gspread.authorize(creds).open("YouTube数据看板")
df = pd.DataFrame(sh.worksheet("视频快照").get_all_records())
df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
df["publish_date"] = pd.to_datetime(df["publish_date"])
df["age_days"] = (df["snapshot_date"] - df["publish_date"]).dt.days

# 每个视频发布后第 7 天表现
day7 = df[df["age_days"] == 7].sort_values("total_views", ascending=False)
print(day7[["title", "total_views", "total_likes"]])
```

---

## 五、常见问题

| 问题 | 处理 |
|---|---|
| 运行失败显示 403 / unauthorized | OAuth 同意屏幕没把账号加为 Test user，回第 1 步第 5 条 |
| Analytics 某天没数据 | 正常，48-72h 延迟；当天会自动跳过，数据不会丢，只是晚一天补上 |
| 视频快照重复行 | 脚本有幂等去重（同一天同视频不重复写），重跑安全 |
| 免费额度够吗 | GitHub Actions 2000 分钟/月，每天 3 分钟 ≈ 用 5%；Sheets 500 万单元格，10 年+ 无压力 |
| 想换飞书看板 | 数据在 Sheets 里开放可导出，随时同步一份到飞书多维表格即可 |

---

## 六、后续可升级（不急）

1. **视频级日明细表**：按视频拆分的新增播放/涨粉（Analytics dimensions=video），用于"哪个视频带来多少粉丝"
2. **BigQuery 深度分析**：数据超百万行或要 SQL 任意关联时，把快照灌进 BigQuery（免费层 10GB 存储 + 1TB 查询/月）
3. **多平台扩展**：B站/抖音数据同表结构追加，飞书做多平台看板
