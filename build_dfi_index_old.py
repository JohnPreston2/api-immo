"""
build_dfi_index.py
==================
Lit dfi.csv (local) et construit cache/dfi_index.json
{ parcelle_mere: [parcelle_fille1, parcelle_fille2, ...] }

dfi.csv = 3.3 Go, ~30M lignes. Parse en streaming, ~5 min.
"""
import os, json, csv, sys, time

BASE_DIR  = os.path.dirname(__file__)
DATA_DIR  = os.path.join(BASE_DIR, "Data")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
OUTPUT    = os.path.join(CACHE_DIR, "dfi_index.json")
os.makedirs(CACHE_DIR, exist_ok=True)

DFI_CSV = os.path.join(DATA_DIR, "dfi.csv")


def main():
    if not os.path.exists(DFI_CSV):
        print(f"ERREUR : fichier introuvable : {DFI_CSV}")
        sys.exit(1)

    taille_go = os.path.getsize(DFI_CSV) / 1e9
    print(f"Lecture {DFI_CSV} ({taille_go:.1f} Go)...")
    print("Patience, ~5 minutes pour 3 Go...")

    index = {}
    n = 0
    t0 = time.time()

    with open(DFI_CSV, "r", encoding="utf-8-sig", errors="replace") as f:
        # Detecter separateur sur la 1ere ligne
        first = f.readline()
        sep = ";" if first.count(";") > first.count(",") else ","
        f.seek(0)

        reader = csv.DictReader(f, delimiter=sep)
        cols = reader.fieldnames or []
        print(f"Colonnes : {cols}")

        # Detection colonnes mere/fille
        col_mere  = next((c for c in cols if "mere"  in c.lower()), None)
        col_fille = next((c for c in cols if "fille" in c.lower()), None)

        if not col_mere or not col_fille:
            print(f"ERREUR : colonnes mere/fille non trouvees dans {cols}")
            sys.exit(1)

        print(f"Colonnes utilisees : mere='{col_mere}' fille='{col_fille}'")

        for row in reader:
            mere  = row.get(col_mere,  "").strip()
            fille = row.get(col_fille, "").strip()

            if not mere or not fille or mere == fille:
                continue

            if mere not in index:
                index[mere] = []
            # Eviter doublons (liste peut grandir)
            if len(index[mere]) < 20:  # cap par mere
                index[mere].append(fille)

            n += 1
            if n % 1_000_000 == 0:
                elapsed = time.time() - t0
                print(f"  {n/1e6:.0f}M lignes | {len(index):,} parcelles meres | {elapsed:.0f}s")

    elapsed = time.time() - t0
    nb_meres  = len(index)
    nb_filles = sum(len(v) for v in index.values())
    print(f"\nTermine en {elapsed:.0f}s")
    print(f"  Parcelles meres  : {nb_meres:,}")
    print(f"  Liens filiation  : {nb_filles:,}")

    print("Sauvegarde JSON...")
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))

    taille_mo = os.path.getsize(OUTPUT) / 1e6
    print(f"\nOK : {OUTPUT} ({taille_mo:.0f} Mo)")
    print("Relancez app.py pour activer la TAB Marchands de Biens.")


if __name__ == "__main__":
    main()
