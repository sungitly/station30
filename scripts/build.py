from datetime import date
from html import escape
import os
from pathlib import Path
import re
import shutil
from string import Template

from markdown_it import MarkdownIt
import yaml


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "dist"
SITE_URL = os.environ.get("SITE_URL", "https://station30.fdeweekly.com").rstrip("/")
MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("table")


def template(name, **fields):
    source = (ROOT / "templates" / f"{name}.html").read_text(encoding="utf-8")
    return Template(source).substitute(fields)


def load_post(path):
    slug = path.stem
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise ValueError(f"{path.name}: use a lowercase, hyphen-separated slug")
    source = path.read_text(encoding="utf-8")
    if not source.startswith("---\n") or "\n---\n" not in source[4:]:
        raise ValueError(f"{path.name}: expected YAML front matter")
    front_matter, body = source[4:].split("\n---\n", 1)
    fields = yaml.safe_load(front_matter)
    if not isinstance(fields, dict):
        raise ValueError(f"{path.name}: expected a metadata mapping")
    if fields.get("draft") is True:
        return None
    for key in ("title", "summary", "category"):
        if not isinstance(fields.get(key), str) or not fields[key].strip():
            raise ValueError(f"{path.name}: missing {key}")
    published = date.fromisoformat(str(fields.get("date"))).isoformat()
    return {
        "slug": slug,
        "path": f"/posts/{slug}/",
        "title": escape(fields["title"]),
        "summary": escape(fields["summary"]),
        "category": escape(fields["category"]),
        "date": published,
        "body": MARKDOWN.render(body),
    }


def page(title, description, path, content):
    return template(
        "base", title=title, description=description,
        canonical=escape(SITE_URL + path), content=content,
    )


def build():
    posts = [load_post(path) for path in sorted((ROOT / "posts").glob("*.md"))]
    posts = sorted((post for post in posts if post), key=lambda post: post["date"], reverse=True)
    if not any(post["slug"] == "station-30" for post in posts):
        raise ValueError("posts/station-30.md is required for the About link")
    entries = "".join(template("entry", **post) for post in posts)
    home = template("home", count=f"{len(posts):02d}", entries=entries)

    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    shutil.copytree(ROOT / "static", OUTPUT)
    (OUTPUT / "index.html").write_text(
        page("三十号地面站 · STATION 30", "记录 AI 着陆之后的事。", "/", home),
        encoding="utf-8",
    )
    for post in posts:
        target = OUTPUT / "posts" / post["slug"]
        target.mkdir(parents=True)
        (target / "index.html").write_text(
            page(
                f'{post["title"]} · 三十号地面站', post["summary"], post["path"],
                template("article", **post),
            ),
            encoding="utf-8",
        )
    print(f"Built {len(posts)} post(s) in {OUTPUT}")


if __name__ == "__main__":
    build()
