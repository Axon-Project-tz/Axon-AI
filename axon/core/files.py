"""
files.py — File parsing for Axon.
Handles reading and extracting text from PDF, docx, txt,
and code files for AI consumption.
"""

import os

MAX_CHARS = 50_000

# Extensions handled as plain text
TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".log", ".rst", ".tex",
    # Code
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss", ".less",
    ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".go", ".rs", ".rb", ".php",
    ".swift", ".kt", ".lua", ".r", ".m", ".sh", ".bash", ".bat", ".ps1",
    ".sql", ".graphql", ".proto", ".makefile", ".dockerfile",
}


def extract_text(file_path):
    """Extract text from a file. Returns (text, truncated) tuple."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        text = _parse_pdf(file_path)
    elif ext == ".docx":
        text = _parse_docx(file_path)
    elif ext in TEXT_EXTENSIONS or ext == "":
        text = _parse_text(file_path)
    else:
        # Try reading as text anyway
        text = _parse_text(file_path)

    truncated = len(text) > MAX_CHARS
    if truncated:
        text = text[:MAX_CHARS]

    return text, truncated


def _parse_pdf(file_path):
    """Extract text from a PDF file using PyMuPDF."""
    import fitz
    doc = fitz.open(file_path)
    pages = []
    for page in doc:
        pages.append(page.get_text())
    doc.close()
    return "\n".join(pages)


def _parse_docx(file_path):
    """Extract text from a Word document using python-docx."""
    from docx import Document
    doc = Document(file_path)
    return "\n".join(p.text for p in doc.paragraphs)


def _parse_text(file_path):
    """Read a plain text or code file."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()
