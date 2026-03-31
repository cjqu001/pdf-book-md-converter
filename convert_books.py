#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import fitz  # PyMuPDF
    import pdfplumber
    import pandas as pd
    from PIL import Image
    import pytesseract
except ImportError:
    fitz = None
    pdfplumber = None
    pd = None
    Image = None
    pytesseract = None


LOW_TEXT_THRESHOLD = 80
OCR_DPI = 250
FRONT_SCAN_PAGES = 10
DEFAULT_LANG = "eng"


@dataclass
class BookManifest:
    book_id: str
    title: str
    author: str
    isbn: str
    source_pdf: str
    markdown_file: str
    manifest_file: str
    page_count: int
    ocr_pages: int
    tables_extracted: int
    figures_extracted: int
    captions_extracted: int


def ensure_imports() -> None:
    global fitz, pdfplumber, pd, Image, pytesseract
    if fitz is None:
        import fitz as _fitz
        fitz = _fitz
    if pdfplumber is None:
        import pdfplumber as _pdfplumber
        pdfplumber = _pdfplumber
    if pd is None:
        import pandas as _pd
        pd = _pd
    if Image is None:
        from PIL import Image as _Image
        Image = _Image
    if pytesseract is None:
        import pytesseract as _pytesseract
        pytesseract = _pytesseract


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\x00", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def slugify(text: str, max_len: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "_", text)
    text = text.strip("_")
    return text[:max_len] if text else "untitled"


def text_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()[:10]


def is_page_number_line(line: str) -> bool:
    line = line.strip()
    return bool(
        re.fullmatch(r"\d{1,4}", line)
        or re.fullmatch(r"page\s+\d{1,4}", line, flags=re.I)
        or re.fullmatch(r"\[\d{1,4}\]", line)
    )


def normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", clean_text(line)).strip()


def extract_isbn_candidates(text: str) -> List[str]:
    text = text.replace("–", "-").replace("—", "-")
    found = set()

    labeled = re.findall(r"ISBN(?:-1[03])?:?\s*([0-9Xx\-\s]{10,24})", text, flags=re.I)
    generic = re.findall(r"\b(?:97[89][\-\s]?)?[0-9][0-9Xx\-\s]{8,22}[0-9Xx]\b", text)

    for raw in labeled + generic:
        digits = re.sub(r"[^0-9Xx]", "", raw).upper()
        if len(digits) in (10, 13):
            found.add(digits)

    return sorted(found)


def get_pdf_metadata(doc) -> Dict[str, str]:
    meta = doc.metadata or {}
    return {
        "title": clean_text(meta.get("title", "") or ""),
        "author": clean_text(meta.get("author", "") or ""),
        "subject": clean_text(meta.get("subject", "") or ""),
        "keywords": clean_text(meta.get("keywords", "") or ""),
    }


def render_page_to_pil(page, dpi: int = OCR_DPI):
    scale = dpi / 72.0
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    mode = "RGB" if pix.n < 5 else "CMYK"
    img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
    if mode == "CMYK":
        img = img.convert("RGB")
    return img


def ocr_page_text(page, lang: str = DEFAULT_LANG) -> str:
    try:
        img = render_page_to_pil(page)
        text = pytesseract.image_to_string(img, lang=lang)
        return clean_text(text)
    except Exception:
        return ""


def get_page_text(page, allow_ocr: bool = True, lang: str = DEFAULT_LANG) -> Tuple[str, bool]:
    native = clean_text(page.get_text("text") or "")
    if len(native) >= LOW_TEXT_THRESHOLD or not allow_ocr:
        return native, False
    ocr_text = ocr_page_text(page, lang=lang)
    if len(ocr_text) > len(native):
        return ocr_text, True
    return native, False


def collect_front_text(doc, lang: str = DEFAULT_LANG, max_pages: int = FRONT_SCAN_PAGES) -> str:
    chunks = []
    for i in range(min(len(doc), max_pages)):
        page = doc[i]
        txt, _ = get_page_text(page, allow_ocr=True, lang=lang)
        if txt:
            chunks.append(txt)
    return clean_text("\n".join(chunks))


