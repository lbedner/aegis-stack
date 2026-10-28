"""Where the chunker cuts, by language: each list the separators tried in
order, the coarsest first (a function or a header before a paragraph, a
paragraph before a line, down to single characters)."""

# Base separators for general text (in order of preference)
BASE_SEPARATORS = [
    "\n\n\n",  # Triple newline (major sections)
    "\n\n",  # Double newline (paragraphs)
    "\n",  # Single newline
    ". ",  # Sentence end
    "? ",  # Question end
    "! ",  # Exclamation end
    "; ",  # Semicolon
    ", ",  # Clause
    " ",  # Word
    "",  # Character (last resort)
]

# Python-specific separators (split on function/class boundaries first)
PYTHON_SEPARATORS = [
    "\n\nclass ",  # Class definitions (double newline)
    "\n\nasync def ",  # Async functions (double newline)
    "\n\ndef ",  # Functions (double newline)
    "\nclass ",  # Class (single newline)
    "\nasync def ",  # Async function (single newline)
    "\ndef ",  # Function (single newline)
    "\n\n",  # Double newline (paragraphs/blocks)
    "\n",  # Single newline
    ". ",  # Sentence
    " ",  # Word
    "",  # Character
]

# JavaScript/TypeScript separators
JS_SEPARATORS = [
    "\n\nexport class ",
    "\n\nexport function ",
    "\n\nexport async function ",
    "\n\nexport const ",
    "\n\nclass ",
    "\n\nfunction ",
    "\n\nasync function ",
    "\n\nconst ",
    "\nexport class ",
    "\nexport function ",
    "\nexport const ",
    "\nclass ",
    "\nfunction ",
    "\nconst ",
    "\n\n",
    "\n",
    " ",
    "",
]

# Markdown separators (split on headers)
MARKDOWN_SEPARATORS = [
    "\n## ",  # H2 headers
    "\n### ",  # H3 headers
    "\n#### ",  # H4 headers
    "\n# ",  # H1 headers
    "\n\n",  # Paragraphs
    "\n",  # Lines
    ". ",  # Sentences
    " ",  # Words
    "",  # Characters
]

# YAML/TOML separators (split on top-level keys)
CONFIG_SEPARATORS = [
    "\n\n",  # Double newline (major sections)
    "\n",  # Single newline
    " ",  # Word
    "",  # Character
]

# Language to separator mapping
LANGUAGE_SEPARATORS: dict[str, list[str]] = {
    "python": PYTHON_SEPARATORS,
    "javascript": JS_SEPARATORS,
    "typescript": JS_SEPARATORS,
    "markdown": MARKDOWN_SEPARATORS,
    "yaml": CONFIG_SEPARATORS,
    "toml": CONFIG_SEPARATORS,
    "json": CONFIG_SEPARATORS,
}
