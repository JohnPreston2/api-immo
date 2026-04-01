#!/usr/bin/env python3
"""
PAP Processor - Zero LLM
JSON -> CSV append + PDF rapport
"""

import json, csv, os, sys
from datetime import datetime

def fix_encoding(text):
    if not isinstance(text, str): return text
    try: return text.encode('latin-1').decode('utf-8')
    except: return text

def fix_listing(l):
    return {k: fix_encoding(v) if isinstance(v, str) else v for k, v in l.items()}

JSON_PATH = sys.argv[1] if len(sys.argv) > 1 else "/tmp/listings-1.json"
PAGE      = sys.argv[2] if len(sys.argv) > 2 else "1"
RAPPORTS  = r"C:\Users\HUGO\Desktop\Api Immo\rapports"
CSV_PATH  = os.path.join(RAPPORTS, "all-listings.csv")
PDF_PATH  = os.path.join(RAPPORTS, f"rapport-{PAGE}.pdf")

with open(JSON_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

listings = data.get("listings", data) if isinstance(data, dict) else data
listings = [fix_listing(l) for l in listings]
print(f"[PAP] {len(listings)} annonces page {PAGE}")

# CSV
fieldnames = ["id","titre","prix","surface","localisation","url","timestamp","page"]
exists = os.path.exists(CSV_PATH)
with open(CSV_PATH, "a", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
    if not exists: w.writeheader()
    for l in listings:
        l["page"] = PAGE
        w.writerow(l)
print(f"[PAP] CSV: {CSV_PATH}")

# PDF
try:
    from fpdf import FPDF
except ImportError:
    os.system("pip install fpdf2 -q")
    from fpdf import FPDF

class PDF(FPDF):
    def header(self):
        self.set_font("Helvetica","B",14)
        self.set_fill_color(30,30,30)
        self.set_text_color(255,255,255)
        self.cell(0,12,f"PAP.fr - Marseille - Page {PAGE}",align="C",fill=True,new_x="LMARGIN",new_y="NEXT")
        self.set_font("Helvetica","",9)
        self.set_text_color(120,120,120)
        self.cell(0,6,f"Genere le {datetime.now().strftime('%d/%m/%Y %H:%M')}",align="C",new_x="LMARGIN",new_y="NEXT")
        self.ln(4)
    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica","I",8)
        self.set_text_color(150,150,150)
        self.cell(0,10,f"Page {self.page_no()}",align="C")

pdf = PDF(orientation="L",unit="mm",format="A4")
pdf.set_auto_page_break(auto=True,margin=15)
pdf.add_page()

headers = ["#","Titre","Prix (EUR)","Surface m2","Localisation","URL"]
widths  = [10, 90,     28,          24,           50,            65]

pdf.set_font("Helvetica","B",9)
pdf.set_fill_color(50,50,50)
pdf.set_text_color(255,255,255)
for h,w in zip(headers,widths):
    pdf.cell(w,8,h,border=1,fill=True)
pdf.ln()

pdf.set_font("Helvetica","",8)
pdf.set_text_color(30,30,30)
colors = [(245,245,245),(255,255,255)]

for i,l in enumerate(listings):
    pdf.set_fill_color(*colors[i%2])
    prix = f"{int(l.get('prix',0)):,}".replace(","," ") if str(l.get('prix','')).isdigit() else "-"
    url  = l.get("url","").replace("https://www.pap.fr/annonces/","pap.fr/.../")
    row  = [str(l.get("id",i+1)), l.get("titre","-"), prix, f"{l.get('surface','-')} m2", l.get("localisation","-"), url]
    for val,w in zip(row,widths):
        pdf.cell(w,7,str(val)[:46],border=1,fill=True)
    pdf.ln()

pdf.ln(6)
prix_list = [int(l["prix"]) for l in listings if str(l.get("prix","")).isdigit()]
if prix_list:
    pdf.set_font("Helvetica","B",10)
    pdf.set_text_color(30,30,30)
    txt = f"Moy: {sum(prix_list)//len(prix_list):,} EUR  Min: {min(prix_list):,} EUR  Max: {max(prix_list):,} EUR".replace(","," ")
    pdf.cell(0,7,txt,new_x="LMARGIN",new_y="NEXT")

pdf.output(PDF_PATH)
print(f"[PAP] PDF: {PDF_PATH}")
print("[PAP] Done - 0 token LLM.")
