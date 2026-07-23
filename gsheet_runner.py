# http://localhost:5000/

import os
import sys
import time
import queue
from datetime import datetime
import threading
import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from flask import Flask, render_template_string, Response, jsonify

app = Flask(__name__)

# Memory storage for logs and SSE broadcast listeners
LOG_HISTORY = []
LISTENERS = []

class SocketLogger:
    def __init__(self, original_stdout):
        self.terminal = original_stdout

    def write(self, message):
        self.terminal.write(message)
        self.terminal.flush()
        msg = message.strip()
        if msg:
            timestamped_msg = f"[{time.strftime('%X')}] {msg}"
            LOG_HISTORY.append(timestamped_msg)
            if len(LOG_HISTORY) > 200:
                LOG_HISTORY.pop(0)
            
            # Broadcast live log to all connected browsers
            for q in list(LISTENERS):
                try:
                    q.put_nowait(timestamped_msg)
                except queue.Full:
                    pass

    def flush(self):
        self.terminal.flush()

sys.stdout = SocketLogger(sys.stdout)
print("🌐 Web Server Started. Automation engine loading...")

# Google Sheet Configuration
SPREADSHEET_NAME = ' V6 SRT 6.3 Dashboard '
SHEET_NAME = 'ID_Entry'
INTERVAL_SECONDS = 63.890 

