"""
agent_marseille.py
==================
Agent immobilier autonome - Marseille
Tourne de 9h a 18h, genere un rapport PDF quotidien.

Usage :
    python agent_marseille.py            # mode production (schedule 9h-18h)
    python agent_marseille.py --now      # lancer une analyse immediate
    python agent_marseille.py --test     # test connexion Qwen + Flask

Dependances :
    pip install reportlab requests schedule
"""

import requests
import json
import os
import sys
import time
import schedule
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)

# ─── CONFIG ────────────────────────────────────────────────────────────────────
FLASK_BASE   = "http://localhost:5001"   # ton app Flask
OLLAMA_URL   = "http://localhost:11434/api/generate"
QWEN_MODEL   = "qwen-fast"               # le modele custom qu'on a cree
RAPPORTS_DIR = os.path.join(os.path.dirname(__file__), "rapports")
os.makedirs(RAPPORTS_DIR, exist_ok=True)

# Les 16 arrondissements de Marseille
ARRONDISSEMENTS_MARSEILLE = [
    ("Marseille 1er",  "13001"),
    ("Marseille 2e",   "13002"),
    ("Marseille 3e",   "13003"),
    ("Marseille 4e",   "13004"),
    ("Marseille 5e",   "13005"),
    ("Marseille 6e",   "13006"),
    ("Marseille 7e",   "13007"),
    ("Marseille 8e",   "13008"),
    ("Marseille 9e",   "13009"),
    ("Marseille 10e",  "13010"),
    ("Marseille 11e",  "13011"),
    ("Marseille 12e",  "13012"),
    ("Marseille 13e",  "13013"),
    ("Marseille 14e",  "13014"),
    ("Marseille 15e",  "13015"),
    ("Marseille 16e",  "13016"),
]


# ─── CERVEAU : QWEN LOCAL ──────────────────────────────────────────────────────
def call_qwen(prompt, system="Tu es un expert en immobilier marseillais. Reponds en francais, de facon concise et professionnelle."):
    """Appelle Qwen 9B local via Ollama."""
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": QWEN_MODEL,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_predict": 500,
            }
        }, timeout=120)
        r.raise_for_status()
        return r.json().get("response", "").strip()
    except Exception as e:
        return f"[Qwen indisponible: {e}]"


# ─── OUTILS PYTHON : APPELS FLASK ─────────────────────────────────────────────
def get_dvf(commune):
    """Recupere les stats DVF pour une commune."""
    try:
        r = requests.get(f"{FLASK_BASE}/api/dvf", params={"commune": commune}, timeout=30)
        return r.json() if r.ok else {}
    except:
        return {}

def get_score(commune):
    """Recupere le score attractivite."""
    try:
        r = requests.get(f"{FLASK_BASE}/api/score", params={"commune": commune}, timeout=30)
        return r.json() if r.ok else {}
    except:
        return {}

def get_densification(commune, section=""):
    """Recupere le potentiel de densification."""
    try:
        params = {"commune": commune}
        if section:
            params["section"] = section
        r = requests.get(f"{FLASK_BASE}/api/densification", params=params, timeout=30)
        return r.json() if r.ok else {}
    except:
        return {}

def get_marchands(commune):
    """Recupere les operations marchands de biens."""
    try:
        r = requests.get(f"{FLASK_BASE}/api/marchands", params={"commune": commune}, timeout=30)
        return r.json() if r.ok else {}
    except:
        return {}

def get_plu(commune):
    """Recupere le zonage PLU."""
    try:
        r = requests.get(f"{FLASK_BASE}/api/plu", params={"commune": commune}, timeout=30)
        return r.json() if r.ok else {}
    except:
        return {}


