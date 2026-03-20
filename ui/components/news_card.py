from __future__ import annotations


def format_news_section(articles: list[dict]) -> str:
    if not articles:
        return ""

    cards = []
    for article in articles[:5]:
        title       = article.get("title", "Untitled")
        source      = article.get("source", "")
        published   = article.get("published_at", "")
        description = article.get("description", "")
        url         = article.get("url", "#")

        date_str = ""
        if published:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                date_str = dt.strftime("%b %d, %Y")
            except Exception:
                date_str = published[:10]

        meta_parts = [p for p in [source, date_str] if p]
        meta_line  = " &middot; ".join(meta_parts)

        cards.append(f"""
<div class="news-card">
  <div class="news-meta">{meta_line}</div>
  <a class="news-title" href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>
  <p class="news-desc">{description}</p>
</div>
""")

    cards_html = "\n".join(cards)

    return f"""
<style>
.news-section-header {{
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #6b7280;
  margin-bottom: 12px;
}}
.news-card {{
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 10px;
  transition: box-shadow 0.15s;
}}
.news-card:hover {{
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
}}
.news-meta {{
  font-size: 0.72rem;
  color: #9ca3af;
  margin-bottom: 4px;
}}
.news-title {{
  display: block;
  font-size: 0.9rem;
  font-weight: 600;
  color: #111827;
  text-decoration: none;
  line-height: 1.4;
  margin-bottom: 6px;
}}
.news-title:hover {{
  color: #4f46e5;
}}
.news-desc {{
  font-size: 0.82rem;
  color: #6b7280;
  margin: 0;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}}
</style>
<div class="news-section-header">News Articles</div>
{cards_html}
"""
