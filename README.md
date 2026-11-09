# 三十号地面站 · STATION 30

记录 AI 着陆之后的事。

- `posts/` 是文章源文件。文件名就是 URL 的 slug。
- `templates/` 放首页、文章页和日志列表模板。
- `static/assets/` 放样式、插图及后续文章配图。
- `scripts/build.py` 从 Markdown 生成 `dist/` 静态站点。

## 写文章

在 `posts/` 添加一个 Markdown 文件，开头写上标题、发布日期、摘要和分类。设 `draft: true` 可在构建时跳过该篇。

```yaml
---
title: 一篇新文章
date: 2026-11-09
summary: 用一句话介绍文章。
category: AI 应用
---
```

仓库的 Markdown 是内容源文件，网址由文件名决定。正式发布后建议保留原文件名。

## 本地预览

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/build.py
.venv/bin/python -m http.server 8030 --directory dist
```

打开 [http://localhost:8030](http://localhost:8030)。

## Cloudflare Pages

在 Workers & Pages 新建 **Pages** 项目，连接 `sungitly/station30`。

| 设置 | 值 |
| --- | --- |
| Production branch | `main` |
| Framework preset | None |
| Root directory | 仓库根目录 |
| Build command | `python3 -m pip install -r requirements.txt && python3 scripts/build.py` |
| Build output directory | `dist` |

先验证 Pages 分配的网址，再在项目的 **Custom domains** 添加 `station30.fdeweekly.com`。如果 `fdeweekly.com` 的 DNS 在同一 Cloudflare 账户，Cloudflare 可在确认后创建记录。如果 DNS 由其他服务管理，按 Pages 提示添加 CNAME。

生产站的 canonical URL 默认是 `https://station30.fdeweekly.com`，可通过构建环境变量 `SITE_URL` 覆盖。

[Cloudflare Pages 自定义域名](https://developers.cloudflare.com/pages/configuration/custom-domains/)
