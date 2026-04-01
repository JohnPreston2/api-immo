#!/usr/bin/env python3
"""
PAP Scraper - Zero LLM
Gere pagination.txt automatiquement
Usage: python pap_scraper.py
"""

import json, csv, os, sys, subprocess
from datetime import datetime

RAPPORTS = r"C:\Users\HUGO\Desktop\Api Immo\rapports"
PAG_FILE = os.path.join(RAPPORTS, "pagination.txt")
CSV_PATH = os.path.join(RAPPORTS, "all-listings.csv")

# Lire et incrementer pagination.txt
with open(PAG_FILE, "r") as f:
    PAGE = f.read().strip() or "1"

PAP_URL  = f"https://www.pap.fr/annonce/vente-immobiliere-marseille-13-g12024?page={PAGE}"
JSON_OUT = f"/tmp/listings-{PAGE}.json"
PDF_PATH = os.path.join(RAPPORTS, f"rapport-{PAGE}.pdf")

JS = "() => { const items = [...document.querySelectorAll('.search-list-item, .search-list-item-alt')]; return items.map((el, i) => { const lines = el.innerText.split('\\n').map(l => l.trim()).filter(l => l); const url = el.querySelector('a.item-thumb-link')?.href || ''; const prixRaw = lines.find(l => /\\d/.test(l) && l.includes('\u20ac')) || ''; const prix = prixRaw.replace(/[^0-9]/g, ''); const surfLine = lines.find(l => /\\d+\\s*m\u00b2/.test(l)) || ''; const surfMatch = surfLine.match(/(\\d+)\\s*m\u00b2/); const surface = surfMatch ? surfMatch[1] : ''; const loca = lines.find(l => l.includes('Marseille') && !l.includes('\u20ac')) || ''; const slug = url.split('/').pop() || ''; const titre = slug.replace(/-r\\d+$/, '').replace(/-/g, ' '); return { id: i+1, titre, prix, surface, localisation: loca, url }; }).filter(x => x.url && x.prix); }"

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.stdout.strip()

print(f"[PAP] Page {PAGE} -> {PAP_URL}")
run(f'openclaw browser navigate "{PAP_URL}"')
run('openclaw browser wait --time 8000')

print("[PAP] Extraction JS...")
raw = run(f'openclaw browser evaluate --fn "{JS}"')

lines = raw.split('\n')
json_start = next((i for i, l in enumerate(lines) if l.strip().startswith('[')), None)

if json_start is None:
    print("[PAP] Erreur: pas de JSON trouve")
    sys.exit(1)

listings = json.loads('\n'.join(lines[json_start:]))
print(f"[PAP] {len(listings)} annonces extraites")

# JSON
with open(JSON_OUT, "w", encoding="utf-8") as f:
    json.dump({"page": int(PAGE), "timestamp": datetime.now().isoformat(), "listings": listings}, f, ensure_ascii=False, indent=2)

# CSV
fieldnames = ["id", "page", "titre", "prix", "surface", "localisation", "url", "timestamp"]
exists = os.path.exists(CSV_PATH)
with open(CSV_PATH, "a", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
    if not exists:
        w.writeheader()
    for l in listings:
        l["page"] = PAGE
        l["timestamp"] = datetime.now().isoformat()
        w.writerow(l)
print(f"[PAP] CSV updated")

# PDF
try:
    from fpdf import FPDF
except ImportError:
    os.system("pip install fpdf2 -q")
    from fpdf import FPDF

class PDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 14)
        self.set_fill_color(30, 30, 30)
        self.set_text_color(255, 255, 255)
        self.cell(0, 12, f"PAP.fr - Vente Marseille - Page {PAGE}", align="C", fill=True, new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(120, 120, 120)
        self.cell(0, 6, f"Genere le {datetime.now().strftime('%d/%m/%Y %H:%M')} - 0 token LLM", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(4)
    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

pdf = PDF(orientation="L", unit="mm", format="A4")
pdf.set_auto_page_break(auto=True, margin=15)
pdf.add_page()

headers = ["#", "Titre", "Prix (EUR)", "Surface m2", "Localisation", "URL"]
widths  = [10, 85, 28, 22, 55, 67]

pdf.set_font("Helvetica", "B", 9)
pdf.set_fill_color(50, 50, 50)
pdf.set_text_color(255, 255, 255)
for h, w in zip(headers, widths):
    pdf.cell(w, 8, h, border=1, fill=True)
pdf.ln()

pdf.set_font("Helvetica", "", 8)
colors = [(245, 245, 245), (255, 255, 255)]
for i, l in enumerate(listings):
    pdf.set_fill_color(*colors[i % 2])
    pdf.set_text_color(30, 30, 30)
    prix_fmt = f"{int(l['prix']):,}".replace(",", " ") if l.get('prix','').isdigit() else l.get('prix','')
    row = [
        str(l.get("id", i+1)),
        str(l.get("titre", ""))[:40],
        prix_fmt,
        f"{l.get('surface', '-')} m2",
        str(l.get("localisation", ""))[:35],
        str(l.get("url", "")).replace("https://www.pap.fr/annonces/", "pap.fr/.../")[:45]
    ]
    for val, w in zip(row, widths):
        pdf.cell(w, 7, str(val), border=1, fill=True)
    pdf.ln()

prix_list = [int(l["prix"]) for l in listings if l.get("prix","").isdigit()]
if prix_list:
    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(30, 30, 30)
    txt = f"Moy: {sum(prix_list)//len(prix_list):,} EUR  |  Min: {min(prix_list):,} EUR  |  Max: {max(prix_list):,} EUR".replace(",", " ")
    pdf.cell(0, 7, txt, new_x="LMARGIN", new_y="NEXT")

pdf.output(PDF_PATH)
print(f"[PAP] PDF: {PDF_PATH}")

# Incrementer pagination.txt
with open(PAG_FILE, "w") as f:
    f.write(str(int(PAGE) + 1))
print(f"[PAP] pagination.txt -> {int(PAGE) + 1}")
print("[PAP] Done - 0 token LLM.")
