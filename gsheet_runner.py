import os
import sys
import time
import threading
import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit

# Initialize Flask App & SocketIO (Force threading for Python 3.14 compatibility)
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Store log history in memory so new page loads see past output
LOG_HISTORY = []

# Custom Logger to redirect print() statements to Terminal, WebSockets, and Memory
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
            socketio.emit('log_message', {'data': timestamped_msg})

    def flush(self):
        self.terminal.flush()

sys.stdout = SocketLogger(sys.stdout)

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
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        body { background-color: #1e1e1e; color: #00ff00; font-family: monospace; padding: 20px; }
        #console { background-color: #000; border: 1px solid #333; padding: 15px; height: 80vh; overflow-y: scroll; border-radius: 5px; }
        .log-entry { margin-bottom: 5px; white-space: pre-wrap; }
    </style>
</head>
<body>
    <h2>Live Terminal Output Dashboard</h2>
    <div id="console"></div>

    <script>
        var socket = io();
        var consoleDiv = document.getElementById('console');

        socket.on('history', function(history) {
            consoleDiv.innerHTML = '';
            history.forEach(function(msg) {
                var item = document.createElement('div');
                item.className = 'log-entry';
                item.textContent = msg;
                consoleDiv.appendChild(item);
            });
            consoleDiv.scrollTop = consoleDiv.scrollHeight;
        });

        socket.on('log_message', function(msg) {
            var item = document.createElement('div');
            item.className = 'log-entry';
            item.textContent = msg.data;
            consoleDiv.appendChild(item);
            consoleDiv.scrollTop = consoleDiv.scrollHeight;
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@socketio.on('connect')
def handle_connect():
    emit('history', LOG_HISTORY)

def connect_to_gsheet():
    print("Checking Google OAuth environment variables...")
    if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
        print("ERROR: One or more OAuth credentials missing in environment variables!")
        raise ValueError("Missing Google OAuth credentials in Environment Variables.")

    print("Building credentials object...")
    creds = Credentials(
        token=None,
        refresh_token=REFRESH_TOKEN,
        token_uri=TOKEN_URI,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=SCOPES
    )

    if not creds.valid:
        print("Refreshing access token from Google OAuth...")
        creds.refresh(Request())

    print("Authorizing gspread client...")
    client = gspread.authorize(creds)
    
    print(f"Opening Google Spreadsheet '{SPREADSHEET_NAME}' and worksheet '{SHEET_NAME}'...")
    sheet = client.open(SPREADSHEET_NAME).worksheet(SHEET_NAME)
    return sheet

def get_initial_state(sheet):
    print("Fetching existing Column A values to check initial state...")
    col_a_values = sheet.col_values(1)
    
    if len(col_a_values) == 0 or col_a_values[0] != 'ID_Entry':
        print("Header 'ID_Entry' not found in A1. Setting A1 to 'ID_Entry'...")
        sheet.update_cell(1, 1, 'ID_Entry')
    
    current_row = max(len(col_a_values), 1) + 1
    if current_row == 1:
        current_row = 2

    try:
        last_val_a = col_a_values[-1] if len(col_a_values) >= 2 else None
        sequence = int(last_val_a) + 1 if last_val_a is not None else 1
    except (ValueError, TypeError):
        sequence = 1

    print(f"Initial state set: Starting at Row {current_row} with Sequence ID {sequence}.")
    return sequence, current_row

def run_sheets_automation():
    time.sleep(2)
    print("--------------------------------------------------")
    print("Starting Google Sheets Automation Loop...")
    print("--------------------------------------------------")
    try:
        sheet = connect_to_gsheet()
        print(f"SUCCESS: Connected to '{SPREADSHEET_NAME}' -> '{SHEET_NAME}'!\n")
        
        sequence, current_row = get_initial_state(sheet)
        last_b_value = 0

        while True:
            print(f"Waiting {INTERVAL_SECONDS} seconds before next check...")
            time.sleep(INTERVAL_SECONDS)
            
            print(f"Checking cell B{current_row} for manual override value...")
            manual_b_val = sheet.cell(current_row, 2).value
            
            if manual_b_val is not None and str(manual_b_val).strip() != "":
                print(f"Found manual entry in B{current_row}: '{manual_b_val}'")
                try:
                    last_b_value = int(manual_b_val)
                    print(f"Parsed manual value as integer: {last_b_value}")
                except ValueError:
                    print(f"Could not convert '{manual_b_val}' to integer. Incrementing previous value instead.")
                    last_b_value += 1
            else:
                print(f"No manual entry found in B{current_row}.")
                if current_row == 2:
                    last_b_value = 0
                else:
                    last_b_value += 1

            print(f"Updating Google Sheet -> A{current_row}: {sequence} | B{current_row}: {last_b_value}...")
            sheet.update(range_name=f"A{current_row}:B{current_row}", values=[[sequence, last_b_value]])
            print(f"[SUCCESS LOGGED] Row {current_row} updated successfully -> Sequence: {sequence}, Value: {last_b_value}\n")
            
            sequence += 1
            current_row += 1

    except Exception as e:
        print(f"\nCRITICAL ERROR in automation loop: {e}")

# Start background thread
thread = threading.Thread(target=run_sheets_automation)
thread.daemon = True
thread.start()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
