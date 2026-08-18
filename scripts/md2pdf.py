"""Render a Markdown file to a print-ready HTML page (mermaid fences preserved).

Usage: python scripts/md2pdf.py INPUT.md OUTPUT.html
"""

import html
import sys
from pathlib import Path

from markdown_it import MarkdownIt

CSS = """
@page { size: A4; margin: 18mm 16mm; }
* { box-sizing: border-box; }
body {
  font-family: -apple-system, "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 10.5pt; line-height: 1.55; color: #1a1a1a; margin: 0;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
h1 { font-size: 21pt; margin: 0 0 .2em; letter-spacing: -.01em; }
h2 { font-size: 14.5pt; margin: 1.6em 0 .5em; padding-bottom: .25em;
     border-bottom: 1px solid #d8dde3; page-break-after: avoid; }
h3 { font-size: 11.5pt; margin: 1.2em 0 .4em; color: #24303d; page-break-after: avoid; }
h1 + h2 { margin-top: .6em; border: 0; font-size: 13pt; color: #4a5663; font-weight: 500; }
p, ul, ol { margin: .5em 0 .75em; }
li { margin: .18em 0; }
strong { color: #10161d; }
hr { border: 0; border-top: 1px solid #e2e6ea; margin: 1.6em 0; }
code { font-family: "SF Mono", Menlo, Consolas, monospace; font-size: .88em;
       background: #f2f4f7; padding: .1em .35em; border-radius: 3px; color: #26313d; }
pre code { background: none; padding: 0; }
pre { background: #f7f8fa; border: 1px solid #e4e8ec; border-radius: 5px;
      padding: .7em .9em; overflow-x: auto; page-break-inside: avoid; }
table { border-collapse: collapse; width: 100%; margin: .8em 0 1.1em;
        font-size: 9.5pt; page-break-inside: avoid; }
th { background: #eef1f5; text-align: left; font-weight: 600; color: #1f2a35; }
th, td { border: 1px solid #dbe0e6; padding: .4em .6em; vertical-align: top; }
tr:nth-child(even) td { background: #fafbfc; }
.mermaid { text-align: center; margin: 1.1em 0; page-break-inside: avoid; }
.mermaid svg { max-width: 100%; height: auto; }
"""

MERMAID_BOOT = """
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>
  mermaid.initialize({
    startOnLoad: true, theme: 'neutral', securityLevel: 'loose',
    // Wide LR flowcharts get scaled down to page width; oversize the labels so
    // they stay readable in print.
    themeVariables: { fontSize: '22px', fontFamily: 'Helvetica, Arial, sans-serif' },
    flowchart: { useMaxWidth: true, htmlLabels: true, nodeSpacing: 40, rankSpacing: 55 },
  });
</script>
"""


def render_fence(self, tokens, idx, options, env):
    token = tokens[idx]
    if token.info.strip().lower() == "mermaid":
        return f'<pre class="mermaid">{html.escape(token.content)}</pre>\n'
    return self.rules["fence_default"](tokens, idx, options, env)


def main() -> None:
    src, dest = Path(sys.argv[1]), Path(sys.argv[2])
    md = MarkdownIt("commonmark", {"html": True, "typographer": True})
    md.enable(["table", "strikethrough"])
    md.renderer.rules["fence_default"] = md.renderer.rules["fence"]
    md.renderer.rules["fence"] = render_fence.__get__(md.renderer)

    title = src.stem.replace("_", " ").title()
    body = md.render(src.read_text(encoding="utf-8"))
    dest.write_text(
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
        f"<body>{body}{MERMAID_BOOT}</body></html>",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
