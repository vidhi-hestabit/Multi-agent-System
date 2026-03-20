from __future__ import annotations
import re


def format_report(markdown: str) -> str:
    if not markdown:
        return ""

    html = _md_to_html(markdown)

    return f"""
<style>
.report-container {{
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 24px 28px;
  font-family: inherit;
  line-height: 1.7;
}}
.report-container h1 {{
  font-size: 1.4rem;
  font-weight: 800;
  color: #111827;
  margin: 0 0 4px 0;
  border-bottom: 2px solid #e5e7eb;
  padding-bottom: 10px;
}}
.report-container h2 {{
  font-size: 1.05rem;
  font-weight: 700;
  color: #1f2937;
  margin: 20px 0 8px 0;
}}
.report-container p {{
  font-size: 0.875rem;
  color: #374151;
  margin: 0 0 12px 0;
}}
.report-container em {{
  color: #9ca3af;
  font-style: italic;
  font-size: 0.8rem;
}}
.report-container strong {{
  color: #111827;
}}
.report-container hr {{
  border: none;
  border-top: 1px solid #f3f4f6;
  margin: 16px 0;
}}
</style>
<div class="report-container">
  {html}
</div>
"""


def _md_to_html(md: str) -> str:
    # Process line by line for headings, then apply inline rules
    lines = md.split("\n")
    output: list[str] = []

    for line in lines:
        if line.startswith("### "):
            output.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            output.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            output.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("---"):
            output.append("<hr>")
        elif line.strip() == "":
            output.append("")
        else:
            output.append(f"<p>{_inline(line)}</p>")

    # Collapse consecutive empty lines
    result = re.sub(r"(\n\s*){3,}", "\n\n", "\n".join(output))
    return result


def _inline(text: str) -> str:
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    return text