CLIENT_ID = os.environ.get("CLIENT_ID") or os.environ.get("G_CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET") or os.environ.get("G_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("REFRESH_TOKEN") or os.environ.get("G_REFRESH_TOKEN")

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Live Script Output Dashboard</title>
    <style>
        body { background-color: #1e1e1e; color: #00ff00; font-family: monospace; padding: 20px; }
        #console { background-color: #000; border: 1px solid #333; padding: 15px; height: 80vh; overflow-y: scroll; border-radius: 5px; }
        .log-entry { margin-bottom: 5px; white-space: pre-wrap; }
    </style>
</head>
<body>
    <h2>Live Terminal Output Dashboard</h2>
    <div id="console"><div class="log-entry">Connecting to live log stream...</div></div>

    <script>
        var consoleDiv = document.getElementById('console');

        function appendLog(text) {
            var item = document.createElement('div');
            item.className = 'log-entry';
            item.textContent = text;
            consoleDiv.appendChild(item);
            consoleDiv.scrollTop = consoleDiv.scrollHeight;
        }

        // 1. Load History on initial page load
        fetch('/api/logs')
            .then(res => res.json())
            .then(data => {
                consoleDiv.innerHTML = '';
                if (data.length === 0) {
                    appendLog("Waiting for automation output...");
                } else {
                    data.forEach(msg => appendLog(msg));
                }
            });

        // 2. Stream Live Log Updates via Server-Sent Events (SSE)
        var evtSource = new EventSource("/stream");
        evtSource.onmessage = function(e) {
            appendLog(e.data);
        };
        evtSource.onerror = function() {
            console.log("Stream reconnecting...");
        };
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/logs')
def get_logs():
    return jsonify(LOG_HISTORY)

@app.route('/stream')
def stream():
    def event_stream():
        q = queue.Queue()
        LISTENERS.append(q)
        try:
            while True:
                msg = q.get()
                yield f"data: {msg}\n\n"
        except GeneratorExit:
            LISTENERS.remove(q)

    return Response(event_stream(), mimetype="text/event-stream")

def connect_to_gsheet():
    if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
        raise ValueError("Missing Google OAuth credentials in Environment Variables.")

    creds = Credentials(
        token=None,
        refresh_token=REFRESH_TOKEN,
        token_uri=TOKEN_URI,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=SCOPES
    )

    if not creds.valid:
        creds.refresh(Request())

    client = gspread.authorize(creds)
    sheet = client.open(SPREADSHEET_NAME).worksheet(SHEET_NAME)
    return sheet

def get_initial_state(sheet):
    col_a_values = sheet.col_values(1)
    
    if len(col_a_values) == 0 or col_a_values[0] != 'ID_Entry':
        sheet.update_cell(1, 1, 'ID_Entry')
    
    current_row = max(len(col_a_values), 1) + 1
    if current_row == 1:
        current_row = 2

    try:
        last_val_a = col_a_values[-1] if len(col_a_values) >= 2 else None
        sequence = int(last_val_a) + 1 if last_val_a is not None else 1
    except (ValueError, TypeError):
        sequence = 1

    return sequence, current_row

def format_detailed_time(dt):
    time_str = dt.strftime("%H:%M:%S")
    hours = dt.strftime("%I")
    minutes = dt.strftime("%M")
    seconds = dt.strftime("%S")
    microseconds = dt.strftime("%f")
    milliseconds = f"{int(microseconds) // 1000:03d}"
    return f"{time_str} ({int(hours)} hours {int(minutes)} minute {int(seconds)} seconds {milliseconds} milliseconds {microseconds} microseconds)"

def run_sheets_automation():
    time.sleep(2)
    print("==================================================")
    print("🚀 INITIALIZING GOOGLE SHEETS AUTOMATION ENGINE")
    print("==================================================")
    print("Connecting to Google Sheets...")
    try:
        sheet = connect_to_gsheet()
        print(f"✅ Connected successfully to: '{SPREADSHEET_NAME}' -> '{SHEET_NAME}'!\n")
        
        sequence, current_row = get_initial_state(sheet)
        print(f"📊 Starting Execution State -> Next Row: {current_row} | Initial ID Sequence: {sequence}")
        print("--------------------------------------------------")
        
        last_b_value = 0

        while True:
            countdown_start_dt = datetime.now()
            print(f"\n⏳ [CYCLE START] Waiting {INTERVAL_SECONDS} seconds before next check...")
            print(f"🕒 [WAIT START] Timer started at: {format_detailed_time(countdown_start_dt)}")

            time.sleep(INTERVAL_SECONDS)
            
            print(f"🔎 Reading Column B value at Row {current_row}...")
            manual_b_val = sheet.cell(current_row, 2).value
            
            if last_b_value == 0 and current_row > 2:
                prev_b_val = sheet.cell(current_row - 1, 2).value
                try:
                    last_b_value = int(prev_b_val) if prev_b_val is not None else 0
                except ValueError:
                    last_b_value = 0

            if current_row == 2:
                if manual_b_val is not None and str(manual_b_val).strip() != "":
                    try:
                        last_b_value = int(manual_b_val)
                    except ValueError:
                        last_b_value = 0
                else:
                    last_b_value = 0
            else:
                if manual_b_val is not None and str(manual_b_val).strip() != "":
                    try:
                        last_b_value = int(manual_b_val)
                    except ValueError:
                        last_b_value = (last_b_value or 0) + 1
                else:
                    last_b_value = (last_b_value or 0) + 1

            print(f"📝 Writing to Google Sheet at Row {current_row} (A: {sequence}, B: {last_b_value})...")
            sheet.update(range_name=f"A{current_row}:B{current_row}", values=[[sequence, last_b_value]])
            
            logged_dt = datetime.now()
            print(f"✅ [LOGGED SUCCESS] Row {current_row} -> A{current_row}: {sequence} | B{current_row}: {last_b_value}")
            print(f"🕒 [LOGGED AT] Completed at: {format_detailed_time(logged_dt)}")

            duration = logged_dt - countdown_start_dt
            total_sec = duration.total_seconds()
            mins = int(total_sec // 60)
            secs = total_sec % 60
            print(f"⏱️ [ROW TIME GAP] Total time from timer start to logged: {mins} minutes {secs:.3f} seconds ({total_sec:.6f} seconds total)")
            print("--------------------------------------------------")

            sequence += 1
            current_row += 1

    except Exception as e:
        print(f"\n❌ [ERROR] An error occurred in the automation loop: {e}")

# Start background thread
thread = threading.Thread(target=run_sheets_automation)
thread.daemon = True
thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
