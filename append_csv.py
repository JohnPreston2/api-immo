import csv
import json

csv_file = r"C:\Users\HUGO\Desktop\Api Immo\rapports\all-listings-seloger.csv"
json_file = r"C:\tmp\listings-seloger-21.json"

with open(json_file, 'r', encoding='utf-8') as f:
    listings = json.load(f)

with open(csv_file, 'a', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    for item in listings:
        writer.writerow([
            item['titre'],
            item['prix'].replace(' €', ''),
            item['surface'].replace(' m²', ''),
            item['localisation'],
            item['url'],
            '21'
        ])

print(f"Appended {len(listings)} listings to CSV")
