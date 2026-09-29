"""Check generated local links/assets and fragments, including project-site paths."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
import sys

root = Path("site").resolve()
base = "/MakerVault/"

class Page(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.ids = set()
        self.links = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        for key in ("href", "src"):
            if attrs.get(key):
                self.links.append(attrs[key])

pages = {p: Page(p.read_text()) for p in root.rglob("*.html")}
errors = []
for source, page in pages.items():
    for link in page.links:
        url = urlsplit(link)
        if url.scheme or url.netloc:
            continue
        path = unquote(url.path)
        if path.startswith(base):
            target = root / path[len(base):]
        elif path.startswith("/"):
            # 404 pages use the site root. A non-project root path is an error.
            errors.append(f"{source.relative_to(root)}: unexpected root path {link}")
            continue
        else:
            target = source.parent / path if path else source
        target = target.resolve()
        if target.is_dir():
            target = target / "index.html"
        if not target.exists():
            errors.append(f"{source.relative_to(root)}: missing {link}")
        elif url.fragment and target in pages and unquote(url.fragment) not in pages[target].ids:
            errors.append(f"{source.relative_to(root)}: missing anchor {link}")
if not pages:
    errors.append("No built pages; run python -m mkdocs build --strict first.")
if errors:
    print("\n".join(errors))
    sys.exit(1)
print(f"Checked local links and fragments across {len(pages)} HTML pages.")
