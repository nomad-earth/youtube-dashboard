#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YouTube 数据看板 · 每日采集脚本
================================
在 GitHub Actions 里每天自动运行一次（也可以手动运行），完成：
  1. Data API：拉取频道全部视频的【当天累计值】→ 写入「视频快照表」
     （每个视频每天一行：snapshot_date + video_id + 当天播放/点赞/评论）
  2. Analytics API：拉取【前天】频道级日明细 → 写入「日聚合表」
     （每天一行：新增播放/观看时长/涨粉/点赞/分享/评论）

历史回溯原理：每天追加一行，不覆盖旧行 → 以后查任意一天 = 筛选 snapshot_date
数据延迟说明：Analytics 有 48-72 小时延迟，所以这里拉的是【前天】(T-2) 的数据。

运行环境变量（GitHub Secrets）：
  GOOGLE_CREDENTIALS_JSON : get_token.py 生成的 credentials.json 完整内容（用于 Analytics + Sheets）
  YOUTUBE_API_KEY         : Google Cloud 创建的 API Key（用于拉视频列表，公开数据无需 OAuth）
  CHANNEL_ID              : 你的 YouTube 频道 ID（UC 开头）
  SPREADSHEET_ID          : （必填）手动创建的 Google 表格 ID（打开 sheets.new 新建，取 URL 中 /d/ 与 /edit 之间的一串）
