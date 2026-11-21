#!/usr/bin/env python3
"""Add a leadership (or other) blog post and rebuild listing, RSS and sitemap.

Usage:
  python3 scripts/add_blog_post.py <caption.md> <image.png> <YYYY-MM-DD> [--title TITLE] [--slug SLUG]
  python3 scripts/add_blog_post.py --rebuild

If the markdown starts with a '# Heading', that heading is the title.
Otherwise pass --title (recommended: the hook on the card).
If neither is set, the line after "Here's the truth:" is used, or the first sentence.

Hashtags should sit on the last line of the markdown (e.g. #Leadership #SMEs).
The script writes a compressed JPG + WebP (1080px, under ~300 KB) to assets/blog/,
creates /blog/<slug>/index.html, and updates /blog/index.html, /blog/feed.xml,
sitemap.xml and blog/posts.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://oludelegbenro.com"
POSTS_PATH = ROOT / "blog" / "posts.json"
ASSETS = ROOT / "assets" / "blog"
MAX_IMAGE_BYTES = 300_000
IMG_SIDE = 1080
BEACON = (
    "<!-- Cloudflare Web Analytics -->"
    "<script type='module' src='https://static.cloudflareinsights.com/beacon.min.js' "
    "data-cf-beacon='{\"token\": \"ed37141234864c09a4eef9b2cd241694\"}'></script>"
    "<!-- End Cloudflare Web Analytics -->"
)

NAV_JS = """
<script>
(function(){
  var btn=document.querySelector('.nav-toggle');
  var links=document.querySelector('#site-nav');
  if(btn && links){
    btn.addEventListener('click', function(){
      var open=btn.getAttribute('aria-expanded')==='true';
      btn.setAttribute('aria-expanded', open?'false':'true');
      links.classList.toggle('is-open', !open);
    });
    links.querySelectorAll('a').forEach(function(a){
      a.addEventListener('click', function(){
        if(window.matchMedia('(max-width:880px)').matches){
          btn.setAttribute('aria-expanded','false');
          links.classList.remove('is-open');
        }
      });
    });
  }
  document.querySelectorAll('.has-sub').forEach(function(li){
    var t=li.querySelector(':scope > a');
    if(!t) return;
    if(!t.hasAttribute('aria-expanded')) t.setAttribute('aria-expanded','false');
    function open(){t.setAttribute('aria-expanded','true');}
    function close(){t.setAttribute('aria-expanded','false');}
    li.addEventListener('mouseenter', open);
    li.addEventListener('mouseleave', close);
    li.addEventListener('focusin', open);
    li.addEventListener('focusout', function(e){
      if(!li.contains(e.relatedTarget)) close();
    });
  });
})();
</script>
"""


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def slugify(title: str) -> str:
    s = title.lower().strip()
    s = s.replace("&", " and ").replace("'", "").replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:80]


def parse_markdown(text: str) -> tuple[str | None, list[str], list[str]]:
    """Return (heading_title or None, body paragraphs, hashtags without #)."""
    text = text.replace("\r\n", "\n").strip()
    heading = None
    lines = text.split("\n")
    if lines and re.match(r"^#\s+\S", lines[0]):
        heading = re.sub(r"^#\s+", "", lines[0]).strip()
        lines = lines[1:]
        if lines and lines[0].strip() == "":
            lines = lines[1:]

    # Trailing hashtag line
    tags: list[str] = []
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and re.match(r"^#[A-Za-z]", lines[-1].strip()) and "," not in lines[-1]:
        raw = lines.pop().strip()
        tags = [t[1:] for t in re.findall(r"#[A-Za-z][A-Za-z0-9_]*", raw)]
        while lines and not lines[-1].strip():
            lines.pop()

    paragraphs: list[str] = []
    buf: list[str] = []
    for line in lines:
        if line.strip() == "":
            if buf:
                paragraphs.append("\n".join(buf).strip())
                buf = []
        else:
            buf.append(line.rstrip())
    if buf:
        paragraphs.append("\n".join(buf).strip())
    return heading, paragraphs, tags


def truth_line(paragraphs: list[str]) -> str | None:
    for i, p in enumerate(paragraphs):
        if p.strip() == "Here's the truth:" and i + 1 < len(paragraphs):
            return paragraphs[i + 1].strip()
        if p.strip().startswith("Here's the truth:"):
            rest = p.split(":", 1)[1].strip()
            if rest:
                return rest
            if i + 1 < len(paragraphs):
                return paragraphs[i + 1].strip()
    return None


def first_sentence(paragraphs: list[str]) -> str:
    for p in paragraphs:
        if p.strip() and not p.strip().startswith("Here's the truth"):
            return p.strip().split("\n")[0].strip()
    return ""


def excerpt_from(paragraphs: list[str], limit: int = 200) -> str:
    parts: list[str] = []
    for p in paragraphs:
        if p.strip().startswith("Here's the truth"):
            break
        parts.append(p.strip().replace("\n", " "))
        text = " ".join(parts)
        # Prefer the opening hook, but keep going if it is only a setup line.
        if text and not text.rstrip().endswith(":") and len(parts[0]) >= 40:
            break
        if len(text) >= 90 and not text.rstrip().endswith(":"):
            break
    text = " ".join(parts).strip()
    if not text:
        text = first_sentence(paragraphs)
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:") + "…"


def parse_date(value: str) -> str:
    return dt.datetime.strptime(value, "%Y-%m-%d").date().isoformat()


def format_display_date(iso: str) -> str:
    d = dt.datetime.strptime(iso, "%Y-%m-%d").date()
    return d.strftime("%-d %B %Y")


def rfc822(iso: str) -> str:
    # Published at 12:30 Africa/Lagos (UTC+1), the series posting time.
    d = dt.datetime.strptime(iso, "%Y-%m-%d")
    return d.replace(hour=12, minute=30, second=0).strftime("%a, %d %b %Y %H:%M:%S +0100")


def load_posts() -> list[dict]:
    if not POSTS_PATH.exists():
        return []
    data = json.loads(POSTS_PATH.read_text())
    return data.get("posts", data if isinstance(data, list) else [])


def save_posts(posts: list[dict]) -> None:
    posts = sorted(posts, key=lambda p: p["date"], reverse=True)
    POSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    POSTS_PATH.write_text(json.dumps({"posts": posts}, indent=2, ensure_ascii=False) + "\n")


def compress_image(src: Path, slug: str) -> tuple[str, str, int, int, int]:
    ASSETS.mkdir(parents=True, exist_ok=True)
    im = Image.open(src).convert("RGB")
    if max(im.size) > IMG_SIDE:
        im.thumbnail((IMG_SIDE, IMG_SIDE), Image.Resampling.LANCZOS)
    w, h = im.size
    jpg_path = ASSETS / f"{slug}.jpg"
    webp_path = ASSETS / f"{slug}.webp"

    def save_jpg(q: int) -> int:
        im.save(jpg_path, "JPEG", quality=q, optimize=True, progressive=True, subsampling=0)
        return jpg_path.stat().st_size

    def save_webp(q: int) -> int:
        im.save(webp_path, "WEBP", quality=q, method=6)
        return webp_path.stat().st_size

    # Prefer high quality but stay under the cap.
    jq = 86
    size = save_jpg(jq)
    while size > MAX_IMAGE_BYTES and jq > 60:
        jq -= 4
        size = save_jpg(jq)
    wq = 82
    wsize = save_webp(wq)
    while wsize > MAX_IMAGE_BYTES and wq > 55:
        wq -= 4
        wsize = save_webp(wq)
    if size > MAX_IMAGE_BYTES:
        raise SystemExit(f"JPEG still {size} bytes after compression (limit {MAX_IMAGE_BYTES})")
    if wsize > MAX_IMAGE_BYTES:
        raise SystemExit(f"WebP still {wsize} bytes after compression (limit {MAX_IMAGE_BYTES})")
    rel_jpg = f"assets/blog/{slug}.jpg"
    rel_webp = f"assets/blog/{slug}.webp"
    print(f"  images: {rel_jpg} {size} bytes (q={jq}); {rel_webp} {wsize} bytes (q={wq}); {w}x{h}")
    return rel_jpg, rel_webp, w, h, size


def icon_links() -> str:
    return """\
<link rel="icon" href="/assets/img/favicon-osg.ico?v=2" sizes="any">
<link rel="icon" type="image/png" href="/assets/img/favicon-osg-32.png?v=2" sizes="32x32">
<link rel="apple-touch-icon" href="/assets/img/apple-touch-icon-osg.png?v=2">
<link rel="icon" type="image/png" href="/assets/img/icon-osg-512.png?v=2" sizes="512x512">
<link rel="stylesheet" href="/assets/css/blog.css">
<link rel="alternate" type="application/rss+xml" title="Oludele Gbenro — Blog" href="/blog/feed.xml">
"""


def nav_html(current: str) -> str:
    def item(href: str, label: str, key: str) -> str:
        cur = ' aria-current="page"' if current == key else ""
        return f'    <li><a href="{href}"{cur}>{label}</a></li>'

    gal_cur = ' aria-current="page" style="color:var(--gold)"' if current == "gallery" else ""
    return f"""\
<nav>
  <a class="logo" href="/" aria-label="Oludele Gbenro, home"><picture>
    <source type="image/webp" srcset="/assets/img/logo-osg-on-dark.webp">
    <img src="/assets/img/logo-osg-on-dark.png" width="79" height="40" alt="Oludele Samson Gbenro monogram">
  </picture></a>
  <button type="button" class="nav-toggle" aria-expanded="false" aria-controls="site-nav" aria-label="Menu"><span class="nav-toggle-bars" aria-hidden="true"></span></button>
  <ul class="nav-links" id="site-nav">
{item("/#about", "About", "about")}
{item("/#skills", "Skills", "skills")}
{item("/#lead", "What I lead", "lead")}
    <li class="has-sub"><a href="/#portfolio" aria-haspopup="true" aria-expanded="false">Portfolio</a>
      <ul class="sub" aria-label="Portfolio submenu">
        <li><a href="/gallery.html"{gal_cur}>Gallery</a></li>
      </ul>
    </li>
{item("/#ai-films", "AI Films", "films")}
{item("/blog/", "Blog", "blog")}
{item("/#testimonials", "Testimonials", "testimonials")}
{item("/#contact", "Contact", "contact")}
    <li><a href="https://www.behance.net/deleg15" target="_blank" rel="noopener" style="color:var(--gold);font-weight:700">Behance ↗</a></li>
  </ul>
</nav>
"""


def footer_html() -> str:
    return """\
<footer>
  <div class="footer-name">OLUDELE SAMSON GBENRO</div>
  <div class="footer-links">
    <a href="/#about">About</a>
    <a href="/#skills">Skills</a>
    <a href="/#lead">What I lead</a>
    <a href="/#portfolio">Portfolio</a>
    <a href="/gallery.html">Gallery</a>
    <a href="/#ai-films">AI Films</a>
    <a href="/blog/">Blog</a>
    <a href="/#testimonials">Testimonials</a>
    <a href="/#contact">Contact</a>
    <a href="mailto:oludele.gbenro@gmail.com">Email</a>
    <a href="https://www.behance.net/deleg15" target="_blank" rel="noopener">Behance</a>
    <a href="https://www.linkedin.com/in/oludelegbenro" target="_blank" rel="noopener">LinkedIn</a>
  </div>
  <div class="footer-copy">&copy; 2026 Oludele Samson Gbenro · Head of Product Management &amp; Brand Communication · Lagos, Nigeria</div>
</footer>
"""


def page_shell(title: str, description: str, canonical: str, og_image: str,
               og_w: int, og_h: int, og_alt: str, body: str, og_type: str = "website") -> str:
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
{icon_links()}<link rel="canonical" href="{esc(canonical)}">
<meta property="og:type" content="{esc(og_type)}">
<meta property="og:site_name" content="Oludele Gbenro">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(canonical)}">
<meta property="og:image" content="{esc(og_image)}">
<meta property="og:image:secure_url" content="{esc(og_image)}">
<meta property="og:image:type" content="image/jpeg">
<meta property="og:image:width" content="{og_w}">
<meta property="og:image:height" content="{og_h}">
<meta property="og:image:alt" content="{esc(og_alt)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(description)}">
<meta name="twitter:image" content="{esc(og_image)}">
</head>
<body>
{nav_html('blog')}
<main>
{body}
</main>
{footer_html()}
{NAV_JS}
{BEACON}
</body>
</html>
"""


def render_body(paragraphs: list[str]) -> str:
    parts: list[str] = []
    i = 0
    while i < len(paragraphs):
        p = paragraphs[i]
        stripped = p.strip()
        if stripped == "Here's the truth:" or stripped.startswith("Here's the truth:"):
            rest = ""
            if stripped.startswith("Here's the truth:"):
                rest = stripped.split(":", 1)[1].strip()
            if not rest and i + 1 < len(paragraphs):
                rest = paragraphs[i + 1].strip()
                i += 1
            parts.append(
                '<div class="post-truth">'
                '<span class="post-truth-label">Here\'s the truth:</span>'
                f'<p class="post-truth-line">{esc(rest)}</p>'
                "</div>"
            )
            i += 1
            continue
        # Preserve single newlines inside a paragraph as <br> only if they were
        # short stacked lines (already joined with \n by the parser).
        if "\n" in p:
            inner = "<br>".join(esc(line) for line in p.split("\n"))
            parts.append(f"<p>{inner}</p>")
        else:
            parts.append(f"<p>{esc(p)}</p>")
        i += 1
    return "\n    ".join(parts)


def write_index(posts: list[str] | list[dict]) -> None:
    posts = sorted(posts, key=lambda p: p["date"], reverse=True)
    cards = []
    for p in posts:
        url = f"/blog/{p['slug']}/"
        img = "/" + p["image"]
        img_w = p.get("image_webp", p["image"].rsplit(".", 1)[0] + ".webp")
        cards.append(f"""\
    <article class="blog-card">
      <a class="card-img" href="{esc(url)}">
        <picture>
          <source type="image/webp" srcset="/{esc(img_w)}">
          <img src="{esc(img)}" width="{p['width']}" height="{p['height']}" alt="{esc(p['title'])}" loading="lazy" decoding="async">
        </picture>
      </a>
      <div class="blog-card-body">
        <div class="blog-card-date">{esc(format_display_date(p['date']))}</div>
        <h2 class="blog-card-title"><a href="{esc(url)}">{esc(p['title'])}</a></h2>
        <p class="blog-card-excerpt">{esc(p['excerpt'])}</p>
        <a class="read-link" href="{esc(url)}">Read</a>
      </div>
    </article>""")
    body = f"""\
