# PDF Book to Markdown Converter

A Windows-ready Python workflow for converting a directory of PDF books into simple Markdown with OCR fallback, table extraction, figure extraction, metadata detection, and master index files.

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
