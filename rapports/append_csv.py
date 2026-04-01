import json
import csv

# Read JSON
with open('/tmp/listings-seloger-5.json') as f:
    listings = json.load(f)

# Append to CSV
csv_path = r'C:\Users\HUGO\Desktop\Api Immo\rapports\all-listings-seloger.csv'

with open(csv_path, 'a', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    for listing in listings:
        writer.writerow([
            listing['titre'],
            listing['prix'],
            listing['surface'],
            listing['localisation'],
            listing['url'],
            '5'
        ])

print('OK: CSV appended - 10 listings from page 5')
