"""
build_dfi_index.py
==================
Lit dfi.csv (local) et construit DEUX index :

1. cache/dfi_index.json
   { ref_parcelle_mere: [ref_fille1, ref_fille2, ...] }
   Clé = identifiant parcelle brut tel que présent dans le CSV.

2. cache/dfi_by_commune.json
   { code_insee_5chars: { ref_mere: [ref_fille, ...] } }
   Permet un lookup rapide par commune dans app.py.

Format attendu des refs parcellaires DFI (source Etalab) :
  - soit le format cadastral long : DDDCCSSSSPPPPNNNN (17 chars)
    ex: 01173000AI0551  → dept=01 commune=173 prefixe=000 section=AI numero=0551
  - soit section+numero court : AI0551

Le script détecte automatiquement la colonne code_commune si présente,
sinon extrait les 5 premiers chars de la ref mère (DDDCC).

dfi.csv ≈ 3.3 Go, ~30M lignes. Parse en streaming, ~5-8 min.
"""
import os, json, csv, sys, time

BASE_DIR  = os.path.dirname(__file__)
DATA_DIR  = os.path.join(BASE_DIR, "Data")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
OUTPUT         = os.path.join(CACHE_DIR, "dfi_index.json")
OUTPUT_COMMUNE = os.path.join(CACHE_DIR, "dfi_by_commune.json")
os.makedirs(CACHE_DIR, exist_ok=True)

DFI_CSV = os.path.join(DATA_DIR, "dfi.csv")


def ref_to_commune(ref: str) -> str:
    """
    Extrait le code INSEE (5 chars) depuis une référence parcellaire.
    Format Etalab DFI :
      - 14 chars : DDDCCSSSSNNNN  → [:5]
      - 17 chars : DDDCCPPPPSSNNNN → [:5]
      - court (lettres+chiffres) : inconnu → ""
    """
    ref = ref.strip()
    if len(ref) >= 14 and ref[:5].isdigit():
        return ref[:5]
    if len(ref) >= 5 and ref[:5].isdigit():
        return ref[:5]
    return ""


def main():
    if not os.path.exists(DFI_CSV):
        print(f"ERREUR : fichier introuvable : {DFI_CSV}")
        sys.exit(1)

    taille_go = os.path.getsize(DFI_CSV) / 1e9
    print(f"Lecture {DFI_CSV} ({taille_go:.1f} Go)...")
    print("Patience, ~5-8 minutes pour 3 Go...")

    # index global : ref_mere → [ref_fille, ...]
    index = {}
    # index par commune : code_insee → { ref_mere → [ref_fille, ...] }
    by_commune = {}

    n = 0
    n_skip_commune = 0
    t0 = time.time()

    with open(DFI_CSV, "r", encoding="utf-8-sig", errors="replace") as f:
        first = f.readline()
        sep = ";" if first.count(";") > first.count(",") else ","
        f.seek(0)

        reader = csv.DictReader(f, delimiter=sep)
        cols = reader.fieldnames or []
        print(f"Colonnes disponibles : {cols}")

        # Détection colonnes mère/fille
        col_mere  = next((c for c in cols if "mere"  in c.lower()), None)
        col_fille = next((c for c in cols if "fille" in c.lower()), None)

        if not col_mere or not col_fille:
            # Fallback : chercher des colonnes contenant "parcelle" ou "ref"
            candidates = [c for c in cols if any(k in c.lower() for k in ("parcelle", "ref", "id_"))]
            if len(candidates) >= 2:
                col_mere, col_fille = candidates[0], candidates[1]
                print(f"Fallback colonnes : mere='{col_mere}' fille='{col_fille}'")
            else:
                print(f"ERREUR : colonnes mere/fille introuvables dans {cols}")
                sys.exit(1)
        else:
            print(f"Colonnes utilisées : mere='{col_mere}' fille='{col_fille}'")

        # Colonne code_insee (présente dans ce fichier)
        col_commune = next((c for c in cols if c.lower() in ("code_insee", "code_commune", "insee")), None)
        if not col_commune:
            col_commune = next((c for c in cols if any(k in c.lower()
                                for k in ("insee", "commune"))), None)
        print(f"Colonne commune : {col_commune or '(non trouvée — extraction depuis ref)'}")

        for row in reader:
            mere  = row.get(col_mere,  "").strip()
            fille = row.get(col_fille, "").strip()

            if not mere or not fille or mere == fille:
                continue

            # ── Index global ───────────────────────────────────────────
            if mere not in index:
                index[mere] = []
            if len(index[mere]) < 50:
                if fille not in index[mere]:
                    index[mere].append(fille)

            # ── Index par commune ──────────────────────────────────────
            if col_commune:
                code = row.get(col_commune, "").strip().zfill(5)
            else:
                code = ref_to_commune(mere)

            if code and len(code) == 5 and code.isdigit():
                if code not in by_commune:
                    by_commune[code] = {}
                if mere not in by_commune[code]:
                    by_commune[code][mere] = []
                if len(by_commune[code][mere]) < 50 and fille not in by_commune[code][mere]:
                    by_commune[code][mere].append(fille)
            else:
                n_skip_commune += 1

            n += 1
            if n % 1_000_000 == 0:
                elapsed = time.time() - t0
                print(f"  {n/1e6:.0f}M lignes | {len(index):,} mères | "
                      f"{len(by_commune):,} communes | {elapsed:.0f}s")

    elapsed = time.time() - t0
    print(f"\nTerminé en {elapsed:.0f}s")
    print(f"  Parcelles mères     : {len(index):,}")
    print(f"  Liens filiation     : {sum(len(v) for v in index.values()):,}")
    print(f"  Communes indexées   : {len(by_commune):,}")
    print(f"  Lignes sans commune : {n_skip_commune:,}")

    print("\nSauvegarde dfi_index.json...")
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  → {os.path.getsize(OUTPUT)/1e6:.0f} Mo")

    print("Sauvegarde dfi_by_commune.json...")
    with open(OUTPUT_COMMUNE, "w", encoding="utf-8") as f:
        json.dump(by_commune, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  → {os.path.getsize(OUTPUT_COMMUNE)/1e6:.0f} Mo")

    print("\nRelancez app.py pour activer la TAB Marchands de Biens.")

    # Tests rapides
    print("\nTests :")
    for code, nom in [("13055","Marseille"),("75056","Paris"),("69123","Lyon")]:
        nb = len(by_commune.get(code, {}))
        print(f"  {nom} ({code}) : {nb} parcelles mères avec divisions")


if __name__ == "__main__":
    main()