<div class="blog-wrap">
  <div class="eyebrow">Blog</div>
  <h1 class="section-title">Leadership notes</h1>
  <div class="divider"></div>
  <p class="blog-intro">Daily notes on leadership, service and showing up well. These posts also appear on <a href="https://www.linkedin.com/in/oludelegbenro" target="_blank" rel="noopener">LinkedIn</a>.</p>
  <div class="blog-grid">
{chr(10).join(cards)}
  </div>
  <p class="rss-link">Subscribe by <a href="/blog/feed.xml">RSS feed</a>.</p>
</div>
"""
    desc = "Leadership notes by Oludele Gbenro: daily lessons on leading yourself, your team and your work."
    html_out = page_shell(
        title="Blog | Oludele Gbenro",
        description=desc,
        canonical=f"{SITE}/blog/",
        og_image=f"{SITE}/{posts[0]['image']}" if posts else f"{SITE}/assets/img/og-image.jpg",
        og_w=posts[0]["width"] if posts else 1200,
        og_h=posts[0]["height"] if posts else 627,
        og_alt=posts[0]["title"] if posts else "Oludele Gbenro",
        body=body,
        og_type="website",
    )
    dest = ROOT / "blog" / "index.html"
    dest.write_text(html_out)
    print(f"  wrote {dest.relative_to(ROOT)}")


def write_post_pages(posts: list[dict]) -> None:
    ordered = sorted(posts, key=lambda p: p["date"])  # oldest -> newest
    by_slug = {p["slug"]: i for i, p in enumerate(ordered)}
    for i, p in enumerate(ordered):
        older = ordered[i - 1] if i > 0 else None
        newer = ordered[i + 1] if i + 1 < len(ordered) else None
        pager = ['<nav class="post-pager" aria-label="More posts">']
        if older:
            pager.append(
                f'<a class="prev" rel="prev" href="/blog/{esc(older["slug"])}/">'
                f'<span class="dir">Previous</span>{esc(older["title"])}</a>'
            )
        if newer:
            pager.append(
                f'<a class="next" rel="next" href="/blog/{esc(newer["slug"])}/">'
                f'<span class="dir">Next</span>{esc(newer["title"])}</a>'
            )
        pager.append("</nav>")

        tags = ""
        if p.get("hashtags"):
            items = "".join(f"<li>#{esc(t)}</li>" for t in p["hashtags"])
            tags = f'<ul class="post-tags">{items}</ul>'

        img = p["image"]
        img_w = p.get("image_webp", img.rsplit(".", 1)[0] + ".webp")
        body = f"""\
