#!/usr/bin/env python3
"""Tiny static blog generator.

    python build.py          # build into _site/
    python build.py serve    # build, serve on http://localhost:8000, rebuild on change
"""
import html, http.server, os, re, shutil, sys, threading, time, tomllib
from datetime import date, datetime
from email.utils import format_datetime
from pathlib import Path

import markdown

ROOT = Path(__file__).parent
POSTS, STATIC, OUT = ROOT / "posts", ROOT / "static", ROOT / "_site"
CONFIG = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
LOCAL = False  # set by "serve": ignore base path on localhost
MD_EXT = ["fenced_code", "codehilite", "tables", "toc", "footnotes", "smarty"]


# ---------- parsing ----------
def parse_post(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    meta = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip().strip('"').strip("'")
        text = text[m.end():]

    slug = meta.get("slug") or re.sub(r"^\d{4}-\d{2}-\d{2}-", "", path.stem)
    d = meta.get("date") or (path.stem[:10] if re.match(r"\d{4}-\d{2}-\d{2}", path.stem) else None)
    d = datetime.strptime(d, "%Y-%m-%d").date() if d else date.fromtimestamp(path.stat().st_mtime)
    tags = [t.strip() for t in meta.get("tags", "").strip("[]").split(",") if t.strip()]
    body = markdown.markdown(text, extensions=MD_EXT,
                             extension_configs={"codehilite": {"guess_lang": False}})
    first_p = re.search(r"<p>(.*?)</p>", body, re.S)
    summary = meta.get("description") or (re.sub(r"<[^>]+>", "", first_p.group(1))[:200] if first_p else "")
    return {
        "title": meta.get("title", slug.replace("-", " ").title()),
        "slug": slug, "date": d, "tags": tags, "body": body, "summary": summary,
        "draft": meta.get("draft", "false").lower() == "true",
        "url": f"/posts/{slug}/",
    }


# ---------- templates ----------
def page(title: str, content: str, description: str = "") -> str:
    site = CONFIG["site"]
    nav = "".join(f'<a href="{u}">{html.escape(n)}</a>' for n, u in CONFIG.get("nav", {}).items())
    full_title = title if title == site["title"] else f"{title} · {site['title']}"
    return f"""<!doctype html>
<html lang="{site.get('lang', 'en')}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(full_title)}</title>
<meta name="description" content="{html.escape(description or site.get('description', ''))}">
<link rel="stylesheet" href="/static/style.css">
<link rel="alternate" type="application/rss+xml" title="{html.escape(site['title'])}" href="/feed.xml">
</head>
<body>
<header class="site-header">
  <a class="site-title" href="/">{html.escape(site['title'])}</a>
  <nav>{nav}</nav>
</header>
<main>
{content}
</main>
</body>
</html>"""


def tag_links(tags):
    return " ".join(f'<a class="tag" href="/tags/{t}/">#{html.escape(t)}</a>' for t in tags)


def post_list(posts):
    items = "".join(
        f'<li><time datetime="{p["date"]}">{p["date"]:%d %b %Y}</time>'
        f'<a href="{p["url"]}">{html.escape(p["title"])}</a></li>' for p in posts)
    return f'<ul class="post-list">{items}</ul>'


def write(rel: str, content: str):
    # Prefix root-relative links with the repo path (e.g. /blog) when hosted at user.github.io/blog/
    base = "" if LOCAL else CONFIG["site"].get("base", "").strip().rstrip("/")
    if base and rel.endswith(".html"):
        content = re.sub(r'(href|src)="/(?!/)', rf'\1="{base}/', content)
    target = OUT / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


# ---------- build ----------
def build():
    t0 = time.time()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    if STATIC.exists():
        shutil.copytree(STATIC, OUT / "static")

    show_drafts = os.environ.get("DRAFTS") == "1"
    posts = [parse_post(p) for p in sorted(POSTS.glob("*.md"))]
    posts = sorted((p for p in posts if show_drafts or not p["draft"]),
                   key=lambda p: p["date"], reverse=True)

    # posts
    for i, p in enumerate(posts):
        newer = posts[i - 1] if i > 0 else None
        older = posts[i + 1] if i + 1 < len(posts) else None
        pager = ('<nav class="pager">'
                 + (f'<a href="{older["url"]}">← {html.escape(older["title"])}</a>' if older else "<span></span>")
                 + (f'<a href="{newer["url"]}">{html.escape(newer["title"])} →</a>' if newer else "")
                 + "</nav>") if (older or newer) else ""
        article = (f'<article><h1>{html.escape(p["title"])}</h1>'
                   f'<p class="meta"><time datetime="{p["date"]}">{p["date"]:%d %B %Y}</time> {tag_links(p["tags"])}</p>'
                   f'{p["body"]}</article>{pager}')
        write(f"posts/{p['slug']}/index.html", page(p["title"], article, p["summary"]))

    # index
    intro = CONFIG["site"].get("intro", "")
    write("index.html", page(CONFIG["site"]["title"],
                             (f'<p class="intro">{intro}</p>' if intro else "") + post_list(posts)))

    # tags
    tags = {}
    for p in posts:
        for t in p["tags"]:
            tags.setdefault(t, []).append(p)
    for t, ps in tags.items():
        write(f"tags/{t}/index.html", page(f"#{t}", f"<h1>#{html.escape(t)}</h1>" + post_list(ps)))

    # standalone pages: pages/*.md -> /<name>/
    for md in sorted((ROOT / "pages").glob("*.md")):
        p = parse_post(md)
        write(f"{md.stem}/index.html", page(p["title"], f'<article><h1>{html.escape(p["title"])}</h1>{p["body"]}</article>'))

    # RSS
    base = CONFIG["site"].get("url", "").rstrip("/")
    items = "".join(
        f"<item><title>{html.escape(p['title'])}</title><link>{base}{p['url']}</link>"
        f"<guid>{base}{p['url']}</guid>"
        f"<pubDate>{format_datetime(datetime.combine(p['date'], datetime.min.time()).astimezone())}</pubDate>"
        f"<description>{html.escape(p['body'])}</description></item>" for p in posts[:20])
    write("feed.xml", f'<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>'
                      f"<title>{html.escape(CONFIG['site']['title'])}</title><link>{base}/</link>"
                      f"<description>{html.escape(CONFIG['site'].get('description', ''))}</description>"
                      f"{items}</channel></rss>")

    # 404, CNAME, .nojekyll
    write("404.html", page("Not found", '<h1>404</h1><p>That page doesn\'t exist. <a href="/">Go home</a>.</p>'))
    domain = CONFIG["site"].get("domain", "").strip()
    if domain:
        write("CNAME", domain + "\n")
    write(".nojekyll", "")

    print(f"Built {len(posts)} posts, {len(tags)} tags in {(time.time() - t0) * 1000:.0f} ms → {OUT}")


# ---------- dev server ----------
def snapshot():
    files = [f for d in (POSTS, ROOT / "pages", STATIC) if d.exists() for f in d.rglob("*") if f.is_file()]
    files.append(ROOT / "config.toml")
    return {f: f.stat().st_mtime for f in files}


def serve(port=8000):
    global CONFIG, LOCAL
    LOCAL = True
    build()

    def watch():
        global CONFIG
        last = snapshot()
        while True:
            time.sleep(0.7)
            now = snapshot()
            if now != last:
                last = now
                try:
                    CONFIG = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
                    build()
                except Exception as e:
                    print("Build failed:", e)

    threading.Thread(target=watch, daemon=True).start()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(OUT), **kw)

        def send_error(self, code, message=None, explain=None):
            if code == 404 and (OUT / "404.html").exists():
                body = (OUT / "404.html").read_bytes()
                self.send_response(404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                super().send_error(code, message, explain)

        def log_message(self, *a):
            pass

    print(f"Serving on http://localhost:{port}  (Ctrl+C to stop, edits rebuild automatically)")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        serve(int(sys.argv[2]) if len(sys.argv) > 2 else 8000)
    else:
        build()