# Renders atopile-analysis.md to XbatteryEDAPlatform.html, single-file, images embedded.
# Usage: cd into the doc folder, then: python _tools/render_doc.py   (needs: pip install markdown)
# Headings get GitHub-style ids so the Contents links work; doc.css must sit next to this script.
import re, markdown, base64, mimetypes, os

src = open("atopile-analysis.md", encoding="utf-8").read()

# de-indent 2-3 space continuation lines outside fenced code so markdown doesn't eat them.
# Fences may themselves be indented (a code block nested in a list item), so match
# leading whitespace when toggling -- otherwise comment lines inside such a block get
# parsed as markdown headings.
out, fence = [], False
for line in src.split("\n"):
    if re.match(r"^\s*```", line):
        fence = not fence
    elif not fence:
        m = re.match(r"^( {2,3})(\S.*)$", line)
        if m:
            line = "    " + m.group(2)
    out.append(line)
src = "\n".join(out)

def gh_slug(value, separator):
    value = re.sub(r"[^\w\- ]", "", value.strip().lower())
    return value.replace(" ", "-")

body = markdown.markdown(
    src,
    extensions=["tables", "fenced_code", "sane_lists", "toc", "attr_list"],
    extension_configs={"toc": {"slugify": gh_slug}},
)
body = body.replace("<table>", '<div class="tbl"><table>').replace("</table>", "</table></div>")

def _embed(m):
    path = m.group(1)
    if not os.path.exists(path):
        return m.group(0)
    data = base64.b64encode(open(path, "rb").read()).decode()
    return f'src="data:{mimetypes.guess_type(path)[0]};base64,{data}"'

body = re.sub(r'src="((?!https?:|data:)[^"]+)"', _embed, body)

css = open(os.path.join(os.path.dirname(__file__), "doc.css"), encoding="utf-8").read()
extra = """
.lede{font-size:17px;color:var(--muted);max-width:80ch}
.tag{display:inline-block;font-size:11.5px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;
     padding:2px 7px;border-radius:4px;border:1px solid var(--line);background:var(--head);color:var(--muted)}
h2{scroll-margin-top:12px}
table td:first-child{white-space:normal}
.small{font-size:13px;color:var(--muted)}
"""
page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Xbattery EDA Platform - atopile Analysis and Build Plan</title><style>{css}{extra}</style></head>
<body><main>
{body}
</main></body></html>
"""
open("XbatteryEDAPlatform.html", "w", encoding="utf-8").write(page)
ids = set(re.findall(r'id="([^"]+)"', page))
links = re.findall(r'href="#([^"]+)"', page)
missing = [l for l in links if l not in ids]
print("html chars:", len(page), "| internal links:", len(links), "| missing:", missing)
