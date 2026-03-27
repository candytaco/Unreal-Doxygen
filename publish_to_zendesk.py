#!/usr/bin/env python3
"""
publish_to_zendesk.py — Publish Markdown documentation to Zendesk Help Center

Reads Markdown files produced by xml_to_markdown.py and creates or updates
articles in a Zendesk Help Center section.

Authentication
--------------
Set the following environment variables (or pass via CLI flags):

  ZENDESK_SUBDOMAIN   — your Zendesk subdomain  (e.g. ``mycompany``)
  ZENDESK_EMAIL       — agent / admin email address
  ZENDESK_API_TOKEN   — Zendesk API token (generate at
                        Admin > Apps and integrations > Zendesk API)

Usage
-----
::

    # Dry-run (prints what would be uploaded)
    python3 publish_to_zendesk.py --docs-dir docs/md --section-id 12345 --dry-run

    # Live upload
    python3 publish_to_zendesk.py --docs-dir docs/md --section-id 12345

    # Pass credentials explicitly
    python3 publish_to_zendesk.py \\
        --subdomain mycompany \\
        --email admin@example.com \\
        --token MY_API_TOKEN \\
        --docs-dir docs/md \\
        --section-id 12345

Dependencies: Python ≥ 3.9, ``requests`` (``pip install requests``)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    print("error: requests is required.  Install with: pip install requests", file=sys.stderr)
    sys.exit(1)

try:
    import markdown  # type: ignore[import]
    _HAS_MARKDOWN = True
except ImportError:
    _HAS_MARKDOWN = False


# ---------------------------------------------------------------------------
# Markdown → HTML conversion
# ---------------------------------------------------------------------------

def _md_to_html(text: str) -> str:
    """Convert Markdown to HTML for the Zendesk API body."""
    if _HAS_MARKDOWN:
        import markdown as md_lib
        return md_lib.markdown(text, extensions=["tables", "fenced_code"])
    # Minimal fallback: wrap in <pre> so content is readable even without
    # the markdown package installed.
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"<pre>{escaped}</pre>"


# ---------------------------------------------------------------------------
# Zendesk API client
# ---------------------------------------------------------------------------

class ZendeskClient:
    """Thin wrapper around the Zendesk Help Center REST API."""

    def __init__(self, subdomain: str, email: str, token: str) -> None:
        self._base = f"https://{subdomain}.zendesk.com/api/v2/help_center"
        self._auth = (f"{email}/token", token)
        self._session = requests.Session()
        self._session.auth = self._auth
        self._session.headers.update({"Content-Type": "application/json"})

    # ------------------------------------------------------------------
    def list_articles(self, section_id: int) -> list[dict]:
        """Return all articles in *section_id*."""
        url = f"{self._base}/sections/{section_id}/articles.json"
        articles: list[dict] = []
        while url:
            resp = self._session.get(url)
            resp.raise_for_status()
            data = resp.json()
            articles.extend(data.get("articles", []))
            url = data.get("next_page")
        return articles

    def create_article(
        self,
        section_id: int,
        title: str,
        body_html: str,
        *,
        locale: str = "en-us",
    ) -> dict:
        """Create a new article and return the API response."""
        url = f"{self._base}/sections/{section_id}/articles.json"
        payload = {
            "article": {
                "title": title,
                "body": body_html,
                "locale": locale,
                "draft": False,
            }
        }
        resp = self._session.post(url, json=payload)
        resp.raise_for_status()
        return resp.json().get("article", {})

    def update_article(self, article_id: int, title: str, body_html: str) -> dict:
        """Update an existing article body."""
        url = f"{self._base}/articles/{article_id}/translations/en-us.json"
        payload = {"translation": {"title": title, "body": body_html}}
        resp = self._session.put(url, json=payload)
        resp.raise_for_status()
        return resp.json().get("translation", {})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_title(content: str) -> str:
    """Return the first H1 heading from Markdown content, or 'Untitled'."""
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "Untitled"


def _collect_pages(docs_dir: Path) -> list[tuple[str, str, Path]]:
    """Recursively collect Markdown files.

    Returns a list of *(title, html_body, file_path)* tuples.
    """
    pages: list[tuple[str, str, Path]] = []
    for md_file in sorted(docs_dir.rglob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        title = _extract_title(content)
        html_body = _md_to_html(content)
        pages.append((title, html_body, md_file))
    return pages


# ---------------------------------------------------------------------------
# Publish logic
# ---------------------------------------------------------------------------

def publish(
    docs_dir: Path,
    section_id: int,
    client: ZendeskClient,
    *,
    dry_run: bool = False,
) -> None:
    """Upload all Markdown pages in *docs_dir* to the given Zendesk section."""
    pages = _collect_pages(docs_dir)
    if not pages:
        print(f"warning: no Markdown files found in {docs_dir}", file=sys.stderr)
        return

    if dry_run:
        print(f"[dry-run] Would publish {len(pages)} article(s) to section {section_id}:")
        for title, _, path in pages:
            print(f"  • {title}  ({path})")
        return

    # Fetch existing articles to detect create-vs-update
    print(f"Fetching existing articles from section {section_id}…")
    existing = {a["title"]: a["id"] for a in client.list_articles(section_id)}

    created = updated = 0
    for title, html_body, path in pages:
        if title in existing:
            article_id = existing[title]
            client.update_article(article_id, title, html_body)
            print(f"  updated [{article_id}]: {title}")
            updated += 1
        else:
            article = client.create_article(section_id, title, html_body)
            article_id = article.get("id", "?")
            print(f"  created [{article_id}]: {title}")
            created += 1

    print(f"\nDone — {created} created, {updated} updated.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Publish Markdown documentation to a Zendesk Help Center section."
    )
    parser.add_argument(
        "--subdomain",
        default=os.environ.get("ZENDESK_SUBDOMAIN", ""),
        help="Zendesk subdomain (env: ZENDESK_SUBDOMAIN)",
    )
    parser.add_argument(
        "--email",
        default=os.environ.get("ZENDESK_EMAIL", ""),
        help="Zendesk agent email (env: ZENDESK_EMAIL)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("ZENDESK_API_TOKEN", ""),
        help="Zendesk API token (env: ZENDESK_API_TOKEN)",
    )
    parser.add_argument(
        "--docs-dir",
        metavar="DIR",
        default="docs/md",
        help="Directory containing generated Markdown files (default: docs/md)",
    )
    parser.add_argument(
        "--section-id",
        metavar="ID",
        type=int,
        required=True,
        help="Zendesk Help Center section ID to publish into",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be uploaded without making API calls",
    )
    args = parser.parse_args(argv)

    docs_dir = Path(args.docs_dir)
    if not docs_dir.exists():
        print(f"error: docs directory not found: {docs_dir}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        # Credentials not required for a dry-run
        client = None  # type: ignore[assignment]
    else:
        missing = [
            f for f, v in [
                ("--subdomain / ZENDESK_SUBDOMAIN", args.subdomain),
                ("--email / ZENDESK_EMAIL", args.email),
                ("--token / ZENDESK_API_TOKEN", args.token),
            ]
            if not v
        ]
        if missing:
            for m in missing:
                print(f"error: missing required credential: {m}", file=sys.stderr)
            sys.exit(1)
        client = ZendeskClient(args.subdomain, args.email, args.token)

    publish(docs_dir, args.section_id, client, dry_run=args.dry_run)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
