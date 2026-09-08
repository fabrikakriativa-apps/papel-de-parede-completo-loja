from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"

html = INDEX.read_text(encoding="utf-8")

# Home Finish serves some legacy JPGs when requested directly but may reject
# requests that carry a third-party Referer. Set a global no-referrer policy so
# both static and dynamically created catalog images request the official files
# directly, without leaking the Fábrika catalog URL as Referer.
if not re.search(r'<meta\s+name=["\']referrer["\']', html, flags=re.IGNORECASE):
    html = re.sub(
        r"(<meta\s+name=\"viewport\"[^>]*>)",
        r'\1<meta name="referrer" content="no-referrer">',
        html,
        count=1,
        flags=re.IGNORECASE,
    )

# Also annotate literal image elements for defense in depth.
html = re.sub(
    r"<img(?![^>]*\breferrerpolicy=)",
    '<img referrerpolicy="no-referrer"',
    html,
    flags=re.IGNORECASE,
)

INDEX.write_text(html, encoding="utf-8")
print("Global external image referrer protection applied")
