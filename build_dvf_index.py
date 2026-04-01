"""
build_dvf_index.py
------------------
Lit les 4 fichiers full.csv.gz (France entière) et crée un fichier JSON
par commune dans cache/dvf/{code_commune}.json

A lancer UNE SEULE FOIS. Durée estimée : 5-15 min selon ton disque.
"""

import gzip, csv, json, os, time

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, "Data")
CACHE_DIR = os.path.join(BASE_DIR, "cache", "dvf")

DVF_FILES = {
    "2022": os.path.join(DATA_DIR, "full (2).csv.gz"),
    "2023": os.path.join(DATA_DIR, "full (1).csv.gz"),
    "2024": os.path.join(DATA_DIR, "full.csv.gz"),
    "2025": os.path.join(DATA_DIR, "full (3).csv.gz"),
}

CHAMPS = [
    "date_mutation", "valeur_fonciere", "surface_reelle_bati",
    "surface_terrain", "type_local", "adresse_numero", "adresse_nom_voie",
    "nature_mutation", "code_commune", "nom_commune", "id_parcelle",
]

os.makedirs(CACHE_DIR, exist_ok=True)

communes  = {}
seen_ids  = set()
total     = 0
t0        = time.time()

for annee, gz_path in DVF_FILES.items():
    if not os.path.exists(gz_path):
        print(f"[SKIP] {gz_path}")
        continue
    print(f"\n[{annee}] {os.path.basename(gz_path)}...")
    t1 = time.time()
    n  = 0
    with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            n += 1
            if n % 500_000 == 0:
                print(f"  {n:,} lignes... ({time.time()-t1:.0f}s)")
            mid  = row.get("id_mutation", "")
            code = row.get("code_commune", "")
            if not code:
                continue
            uid = f"{mid}_{annee}"
            if uid in seen_ids:
                continue
            seen_ids.add(uid)
            mut = {}
            for c in CHAMPS:
                v = row.get(c, "")
                if c in ("valeur_fonciere", "surface_reelle_bati", "surface_terrain"):
                    v = v.replace(",", ".")
                mut[c] = v
            communes.setdefault(code, []).append(mut)
    print(f"  -> {n:,} lignes en {time.time()-t1:.1f}s")
    total += n

print(f"\n[INDEX] {len(communes):,} communes, {total:,} lignes")
print("[INDEX] Ecriture JSON...")
t2 = time.time()
for i, (code, muts) in enumerate(communes.items()):
    with open(os.path.join(CACHE_DIR, f"{code}.json"), "w", encoding="utf-8") as f:
        json.dump(muts, f, ensure_ascii=False, separators=(",", ":"))
    if (i+1) % 5000 == 0:
        print(f"  {i+1:,}/{len(communes):,}...")

print(f"  -> {len(communes):,} fichiers en {time.time()-t2:.1f}s")
print(f"\nTermine en {(time.time()-t0)/60:.1f} minutes")
print(f"Index dans : {CACHE_DIR}")