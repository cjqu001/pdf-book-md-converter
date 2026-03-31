# PDF Book to Markdown Converter

A Windows-ready Python workflow for converting a directory of PDF books into simple Markdown with OCR fallback, table extraction, figure extraction, metadata detection, and master index files.

---

## What this does

This project scans a folder of PDF books and attempts to:

- detect title, author, and ISBN from the first 10 pages
- apply a consistent naming convention
- convert each book into simple Markdown
- use OCR on low-text or scanned pages
- extract tables into CSV files
- extract figures/images into PNG files
- guess figure and table captions from page text
- create a per-book `manifest.json`
- create a master `index.csv`
- create a master `index.md`
- log failures into `failures.json`

---

## Best use case

This works best for:

- digital PDFs with selectable text
- mixed PDFs where some pages are scanned
- building a searchable working archive of books

This is less reliable for:

- heavily scanned books with poor image quality
- complex multi-column layouts
- highly formatted textbooks with complicated tables
- pages where captions are far away from figures

---

## Naming convention

Each book gets a stable folder name.

### If ISBN is found

`isbn_<isbn>`

Example:

`isbn_9780323445481`

### If ISBN is not found

`<author_slug>__<title_slug>`

Example:

`wyatt_crosby__crazy_busy_doctor`

---

## Output structure

```text
output/
  index.csv
  index.md
  failures.json
  isbn_9781234567890/
    isbn_9781234567890.md
    manifest.json
    assets/
      tables/
        page_0005_table_01.csv
      figures/
        page_0007_img_01.png
```

---

# FULL SETUP GUIDE (BEGINNER)

Follow these steps exactly. You only need to do this once.

## Step 1 — Install Python

1. Go to:
   https://www.python.org/downloads/

2. Download Python 3.11 or newer

3. During installation, check this box:

```text
Add Python to PATH
```

4. After installing, open PowerShell and verify:

```powershell
python --version
```

Expected output:

```text
Python 3.11.x
```

## Step 2 — Install Tesseract OCR (Required for scanned PDFs)

1. Download Tesseract OCR for Windows.
2. Install it using default settings.

Default install location:

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

You may need this path later.

## Step 3 — Create your project folder

Open PowerShell:

```powershell
mkdir pdf-book-md-converter
cd pdf-book-md-converter
```

## Step 4 — Create the script file

Create a file named:

```text
convert_books.py
```

Paste the full Python script into this file.

## Step 5 — Create virtual environment

```powershell
python -m venv .venv
```

## Step 6 — Activate environment

```powershell
.venv\Scripts\Activate.ps1
```

If you get a permission error, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

## Step 7 — Install dependencies

```powershell
pip install pymupdf pdfplumber pandas openpyxl pillow pytesseract
```

## Step 8 — Run the script

Basic run:

```powershell
python convert_books.py --input "D:\books" --output "D:\books_md"
```

If Tesseract is not detected:

```powershell
python convert_books.py --input "D:\books" --output "D:\books_md" --tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

---

# What the script is doing (simple)

For each PDF:

1. scans first 10 pages
2. detects:
   - title
   - author
   - ISBN
3. creates a consistent folder name
4. extracts text
5. uses OCR if needed
6. removes repeated headers/footers
7. converts text to Markdown
8. extracts:
   - tables to CSV
   - images to PNG
9. detects captions
10. saves:
   - markdown file
   - manifest.json

Then creates:

- index.csv
- index.md
- failures.json

---

# Tables and Figures

## Tables

- saved as CSV
- linked in Markdown
- not flattened into messy text

## Figures

- saved as PNG
- embedded in Markdown
- captions included when detected

---

# Example run

```powershell
python convert_books.py --input "D:\medical_books" --output "D:\md_books" --tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

---

# After setup (future runs)

Only run:

```powershell
.venv\Scripts\Activate.ps1
python convert_books.py --input "D:\books" --output "D:\books_md"
```

---

# Limitations

Expect weaker results for:

- scanned low-quality PDFs
- complex tables
- multi-column layouts
- distant captions
- poor metadata

---

# Practical recommendation

Use this for:

- building a clean archive
- creating searchable datasets
- preprocessing for AI

Not for:

- perfect formatting reproduction

---

# Suggested repo name

```text
pdf-book-md-converter
```
