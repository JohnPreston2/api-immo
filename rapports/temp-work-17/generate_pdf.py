import json
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from datetime import datetime

# Lire le fichier JSON
with open('/tmp/listings-seloger-12.json', 'r', encoding='utf-8') as f:
    listings = json.load(f)

# Créer le PDF
pdf_filename = '/tmp/output-seloger-12.pdf'
doc = SimpleDocTemplate(pdf_filename, pagesize=A4, rightMargin=0.5*inch, leftMargin=0.5*inch,
                        topMargin=0.75*inch, bottomMargin=0.75*inch)

# Style
styles = getSampleStyleSheet()
title_style = ParagraphStyle(
    'CustomTitle',
    parent=styles['Heading1'],
    fontSize=24,
    textColor=colors.HexColor('#1a3a52'),
    spaceAfter=12,
    alignment=TA_CENTER,
    fontName='Helvetica-Bold'
)

subtitle_style = ParagraphStyle(
    'SubTitle',
    parent=styles['Normal'],
    fontSize=11,
    textColor=colors.HexColor('#666666'),
    spaceAfter=20,
    alignment=TA_CENTER,
    fontName='Helvetica'
)

listing_title_style = ParagraphStyle(
    'ListingTitle',
    parent=styles['Normal'],
    fontSize=11,
    textColor=colors.HexColor('#1a3a52'),
    fontName='Helvetica-Bold'
)

listing_text_style = ParagraphStyle(
    'ListingText',
    parent=styles['Normal'],
    fontSize=9,
    textColor=colors.HexColor('#333333'),
    fontName='Helvetica'
)

# Construire le contenu
elements = []

# Titre
elements.append(Paragraph("SeLoger Listings - Page 12", title_style))
elements.append(Paragraph(f"Annonces immobilières à Marseille | {datetime.now().strftime('%d/%m/%Y')}", subtitle_style))

# Créer le tableau avec les annonces
data = [['N°', 'Annonce', 'Prix', 'Surface', 'Localisation']]

for idx, listing in enumerate(listings, 1):
    title = listing.get('titre', 'N/A')
    prix = listing.get('prix', 'N/A')
    surface = listing.get('surface', 'N/A')
    localisation = listing.get('localisation', 'N/A')
    url = listing.get('url', '')
    
    # Créer un lien cliquable dans le titre
    if url:
        title_with_link = f'<a href="{url}" color="blue"><u>{title}</u></a>'
    else:
        title_with_link = title
    
    data.append([
        str(idx),
        Paragraph(title_with_link, listing_text_style),
        prix,
        surface,
        localisation
    ])

# Créer le tableau
table = Table(data, colWidths=[0.5*cm, 6.5*cm, 1.8*cm, 1.5*cm, 2.7*cm])

# Style du tableau
table.setStyle(TableStyle([
    # Header
    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3a52')),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
    ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
    ('FONTSIZE', (0, 0), (-1, 0), 10),
    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
    ('TOPPADDING', (0, 0), (-1, 0), 12),
    
    # Corps du tableau
    ('ALIGN', (0, 1), (0, -1), 'CENTER'),
    ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
    ('ALIGN', (3, 1), (3, -1), 'RIGHT'),
    ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
    ('FONTSIZE', (0, 1), (-1, -1), 9),
    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
    ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cccccc')),
    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ('TOPPADDING', (0, 1), (-1, -1), 8),
    ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
]))

elements.append(table)

# Footer
elements.append(Spacer(1, 0.5*inch))
footer_text = f"<i>Extrait de SeLoger - Page 12 | Total: {len(listings)} annonces</i>"
elements.append(Paragraph(footer_text, ParagraphStyle(
    'Footer',
    parent=styles['Normal'],
    fontSize=8,
    textColor=colors.HexColor('#999999'),
    alignment=TA_CENTER
)))

# Générer le PDF
doc.build(elements)

print(f"PDF généré avec succès: {pdf_filename}")
