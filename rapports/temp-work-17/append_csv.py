import json
from datetime import datetime

csv_path = r'C:\Users\HUGO\Desktop\Api Immo\rapports\all-listings.csv'
json_path = '/tmp/listings-19.json'

# Read JSON
with open(json_path, 'r') as f:
    data = json.load(f)

# Read CSV to get max ID
with open(csv_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()
    last_id = int(lines[-1].split(',')[0])

# Prepare new rows
timestamp = datetime.utcnow().isoformat() + 'Z'
new_rows = []
next_id = last_id + 1

for listing in data['listings']:
    title = listing['titre'].replace('"', '""')
    location = listing['localisation'].replace('"', '""')
    surface = listing['surface'].replace(' m²', '')
    row = f'{next_id},19,"{title}",{listing["prix"]},{surface},"{location}",{listing["url"]},{timestamp}\n'
    new_rows.append(row)
    next_id += 1

# Append to CSV
with open(csv_path, 'a', encoding='utf-8') as f:
    f.writelines(new_rows)

print(f'Appended 10 listings to CSV (IDs 200-209)')
