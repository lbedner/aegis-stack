"""Hand-built PDFs for tests: one page per entry, blank where the text is empty.

Generated rather than checked in, so the suite carries no binary fixtures
and a "scan" (a page with no text layer) is just an empty string.
"""


def pdf_bytes(texts: list[str]) -> bytes:
    pages = [(3 + 2 * i, 4 + 2 * i) for i in range(len(texts))]
    font = 3 + 2 * len(texts)
    body = b"%PDF-1.4\n"
    offsets: list[int] = []

    def add(obj: bytes) -> None:
        nonlocal body
        offsets.append(len(body))
        body += obj

    kids = " ".join(f"{p} 0 R" for p, _ in pages)
    add(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
    add(
        f"2 0 obj << /Type /Pages /Kids [{kids}] /Count {len(pages)} >> endobj\n".encode()
    )
    for (page, content), text in zip(pages, texts, strict=True):
        stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode() if text else b""
        add(
            f"{page} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content} 0 R /Resources << /Font << /F1 {font} 0 R >> >> >> "
            "endobj\n".encode()
        )
        add(
            f"{content} 0 obj << /Length {len(stream)} >> stream\n".encode()
            + stream
            + b"\nendstream endobj\n"
        )
    add(
        f"{font} 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n".encode()
    )
    xref = len(body)
    body += f"xref\n0 {font + 1}\n0000000000 65535 f \n".encode()
    body += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    body += (
        f"trailer << /Size {font + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return body
