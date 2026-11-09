"""Sync Station 30 articles to WeChat's official draft API."""
import argparse
from contextlib import contextmanager
import fcntl
from getpass import getpass
from hashlib import sha256
from html import escape
import json
import os
import plistlib
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from build import MARKDOWN, ROOT, SITE_URL, read_post


STATE = Path.home() / ".config" / "station30"
REPO = "https://github.com/sungitly/station30.git"
DEFAULT_COVER = "/assets/wechat-cover.jpg"
STYLES = {
    "p": "margin:0 0 17px;line-height:1.85",
    "h1": "font-size:22px;line-height:1.45;color:#254b35;margin:28px 0 13px",
    "h2": "font-size:21px;line-height:1.45;color:#254b35;margin:26px 0 12px",
    "h3": "font-size:18px;color:#254b35;margin:22px 0 10px",
    "blockquote": "margin:20px 0;padding:12px 16px;border-left:3px solid #63845d;background:#eef2e9;color:#314735",
    "strong": "font-weight:700;color:#254b35",
    "ul": "margin:0 0 17px;padding-left:25px",
    "ol": "margin:0 0 17px;padding-left:25px",
    "li": "margin:5px 0",
    "code": "font-family:monospace;font-size:14px;overflow-wrap:anywhere",
    "pre": "margin:18px 0;padding:12px;background:#eef2e9;white-space:pre-wrap",
    "table": "width:100%;border-collapse:collapse;margin:18px 0",
    "th": "border:1px solid #b8c9b3;padding:6px;background:#eef2e9;text-align:left",
    "td": "border:1px solid #b8c9b3;padding:6px",
    "img": "display:block;max-width:100%;height:auto;margin:14px auto",
    "hr": "border:0;border-top:1px solid #b8c9b3;margin:24px 0",
}


class WeChatError(Exception):
    def __init__(self, endpoint, code, message=""):
        self.code = code
        suffix = {
            40164: "。请把当前执行机器的公网出口 IP 加入 API IP 白名单",
            40013: "。请确认 AppID 属于目标公众号",
            40125: "。请核对该公众号的 AppSecret",
            48001: "。该账号未授权这个接口",
        }.get(code, "")
        super().__init__(f"{endpoint}: 微信错误 {code}{suffix}" + (f" ({message})" if message else ""))


class WeChat:
    def __init__(self, app_id, app_secret):
        self.token = ""
        response = self.post(
            "stable_token",
            {"grant_type": "client_credential", "appid": app_id,
             "secret": app_secret, "force_refresh": False},
        )
        self.token = response["access_token"]

    def post(self, endpoint, payload=None, media=None):
        url = f"https://api.weixin.qq.com/cgi-bin/{endpoint}"
        if self.token:
            url += "?" + urlencode({"access_token": self.token})
        if media:
            boundary = uuid4().hex
            mime = "image/png" if media.suffix.lower() == ".png" else "image/jpeg"
            body = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="media"; filename="image{media.suffix.lower()}"\r\n'
                f"Content-Type: {mime}\r\n\r\n"
            ).encode() + media.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
            content_type = f"multipart/form-data; boundary={boundary}"
            if endpoint == "material/add_material":
                url += "&type=image"
        else:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            content_type = "application/json; charset=utf-8"
        request = Request(url, data=body, headers={"Content-Type": content_type})
        try:
            with urlopen(request, timeout=25) as response:
                result = json.load(response)
        except HTTPError as error:
            raise RuntimeError(f"{endpoint}: HTTP {error.code}") from None
        except (URLError, TimeoutError, ValueError):
            raise RuntimeError(f"{endpoint}: 请求超时、网络错误或响应无法解析") from None
        if result.get("errcode", 0) != 0:
            message = ""
            if result["errcode"] == 40164:
                match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", result.get("errmsg", ""))
                if match:
                    message = f"微信看到的出口 IP 为 {match.group()}"
            raise WeChatError(endpoint, result["errcode"], message)
        return result


def save_json(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temp:
        try:
            json.dump(data, temp, ensure_ascii=False, indent=2)
            temp.flush()
            os.fsync(temp.fileno())
            os.replace(temp.name, path)
        finally:
            Path(temp.name).unlink(missing_ok=True)


def load_json(path, default=None):
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    if default is not None:
        return default
    raise ValueError("尚未配置公众号。先运行 scripts/wechat.py configure。")


def configure():
    if not sys.stdin.isatty():
        raise ValueError("请在自己的终端中交互式输入凭据。")
    app_id = input("微信公众号 AppID: ").strip()
    app_secret = getpass("AppSecret（输入不会显示）: ").strip()
    if not re.fullmatch(r"wx[0-9a-fA-F]{16}", app_id) or not app_secret:
        raise ValueError("AppID 格式不正确或 AppSecret 为空")
    save_json(STATE / "wechat.json", {"app_id": app_id, "app_secret": app_secret})
    print("凭据已保存到 ~/.config/station30/wechat.json（权限 0600）。")


@contextmanager
def locked_state():
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / "sync.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("已有一个同步任务在运行") from None
        yield


def image_path(root, post, reference, *, cover=False):
    url = urlsplit(reference)
    if url.scheme or url.netloc or url.query or url.fragment:
        raise ValueError(f"{post.name}: 请把微信配图保存到仓库内: {reference}")
    name = unquote(url.path)
    path = (root / "static" / name.lstrip("/") if name.startswith("/assets/") else post.parent / name).resolve()
    valid_root = root / ("static/assets" if name.startswith("/assets/") else "posts")
    if not path.is_relative_to(valid_root.resolve()):
        raise ValueError(f"{post.name}: 图片须在 posts/ 或 static/assets/ 内")
    limit = (2 if cover else 1) * 1024 * 1024
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg"} or not path.is_file():
        raise ValueError(f"{post.name}: 微信图片须是仓库内的 JPG 或 PNG: {reference}")
    if path.stat().st_size >= limit:
        raise ValueError(f"{post.name}: {reference} 须小于 {limit // (1024 * 1024)} MB")
    return path


def render(body, post, root, image_url):
    tokens = MARKDOWN.parse(body)
    links = {}

    def format_tokens(items):
        for token in items:
            if token.children:
                format_tokens(token.children)
            if token.type == "link_open":
                href = token.attrGet("href") or ""
                if not href.startswith("https://mp.weixin.qq.com/"):
                    links.setdefault(href, len(links) + 1)
                    token.meta["reference"] = links[href]
                    token.tag = "span"
            if token.type == "image":
                token.attrSet("src", image_url(image_path(root, post, token.attrGet("src"))))
            if token.nesting >= 0 and token.tag in STYLES:
                token.attrSet("style", STYLES[token.tag])
            if token.type == "blockquote_open":
                token.tag = "section"
            if token.type == "blockquote_close":
                token.tag = "section"
        # Link tokens are paired within a single inline token list.
        reference = None
        for token in items:
            if token.type == "link_open":
                reference = token.meta.get("reference")
                if reference:
                    token.attrs.pop("href", None)
            if token.type == "link_close" and reference:
                token.tag = "span"
                token.meta["reference"] = reference
                reference = None

    def close_link(items, idx, options, env):
        token = items[idx]
        if ref := token.meta.get("reference"):
            return f'</span><sup style="color:#436744">[{ref}]</sup>'
        return "</a>"

    def fenced_code(items, idx, options, env):
        return f'<pre style="{STYLES["pre"]}"><code style="{STYLES["code"]}">{escape(items[idx].content)}</code></pre>'

    format_tokens(tokens)
    # The website renderer remains untouched.
    renderer = type(MARKDOWN.renderer)(MARKDOWN)
    renderer.rules["link_close"] = close_link
    renderer.rules["fence"] = fenced_code
    renderer.rules["code_block"] = fenced_code
    result = renderer.render(tokens, MARKDOWN.options, {})
    if links:
        result += '<p style="margin:26px 0 7px;color:#254b35;font-weight:700">参考链接</p>'
        for href, index in links.items():
            result += f'<p style="margin:0 0 8px;font-size:13px;overflow-wrap:anywhere">[{index}] {escape(href)}</p>'
    return f'<section style="font-size:16px;line-height:1.85;letter-spacing:.025em;color:#252d27">{result}</section>'


def article(root, post, fields, body, image_url):
    for key in ("title", "summary"):
        if not isinstance(fields.get(key), str) or not fields[key].strip():
            raise ValueError(f"{post.name}: 缺少 {key}")
    return {
        "article_type": "news",
        "title": fields["title"],
        "digest": fields["summary"],
        "author": fields.get("author", ""),
        "content": render(body, post, root, image_url),
        "content_source_url": f"{SITE_URL}/posts/{post.stem}/",
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }


def check_permissions(client):
    client.post("draft/batchget", {"offset": 0, "count": 1, "no_content": 1})
    print("稳定版 access_token 与草稿列表接口均可用。")
    try:
        client.post("freepublish/batchget", {"offset": 0, "count": 1, "no_content": 1})
    except WeChatError as error:
        print(f"发表记录读取：{error}。请同时在微信后台核对提交发布接口权限。")
    else:
        print("发表记录读取可用。提交发布的权限需要单独在微信后台核对。")


def sync(root, slug=None):
    config = load_json(STATE / "wechat.json")
    state_path = STATE / f'drafts-{config["app_id"]}.json'
    state = load_json(state_path, {"drafts": {}, "covers": {}, "images": {}})
    client = None
    for post in sorted((root / "posts").glob("*.md")):
        if slug and post.stem != slug:
            continue
        _, fields, body = read_post(post)
        if fields.get("draft") is True or fields.get("wechat") is not True:
            continue
        cover = image_path(root, post, fields.get("wechat_cover", DEFAULT_COVER), cover=True)
        cover_hash = sha256(cover.read_bytes()).hexdigest()
        hash_image = lambda path: sha256(path.read_bytes()).hexdigest()
        payload = article(root, post, fields, body, hash_image)
        digest = sha256(json.dumps([payload, cover_hash], sort_keys=True).encode()).hexdigest()
        previous = state["drafts"].get(post.stem, {})
        if previous.get("pending"):
            print(f"{post.stem}: 上次新建结果未确认，请先检查草稿箱和本地同步状态。", file=sys.stderr)
            continue
        if previous.get("digest") == digest:
            continue
        client = client or WeChat(**config)

        def upload_image(path):
            key = hash_image(path)
            if key not in state["images"]:
                state["images"][key] = client.post("media/uploadimg", media=path)["url"]
                save_json(state_path, state)
            return state["images"][key]

        payload = article(root, post, fields, body, upload_image)
        if cover_hash not in state["covers"]:
            state["covers"][cover_hash] = client.post("material/add_material", media=cover)["media_id"]
            save_json(state_path, state)
        payload["thumb_media_id"] = state["covers"][cover_hash]
        media_id = previous.get("media_id")
        if media_id:
            client.post("draft/update", {"media_id": media_id, "index": 0, "articles": payload})
            action = "更新"
        else:
            # An interrupted request can have succeeded. Hold creation until reviewed.
            state["drafts"][post.stem] = {"pending": True}
            save_json(state_path, state)
            try:
                media_id = client.post("draft/add", {"articles": [payload]})["media_id"]
            except WeChatError:
                del state["drafts"][post.stem]
                save_json(state_path, state)
                raise
            action = "新建"
        state["drafts"][post.stem] = {"media_id": media_id, "digest": digest}
        save_json(state_path, state)
        print(f"{post.stem}: 微信草稿已{action}。", flush=True)


def git_sync():
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    checkout = STATE / "source"
    if not (checkout / ".git").is_dir():
        subprocess.run(["git", "clone", "--branch", "main", "--single-branch", REPO, str(checkout)], check=True)
    else:
        subprocess.run(["git", "-C", str(checkout), "pull", "--ff-only", REPO, "main"], check=True)
    sync(checkout)


def schedule():
    if sys.platform != "darwin":
        raise ValueError("schedule 仅支持 macOS。其他系统请定时调用 poll。")
    load_json(STATE / "wechat.json")
    label = "com.station30.wechat-drafts"
    path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps({
        "Label": label,
        "ProgramArguments": [sys.executable, str(Path(__file__).resolve()), "poll"],
        "StartInterval": 300,
        "RunAtLoad": True,
        "StandardOutPath": str(STATE / "sync.log"),
        "StandardErrorPath": str(STATE / "sync.log"),
    }))
    domain = f"gui/{os.getuid()}"
    loaded = subprocess.run(
        ["launchctl", "print", f"{domain}/{label}"], capture_output=True,
    ).returncode == 0
    if loaded:
        subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], check=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
    print("已启用每五分钟检查 GitHub 的同步任务。日志：~/.config/station30/sync.log")


