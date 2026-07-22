import time
import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import os



# Google Sheet Configuration
SPREADSHEET_NAME = ' V6 SRT 6.3 Dashboard '
SHEET_NAME = 'ID_Entry'

# Exactly 63.890 seconds (1 minute, 3 seconds, 890 milliseconds)
INTERVAL_SECONDS = 63.890 

# Load credentials securely from environment variables
CLIENT_ID = os.environ.get("G_CLIENT_ID")
CLIENT_SECRET = os.environ.get("G_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("G_REFRESH_TOKEN")
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def connect_to_gsheet():
    """Authenticates using User OAuth Refresh Token directly."""
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
    """Calculates starting row, sequence for Col A, and current value for Col B."""
    col_a_values = sheet.col_values(1)
    
    # Check headers at Row 1
    if len(col_a_values) == 0 or col_a_values[0] != 'ID_Entry':
        sheet.update_cell(1, 1, 'ID_Entry')
    
    current_row = max(len(col_a_values), 1) + 1
    if current_row == 1:
        current_row = 2

    # Calculate Sequence (Col A)
    try:
        last_val_a = col_a_values[-1] if len(col_a_values) >= 2 else None
        sequence = int(last_val_a) + 1 if last_val_a is not None else 1
    except (ValueError, TypeError):
        sequence = 1

    return sequence, current_row

def main():
    print("Connecting to Google Sheets...")
    sheet = connect_to_gsheet()
    print(f"Connected successfully to '{SPREADSHEET_NAME}' -> '{SHEET_NAME}'!\n")

    sequence, current_row = get_initial_state(sheet)
    last_b_value = None

    try:
        while True:
            print(f"Waiting {INTERVAL_SECONDS} seconds... (Type/verify your number in B{current_row} if it's the first entry)")
            time.sleep(INTERVAL_SECONDS)
            
            # Fetch latest value from Column B for current row
            manual_b_val = sheet.cell(current_row, 2).value
            
            if current_row == 2:
                # First data row: Read manual entry in B2
                if manual_b_val is not None and str(manual_b_val).strip() != "":
                    try:
                        last_b_value = int(manual_b_val)
                    except ValueError:
                        last_b_value = 0
                else:
                    last_b_value = 0
            else:
                # Subsequent rows: If user manually typed something new in B, use it. Otherwise increment +1
                if manual_b_val is not None and str(manual_b_val).strip() != "":
                    try:
                        last_b_value = int(manual_b_val)
                    except ValueError:
                        last_b_value += 1
                else:
                    last_b_value += 1

            # Update row in batch without deprecation warning
            sheet.update(range_name=f"A{current_row}:B{current_row}", values=[[sequence, last_b_value]])
            print(f"[LOGGED] Row {current_row} -> A{current_row}: {sequence} | B{current_row}: {last_b_value}")
            
            # Prepare next increment
            sequence += 1
            current_row += 1

    except KeyboardInterrupt:
        print("\nProcess stopped manually by user.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")

if __name__ == '__main__':
    main()