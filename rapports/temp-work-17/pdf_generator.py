#!/usr/bin/env python3
import json
import sys
from datetime import datetime

def generate_pdf(json_path, output_path, page_num):
    """Generate a simple PDF report from listings JSON"""
    
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib import colors
    except ImportError:
        print("reportlab not installed, using fpdf2 fallback...")
        from fpdf import FPDF
        
        with open(json_path, 'r') as f:
            data = json.load(f)
        
        # Handle both array and object formats
        listings = data if isinstance(data, list) else data.get('listings', [])
        
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(0, 10, f'Listings Marseille - Page {page_num}', ln=True)
        pdf.ln(5)
        
        pdf.set_font('Arial', '', 10)
        for i, listing in enumerate(listings, 1):
            pdf.set_font('Arial', 'B', 10)
            title = listing.get('titre') or listing.get('title', 'N/A')
            pdf.cell(0, 5, f"{i}. {title}", ln=True)
            pdf.set_font('Arial', '', 9)
            price = listing.get('prix') or listing.get('price', 'N/A')
            surface = listing.get('surface', 'N/A')
            location = listing.get('localisation') or listing.get('location', 'N/A')
            url = listing.get('url', 'N/A')
            pdf.cell(0, 4, f"Prix: {price} | Surface: {surface}", ln=True)
            pdf.cell(0, 4, f"Localisation: {location}", ln=True)
            pdf.cell(0, 4, f"URL: {url[:50] if url != 'N/A' else 'N/A'}...", ln=True)
            pdf.ln(2)
        
        pdf.output(output_path)
        print(f"PDF generated: {output_path}")
        return
    
    # Use reportlab if available
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    # Handle both array and object formats
    listings = data if isinstance(data, list) else data.get('listings', [])
    
    pdf = SimpleDocTemplate(output_path, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title = Paragraph(f"Listings Marseille - Page {page_num}", styles['Title'])
    story.append(title)
    story.append(Spacer(1, 0.3*inch))
    
    # Table data
    table_data = [['Titre', 'Prix', 'Surface', 'Localisation']]
    for listing in listings:
        title = (listing.get('titre') or listing.get('title', 'N/A'))[:30]
        price = listing.get('prix') or listing.get('price', 'N/A')
        surface = listing.get('surface', 'N/A')
        location = (listing.get('localisation') or listing.get('location', 'N/A'))[:20]
        table_data.append([
            title,
            str(price),
            str(surface),
            location
        ])
    
    table = Table(table_data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    
    story.append(table)
    pdf.build(story)
    print(f"PDF generated: {output_path}")

if __name__ == '__main__':
    json_path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/listings-19.json'
    output_path = sys.argv[2] if len(sys.argv) > 2 else '/tmp/output-19.pdf'
    page_num = sys.argv[3] if len(sys.argv) > 3 else '19'
    
    generate_pdf(json_path, output_path, page_num)