def preview(slug, target):
    post = ROOT / "posts" / f"{slug}.md"
    _, fields, body = read_post(post)
    cover = image_path(ROOT, post, fields.get("wechat_cover", DEFAULT_COVER), cover=True)
    payload = article(ROOT, post, fields, body, lambda path: path.as_uri())
    target.write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<body style="max-width:630px;margin:24px auto;padding:0 18px;font-family:system-ui">'
        f'<h1 style="font-size:24px">{escape(payload["title"])}</h1>'
        f'<img src="{cover.as_uri()}" style="width:100%;height:auto" alt="">'
        + payload["content"] + "</body></html>", encoding="utf-8"
    )
    print(target.resolve())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    modes.add_parser("configure")
    modes.add_parser("check")
    modes.add_parser("poll")
    modes.add_parser("schedule")
    sync_cmd = modes.add_parser("sync")
    sync_cmd.add_argument("slug", nargs="?")
    preview_cmd = modes.add_parser("preview")
    preview_cmd.add_argument("slug")
    preview_cmd.add_argument("output", type=Path)
    args = parser.parse_args()
    slug = getattr(args, "slug", None)
    if slug and not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        parser.error("文章 slug 只能包含小写英数字和连字符")
    try:
        if args.mode == "configure":
            configure()
        elif args.mode == "check":
            check_permissions(WeChat(**load_json(STATE / "wechat.json")))
        elif args.mode == "preview":
            preview(args.slug, args.output)
        elif args.mode == "schedule":
            schedule()
        else:
            with locked_state():
                if args.mode == "poll":
                    git_sync()
                else:
                    sync(ROOT, args.slug)
    except (WeChatError, RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
