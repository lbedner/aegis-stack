# scripts/gen_docs.py
"""
A script to dynamically generate documentation files for MkDocs.
This is run automatically by the mkdocs-gen-files plugin.
"""

import mkdocs_gen_files  # noqa: F401

print("--- Running gen_docs.py ---")

# Copy the root README.md to be the documentation's index page.
# This allows us to maintain a single source of truth for the project's
# main landing page, which is visible on both GitHub and the docs site.
# We need to convert GitHub-style relative links to MkDocs-compatible links.
with open("README.md") as readme:
    content = readme.read()

    # Convert GitHub-style relative links to MkDocs-compatible links
    content = content.replace("docs/images/dashboard.png", "images/dashboard.png")
    content = content.replace("docs/index.md", "index.md")
    content = content.replace("docs/components/index.md", "components/index.md")
    content = content.replace("docs/cli-reference.md", "cli-reference.md")
    content = content.replace(
        "docs/guides/project-creation.md", "guides/project-creation.md"
    )
    content = content.replace("docs/philosophy.md", "philosophy.md")

    # Only write if content has changed to avoid infinite rebuild loops
    try:
        with open("docs/index.md") as existing:
            existing_content = existing.read()
            if existing_content == content:
                print("✓ docs/index.md is already up to date")
                exit()
    except FileNotFoundError:
        pass  # File doesn't exist yet, we'll create it

    with open("docs/index.md", "w") as index:
        index.write(content)
        print("✓ Copied README.md to docs/index.md with MkDocs-compatible links")
