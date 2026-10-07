#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ISO-NE Web Services API 最小连通性测试（只测 /hourlysysload/day/{day} 一天）。

用法:
    python test_iso_ne_api.py [YYYYMMDD]     # 默认 20260101

凭据从项目根 .env 读取 ISO_NE_USERNAME / ISO_NE_PASSWORD，不在脚本中硬编码。
只做探测与分析，不写库、不改模型、不下载全量数据。
"""

import os
import sys
import xml.etree.ElementTree as ET

import requests

ISO_NE_BASE = "https://webservices.iso-ne.com/api/v1.1"


def load_env(root_env_path: str) -> dict:
    """读取项目根 .env（仅取所需键，不回显值）"""
    env = {}
    with open(root_env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def local_tag(tag: str) -> str:
    """去掉 XML namespace 前缀，仅保留本地标签名"""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def main() -> int:
    day = sys.argv[1] if len(sys.argv) > 1 else "20260101"
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(script_dir, "..", "..", ".env")  # backend/scripts -> 项目根
    env = load_env(env_path)

    username = env.get("ISO_NE_USERNAME", "").strip()
    password = env.get("ISO_NE_PASSWORD", "").strip()
    if not username or not password:
        print("❌ 项目根 .env 缺少 ISO_NE_USERNAME / ISO_NE_PASSWORD")
        return 1
    print(f"✅ 已从 .env 读取凭据（用户名: {username[:4]}***，长度 {len(password)}）")

    url = f"{ISO_NE_BASE}/hourlysysload/day/{day}"
    print(f"\nGET {url}")
    try:
        resp = requests.get(url, auth=(username, password), timeout=30)
    except requests.RequestException as exc:
        print(f"❌ 请求异常: {type(exc).__name__}: {exc}")
        return 1

    print(f"\nHTTP 状态码: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('Content-Type')}")
    print(f"响应体大小: {len(resp.content)} bytes")

    # ── 非 200：打印官方返回内容并给出针对性提示 ──
    if resp.status_code != 200:
        print(f"\n⚠️ 请求失败，官方返回内容（前 1200 字符）:\n{resp.text[:1200]}")
        hints = {
            401: "认证失败：Basic Auth 用户名/密码错误，或账户无 Web Services 权限",
            403: "禁止访问：凭据有效但无该端点权限（需在 ISO Express 接受服务条款）",
            404: "端点或日期不存在：检查 URL 与日期格式（YYYYMMDD）",
            429: "请求过于频繁，被限流",
            500: "ISO-NE 服务器错误",
        }
        print(f"提示: {hints.get(resp.status_code, '见官方文档 https://webservices.iso-ne.com/docs/v1.1/')}")
        return 1

    # ── 200：分析返回结构 ──
    print("\n返回内容预览（前 1500 字符）:")
    print(resp.text[:1500])

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        print(f"\n⚠️ 响应不是合法 XML（{exc}）。Content-Type={resp.headers.get('Content-Type')}，"
              f"可能是 JSON 或其他格式，请查看上方原文。")
        return 1

    # 统计树中出现过的标签（去 namespace）及出现次数
    tag_counts: dict = {}
    for elem in root.iter():
        t = local_tag(elem.tag)
        tag_counts[t] = tag_counts.get(t, 0) + 1
    print("\n响应元素标签统计:")
    for t, c in sorted(tag_counts.items()):
        print(f"  <{t}> x {c}")

    # 尝试抽取"记录级"结构：所有含文本的叶子字段
    leaf_fields: dict = {}
    for elem in root.iter():
        if elem.text is not None and elem.text.strip() and not list(elem):
            leaf_fields.setdefault(local_tag(elem.tag), []).append(elem.text.strip())

    print("\n含值字段统计（字段名 → 出现次数 → 前 3 个值）:")
    for field, values in sorted(leaf_fields.items()):
        print(f"  {field}: {len(values)} 条 | 示例 {values[:3]}")

    # 推断记录数：取常见"记录行"计数键
    n = len(leaf_fields)  # placeholder
    print(f"\n记录数量（按叶子值条数估计）: {n if n else '见上方字段统计'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
