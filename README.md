# SyllaSift

SyllaSift is a local Streamlit application that turns syllabus PDFs into an editable deadline list. It extracts course information, lets the user review every result, tracks completion in SQLite, and exports unfinished deadlines to a portable calendar file.

## Features

- Upload and analyze one or more syllabus PDFs.
- Remove one unsaved syllabus or clear the entire temporary upload queue.
- Receive a browser warning before reloading while unsaved work exists.
- Extract text, tables, and scanned-page content with local OCR.
- Detect course name, course code, semester, year, and dated coursework.
- Review, rename, add, remove, or uncheck deadlines before importing.
- Save courses and completion status in a local SQLite database.
- View live course, assignment, completed, remaining, and percentage metrics.
- Export incomplete deadlines as an `.ics` calendar for Google Calendar, Apple Calendar, or Outlook.
- Clear all saved data through a confirmation-protected action.

No AI API, cloud account, or syllabus upload service is required. PDF processing and storage happen locally.

## Technology

- Python
- Streamlit
- pandas
- SQLite
- pdfplumber and pypdf
- RapidOCR and pypdfium2
- Regular expressions and rule-based parsing
- pytest

## Install and run

Open Terminal and move into the project folder:

```bash
cd "/Users/essi/Library/Mobile Documents/com~apple~CloudDocs/Python Work VSC/Syllabus Extractor"
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the dependencies:

```bash
python -m pip install -r requirements.txt
```

Start SyllaSift:

```bash
python -m streamlit run app.py
```

Streamlit will print a local address, normally `http://localhost:8501`.

## Typical workflow

1. Upload one or more syllabus PDFs.
2. Select **Analyze uploaded syllabi**.
3. Review the detected course information and deadline table.
4. Correct, add, remove, or uncheck rows as needed.
5. Remove an unwanted syllabus individually, or clear all temporary uploads.
6. Import the course into the saved-course dashboard.
7. Check a saved deadline only after completing it.
8. Download unfinished deadlines from **Export Calendar**.

New deadlines start incomplete. After a calendar download, the temporary export selection clears automatically; saved courses and dashboard progress remain unchanged.

## Calendar import

The downloaded `.ics` file contains all-day events and a reminder one day before each deadline.

- **Google Calendar:** Settings → Import & export → Import.
- **Apple Calendar:** File → Import.
- **Outlook:** Add calendar → Upload from file.

## Tests

Run the complete test suite from the project folder:

```bash
python -m pytest -q
```

Tests use temporary databases and do not modify `SyllaSift.db`.

## Project structure

- `app.py` is the small Streamlit entrypoint.
- `syllasift/ui/` contains the independent application sections.
- `syllasift/state/` owns temporary uploads, widget state, and reload protection.
- `syllasift/services/` coordinates PDF upload processing.
- `syllasift/parsing/` contains metadata, dates, OCR, provenance, and focused extraction strategies.
- `syllasift/storage/` and `syllasift/calendar/` contain SQLite and `.ics` behavior.
- `tests/` mirrors these concerns with unit and Streamlit-facing coverage.

The root `parser.py`, `database.py`, and `calendar_export.py` modules remain as
compatibility imports for earlier code.

## Data and limitations

- `SyllaSift.db` contains the locally saved courses and completion status.
- **Clear Saved Data** removes saved courses and deadlines but does not delete the database file.
- Syllabus layouts vary, so the editable preview is the final verification step.
- Dates available only in Canvas, WeBWorK, MyLab, or another course platform cannot be invented; SyllaSift displays a notice so they can be added manually.
- OCR improves scanned-PDF support, but image quality can still affect recognition.
- Reload protection uses the browser's standard confirmation dialog; browsers control its wording and may require the user to interact with the page first.

## Deployment note

The application can be deployed from `app.py` on Streamlit Community Cloud. SQLite storage on many hosted platforms is temporary, so a public demo may lose saved data when the service restarts. Local use preserves the database normally. A future multi-user deployment should replace the local SQLite file with persistent hosted storage.
