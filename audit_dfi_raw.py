import csv, os
from pathlib import Path

dfi_path = Path("Data/dfi.csv")
if not dfi_path.exists():
    print("dfi.csv absent")
    exit()

print(f"Taille : {dfi_path.stat().st_size / 1e9:.1f} Go")

with open(dfi_path, "r", encoding="utf-8-sig", errors="replace") as f:
    first = f.readline()
    sep = ";" if first.count(";") > first.count(",") else ","
    f.seek(0)
    reader = csv.DictReader(f, delimiter=sep)
    cols = reader.fieldnames or []
    print(f"Colonnes : {cols}")
    print()
    print("=== 15 premieres lignes ===")
    for i, row in enumerate(reader):
        if i >= 15:
            break
        print(dict(row))