<div class="blog-wrap">
  <article class="post">
    <p class="crumb"><a href="/">Home</a> <span>/</span> <a href="/blog/">Blog</a> <span>/</span> {esc(p['title'])}</p>
    <div class="post-date"><time datetime="{esc(p['date'])}">{esc(format_display_date(p['date']))}</time></div>
    <h1>{esc(p['title'])}</h1>
    <div class="post-hero">
      <picture>
        <source type="image/webp" srcset="/{esc(img_w)}">
        <img src="/{esc(img)}" width="{p['width']}" height="{p['height']}" alt="{esc(p['title'])}">
      </picture>
    </div>
    <div class="post-body">
    {render_body(p['paragraphs'])}
    </div>
    {tags}
    <div class="post-cta">
      <h2>Continue the conversation</h2>
      <p>Follow along on LinkedIn and Ginspirations TV, or get in touch from the portfolio.</p>
      <div class="post-cta-actions">
        <a class="btn-primary" href="https://www.linkedin.com/in/oludelegbenro" target="_blank" rel="noopener">Follow on LinkedIn</a>
        <a class="btn-outline" href="https://www.tiktok.com/@ginspirations.tv" target="_blank" rel="noopener">Ginspirations TV on TikTok</a>
        <a class="btn-outline" href="/#contact">Portfolio &amp; contact</a>
      </div>
    </div>
    {''.join(pager)}
  </article>
