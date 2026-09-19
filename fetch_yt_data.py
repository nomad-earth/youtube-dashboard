#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YouTube 数据看板 · 每日全量采集脚本
=====================================
每天自动运行一次，采集 YouTube Analytics API 能提供的所有维度和指标。

工作表列表：
  1. 视频快照       — Data API：每个视频当天累计值
  2. 日聚合         — Analytics API：频道级每日汇总（按天）
  3. 视频明细       — Analytics API：按视频聚合（指定日期范围）
  4. 国家明细       — Analytics API：按国家
  5. 流量来源明细    — Analytics API：按流量来源类型
  6. 设备明细       — Analytics API：按设备类型
  7. 人口统计明细    — Analytics API：按年龄+性别
  8. 播放位置明细    — Analytics API：按播放位置类型
  9. 订阅状态明细    — Analytics API：按订阅者/非订阅者
 10. 卡片明细       — Analytics API：卡片展示/点击（按天）
 11. 播放列表明细   — Analytics API：添加/移除播放列表（按天）

注意：Analytics API 不支持 day 和其他维度组合，
所以非"按天"的维度用 startDate~endDate 范围拉取，每天覆盖写入。
"""

import json
import os
import sys
from datetime import date, timedelta

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# ---------- 配置 ----------
SHEET_SNAPSHOT = "视频快照"
SHEET_DAILY = "日聚合"
SHEET_VIDEO = "视频明细"
SHEET_COUNTRY = "国家明细"
SHEET_TRAFFIC = "流量来源明细"
SHEET_DEVICE = "设备明细"
SHEET_DEMO = "人口统计明细"
SHEET_PLAYBACK = "播放位置明细"
SHEET_SUB = "订阅状态明细"
SHEET_CARD = "卡片明细"
SHEET_PLAYLIST = "播放列表明细"

CORE_METRICS = (
    "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
    "engagedViews,likes,dislikes,comments,shares,"
    "subscribersGained,subscribersLost"
)
CARD_METRICS = (
    "cardImpressions,cardClicks,cardClickRate,"
    "cardTeaserImpressions,cardTeaserClicks,cardTeaserClickRate"
)
PLAYLIST_METRICS = "videosAddedToPlaylists,videosRemovedFromPlaylists"


def get_credentials(env_var, label):
    creds_json = os.environ.get(env_var)
    if not creds_json:
        print(f"❌ 缺少环境变量 {env_var}（{label}）")
        sys.exit(1)
    return Credentials.from_authorized_user_info(json.loads(creds_json))


def fetch_all_video_stats(youtube, channel_id):
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
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = youtube.videos().list(part="snippet,statistics", id=",".join(batch)).execute()
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


def analytics_query(analytics, channel_id, start_date, end_date, dimensions, metrics, sort=None):
    params = {
        "ids": f"channel=={channel_id}",
        "startDate": start_date,
        "endDate": end_date,
        "metrics": metrics,
        "dimensions": dimensions,
        "maxResults": 200,
    }
    if sort:
        params["sort"] = sort
    try:
        resp = analytics.reports().query(**params).execute()
        return resp.get("rows", [])
    except Exception as e:
        print(f"⚠️ 查询失败 (dim={dimensions}): {str(e)[:120]}")
        return []


def get_sheet(gc):
    sheet_id = os.environ.get("SPREADSHEET_ID", "").strip()
    if not sheet_id:
        print("❌ 缺少 SPREADSHEET_ID")
        sys.exit(1)
    return gc.open_by_key(sheet_id)


def ensure_sheet(sh, name, header):
    try:
        ws = sh.worksheet(name)
    except Exception:
        ws = sh.add_worksheet(title=name, rows=5000, cols=len(header))
        ws.append_row(header)
    return ws


def batch_append_new(ws, key_cols_idx, rows):
    existing = ws.get_all_values()
    existing_keys = set()
    for row in existing[1:]:
        if len(row) >= max(key_cols_idx) + 1:
            existing_keys.add(tuple(row[i] for i in key_cols_idx))
    new_rows = []
    for r in rows:
        key = tuple(r[i] for i in key_cols_idx)
        if key not in existing_keys:
            new_rows.append(r)
            existing_keys.add(key)
    if new_rows:
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
    return len(new_rows)


def overwrite_sheet(ws, header, data):
    ws.clear()
    ws.append_row(header)
    if data:
        ws.append_rows(data, value_input_option="USER_ENTERED")
    return len(data)


def main():
    sheets_creds = get_credentials("GOOGLE_CREDENTIALS_JSON", "Sheets写入")
    analytics_creds = get_credentials("ANALYTICS_CREDENTIALS_JSON", "Analytics读取")
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    channel_id = os.environ.get("CHANNEL_ID", "").strip()
    if not api_key or not channel_id:
        print("❌ 缺少环境变量 YOUTUBE_API_KEY 或 CHANNEL_ID")
        sys.exit(1)

    youtube = build("youtube", "v3", developerKey=api_key)
    analytics = build("youtubeAnalytics", "v2", credentials=analytics_creds)
    import gspread
    gc = gspread.authorize(sheets_creds)

    today = date.today()
    start_date = (today - timedelta(days=8)).isoformat()
    end_date = (today - timedelta(days=2)).isoformat()
    period = f"{start_date}~{end_date}"
    print(f"📅 采集范围 {period}")

    sh = get_sheet(gc)

    # === 1. 视频快照（Data API）===
    video_stats = fetch_all_video_stats(youtube, channel_id)
    ws_snap = ensure_sheet(sh, SHEET_SNAPSHOT,
        ["snapshot_date", "video_id", "title", "publish_date",
         "age_days", "total_views", "total_likes", "total_comments"])
    snap_rows = []
    end_day = date.fromisoformat(end_date)
    for v in video_stats:
        age = (end_day - date.fromisoformat(v["publish_date"])).days
        snap_rows.append([end_date, v["video_id"], v["title"], v["publish_date"],
                          age, v["views"], v["likes"], v["comments"]])
    added = batch_append_new(ws_snap, [0, 1], snap_rows)
    print(f"✅ 视频快照：新增 {added} 行")

    # === 2. 日聚合（按天）===
    rows = analytics_query(analytics, channel_id, start_date, end_date, "day", CORE_METRICS)
    if rows:
        ws = ensure_sheet(sh, SHEET_DAILY,
            ["date", "views", "estimatedMinutesWatched", "averageViewDuration",
             "averageViewPercentage", "engagedViews", "likes", "dislikes",
             "comments", "shares", "subscribersGained", "subscribersLost"])
        data = [[r[0]] + [float(x) if isinstance(x, float) else int(x) for x in r[1:]] for r in rows]
        added = batch_append_new(ws, [0], data)
        print(f"✅ 日聚合：新增 {added} 行")

    # === 3. 视频明细（按视频，日期范围聚合）===
    rows = analytics_query(analytics, channel_id, start_date, end_date, "video", CORE_METRICS, sort="-views")
    if rows:
        ws = ensure_sheet(sh, SHEET_VIDEO,
            ["period", "video_id", "views", "estimatedMinutesWatched",
             "averageViewDuration", "averageViewPercentage", "engagedViews",
             "likes", "dislikes", "comments", "shares",
             "subscribersGained", "subscribersLost"])
        data = [[period] + [str(x) for x in r] for r in rows]
        n = overwrite_sheet(ws,
            ["period", "video_id", "views", "estimatedMinutesWatched",
             "averageViewDuration", "averageViewPercentage", "engagedViews",
             "likes", "dislikes", "comments", "shares",
             "subscribersGained", "subscribersLost"], data)
        print(f"✅ 视频明细：{n} 行（{period}）")

    # === 4. 国家明细 ===
    rows = analytics_query(analytics, channel_id, start_date, end_date, "country",
                           "views,estimatedMinutesWatched,subscribersGained", sort="-views")
    if rows:
        ws = ensure_sheet(sh, SHEET_COUNTRY,
            ["period", "country", "views", "estimatedMinutesWatched", "subscribersGained"])
        data = [[period] + [str(x) for x in r] for r in rows]
        n = overwrite_sheet(ws,
            ["period", "country", "views", "estimatedMinutesWatched", "subscribersGained"], data)
        print(f"✅ 国家明细：{n} 行")

    # === 5. 流量来源明细 ===
    rows = analytics_query(analytics, channel_id, start_date, end_date, "insightTrafficSourceType",
                           "views,estimatedMinutesWatched", sort="-views")
    if rows:
        ws = ensure_sheet(sh, SHEET_TRAFFIC,
            ["period", "traffic_source", "views", "estimatedMinutesWatched", "subscribersGained"])
        data = [[period] + [str(x) for x in r] for r in rows]
        n = overwrite_sheet(ws,
            ["period", "traffic_source", "views", "estimatedMinutesWatched", "subscribersGained"], data)
        print(f"✅ 流量来源明细：{n} 行")

    # === 6. 设备明细 ===
    rows = analytics_query(analytics, channel_id, start_date, end_date, "deviceType",
                           "views,estimatedMinutesWatched,averageViewDuration", sort="-views")
    if rows:
        ws = ensure_sheet(sh, SHEET_DEVICE,
            ["period", "device_type", "views", "estimatedMinutesWatched", "averageViewDuration"])
        data = [[period] + [str(x) for x in r] for r in rows]
        n = overwrite_sheet(ws,
            ["period", "device_type", "views", "estimatedMinutesWatched", "averageViewDuration"], data)
        print(f"✅ 设备明细：{n} 行")

    # === 7. 人口统计明细 ===
    # 注意：ageGroup/gender 维度对小频道/新频道可能返回 400（隐私阈值），
    # YouTube 要求每个分组至少有一定量级数据才返回，不够就静默跳过。
    rows = analytics_query(analytics, channel_id, start_date, end_date, "ageGroup,gender",
                           "views,estimatedMinutesWatched", sort="-views")
    if rows:
        ws = ensure_sheet(sh, SHEET_DEMO,
            ["period", "age_group", "gender", "views", "estimatedMinutesWatched"])
        data = [[period] + [str(x) for x in r] for r in rows]
        n = overwrite_sheet(ws,
            ["period", "age_group", "gender", "views", "estimatedMinutesWatched"], data)
        print(f"✅ 人口统计明细：{n} 行")

    # === 8. 播放位置明细 ===
    rows = analytics_query(analytics, channel_id, start_date, end_date, "insightPlaybackLocationType",
                           "views,estimatedMinutesWatched", sort="-views")
    if rows:
        ws = ensure_sheet(sh, SHEET_PLAYBACK,
            ["period", "playback_location", "views", "estimatedMinutesWatched"])
        data = [[period] + [str(x) for x in r] for r in rows]
        n = overwrite_sheet(ws,
            ["period", "playback_location", "views", "estimatedMinutesWatched"], data)
        print(f"✅ 播放位置明细：{n} 行")

    # === 9. 订阅状态明细 ===
    rows = analytics_query(analytics, channel_id, start_date, end_date, "subscribedStatus",
                           "views,estimatedMinutesWatched", sort="-views")
    if rows:
        ws = ensure_sheet(sh, SHEET_SUB,
            ["period", "subscribed_status", "views", "estimatedMinutesWatched", "subscribersGained"])
        data = [[period] + [str(x) for x in r] for r in rows]
        n = overwrite_sheet(ws,
            ["period", "subscribed_status", "views", "estimatedMinutesWatched"], data)
        print(f"✅ 订阅状态明细：{n} 行")

    # === 10. 卡片明细（按天）===
    rows = analytics_query(analytics, channel_id, start_date, end_date, "day", CARD_METRICS)
    if rows:
        ws = ensure_sheet(sh, SHEET_CARD,
            ["date", "cardImpressions", "cardClicks", "cardClickRate",
             "cardTeaserImpressions", "cardTeaserClicks", "cardTeaserClickRate"])
        data = [[r[0]] + [float(x) if isinstance(x, float) else int(x) for x in r[1:]] for r in rows]
        added = batch_append_new(ws, [0], data)
        print(f"✅ 卡片明细：新增 {added} 行")

    # === 11. 播放列表明细（按天）===
    rows = analytics_query(analytics, channel_id, start_date, end_date, "day", PLAYLIST_METRICS)
    if rows:
        ws = ensure_sheet(sh, SHEET_PLAYLIST,
            ["date", "videosAddedToPlaylists", "videosRemovedFromPlaylists"])
        data = [[r[0]] + [int(x) for x in r[1:]] for r in rows]
        added = batch_append_new(ws, [0], data)
        print(f"✅ 播放列表明细：新增 {added} 行")

    print("🎉 全量采集完成")


if __name__ == "__main__":
    main()
