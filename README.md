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

## 微信公众号草稿同步

文章加上 `wechat: true` 后会被同步脚本处理。与网站一样，`draft: true` 会跳过。可用 `wechat_cover: /assets/cover.jpg` 覆盖默认封面，`author` 可选。正文配图请用仓库里的 JPG/PNG，路径写成 `/assets/image.jpg`（对应 `static/assets/`）或相对于文章的路径。外链会排成正文脚注，文章原始链接指向站点。

在微信开发者平台打开目标公众号的基础信息，查看 **AppID、AppSecret、API IP 白名单**。把执行脚本的公网出口 IPv4 加进白名单。AppSecret 只在运行机器上输入并保存。

```sh
.venv/bin/python scripts/wechat.py configure
.venv/bin/python scripts/wechat.py check
.venv/bin/python scripts/wechat.py preview station-30 /tmp/station30-wechat.html
.venv/bin/python scripts/wechat.py sync station-30
```

`check` 读取草稿列表，并单独尝试读取发表记录。提交发表的权限需另看账号后台。`sync` 上传微信封面与正文图片，创建或更新草稿。同步状态存在 `~/.config/station30/`，同一账号只在一台机器上运行。若新建草稿时网络中断，脚本会等待你在草稿箱核对结果，避免盲目重复创建。若文章已手动发表或删除，保留其同步记录。对已同步文章的改稿会尝试更新原草稿，微信如果已移除该草稿，脚本会报告微信返回的错误。

### GitHub 推送后的自动同步

在已加入微信白名单的机器上定时运行下列命令。它会从 GitHub 拉取 `main` 到独立目录，再同步所有勾选 `wechat: true` 的文章。主工作区和 Cloudflare 构建互相独立。

```sh
cd /Users/sunlei/Projects/station30
.venv/bin/python scripts/wechat.py poll
```

首次同步确认成功后，在 macOS 运行 `.venv/bin/python scripts/wechat.py schedule`，安装 LaunchAgent，每五分钟执行一次。日志在 `~/.config/station30/sync.log`。需要停用时运行 `launchctl bootout gui/$(id -u)/com.station30.wechat-drafts`。机器需保持联网，公网出口 IP 变更后需更新白名单。同步脚本只使用微信草稿接口写入，正式发表在微信后台完成。

[微信新增草稿接口](https://developers.weixin.qq.com/doc/service/api/draftbox/draftmanage/api_draft_add) · [微信提交发布接口](https://developers.weixin.qq.com/doc/service/api/public/api_freepublish_submit)