</div>
"""
        desc = p["excerpt"]
        html_out = page_shell(
            title=f"{p['title']} | Oludele Gbenro",
            description=desc,
            canonical=f"{SITE}/blog/{p['slug']}/",
            og_image=f"{SITE}/{p['image']}",
            og_w=p["width"],
            og_h=p["height"],
            og_alt=p["title"],
            body=body,
            og_type="article",
        )
        dest = ROOT / "blog" / p["slug"] / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html_out)
        print(f"  wrote {dest.relative_to(ROOT)}")


def write_feed(posts: list[dict]) -> None:
    posts = sorted(posts, key=lambda p: p["date"], reverse=True)
    items = []
    for p in posts:
        url = f"{SITE}/blog/{p['slug']}/"
        img = f"{SITE}/{p['image']}"
        # Full caption as simple paragraphs in the RSS description.
        body = []
        for para in p["paragraphs"]:
            body.append(f"<p>{esc(para).replace(chr(10), '<br>')}</p>")
        if p.get("hashtags"):
            body.append("<p>" + " ".join(f"#{esc(t)}" for t in p["hashtags"]) + "</p>")
        desc = "\n".join(body)
        items.append(f"""\
    <item>
      <title>{esc(p['title'])}</title>
      <link>{url}</link>
      <guid>{url}</guid>
      <pubDate>{rfc822(p['date'])}</pubDate>
      <description><![CDATA[
        <p><img src="{img}" alt="{esc(p['title'])}" width="{p['width']}" height="{p['height']}"></p>
        {desc}
      ]]></description>
    </item>""")
    built = dt.datetime.now(dt.timezone(dt.timedelta(hours=1))).strftime("%a, %d %b %Y %H:%M:%S +0100")
    xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Oludele Gbenro — Blog</title>
    <link>{SITE}/blog/</link>
    <description>Leadership notes by Oludele Gbenro.</description>
    <language>en</language>
    <lastBuildDate>{built}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
"""
    dest = ROOT / "blog" / "feed.xml"
    dest.write_text(xml)
    print(f"  wrote {dest.relative_to(ROOT)}")


