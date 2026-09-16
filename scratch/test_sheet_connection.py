import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import sheets

print("GOOGLE_SHEET_ID:", os.environ.get("GOOGLE_SHEET_ID"))
print("GOOGLE_CREDENTIALS_JSON exists:", bool(os.environ.get("GOOGLE_CREDENTIALS_JSON")))
print("GOOGLE_CREDENTIALS_PATH:", os.environ.get("GOOGLE_CREDENTIALS_PATH"))

try:
    ws = sheets._get_worksheet()
    print("Worksheet conectada exitosamente:", ws.title)
    sh = ws.spreadsheet
    print("Pestañas existentes en el libro:", [w.title for w in sh.worksheets()])
except Exception as e:
    print("Error conectando:", e)
