"""Build small FICTIONAL sample manuals (PDF, DOCX, MD) for tests. No third-party libraries."""
from __future__ import annotations

import zipfile
from pathlib import Path

TITLE = "Sample Airline Safety Management Manual (FICTIONAL)"

# (heading, paragraphs) — numbering mimics a real manual so heading detection is exercised.
SECTIONS = [
    ("Chapter 1 Introduction", [
        "This fictional manual exists only to test the knowledge base tooling.",
        "It describes a made-up safety management system for a made-up airline.",
    ]),
    ("1.1 Purpose", ["The purpose of this manual is to demonstrate section splitting and page citations."]),
    ("Chapter 2 Safety Policy", [
        "Management commits to a just culture and to the reporting of hazards without fear of reprisal.",
        "Accountable Manager signs the safety policy once per year.",
    ]),
    ("Chapter 3 Hazard Identification", [
        "Hazards are identified through voluntary reports, flight data monitoring and audits.",
    ]),
    ("3.1 Reporting", [
        "Every employee shall submit a safety report within 24 hours of an event.",
        "Reports are acknowledged by the Safety Office within 2 working days.",
    ]),
    ("3.2 Risk assessment", [
        "Each hazard is assessed using the company risk matrix with severity A to E and likelihood 1 to 5.",
        "A risk index of 5A is intolerable and requires immediate action by the Accountable Manager.",
        "Residual risk is reviewed after mitigation by the Safety Review Board.",
    ]),
    ("Chapter 4 Safety Assurance", [
        "Safety performance indicators are reviewed monthly by the Safety Review Board.",
        "Unstable approach rate per 1000 flights is a lead indicator in this fictional programme.",
    ]),
    ("4.1 Management of change", ["Any change to fleet, routes or procedures requires a safety assessment before implementation."]),
]


def sections_text() -> str:
    out = [f"# {TITLE}", ""]
    for head, paras in SECTIONS:
        lvl = 1 if head.startswith("Chapter") else 2
        out += [f"{'#' * lvl} {head}", ""] + [p + "\n" for p in paras]
    return "\n".join(out)


def make_md(path: Path) -> Path:
    path.write_text(sections_text(), encoding="utf-8")
    return path


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(path: Path, pages_per_section: int = 1) -> Path:
    """One or more pages per section, each with a running header and footer to be stripped."""
    pages: list[list[str]] = []
    for head, paras in SECTIONS:
        for k in range(pages_per_section):
            lines = [head] if k == 0 else []
            for p in paras:
                lines += [p[i:i + 85] for i in range(0, len(p), 85)] + [""]
            pages.append(lines)
    total = len(pages)
    objs: list[bytes] = []

    def add(b: bytes) -> int:
        objs.append(b)
        return len(objs)

    add(b"<< /Type /Catalog /Pages 2 0 R >>")
    add(b"")  # placeholder for Pages
    font = 3
    add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids = []
    for n, lines in enumerate(pages, 1):
        body = ["BT /F1 10 Tf 40 800 Td 12 TL", f"({_esc('Sample Airline Fictional SMS Manual  Rev 2')}) Tj T*", "T* T*"]
        body += [f"({_esc(l)}) Tj T*" for l in lines]
        body += ["ET", f"BT /F1 9 Tf 40 30 Td ({_esc(f'Page {n} of {total}')}) Tj ET"]
        stream = "\n".join(body).encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page = add(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {content} 0 R "
                   f"/Resources << /Font << /F1 {font} 0 R >> >> >>".encode())
        kids.append(f"{page} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return path


def make_docx(path: Path) -> Path:
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def p(text: str, style: str | None = None) -> str:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"

    body = [p(TITLE, "Title")]
    for head, paras in SECTIONS:
        body.append(p(head, "Heading1" if head.startswith("Chapter") else "Heading2"))
        body += [p(x) for x in paras]
    rows = [("Severity", "Meaning"), ("A", "Catastrophic"), ("B", "Hazardous")]
    tbl = "<w:tbl>" + "".join(
        "<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in r) + "</w:tr>" for r in rows
    ) + "</w:tbl>"
    body.append(tbl)
    document = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W}"><w:body>{"".join(body)}</w:body></w:document>'
    styles = (f'<?xml version="1.0" encoding="UTF-8"?><w:styles xmlns:w="{W}">'
              '<w:style w:styleId="Title"><w:name w:val="Title"/></w:style>'
              '<w:style w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
              '<w:style w:styleId="Heading2"><w:name w:val="heading 2"/></w:style></w:styles>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles)
    return path