def write_sitemap(posts: list[dict]) -> None:
    posts = sorted(posts, key=lambda p: p["date"], reverse=True)
    latest = posts[0]["date"] if posts else dt.date.today().isoformat()
    urls = [
        (f"{SITE}/", None, "weekly", "1.0"),
        (f"{SITE}/gallery.html", None, "monthly", "0.7"),
        (f"{SITE}/blog/", latest, "daily", "0.8"),
    ]
    for p in posts:
        urls.append((f"{SITE}/blog/{p['slug']}/", p["date"], "monthly", "0.7"))

    def url_el(loc, lastmod, freq, pri):
        lm = f"    <lastmod>{lastmod}</lastmod>\n" if lastmod else ""
        return (
            f"  <url>\n    <loc>{loc}</loc>\n{lm}"
            f"    <changefreq>{freq}</changefreq>\n    <priority>{pri}</priority>\n  </url>"
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(url_el(*u) for u in urls)
        + "\n</urlset>\n"
    )
    dest = ROOT / "sitemap.xml"
    dest.write_text(xml)
    print(f"  wrote {dest.relative_to(ROOT)}")


def write_robots() -> None:
    dest = ROOT / "robots.txt"
    dest.write_text(
        "User-agent: *\nAllow: /\n\n"
        f"Sitemap: {SITE}/sitemap.xml\n"
    )
    print(f"  wrote {dest.relative_to(ROOT)}")


