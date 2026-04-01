import os
import json
import datetime
from playwright.sync_api import sync_playwright
from fpdf import FPDF

# --- CONFIGURATION ---
# Adresse de votre OpenClaw/Relay local
BROWSER_WS_ENDPOINT = "ws://127.0.0.1:18789"

TARGET_URL = "https://www.pap.fr/annonce/vente-immobiliere-marseille-13-g12024"
OUTPUT_DIR = r"C:\Users\HUGO\Desktop\Api Immo\rapports"
HISTORY_FILE = os.path.join(r"C:\Users\HUGO\Desktop\Api Immo", "history.json")
MAX_ITEMS = 5

# --- GESTION HISTORIQUE ---
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_history(seen_ids):
    data = list(seen_ids)[-1000:] 
    with open(HISTORY_FILE, 'w') as f:
        json.dump(data, f)

# --- SCRAPING ---
def scrape_via_relay():
    new_listings = []
    seen_ids = load_history()
    
    with sync_playwright() as p:
        print(f"Connexion au relay : {BROWSER_WS_ENDPOINT}...")
        try:
            # Connexion WebSocket au navigateur distant
            browser = p.chromium.connect(ws_endpoint=BROWSER_WS_ENDPOINT)
            
            # Création d'un nouveau contexte (session vierge)
            context = browser.new_context()
            page = context.new_page()
            
            print(f"Navigation vers {TARGET_URL}...")
            # Timeout augmenté à 60s car les relays peuvent être lents
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
            
            try:
                # On attend que la liste apparaisse
                page.wait_for_selector('.search-list-item', timeout=15000)
            except:
                print("Pas d'annonces détectées (Timeout).")
                browser.close()
                return [], seen_ids

            listings = page.query_selector_all('.search-list-item')
            
            count = 0
            for item in listings:
                if count >= MAX_ITEMS:
                    break
                
                try:
                    link_el = item.query_selector("a.item-title")
                    if not link_el: continue
                    
                    href = link_el.get_attribute("href")
                    listing_id = href.split("-r")[-1] if "-r" in href else href
                    
                    if listing_id in seen_ids:
                        continue
                        
                    title = link_el.inner_text().strip()
                    
                    price_el = item.query_selector(".item-price")
                    price = price_el.inner_text().strip() if price_el else "N/A"
                    
                    full_link = f"https://www.pap.fr{href}"
                    
                    new_listings.append({
                        "id": listing_id,
                        "title": title,
                        "price": price,
                        "link": full_link
                    })
                    seen_ids.add(listing_id)
                    count += 1
                    
                except Exception as e:
                    print(f"Erreur parsing: {e}")
                    continue
            
            browser.close()
            
        except Exception as e:
            print(f"ERREUR CRITIQUE: Impossible de connecter au relay {BROWSER_WS_ENDPOINT}")
            print(f"Détail: {e}")
            return [], seen_ids
            
    return new_listings, seen_ids

# --- PDF ---
def create_pdf(listings):
    if not listings: return None
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    ts = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    pdf.cell(0, 10, txt=f"Rapport PAP Marseille - {ts}", ln=1, align='C')
    pdf.ln(10)
    
    for item in listings:
        title_clean = item['title'].encode('latin-1', 'replace').decode('latin-1')
        
        pdf.set_font("Arial", 'B', 12)
        pdf.multi_cell(0, 10, txt=title_clean)
        
        pdf.set_font("Arial", '', 11)
        pdf.cell(0, 8, txt=f"Prix: {item['price']}", ln=1)
        
        pdf.set_text_color(0, 0, 255)
        pdf.set_font("Arial", 'U', 11)
        pdf.cell(0, 8, txt="Lien annonce", ln=1, link=item['link'])
        
        pdf.set_text_color(0, 0, 0)
        pdf.ln(5)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    filename = f"PAP_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    path = os.path.join(OUTPUT_DIR, filename)
    pdf.output(path)
    return path

# --- EXECUTION ---
if __name__ == "__main__":
    print("--- Démarrage Job ---")
    data, updated_history = scrape_via_relay()
    
    if data:
        print(f"Récupération de {len(data)} nouvelles annonces.")
        pdf_file = create_pdf(data)
        save_history(updated_history)
        print(f"PDF généré : {pdf_file}")
    else:
        print("Aucune nouvelle annonce à traiter.")