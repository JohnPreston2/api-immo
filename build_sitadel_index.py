"""
build_sitadel_index.py
======================
Lit les CSV SITADEL locaux et construit cache/sitadel_index.json
{ code_insee: [ {ref_dossier, annee, type, ref_cadastrale, nb_logements}, ... ] }

Fichiers lus :
- Liste-des-autorisations-durbanisme-crea...csv (x2) -> PC logements
- Liste-des-permis-de-damenager.2026-01.csv
- Liste-des-permis-de-demolir.2026-01.csv
"""
import os, json, csv, sys, glob, time

BASE_DIR  = os.path.dirname(__file__)
DATA_DIR  = os.path.join(BASE_DIR, "Data")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
OUTPUT    = os.path.join(CACHE_DIR, "sitadel_index.json")
os.makedirs(CACHE_DIR, exist_ok=True)


def detecter_colonnes(cols):
    """Retourne un dict des colonnes utiles."""
    cols_lower = {c.lower(): c for c in cols}

    def find(*keywords):
        for kw in keywords:
            for cl, orig in cols_lower.items():
                if kw in cl:
                    return orig
        return None

    return {
        "code"  : find("dep_com", "com_cod", "commune", "insee", "code de la commune"),
        "ref"   : find("num_dossier", "numero", "ref_dos", "num\u00e9ro", "identifiant"),
        "annee" : find("annee", "date_depot", "date_autor", "ann\u00e9e", "date de"),
        "type"  : find("type_dos", "type_aut", "nature", "nature du"),
        "cad"   : find("ref_cad", "parcelle", "cadastr", "num\u00e9ro parcelle"),
        "logts" : find("nb_logement", "logement_cree", "nb_lot", "logements", "nombre de log"),
    }


def parse_csv(filepath, type_defaut="PC"):
    print(f"  Lecture {os.path.basename(filepath)}...")
    index = {}
    n = 0

    with open(filepath, "r", encoding="utf-8-sig", errors="replace") as f:
        first = f.readline()
        sep = ";" if first.count(";") > first.count(",") else ","
        f.seek(0)
        reader = csv.DictReader(f, delimiter=sep)
        cols = reader.fieldnames or []

        if not cols:
            print("    Vide ou non parseable")
            return {}

        mapping = detecter_colonnes(cols)
        col_code = mapping["code"]
        if not col_code:
            print(f"    ERREUR : colonne commune/INSEE introuvable dans {cols[:8]}")
            return {}

        print(f"    Colonnes detectees : {mapping}")

        for row in reader:
            code = row.get(col_code, "").strip()
            if not code:
                continue

            # Normalisation code INSEE : peut etre "75056", "075056", "750", etc.
            code = code.zfill(5) if len(code) <= 5 else code[:5]

            annee = ""
            if mapping["annee"]:
                val = row.get(mapping["annee"], "")
                annee = str(val).strip()[:4] if val else ""

            ref = row.get(mapping["ref"], "").strip() if mapping["ref"] else ""
            type_dos = row.get(mapping["type"], type_defaut).strip() if mapping["type"] else type_defaut
            ref_cad = row.get(mapping["cad"], "").strip() if mapping["cad"] else ""

            nb_log = 0
            if mapping["logts"]:
                try:
                    nb_log = int(float(row.get(mapping["logts"], 0) or 0))
                except:
                    pass

            if code not in index:
                index[code] = []

            index[code].append({
                "ref_dossier"   : ref,
                "annee"         : annee,
                "type_dossier"  : type_dos,
                "ref_cadastrale": ref_cad,
                "nb_logements"  : nb_log,
            })
            n += 1
            if n % 100_000 == 0:
                print(f"    {n:,} permis, {len(index):,} communes...")

    print(f"    -> {n:,} permis, {len(index):,} communes")
    return index


def merge(index_total, index_nouveau):
    for code, permis in index_nouveau.items():
        if code not in index_total:
            index_total[code] = []
        index_total[code].extend(permis)
    return index_total


def main():
    print("=" * 60)

    # Trouver tous les CSV SITADEL dans Data/
    patterns = [
        os.path.join(DATA_DIR, "Liste-des-autorisations-durbanisme*.csv"),
        os.path.join(DATA_DIR, "Liste-des-permis-de-damenager*.csv"),
        os.path.join(DATA_DIR, "Liste-des-permis-de-demolir*.csv"),
    ]

    fichiers = []
    for pattern in patterns:
        fichiers.extend(glob.glob(pattern))

    if not fichiers:
        print(f"ERREUR : aucun fichier SITADEL trouve dans {DATA_DIR}")
        print("Fichiers attendus : Liste-des-autorisations-durbanisme*.csv")
        sys.exit(1)

    print(f"Fichiers trouves : {len(fichiers)}")
    for f in fichiers:
        taille = os.path.getsize(f) / 1e6
        print(f"  {os.path.basename(f)} ({taille:.0f} Mo)")

    index_total = {}
    t0 = time.time()

    for filepath in sorted(fichiers):
        nom = os.path.basename(filepath).lower()
        if "damenager" in nom:
            type_def = "PA"
        elif "demolir" in nom:
            type_def = "PD"
        else:
            type_def = "PC"

        idx = parse_csv(filepath, type_def)
        index_total = merge(index_total, idx)

    elapsed = time.time() - t0
    nb_communes = len(index_total)
    nb_permis   = sum(len(v) for v in index_total.values())

    print(f"\nTermine en {elapsed:.0f}s")
    print(f"  Communes : {nb_communes:,}")
    print(f"  Permis   : {nb_permis:,}")

    # Tests
    for code, nom in [("13055","Marseille"), ("75056","Paris"), ("69123","Lyon")]:
        nb = len(index_total.get(code, []))
        print(f"  {nom} ({code}) : {nb} permis")

    print("Sauvegarde JSON...")
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(index_total, f, ensure_ascii=False, separators=(",", ":"))

    taille_mo = os.path.getsize(OUTPUT) / 1e6
    print(f"\nOK : {OUTPUT} ({taille_mo:.0f} Mo)")
    print("Relancez app.py pour activer la TAB Marchands de Biens.")


if __name__ == "__main__":
    main()
