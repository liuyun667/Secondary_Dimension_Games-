"""零依赖 Markdown → HTML 渲染器（够用：标题/列表/表格/代码块/粗体/引用/链接）。

用于 /docs 文档页（局域网访问），避免引入第三方 markdown 库。
"""
from __future__ import annotations

import html
import re

_INLINE_RE = [
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"\[([^\]]+)\]\(([^)]+)\)"), r'<a href="\2" target="_blank" rel="noopener">\1</a>'),
]


def _inline(text: str) -> str:
    esc = html.escape(text)
    for pat, repl in _INLINE_RE:
        esc = pat.sub(repl, esc)
    return esc


def _render_table(rows: list[str]) -> str:
    cells = []
    for r in rows[1:]:  # 跳过表头分隔行
        parts = [c.strip() for c in r.strip().strip("|").split("|")]
        cells.append(parts)
    if not cells:
        return ""
    head = cells[0]
    body = cells[1:]
    html_t = "<table><thead><tr>" + "".join(f"<th>{_inline(h)}</th>" for h in head) + "</tr></thead><tbody>"
    for row in body:
        html_t += "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>"
    html_t += "</tbody></table>"
    return html_t


def render_md(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    in_code = False
    code_buf: list[str] = []
    list_buf: list[str] = []

    def flush_list():
        if list_buf:
            out.append("<ul>" + "".join(list_buf) + "</ul>")
            list_buf.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
                code_buf, in_code = [], False
            else:
                flush_list()
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue
        # 表格：当前行以 | 开头且下一行是分隔行
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(
                r"^\s*\|[\s:\-|]+\|\s*$", lines[i + 1]):
            flush_list()
            rows = [line]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_render_table(rows))
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            flush_list()
            lv = len(m.group(1))
            out.append(f"<h{lv}>{_inline(m.group(2))}</h{lv}>")
            i += 1
            continue
        if stripped in ("---", "***", "___"):
            flush_list()
            out.append("<hr>")
            i += 1
            continue
        if stripped == "":
            flush_list()
            i += 1
            continue
        m = re.match(r"^\s*[-*+]\s+(.*)", line)
        if m:
            list_buf.append(f"<li>{_inline(m.group(1))}</li>")
            i += 1
            continue
        flush_list()
        m = re.match(r"^>\s?(.*)", line)
        if m:
            out.append(f"<blockquote>{_inline(m.group(1))}</blockquote>")
        else:
            out.append(f"<p>{_inline(line)}</p>")
        i += 1
    flush_list()
    if in_code:
        out.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
    return "\n".join(out)


PAGE_CSS = """
:root { --bg:#f6f7f9; --panel:#fff; --line:#e6e8eb; --text:#1f2329; --muted:#6b7280; --accent:#3b82f6; --accent-soft:#eef4ff; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif; background: var(--bg); color: var(--text); line-height: 1.7; }
.wrap { display: flex; max-width: 1100px; margin: 0 auto; min-height: 100vh; }
nav { width: 200px; flex-shrink: 0; padding: 24px 16px; background: var(--panel); border-right: 1px solid var(--line); position: sticky; top: 0; height: 100vh; overflow-y: auto; }
nav a { display: block; padding: 8px 10px; border-radius: 8px; color: var(--muted); text-decoration: none; font-size: 14px; }
nav a:hover { background: var(--accent-soft); color: var(--accent); }
nav a.active { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
article { flex: 1; padding: 28px 36px 80px; max-width: 860px; }
article h1 { font-size: 26px; margin: 8px 0 14px; padding-bottom: 8px; border-bottom: 2px solid var(--accent); }
article h2 { font-size: 20px; margin: 26px 0 10px; }
article h3 { font-size: 17px; margin: 20px 0 8px; }
article h4 { font-size: 15px; margin: 16px 0 6px; }
article p { margin: 8px 0; }
article blockquote { border-left: 3px solid var(--accent); background: var(--accent-soft); padding: 8px 14px; border-radius: 0 8px 8px 0; margin: 10px 0; color: var(--muted); }
article ul { margin: 8px 0 8px 22px; }
article li { margin: 4px 0; }
article table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13.5px; }
article th, article td { border: 1px solid var(--line); padding: 6px 10px; text-align: left; }
article th { background: var(--accent-soft); color: var(--accent); }
article pre { background: #0f172a; color: #e2e8f0; padding: 12px 16px; border-radius: 10px; overflow-x: auto; margin: 10px 0; font-size: 13px; }
article code { font-family: Consolas, "Courier New", monospace; }
article a { color: var(--accent); }
hr { border: none; border-top: 1px solid var(--line); margin: 18px 0; }
"""


def docs_page(title: str, nav: list[tuple[str, str, bool]], content_html: str) -> str:
    nav_html = "".join(
        f'<a href="/docs?doc={name}" class="{"active" if active else ""}">{label}</a>'
        for label, name, active in nav)
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title><style>{PAGE_CSS}</style></head>
<body><div class="wrap"><nav>{nav_html}</nav>
<article>{content_html}</article></div></body></html>"""
