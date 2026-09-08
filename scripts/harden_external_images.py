from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"

html = INDEX.read_text(encoding="utf-8")

# Home Finish serves some legacy JPGs when requested directly but may reject
# requests that carry a third-party Referer. Apply no-referrer to every image
# element (cards and modal) so official external images are requested directly.
html = re.sub(
    r"<img(?![^>]*\breferrerpolicy=)",
    '<img referrerpolicy="no-referrer"',
    html,
    flags=re.IGNORECASE,
)

INDEX.write_text(html, encoding="utf-8")
print("External image referrer protection applied")
