#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性授权脚本：在你的电脑上运行一次，生成 credentials.json
用法（在能访问 Google 的环境里）：
    pip install -r requirements.txt
    python get_token.py

运行后会：
  1. 读取你从 Google Cloud 下载的 client_secret.json（放在本脚本同目录）
  2. 打开浏览器让你登录 Google 并点击「允许」
  3. 生成 credentials.json（包含长期有效的 refresh_token）

然后把这个 credentials.json 的【完整内容】粘贴到 GitHub 仓库的
Settings → Secrets and variables → Actions → New repository secret
变量名填：GOOGLE_CREDENTIALS_JSON
"""

import json
import os
import sys

SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

CLIENT_SECRET_FILE = "client_secret.json"
OUTPUT_FILE = "credentials.json"


def main():
    if not os.path.exists(CLIENT_SECRET_FILE):
        print(f"❌ 找不到 {CLIENT_SECRET_FILE}，请先把从 Google Cloud 下载的 OAuth 客户端 JSON 放到本目录")
        print("   下载位置：Google Cloud Console → APIs & Services → Credentials → 你的 OAuth 客户端 → 下载 JSON")
        sys.exit(1)

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")

    # 强制输出 refresh_token（首次授权一定有）
    if not creds.refresh_token:
        print("⚠️ 没有拿到 refresh_token：请删除 client_secret.json 对应的授权记录后重试，"
              "或确认 OAuth 同意屏幕中你已把账号加为测试用户")
        sys.exit(1)

    with open(OUTPUT_FILE, "w") as f:
        f.write(creds.to_json())

    print(f"✅ 已生成 {OUTPUT_FILE}")
    print("\n下一步：打开这个文件复制【完整内容】，去 GitHub 仓库：")
    print("Settings → Secrets and variables → Actions → New repository secret")
    print("Name: GOOGLE_CREDENTIALS_JSON")
    print("Secret: <粘贴完整 JSON 内容>")


if __name__ == "__main__":
    main()
