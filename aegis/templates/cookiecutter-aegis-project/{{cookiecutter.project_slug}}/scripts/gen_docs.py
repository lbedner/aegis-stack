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
with open("README.md") as readme, open("docs/index.md", "w") as index:
    index.write(readme.read())
    print("✓ Copied README.md to docs/index.md")