def rebuild(posts: list[dict]) -> None:
    if not posts:
        print("No posts in blog/posts.json")
        return
    save_posts(posts)
    posts = load_posts()
    write_index(posts)
    write_post_pages(posts)
    write_feed(posts)
    write_sitemap(posts)
    write_robots()


def add_post(md_path: Path, img_path: Path, date: str, title: str | None, slug: str | None) -> None:
    if not md_path.is_file():
        raise SystemExit(f"Markdown not found: {md_path}")
    if not img_path.is_file():
        raise SystemExit(f"Image not found: {img_path}")
    date = parse_date(date)
    heading, paragraphs, tags = parse_markdown(md_path.read_text(encoding="utf-8"))
    if not paragraphs:
        raise SystemExit("Markdown has no body text")
    title = (title or heading or truth_line(paragraphs) or first_sentence(paragraphs) or "").strip()
    if not title:
        raise SystemExit("Could not determine a title; pass --title")
    if title.endswith(".") and title.count(".") == 1:
        # Keep a single closing full stop if it is part of the hook; leave as authored.
        pass
    slug = slugify(slug or title)
    if not slug:
        raise SystemExit("Could not build a slug; pass --slug")

    rel_jpg, rel_webp, width, height, _ = compress_image(img_path, slug)
    entry = {
        "slug": slug,
        "date": date,
        "title": title,
        "excerpt": excerpt_from(paragraphs),
        "hashtags": tags,
        "image": rel_jpg,
        "image_webp": rel_webp,
        "width": width,
        "height": height,
        "paragraphs": paragraphs,
        "source": md_path.name,
    }
    posts = [p for p in load_posts() if p.get("slug") != slug]
    posts.append(entry)
    print(f"  post: {date} /{slug}/ — {title}")
    rebuild(posts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("md", nargs="?", help="Caption markdown file")
    ap.add_argument("png", nargs="?", help="1080×1080 (or similar) card image")
    ap.add_argument("date", nargs="?", help="Publication date YYYY-MM-DD (Africa/Lagos)")
    ap.add_argument("--title", help="Post title (the hook or key line)")
    ap.add_argument("--slug", help="URL slug (default: from the title)")
    ap.add_argument("--rebuild", action="store_true", help="Regenerate pages from blog/posts.json only")
    args = ap.parse_args(argv)

    if args.rebuild:
        rebuild(load_posts())
        return 0
    if not (args.md and args.png and args.date):
        ap.print_help()
        return 2
    add_post(Path(args.md), Path(args.png), args.date, args.title, args.slug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
