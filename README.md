# Meadow House Repairs

A small Python (Flask) browser app for staff at the fictional Meadow House to
report repairs, track progress and see what was done. Each repair job keeps its
own fields, status, notes and full dated history.

## Run it

Requires Python 3.10+.

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>. Set `PORT` to use a different port.

Jobs are saved to `data/jobs.json` (created automatically), so they survive page
refreshes and server restarts. Set `MEADOW_DATA_FILE` to store them elsewhere.
Delete that file to start fresh.

## Run the tests

```bash
python -m pytest -q
```

`test_app.py` automates the ten published judging tests.

## How it works

| Need | Where |
| --- | --- |
| Report form (description, reporter, Normal/Urgent) | Home page, left panel |
| Validation of blank / spaces-only input | `create_job` in `app.py`; errors shown inline and in a summary, valid input kept |
| New job with ID (`MH-0001`…), date, Meadow House | `JobStore.create` |
| View many jobs, filter by status | Home page, right panel |
| Move to In Progress, add progress notes | Job page → "Update this job" |
| Mark Completed (completion note required) | Job page → "Mark as Completed" |
| History with date and time, earlier entries kept | Job page → "History" |
| Persistence | JSON file, atomic writes |
| Plain-text display of `<b>like this</b>` | Jinja autoescaping (never marked `safe`) |

Accessibility: every control has a visible label, errors are linked to their
inputs with `aria-describedby`/`aria-invalid`, focus moves to the error summary
or the "Saved" banner after each action, focus outlines are visible, and the
layout stacks on narrow screens with no horizontal scrolling.

All data is fictional. No accounts, API keys or paid services are used.