def guess_title_author_from_frontmatter(text: str) -> Tuple[Optional[str], Optional[str]]:
    lines = [normalize_line(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    bad_patterns = [
        r"copyright",
        r"all rights reserved",
        r"library of congress",
        r"isbn",
        r"publisher",
        r"table of contents",
        r"contents",
        r"printed in",
        r"edition",
        r"www\.",
        r"chapter \d+",
    ]

    kept = []
    for line in lines[:120]:
        low = line.lower()
        if is_page_number_line(line):
            continue
        if len(line) < 3:
            continue
        if any(re.search(p, low) for p in bad_patterns):
            continue
        kept.append(line)

    title = None
    author = None

    for i, line in enumerate(kept[:25]):
        if 4 <= len(line) <= 220:
            letters = re.sub(r"[^A-Za-z]", "", line)
            if letters and not line.islower():
                title = line
                for j in range(i + 1, min(i + 6, len(kept))):
                    nxt = kept[j]
                    if re.match(r"^(by|author[s]?:?)\s+", nxt, flags=re.I):
                        author = re.sub(r"^(by|author[s]?:?)\s+", "", nxt, flags=re.I).strip()
                        break
                break

    if not author:
        m = re.search(r"\bby\s+([A-Z][A-Za-z\.\-']+(?:\s+[A-Z][A-Za-z\.\-']+){0,5})", text)
        if m:
            author = m.group(1).strip()

    return title, author


def choose_best_metadata(pdf_path: Path, doc, lang: str = DEFAULT_LANG) -> Dict[str, str]:
    meta = get_pdf_metadata(doc)
    front = collect_front_text(doc, lang=lang, max_pages=FRONT_SCAN_PAGES)
    title_guess, author_guess = guess_title_author_from_frontmatter(front)
    isbns = extract_isbn_candidates(front)

    title = meta["title"] or title_guess or pdf_path.stem
    author = meta["author"] or author_guess or "unknown_author"
    isbn = isbns[0] if isbns else ""

    return {
        "title": title.strip()[:220],
        "author": author.strip()[:160],
        "isbn": isbn,
        "front_hash": text_hash(front[:8000]),
    }


def make_book_id(title: str, author: str, isbn: str, fallback: str) -> str:
    if isbn:
        return f"isbn_{isbn}"
    core = f"{slugify(author, 40)}__{slugify(title, 60)}".strip("_")
    return core if core else slugify(fallback, 80)


def remove_running_headers_footers(page_texts: List[str]) -> List[str]:
    firsts = Counter()
    lasts = Counter()
    split_pages = []

    for text in page_texts:
        lines = [normalize_line(x) for x in text.splitlines()]
        lines = [x for x in lines if x]
        split_pages.append(lines)
        if lines:
            firsts[lines[0]] += 1
            lasts[lines[-1]] += 1

    common_firsts = {k for k, v in firsts.items() if v >= max(3, len(page_texts) // 5) and len(k) < 120}
    common_lasts = {k for k, v in lasts.items() if v >= max(3, len(page_texts) // 5) and len(k) < 120}

    cleaned = []
    for lines in split_pages:
        if lines and (lines[0] in common_firsts or is_page_number_line(lines[0])):
            lines = lines[1:]
        if lines and (lines[-1] in common_lasts or is_page_number_line(lines[-1])):
            lines = lines[:-1]
        cleaned.append("\n".join(lines).strip())

    return cleaned


def simple_markdown_from_text(text: str) -> str:
    text = clean_text(text)
    lines = text.splitlines()
    out = []

    for line in lines:
        s = line.strip()
        if not s:
            out.append("")
            continue
        if is_page_number_line(s):
            continue
        if len(s) <= 120 and s.isupper() and len(s.split()) <= 14:
            out.append(f"## {s.title()}")
            continue
        if re.match(r"^(chapter|part|appendix)\b", s, flags=re.I):
            out.append(f"## {s}")
            continue
        if re.match(r"^\d+(\.\d+)*\s+\S+", s):
            out.append(f"### {s}")
            continue
        if re.match(r"^(figure|fig\.|table)\s+\d+", s, flags=re.I):
            out.append(f"**{s}**")
            continue
        out.append(s)

    md = "\n".join(out)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"


def extract_tables_from_page(pdf_path: Path, page_num_1: int, out_dir: Path) -> List[str]:
    files = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            idx = page_num_1 - 1
            if idx >= len(pdf.pages):
                return files
            page = pdf.pages[idx]
            tables = page.extract_tables() or []
            for i, table in enumerate(tables, 1):
                if not table:
                    continue
                out = out_dir / f"page_{page_num_1:04d}_table_{i:02d}.csv"
                with open(out, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    for row in table:
                        writer.writerow(row if row is not None else [])
                files.append(out.name)
    except Exception:
        pass
    return files


def extract_images_from_page(page, figs_dir: Path, page_num_1: int) -> List[str]:
    saved = []
    try:
        images = page.get_images(full=True)
        for i, img in enumerate(images, 1):
            xref = img[0]
            try:
                pix = fitz.Pixmap(page.parent, xref)
                if pix.n - pix.alpha > 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                out = figs_dir / f"page_{page_num_1:04d}_img_{i:02d}.png"
                pix.save(str(out))
                saved.append(out.name)
            except Exception:
                continue
    except Exception:
        pass
    return saved


def guess_captions_from_page_text(text: str) -> List[str]:
    lines = [normalize_line(x) for x in text.splitlines()]
    lines = [x for x in lines if x]
    caps = []
    for line in lines:
        if re.match(r"^(figure|fig\.|table)\s+\d+[:\.\-\s]", line, flags=re.I):
            caps.append(line)
        elif re.match(r"^(figure|fig\.)\s+\d+\b", line, flags=re.I):
            caps.append(line)
    return caps[:10]


def write_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def check_tesseract() -> None:
    try:
        pytesseract.get_tesseract_version()
    except Exception as e:
        raise RuntimeError(
            "Tesseract OCR is not installed or not on PATH. Install it on Windows first, "
            "then reopen your terminal. Common install path is "
            "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
        ) from e


def convert_book(pdf_path: Path, output_root: Path, lang: str = DEFAULT_LANG) -> BookManifest:
    ensure_imports()

    doc = fitz.open(str(pdf_path))
    meta = choose_best_metadata(pdf_path, doc, lang=lang)
    book_id = make_book_id(meta["title"], meta["author"], meta["isbn"], pdf_path.stem)

    book_dir = output_root / book_id
    assets = book_dir / "assets"
    tables_dir = assets / "tables"
    figs_dir = assets / "figures"

    book_dir.mkdir(parents=True, exist_ok=True)
    assets.mkdir(exist_ok=True)
    tables_dir.mkdir(exist_ok=True)
    figs_dir.mkdir(exist_ok=True)

    md_path = book_dir / f"{book_id}.md"
    manifest_path = book_dir / "manifest.json"

    page_texts_raw: List[str] = []
    page_ocr_flags: List[bool] = []
    page_tables_map: Dict[int, List[str]] = {}
    page_figs_map: Dict[int, List[str]] = {}
    page_caps_map: Dict[int, List[str]] = {}

    tables_total = 0
    figs_total = 0
    caps_total = 0

    for i in range(len(doc)):
        page = doc[i]
        page_num = i + 1

        text, used_ocr = get_page_text(page, allow_ocr=True, lang=lang)
        page_texts_raw.append(text)
        page_ocr_flags.append(used_ocr)

        table_files = extract_tables_from_page(pdf_path, page_num, tables_dir)
        page_tables_map[page_num] = table_files
        tables_total += len(table_files)

        fig_files = extract_images_from_page(page, figs_dir, page_num)
        page_figs_map[page_num] = fig_files
        figs_total += len(fig_files)

        caps = guess_captions_from_page_text(text)
        page_caps_map[page_num] = caps
        caps_total += len(caps)

    page_texts = remove_running_headers_footers(page_texts_raw)

    md = []
    md.append(f"# {meta['title']}\n")
    md.append(f"- Author: {meta['author']}")
    md.append(f"- ISBN: {meta['isbn'] or 'not_found'}")
    md.append(f"- Source PDF: {pdf_path.name}")
    md.append(f"- Pages: {len(doc)}")
    md.append(f"- OCR pages: {sum(page_ocr_flags)}")
    md.append("")

    for idx, page_text in enumerate(page_texts, start=1):
        md.append(f"## Page {idx}\n")

        tables = page_tables_map.get(idx, [])
        if tables:
            md.append("### Tables")
            for t in tables:
                md.append(f"- [assets/tables/{t}](assets/tables/{t})")
            md.append("")

        figs = page_figs_map.get(idx, [])
        caps = page_caps_map.get(idx, [])
        if figs:
            md.append("### Figures")
            for j, fig in enumerate(figs):
                md.append(f"![{fig}](assets/figures/{fig})")
                if j < len(caps):
                    md.append(f"*{caps[j]}*")
                md.append("")
        elif caps:
            md.append("### Figure/Table Captions")
            for c in caps:
                md.append(f"- {c}")
            md.append("")

        if page_text:
            md.append(simple_markdown_from_text(page_text))
        else:
            md.append("_No extractable text on this page._\n")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md).strip() + "\n")

    manifest = BookManifest(
        book_id=book_id,
        title=meta["title"],
        author=meta["author"],
        isbn=meta["isbn"],
        source_pdf=str(pdf_path),
        markdown_file=str(md_path),
        manifest_file=str(manifest_path),
        page_count=len(doc),
        ocr_pages=sum(page_ocr_flags),
        tables_extracted=tables_total,
        figures_extracted=figs_total,
        captions_extracted=caps_total,
    )

    write_json(manifest_path, asdict(manifest))
    return manifest


def build_indexes(output_root: Path, manifests: List[BookManifest]) -> None:
    index_csv = output_root / "index.csv"
    index_md = output_root / "index.md"

    rows = [asdict(m) for m in manifests]
    fieldnames = [
        "book_id",
        "title",
        "author",
        "isbn",
        "source_pdf",
        "markdown_file",
        "manifest_file",
        "page_count",
        "ocr_pages",
        "tables_extracted",
        "figures_extracted",
        "captions_extracted",
    ]

    with open(index_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    lines = ["# Book Index", ""]
    for m in manifests:
        rel_md = Path(m.markdown_file).relative_to(output_root)
        lines.append(f"## {m.title}")
        lines.append(f"- Author: {m.author}")
        lines.append(f"- ISBN: {m.isbn or 'not_found'}")
        lines.append(f"- Pages: {m.page_count}")
        lines.append(f"- OCR pages: {m.ocr_pages}")
        lines.append(f"- Tables: {m.tables_extracted}")
        lines.append(f"- Figures: {m.figures_extracted}")
        lines.append(f"- Captions: {m.captions_extracted}")
        lines.append(f"- Markdown: [{rel_md}]({rel_md.as_posix()})")
        lines.append("")

    with open(index_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).strip() + "\n")


def find_pdfs(input_dir: Path) -> List[Path]:
    return sorted([p for p in input_dir.rglob("*.pdf") if p.is_file()])


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a directory of PDF books to simple Markdown with OCR, tables, figures, and index files.")
    parser.add_argument("--input", required=True, help="Input directory containing PDFs")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--lang", default=DEFAULT_LANG, help="OCR language, default: eng")
    parser.add_argument("--tesseract-cmd", default="", help="Optional full path to tesseract.exe")
    args = parser.parse_args()

    ensure_imports()

    if args.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = args.tesseract_cmd

    check_tesseract()

    input_dir = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    pdfs = find_pdfs(input_dir)
    if not pdfs:
        print(f"No PDFs found in: {input_dir}")
        sys.exit(1)

    manifests: List[BookManifest] = []
    failures = []

    for pdf in pdfs:
        print(f"Processing: {pdf.name}")
        try:
            manifest = convert_book(pdf, output_dir, lang=args.lang)
            manifests.append(manifest)
        except Exception as e:
            failures.append({"file": str(pdf), "error": str(e)})
            print(f"Failed: {pdf.name}: {e}")

    manifests.sort(key=lambda x: ((x.author or "").lower(), (x.title or "").lower()))
    build_indexes(output_dir, manifests)

    if failures:
        write_json(output_dir / "failures.json", failures)

    print()
    print(f"Processed: {len(manifests)}")
    print(f"Failed: {len(failures)}")
    print(f"Index CSV: {output_dir / 'index.csv'}")
    print(f"Index MD: {output_dir / 'index.md'}")


if __name__ == "__main__":
    main()
