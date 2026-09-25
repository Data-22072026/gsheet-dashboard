# gsheet-dashboard

A small single-file Python service that appends timestamped rows to a Google Sheet on a
fixed interval, while streaming its own console output to a live web dashboard.

Everything lives in [`gsheet_runner.py`](gsheet_runner.py): a Flask web app plus a
background worker thread that talks to the Google Sheets API.

## What it does

The script does two things at once.

**1. Google Sheets automation (background thread)**

On start-up it authenticates to Google with an OAuth2 refresh token, opens the
spreadsheet named `" V6 SRT 6.3 Dashboard "` and its `ID_Entry` worksheet, then loops
forever:

1. Sleeps for `INTERVAL_SECONDS` (default `63.890`).
2. Reads column B of the row it is about to write.
3. Writes two cells in that row:
   - **Column A** — an incrementing ID sequence.
   - **Column B** — the value it read, if the cell was filled in manually; otherwise the
     previous B value plus one.
4. Logs the row it wrote, the exact wall-clock times, and the elapsed gap between the
   start of the wait and the moment the row landed.
5. Moves to the next row and repeats.

State is derived from the sheet at start-up (`get_initial_state`): it ensures cell A1
holds the header `ID_Entry`, picks the first empty row as the next target, and resumes
the ID sequence from the last value in column A. That means the script can be restarted
and it will continue where the sheet left off rather than from scratch.

Any exception in the loop is caught, printed with a full traceback, and ends the
automation thread — the web server keeps running so the error stays visible in the
dashboard.

**2. Live log dashboard (Flask)**

`sys.stdout` is replaced by a `SocketLogger` that mirrors every `print()` to the real
terminal *and* into an in-memory ring buffer of the last 200 lines, timestamped. Those
lines are pushed to every connected browser over Server-Sent Events.

| Route | Purpose |
| --- | --- |
| `GET /` | Terminal-styled HTML page that loads history then subscribes to the live stream |
| `GET /api/logs` | JSON array of the buffered log lines |
| `GET /stream` | `text/event-stream` SSE feed of new log lines |

Logs are kept in memory only; they are lost when the process restarts.

## Requirements

- Python 3.8+
- The packages in [`requirements.txt`](requirements.txt): `flask`, `gspread`,
  `google-auth`, `gunicorn`
- A Google account with access to the target spreadsheet
- Google OAuth2 client credentials (client ID, client secret) and a refresh token with
  the scopes `spreadsheets` and `drive`

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get Google OAuth credentials

1. In the [Google Cloud Console](https://console.cloud.google.com/), create (or pick) a
   project and enable the **Google Sheets API** and the **Google Drive API**. Drive is
   required because the script opens the spreadsheet by name.
2. Configure the OAuth consent screen and create an **OAuth client ID** of type
   *Desktop app*. Note the client ID and client secret.
3. Obtain a **refresh token** for that client with both scopes:

   ```
   https://www.googleapis.com/auth/spreadsheets
   https://www.googleapis.com/auth/drive
   ```

   The [OAuth 2.0 Playground](https://developers.google.com/oauthplayground/) can do
   this: in the settings panel tick *Use your own OAuth credentials*, enter your client
   ID/secret, authorise the two scopes above, then exchange the authorisation code for
   tokens and copy the refresh token.

### 3. Set environment variables

The script reads each value from either name, so both spellings work:

| Variable | Alternative | Description |
| --- | --- | --- |
| `CLIENT_ID` | `G_CLIENT_ID` | OAuth client ID |
| `CLIENT_SECRET` | `G_CLIENT_SECRET` | OAuth client secret |
| `REFRESH_TOKEN` | `G_REFRESH_TOKEN` | OAuth refresh token |

```bash
export CLIENT_ID="...apps.googleusercontent.com"
export CLIENT_SECRET="..."
export REFRESH_TOKEN="..."
```

If any of the three is missing the automation thread stops immediately with
`Missing Google OAuth credentials in Environment Variables.` — the web dashboard still
starts, and the error appears in the log stream.

Keep these values out of version control; use your shell, a `.env` file that is not
committed, or your host's secret manager.

### 4. Prepare the spreadsheet

Create a spreadsheet whose title exactly matches `SPREADSHEET_NAME` in
`gsheet_runner.py` — by default `" V6 SRT 6.3 Dashboard "`, **including the leading and
trailing spaces** — containing a worksheet (tab) named `ID_Entry`. Make sure the Google
account that issued the refresh token can edit it.

To use a different sheet, edit these constants near the top of the file:

```python
SPREADSHEET_NAME = ' V6 SRT 6.3 Dashboard '
SHEET_NAME = 'ID_Entry'
INTERVAL_SECONDS = 63.890
```

## Running it

### Development

```bash
python gsheet_runner.py
```

Flask serves on `http://0.0.0.0:5000` — open <http://localhost:5000> to watch the live
output.

### Production

`gunicorn` is included in the requirements. The automation thread is started at import
time, so it runs under gunicorn as well:

```bash
gunicorn gsheet_runner:app --bind 0.0.0.0:5000 --workers 1 --threads 4 --timeout 0
```

Two things matter here:

- **Use a single worker.** Each worker process imports the module and therefore starts
  its own automation thread, which would write duplicate rows to the sheet.
- **Allow long-lived requests.** `/stream` never finishes, so give the worker threads
  (`--threads`) room and disable the request timeout (`--timeout 0`), otherwise gunicorn
  will kill SSE connections.

On a platform that supplies a `$PORT` (Heroku, Render, Railway, …):

```bash
gunicorn gsheet_runner:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 0
```

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `Missing Google OAuth credentials in Environment Variables.` | One of the three variables is unset or empty |
| `SpreadsheetNotFound` | Title mismatch — check the leading/trailing spaces in `SPREADSHEET_NAME`, and that the authorised account can see the file |
| `WorksheetNotFound` | No tab named `ID_Entry` |
| `invalid_grant` on refresh | The refresh token was revoked, expired, or belongs to a different client ID/secret |
| `429` / quota errors | The interval is too short for the Sheets API quota, or several instances are running at once |
| Dashboard shows history but no new lines | The automation thread exited — reload `/api/logs` and look for the `[CRITICAL AUTOMATION ERROR]` traceback |
