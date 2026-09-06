# scripts/gen_docs.py
"""
A script to dynamically generate documentation files for MkDocs.
This is run automatically by the mkdocs-gen-files plugin.
"""

import re

import mkdocs_gen_files

print("--- Running gen_docs.py ---")

# Special-case image rewrites that need more than a path fix. Plain
# ``![...](docs/images/...)`` references are handled generically below —
# new README images need no entry here.
IMAGE_PATH_MAPPINGS = {
    # Dashboard - single dark image -> dual light/dark
    "![System Health Dashboard](docs/images/dashboard-dark.png)": (
        "![System Health Dashboard](images/dashboard-light.png#only-light)\n"
        "![System Health Dashboard](images/dashboard-dark.png#only-dark)"
    ),
}

# Copy the root README.md to be the documentation's index page.
# This allows us to maintain a single source of truth for the project's
# main landing page, which is visible on both GitHub and the docs site.
with open("README.md") as readme:
    content = readme.read()

    # Apply the special-case image rewrites first (their keys still carry
    # the ``docs/`` prefix), then strip the prefix from every remaining
    # markdown image: GitHub renders README images from ``docs/images/...``
    # but the docs root has no ``docs/`` segment.
    for github_path, mkdocs_path in IMAGE_PATH_MAPPINGS.items():
        content = content.replace(github_path, mkdocs_path)
    content = content.replace("](docs/images/", "](images/")
    # Strip the ``docs/`` prefix from any ``<img src="docs/images/...">`` so
    # MkDocs serves them from ``images/...`` (the docs root has no ``docs/``
    # segment, but GitHub's renderer needs the prefix). Catches the hero SVG
    # plus every ``<img>``-wrapped GIF in the README.
    # The README uses <picture> + prefers-color-scheme for theme-aware
    # logos because that is the only form GitHub.com honors. MkDocs
    # Material has its own light/dark toggle that is independent of the
    # OS preference, so <picture> renders the wrong asset whenever the
    # docs theme and OS disagree. Rewrite each <picture> block into the
    # dual-<img> ``#only-light`` / ``#only-dark`` form that Material's
    # theme toggle drives.
    content = re.sub(
        r'<picture><source media="\(prefers-color-scheme: dark\)" srcset="([^"]+)"><img src="([^"]+)"([^/]*)/></picture>',
        r'<img src="\2#only-light"\3/><img src="\1#only-dark"\3/>',
        content,
    )

    content = re.sub(
        r'src="docs/images/([^"]+)"',
        r'src="images/\1"',
        content,
    )

    # Fix links to documentation pages (remove 'docs/' prefix)
    # Use regex to catch all docs/*.md links instead of manually listing each one
    content = re.sub(r"\]\(docs/([^)]+\.md)\)", r"](\1)", content)

    # Convert absolute docs URLs to relative for MkDocs (works locally and deployed)
    content = content.replace("https://docs.aegis-stack.io/", "")

    # Fix trailing slash links to explicit file references for MkDocs
    # Check if it's a directory (has index.md) or a top-level page
    from pathlib import Path

    docs_dir = Path("docs")

    def fix_trailing_slash(match: re.Match[str]) -> str:
        path = match.group(1).rstrip("/")
        # Optional ``#anchor`` fragment that followed the trailing slash; preserve
        # it so mkdocs links to the right heading after we rewrite to index.md.
        anchor = match.group(2) or ""
        check_path = docs_dir / path / "index.md"
        # Check if it's a directory with index.md
        if check_path.exists():
            return f"]({path}/index.md{anchor})"
        # No folder with an index: it is a top-level page.
        return f"]({path}.md{anchor})"

    content = re.sub(
        r"\]\(([a-z][a-z0-9-/]*)/(#[^)]*)?\)",
        fix_trailing_slash,
        content,
    )

    # Use mkdocs_gen_files to create a virtual file instead of writing directly
    # This prevents triggering file change detection loops
    with mkdocs_gen_files.open("index.md", "w") as index:
        index.write(content)
        print("✓ Generated virtual index.md from README.md with fixed paths")
