# oludelegbenro
Portfolio of Oludele Samson Gbenro — Head of Product Management and Brand Communication. Explore brand, product and customer experience leadership, along with brand identity and visual design work built over a career at First Registrars &amp; Investor Services Limited.

## Blog

The blog lives at `/blog/`. To publish a new post (after it has gone out on LinkedIn):

```bash
python3 scripts/add_blog_post.py path/to/caption.md path/to/card.png YYYY-MM-DD --title "Hook or key line"
```

That command compresses the 1080×1080 card (JPG + WebP, under 300 KB), creates `/blog/<slug>/`, and updates the listing, RSS feed (`/blog/feed.xml`) and `sitemap.xml`.

- If the markdown starts with a `# Heading`, that heading is used as the title. Otherwise pass `--title` (use the hook on the card, or the line after “Here's the truth:”).
- Optional `--slug` overrides the URL slug derived from the title.
- Hashtags should be on the last line of the markdown, for example `#Leadership #SMEs`.
- To regenerate pages from `blog/posts.json` without adding a post: `python3 scripts/add_blog_post.py --rebuild`.