# ─── ANALYSE PAR ARRONDISSEMENT ───────────────────────────────────────────────
def analyser_arrondissement(nom, code):
    """Analyse complete d'un arrondissement + raisonnement Qwen."""
    print(f"  → Analyse {nom}...")
    data = {}

    # Collecte des donnees (outils Python)
    dvf   = get_dvf(nom)
    score = get_score(nom)
    dense = get_densification(nom)
    march = get_marchands(nom)

    data["dvf"]          = dvf
    data["score"]        = score
    data["densification"] = dense
    data["marchands"]    = march

    # Resume numerique pour le prompt
    prix_appart  = dvf.get("appartements", {}).get("prix_m2_moyen")
    nb_ventes    = dvf.get("total_transactions", 0)
    score_global = score.get("score_global")
    nb_parcelles = dense.get("nb_avec_potentiel", 0)
    nb_ops       = march.get("nb_operations_detectees", 0)
    zones_plu    = dense.get("zones_plu", {})

    # Raisonnement Qwen
    prompt = f"""Analyse immobiliere de {nom} (code {code}) basee sur les donnees officielles :

MARCHE DVF :
- Prix moyen appartements : {prix_appart} EUR/m2
- Nombre de transactions : {nb_ventes}
- Score attractivite global : {score_global}/100

POTENTIEL FONCIER :
- Parcelles avec potentiel de densification : {nb_parcelles}
- Operations marchands de biens detectees : {nb_ops}
- Zones PLU presentes : {list(zones_plu.keys())}

En 3-4 phrases, donne :
1. Le positionnement de cet arrondissement sur le marche marseillais
2. Le potentiel d'investissement (densification ou marchand de biens)
3. Un conseil operationnel concret pour un investisseur
"""

    analyse_qwen = call_qwen(prompt)

    return {
        "nom": nom,
        "code": code,
        "prix_m2": prix_appart,
        "nb_ventes": nb_ventes,
        "score": score_global,
        "nb_parcelles_denses": nb_parcelles,
        "nb_ops_marchands": nb_ops,
        "zones_plu": list(zones_plu.keys()),
        "analyse_qwen": analyse_qwen,
        "data_brute": data,
    }