"""

import json
import os
import sys
from datetime import date, timedelta

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# ---------- 配置 ----------
SHEET_TITLE = "YouTube数据看板"
SHEET_SNAPSHOT = "视频快照"
SHEET_DAILY = "日聚合"

# ---------- 1. 读取凭证 ----------
def get_credentials():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        print("❌ 缺少环境变量 GOOGLE_CREDENTIALS_JSON（get_token.py 生成的 credentials.json 内容）")
        sys.exit(1)
    return Credentials.from_authorized_user_info(json.loads(creds_json))

# ---------- 2. Data API：拉全部视频当天累计值（公开数据，用 API Key，无需 OAuth） ----------
def fetch_all_video_stats(youtube, channel_id):
    """返回 [{video_id, title, publish_date, views, likes, comments}]"""
    # 找到「上传」播放列表
    ch = youtube.channels().list(part="contentDetails", id=channel_id).execute()
    uploads_id = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    video_ids = []
    page_token = None
    while True:
        resp = youtube.playlistItems().list(
            part="contentDetails", playlistId=uploads_id,
            maxResults=50, pageToken=page_token or ""
        ).execute()
        video_ids += [it["contentDetails"]["videoId"] for it in resp.get("items", [])]
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    stats = []
    # 每 50 个一批批量查询（Data API 单次最多 50 个 id）
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = youtube.videos().list(
            part="snippet,statistics", id=",".join(batch)
        ).execute()
        for item in resp.get("items", []):
            st = item.get("statistics", {})
            stats.append({
                "video_id": item["id"],
                "title": item["snippet"]["title"],
                "publish_date": item["snippet"]["publishedAt"][:10],
                "views": int(st.get("viewCount", 0)),
                "likes": int(st.get("likeCount", 0)),
                "comments": int(st.get("commentCount", 0)),
            })
    print(f"✅ Data API：共 {len(stats)} 个视频")
    return stats

# ---------- 3. Analytics API：拉前天频道级日明细 ----------
def fetch_daily_stats(analytics, target_day: str, channel_id: str):
    """返回前天一天的频道级指标 dict"""
    resp = analytics.reports().query(
        ids=f"channel=={channel_id}",
        startDate=target_day,
        endDate=target_day,
        metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost,"
                "likes,shares,comments,averageViewDuration",
        dimensions="day",
    ).execute()
    rows = resp.get("rows", [])
    if not rows:
        print(f"⚠️ {target_day} 无 Analytics 数据（可能还在延迟中，明天会补拉）")
        return None
    # rows[0] = [date, views, minutes, subsG, subsL, likes, shares, comments, avgDur]
    r = rows[0]
    return {
        "date": r[0],
        "views": int(r[1]),
        "watch_time_minutes": int(r[2]),
        "subs_gained": int(r[3]),
        "subs_lost": int(r[4]),
        "likes": int(r[5]),
        "shares": int(r[6]),
        "comments": int(r[7]),
        "avg_view_duration_seconds": float(r[8]),
    }

# ---------- 4. 写 Google Sheets ----------
def get_sheet(gc):
    sheet_id = os.environ.get("SPREADSHEET_ID", "").strip()
    if not sheet_id:
        print("❌ 缺少 SPREADSHEET_ID：请先手动创建 Google 表格（打开 sheets.new 新建），")
        print("   然后把表格 URL 里 /d/ 和 /edit 之间的一串 ID 设为 GitHub Secret：SPREADSHEET_ID")
        sys.exit(1)
    return gc.open_by_key(sheet_id)


def ensure_sheet(sh, name, header):
    try:
        ws = sh.worksheet(name)
    except Exception:
        ws = sh.add_worksheet(title=name, rows=1000, cols=len(header))
        ws.append_row(header)
    return ws


def append_if_new(ws, key_cols_idx, new_row, key_values):
    """幂等追加：同一 (date, video_id) 已存在则跳过，避免重复行"""
    existing = ws.get_all_values()
    existing_keys = set()
    for row in existing[1:]:  # 跳过表头
        if len(row) >= max(key_cols_idx) + 1:
            existing_keys.add(tuple(row[i] for i in key_cols_idx))
    if tuple(key_values) in existing_keys:
        print(f"⏭️ 已存在，跳过：{key_values}")
        return False
    ws.append_row(new_row)
    return True


def main():
    creds = get_credentials()
    # Data API 用 API Key（公开数据，不需要 OAuth，也规避 scope 冲突）
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    channel_id = os.environ.get("CHANNEL_ID", "").strip()
    if not api_key or not channel_id:
        print("❌ 缺少环境变量 YOUTUBE_API_KEY 或 CHANNEL_ID")
        sys.exit(1)
    youtube = build("youtube", "v3", developerKey=api_key)
    analytics = build("youtubeAnalytics", "v2", credentials=creds)
    import gspread
    gc = gspread.authorize(creds)

    today = date.today()
    target_day = today - timedelta(days=2)  # 前天（T-2，规避 48-72h 延迟）
    target_str = target_day.isoformat()
    print(f"📅 运行日期 {today.isoformat()}，采集目标 {target_str}")

    # 视频快照（每天全量）
    video_stats = fetch_all_video_stats(youtube, channel_id)
    sh = get_sheet(gc)
    ws_snap = ensure_sheet(sh, SHEET_SNAPSHOT,
        ["snapshot_date", "video_id", "title", "publish_date",
         "age_days", "total_views", "total_likes", "total_comments"])

    added = 0
    for v in video_stats:
        age = (target_day - date.fromisoformat(v["publish_date"])).days
        row = [target_str, v["video_id"], v["title"], v["publish_date"],
               age, v["views"], v["likes"], v["comments"]]
        if append_if_new(ws_snap, [0, 1], row, [target_str, v["video_id"]]):
            added += 1
    print(f"✅ 视频快照：新增 {added} 行（共 {len(video_stats)} 个视频）")

    # 日聚合（前天）
    daily = fetch_daily_stats(analytics, target_str, channel_id)
    if daily:
        ws_daily = ensure_sheet(sh, SHEET_DAILY,
            ["date", "views", "watch_time_minutes", "subs_gained", "subs_lost",
             "likes", "shares", "comments", "avg_view_duration_seconds"])
        row = [daily["date"], daily["views"], daily["watch_time_minutes"],
               daily["subs_gained"], daily["subs_lost"], daily["likes"],
               daily["shares"], daily["comments"], daily["avg_view_duration_seconds"]]
        if append_if_new(ws_daily, [0], row, [daily["date"]]):
            print(f"✅ 日聚合：已写入 {daily['date']} 的数据")
        else:
            print(f"⏭️ 日聚合 {daily['date']} 已存在，跳过")

    print("🎉 本次采集完成")


if __name__ == "__main__":
    main()
