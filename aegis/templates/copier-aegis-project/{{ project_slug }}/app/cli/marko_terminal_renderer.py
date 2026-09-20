"""
Custom terminal renderer for marko markdown parser.

Renders markdown elements as ANSI-styled strings for beautiful terminal output.
Integrates with Rich Console for output management while keeping rendering simple.
"""

from marko.renderer import Renderer

from app.cli.marko_table_renderer import TableRenderMixin


class TerminalRenderer(TableRenderMixin, Renderer):
    """
    Terminal renderer that outputs ANSI-styled strings.

    Renders markdown elements with ANSI escape codes for colored,
    styled terminal output. Works with Rich Console for output but
    doesn't depend on Rich components.
    """

    def _get_content(self, element) -> str:
        """
        Safely get content from element, handling both string and list children.

        Args:
            element: Element with children attribute

        Returns:
            String content
        """
        # If children is already a string, return it
        if isinstance(element.children, str):
            return element.children
        # Otherwise render children as normal
        return self.render_children(element)

    def render_document(self, element) -> str:
        """Render the root document element."""
        return self.render_children(element)

    def render_heading(self, element) -> str:
        """
        Render heading with ANSI color codes based on level.

        Args:
            element: Heading element with level attribute

        Returns:
            ANSI-styled heading string
        """
        # Extract heading level (h1=1, h2=2, h3=3, etc.)
        level = int(element.level)

        # Render children to get heading text
        content = self.render_children(element)

        # Color codes by level
        colors = {
            1: "\033[1;32m",  # Bold green
            2: "\033[1;36m",  # Bold cyan
            3: "\033[1;34m",  # Bold blue
        }
        reset = "\033[0m"

        # Get color for this level (default to bold white)
        color = colors.get(level, "\033[1;37m")

        # Clean title rendering (no ### prefix)
        return f"{color}{content}{reset}\n"

    def render_fenced_code(self, element) -> str:
        """
        Render fenced code block with syntax highlighting.

        Args:
            element: Fenced code element with lang and children

        Returns:
            Code block with syntax highlighting (no background)
        """
        # Get code content from children (safely handles string or list)
        code = self._get_content(element)
        lang = getattr(element, "lang", "") or "text"

        if not code or not code.strip():
            return ""

        # Try to use pygments for syntax highlighting if available
        try:
            from pygments import highlight
            from pygments.formatters import Terminal256Formatter
            from pygments.lexers import get_lexer_by_name
            from pygments.util import ClassNotFound

            try:
                lexer = get_lexer_by_name(lang, stripall=True)
                formatter = Terminal256Formatter(style="ir-black")
                highlighted = highlight(code, lexer, formatter)

                # Process each line: add indentation only
                lines = highlighted.rstrip("\n").split("\n")
                formatted_lines = []
                for line in lines:
                    # Add 4-space indentation
                    formatted_lines.append(f"    {line}")

                result = "\n".join(formatted_lines)
                # Add blank lines before/after
                return f"\n{result}\n\n"

            except ClassNotFound:
                # Lexer not found, fall back to plain display
                pass

        except ImportError:
            # Pygments not available, use plain display
            pass

        # Fallback: plain code with indentation
        lines = code.strip().split("\n")
        formatted_lines = []
        for line in lines:
            formatted_lines.append(f"    {line}")

        result = "\n".join(formatted_lines)
        return f"\n{result}\n\n"

    def render_code_block(self, element) -> str:
        """Render indented code block with simple indentation."""
        code = self._get_content(element)

        if not code or not code.strip():
            return ""

        # Simple indented code (no background)
        lines = code.strip().split("\n")
        formatted_lines = []
        for line in lines:
            formatted_lines.append(f"    {line}")

        result = "\n".join(formatted_lines)
        return f"\n{result}\n\n"

    def render_list(self, element) -> str:
        """Render bullet or ordered list."""
        return self.render_children(element)

    def render_list_item(self, element) -> str:
        """
        Render list item with styled bullet.

        Args:
            element: List item element

        Returns:
            Styled list item string
        """
        content = self.render_children(element).strip()

        # Yellow bullet with proper indentation
        bullet_color = "\033[93m"  # Bright yellow
        reset = "\033[0m"

        return f"  {bullet_color}•{reset} {content}\n"

    def render_paragraph(self, element) -> str:
        """
        Render paragraph as plain text.

        Args:
            element: Paragraph element

        Returns:
            Paragraph text with newline
        """
        content = self.render_children(element)
        return f"{content}\n"

    def render_blank_line(self, element) -> str:
        """
        Render blank line.

        Args:
            element: Blank line element

        Returns:
            Single newline
        """
        return "\n"

    def render_emphasis(self, element) -> str:
        """
        Render italic text with ANSI codes.

        Args:
            element: Emphasis element

        Returns:
            Italic styled string
        """
        content = self.render_children(element)
        return f"\033[3m{content}\033[0m"  # Italic

    def render_strong_emphasis(self, element) -> str:
        """
        Render bold text with ANSI codes.

        Args:
            element: Strong emphasis element

        Returns:
            Bold styled string
        """
        content = self.render_children(element)
        return f"\033[1m{content}\033[0m"  # Bold

    def render_code_span(self, element) -> str:
        """
        Render inline code with background color.

        Args:
            element: Inline code element

        Returns:
            Styled inline code string
        """
        content = self._get_content(element)
        # Bright magenta on black background
        return f"\033[95;40m{content}\033[0m"

    def render_raw_text(self, element) -> str:
        """
        Render raw text content.

        Args:
            element: Raw text element

        Returns:
            Plain text string
        """
        # RawText.children is already a string, not a list
        # Just return it directly
        if isinstance(element.children, str):
            return element.children
        # Fallback for safety
        return str(element.children)

    def render_line_break(self, element) -> str:
        """Render line break."""
        return "\n"

    def render_link(self, element) -> str:
        """
        Render hyperlink.

        Args:
            element: Link element

        Returns:
            Link text (URLs hidden in terminal)
        """
        content = self.render_children(element)
        # Just show the link text, not the URL (terminal limitation)
        return content

    def render_image(self, element) -> str:
        """
        Render image placeholder.

        Args:
            element: Image element

        Returns:
            Image placeholder text
        """
        title = getattr(element, "title", "") or "image"
        return f"[Image: {title}]"

    def render_thematic_break(self, element) -> str:
        """Render horizontal rule."""
        return f"\033[2m{'─' * 60}\033[0m\n"

    def render_block_quote(self, element) -> str:
        """
        Render block quote with left border.

        Args:
            element: Block quote element

        Returns:
            Quoted text with border
        """
        content = self.render_children(element)
        lines = content.strip().split("\n")

        border = "\033[36m│\033[0m"  # Cyan border
        result = []
        for line in lines:
            result.append(f"{border} {line}")

        return "\n".join(result) + "\n"

    def render_strikethrough(self, element) -> str:
        """
        Render strikethrough text (~~text~~) with dim styling.

        Args:
            element: Strikethrough element from GFM extension

        Returns:
            Dimmed/faint text string
        """
        content = self._get_content(element)
        return f"\033[2m{content}\033[0m"  # Dim/faint text

    def render_url(self, element) -> str:
        """
        Render autolinked URLs.

        Args:
            element: URL element from GFM extension

        Returns:
            Cyan-colored URL string
        """
        url = element.dest if hasattr(element, "dest") else str(element.children)
        return f"\033[36m{url}\033[0m"  # Cyan color

    def render_inline_html(self, element) -> str:
        """
        Render inline HTML elements.

        Required for GFM extension compatibility - the @render_dispatch decorator
        needs a fallback method in the MRO when the renderer is not HTMLRenderer.

        Args:
            element: InlineHTML element

        Returns:
            The HTML content as plain text (dimmed)
        """
        content = element.children if isinstance(element.children, str) else ""
        return f"\033[2m{content}\033[0m"  # Dim style for HTML

    def render_html_block(self, element) -> str:
        """
        Render HTML block elements.

        Required for GFM extension compatibility - the @render_dispatch decorator
        needs a fallback method in the MRO when the renderer is not HTMLRenderer.

        Args:
            element: HTMLBlock element

        Returns:
            The HTML content as plain text (dimmed)
        """
        content = getattr(element, "body", "") or getattr(element, "children", "")
        if not isinstance(content, str):
            content = str(content)
        return f"\033[2m{content}\033[0m\n"  # Dim style for HTML blocks

    def __getattr__(self, name: str):
        """
        Fallback for any missing render methods.

        Prevents crashes from unknown GFM elements by providing a generic
        renderer that outputs plain text. This ensures compatibility with
        future GFM extensions or elements we haven't explicitly handled.

        Args:
            name: Attribute name being accessed

        Returns:
            Fallback render function for render_* methods

        Raises:
            AttributeError: If attribute is not a render method
        """
        if name.startswith("render_"):

            def fallback_render(element):
                """Generic fallback - renders as plain text."""
                if hasattr(element, "children"):
                    if isinstance(element.children, str):
                        return element.children
                    return self.render_children(element)
                return str(element)

            return fallback_render
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )
