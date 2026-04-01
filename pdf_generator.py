import json
import sys
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from datetime import datetime

# Load JSON
json_path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/listings-seloger-14.json'
pdf_path = sys.argv[2] if len(sys.argv) > 2 else '/tmp/listings-seloger-14.pdf'

with open(json_path, 'r', encoding='utf-8') as f:
    listings = json.load(f)

# Create PDF
doc = SimpleDocTemplate(pdf_path, pagesize=A4)
styles = getSampleStyleSheet()
story = []

# Title
title_style = ParagraphStyle(
    'CustomTitle',
    parent=styles['Heading1'],
    fontSize=24,
    textColor=colors.HexColor('#1f4788'),
    spaceAfter=30,
    alignment=1
)
story.append(Paragraph('Listings SeLoger - Page 14', title_style))
story.append(Spacer(1, 0.3*inch))

# Metadata
now = datetime.now().strftime("%d/%m/%Y à %H:%M")
meta_text = f'Rapport généré le {now}<br/>Total annonces: {len(listings)}'
story.append(Paragraph(meta_text, styles['Normal']))
story.append(Spacer(1, 0.3*inch))

# Table data
table_data = [['Titre', 'Prix', 'Surface (m²)', 'Localisation']]
for listing in listings:
    titre = listing['titre'][:50] + '...' if len(listing['titre']) > 50 else listing['titre']
    prix = "{:,.0f}€".format(listing['prix'])
    surface = str(listing['surface'])
    localisation = listing['localisation'][:30]
    table_data.append([titre, prix, surface, localisation])

# Create table
t = Table(table_data, colWidths=[2.5*inch, 1.2*inch, 1*inch, 2*inch])
t.setStyle(TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f4788')),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
    ('FONTSIZE', (0, 0), (-1, 0), 10),
    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
    ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ('FONTSIZE', (0, 1), (-1, -1), 9),
    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
]))
story.append(t)

# Stats
story.append(Spacer(1, 0.3*inch))
avg_price = sum(l['prix'] for l in listings) / len(listings)
avg_surface = sum(l['surface'] for l in listings) / len(listings)
stats = '<b>Statistiques:</b><br/>Prix moyen: {:.0f}€ | Surface moyenne: {:.1f}m²'.format(avg_price, avg_surface)
story.append(Paragraph(stats, styles['Normal']))

# Build PDF
doc.build(story)
print('PDF generated: {}'.format(pdf_path))
