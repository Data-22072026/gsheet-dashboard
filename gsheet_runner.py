import os
import sys
import time
import threading
import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit

# Initialize Flask App & SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

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
            # Keep history to last 200 lines to preserve memory
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

# Read tokens securely from Environment Variables (Set in Render Dashboard)
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

        // Receives all past logs when connected
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

        // Receives new live logs
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
    # Send historical logs to client immediately when they connect
    emit('history', LOG_HISTORY)

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

def run_sheets_automation():
    time.sleep(2)
    print("Connecting to Google Sheets...")
    try:
        sheet = connect_to_gsheet()
        print(f"Connected successfully to '{SPREADSHEET_NAME}' -> '{SHEET_NAME}'!\n")
        sequence, current_row = get_initial_state(sheet)
        last_b_value = None

        while True:
            print(f"Waiting {INTERVAL_SECONDS} seconds...")
            time.sleep(INTERVAL_SECONDS)
            
            manual_b_val = sheet.cell(current_row, 2).value
            
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
                        last_b_value += 1
                else:
                    last_b_value += 1

            sheet.update(range_name=f"A{current_row}:B{current_row}", values=[[sequence, last_b_value]])
            print(f"[LOGGED] Row {current_row} -> A{current_row}: {sequence} | B{current_row}: {last_b_value}")
            
            sequence += 1
            current_row += 1

    except Exception as e:
        print(f"\nAn error occurred: {e}")

# Start background thread
thread = threading.Thread(target=run_sheets_automation)
thread.daemon = True
thread.start()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