# ─── GENERATION RAPPORT PDF ───────────────────────────────────────────────────
def generer_rapport_pdf(resultats, synthese_globale):
    """Genere le rapport PDF quotidien."""
    date_str  = datetime.now().strftime("%Y-%m-%d")
    heure_str = datetime.now().strftime("%H:%M")
    filename  = os.path.join(RAPPORTS_DIR, f"rapport_marseille_{date_str}.pdf")

    doc    = SimpleDocTemplate(filename, pagesize=A4,
                               topMargin=2*cm, bottomMargin=2*cm,
                               leftMargin=2*cm, rightMargin=2*cm)
    styles = getSampleStyleSheet()
    story  = []

    # Styles custom
    titre_style = ParagraphStyle('Titre', parent=styles['Title'],
                                 fontSize=22, textColor=colors.HexColor('#1a3a5c'),
                                 spaceAfter=6)
    sous_titre_style = ParagraphStyle('SousTitre', parent=styles['Normal'],
                                      fontSize=11, textColor=colors.HexColor('#666666'),
                                      spaceAfter=20)
    h1_style = ParagraphStyle('H1', parent=styles['Heading1'],
                              fontSize=14, textColor=colors.HexColor('#1a3a5c'),
                              spaceBefore=16, spaceAfter=8)
    h2_style = ParagraphStyle('H2', parent=styles['Heading2'],
                              fontSize=12, textColor=colors.HexColor('#2e6da4'),
                              spaceBefore=12, spaceAfter=6)
    body_style = ParagraphStyle('Body', parent=styles['Normal'],
                                fontSize=10, leading=14, spaceAfter=8)
    alert_style = ParagraphStyle('Alert', parent=styles['Normal'],
                                 fontSize=10, leading=14,
                                 backColor=colors.HexColor('#fff3cd'),
                                 borderColor=colors.HexColor('#ffc107'),
                                 borderWidth=1, borderPadding=8,
                                 spaceAfter=10)

    # ── PAGE DE GARDE ──────────────────────────────────────────────────────────
    story.append(Spacer(1, 3*cm))
    story.append(Paragraph("OBSERVATOIRE IMMOBILIER", titre_style))
    story.append(Paragraph("Marseille — Rapport d'Analyse Quotidien", sous_titre_style))
    story.append(Paragraph(f"Date : {date_str} | Heure : {heure_str}", sous_titre_style))
    story.append(Spacer(1, 1*cm))

    # Cadre intro
    story.append(Paragraph(
        "Rapport genere automatiquement par l'agent Api Immo. "
        "Sources : DVF (transactions notariales), PLU Geoportail IGN, "
        "DFI (divisions foncières), SITADEL (permis de construire). "
        "Analyse par Qwen 3.5 9B local.",
        body_style
    ))
    story.append(PageBreak())

    # ── SYNTHESE GLOBALE ───────────────────────────────────────────────────────
    story.append(Paragraph("1. SYNTHESE GLOBALE", h1_style))
    story.append(Paragraph(synthese_globale, body_style))
    story.append(Spacer(1, 0.5*cm))

    # ── TABLEAU COMPARATIF ─────────────────────────────────────────────────────
    story.append(Paragraph("2. TABLEAU COMPARATIF DES ARRONDISSEMENTS", h1_style))

    headers = ["Arrondissement", "Prix/m2", "Transactions", "Score", "Parcelles", "Ops MDB"]
    table_data = [headers]

    resultats_tries = sorted(
        [r for r in resultats if r.get("score")],
        key=lambda x: x["score"], reverse=True
    )

    for r in resultats_tries:
        table_data.append([
            r["nom"],
            f"{r['prix_m2']} EUR" if r["prix_m2"] else "N/A",
            str(r["nb_ventes"]) if r["nb_ventes"] else "N/A",
            f"{r['score']}/100" if r["score"] else "N/A",
            str(r["nb_parcelles_denses"]),
            str(r["nb_ops_marchands"]),
        ])

    t = Table(table_data, colWidths=[4*cm, 2.5*cm, 2.8*cm, 2*cm, 2.5*cm, 2.2*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a3a5c')),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 9),
        ('ALIGN',      (0,0), (-1,-1), 'CENTER'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f0f4f8')]),
        ('GRID',       (0,0), (-1,-1), 0.5, colors.HexColor('#cccccc')),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t)
    story.append(PageBreak())

    # ── TOP 3 OPPORTUNITES ─────────────────────────────────────────────────────
    story.append(Paragraph("3. TOP 3 OPPORTUNITES DU JOUR", h1_style))

    top3 = resultats_tries[:3]
    for i, r in enumerate(top3, 1):
        story.append(Paragraph(f"#{i} — {r['nom']}", h2_style))
        story.append(Paragraph(
            f"Score : {r['score']}/100 | Prix : {r['prix_m2']} EUR/m2 | "
            f"Parcelles densifiables : {r['nb_parcelles_denses']} | "
            f"Ops marchands : {r['nb_ops_marchands']}",
            body_style
        ))
        if r["analyse_qwen"] and not r["analyse_qwen"].startswith("[Qwen"):
            story.append(Paragraph(r["analyse_qwen"], alert_style))
        story.append(Spacer(1, 0.3*cm))

    story.append(PageBreak())

    # ── DETAIL PAR ARRONDISSEMENT ──────────────────────────────────────────────
    story.append(Paragraph("4. ANALYSE DETAILLEE PAR ARRONDISSEMENT", h1_style))

    for r in resultats_tries:
        story.append(Paragraph(r["nom"], h2_style))
        story.append(Paragraph(
            f"Prix moyen : {r['prix_m2']} EUR/m2 | "
            f"Transactions : {r['nb_ventes']} | "
            f"Score : {r['score']}/100 | "
            f"Zones PLU : {', '.join(r['zones_plu']) if r['zones_plu'] else 'N/A'}",
            body_style
        ))
        if r["analyse_qwen"] and not r["analyse_qwen"].startswith("[Qwen"):
            story.append(Paragraph(r["analyse_qwen"], body_style))
        story.append(Spacer(1, 0.2*cm))

    # Build
    doc.build(story)
    print(f"\n[PDF] Rapport genere : {filename}")
    return filename


# ─── BOUCLE PRINCIPALE DE L'AGENT ─────────────────────────────────────────────
def run_agent():
    """Analyse complete de Marseille + rapport PDF."""
    print(f"\n{'='*60}")
    print(f"[AGENT] Demarrage analyse Marseille — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    resultats = []

    # Analyse de chaque arrondissement
    for nom, code in ARRONDISSEMENTS_MARSEILLE:
        try:
            r = analyser_arrondissement(nom, code)
            resultats.append(r)
            time.sleep(1)  # Respect de l'API Flask
        except Exception as e:
            print(f"  [ERREUR] {nom} : {e}")

    print(f"\n[AGENT] {len(resultats)} arrondissements analyses. Generation synthese Qwen...")

    # Synthese globale par Qwen
    top_scores = sorted(
        [r for r in resultats if r.get("score")],
        key=lambda x: x["score"], reverse=True
    )[:5]

    resume = "\n".join([
        f"- {r['nom']}: score {r['score']}/100, {r['prix_m2']} EUR/m2, "
        f"{r['nb_parcelles_denses']} parcelles densifiables"
        for r in top_scores
    ])

    synthese = call_qwen(
        f"""Voici les 5 meilleurs arrondissements de Marseille aujourd'hui selon nos donnees :

{resume}

Redige une synthese executive de 5-6 phrases pour un investisseur immobilier :
- Vue d'ensemble du marche marseillais
- Zones a privilégier et pourquoi
- Risques eventuels a surveiller
- Recommandation strategique globale
""",
        system="Tu es un analyste immobilier senior specialise sur Marseille. Sois precis, factuel et actionnable."
    )

    # Generation rapport PDF
    pdf_path = generer_rapport_pdf(resultats, synthese)

    print(f"\n[AGENT] Analyse terminee.")
    print(f"[AGENT] Rapport : {pdf_path}")
    print(f"{'='*60}\n")
    return pdf_path


# ─── TESTS ────────────────────────────────────────────────────────────────────
def test_connexions():
    """Verifie que Qwen et Flask sont disponibles."""
    print("\n[TEST] Verification des connexions...")

    # Test Qwen
    rep = call_qwen("Dis juste 'OK' en un mot.")
    print(f"  Qwen : {'OK' if 'OK' in rep.upper() or len(rep) < 20 else rep[:50]}")

    # Test Flask
    try:
        r = requests.get(f"{FLASK_BASE}/api/dvf", params={"commune": "Marseille"}, timeout=15)
        print(f"  Flask DVF : {r.status_code} ({'OK' if r.ok else 'ERREUR'})")
    except Exception as e:
        print(f"  Flask : ERREUR — {e}")
        print("  → Lance d'abord : python app.py")

    print("[TEST] Termine.\n")


# ─── SCHEDULER 9H-18H ─────────────────────────────────────────────────────────
def demarrer_scheduler():
    """Lance l'agent chaque jour a 9h et 14h."""
    print("[SCHEDULER] Agent demarre. Execution planifiee a 9h00 et 14h00.")
    print("[SCHEDULER] Ctrl+C pour arreter.\n")

    schedule.every().day.at("09:00").do(run_agent)
    schedule.every().day.at("14:00").do(run_agent)

    while True:
        schedule.run_pending()
        time.sleep(60)


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if "--test" in sys.argv:
        test_connexions()
    elif "--now" in sys.argv:
        run_agent()
    else:
        demarrer_scheduler()
