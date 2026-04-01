"""
build_insee_pop_index.py - Genere cache/insee_pop.json
Source 1 : geo.api.gouv.fr (toutes communes, population 2023, rapide)
Source 2 : ZIPs millesimes INSEE.fr (historique 2015-2021)
Usage : python build_insee_pop_index.py
"""

import os, json, csv, io, sys, zipfile, requests, time

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
OUTPUT    = os.path.join(CACHE_DIR, "insee_pop.json")
os.makedirs(CACHE_DIR, exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 ApiImmo/1.0"}

MILLESIMES = {
    "2018": "https://www.insee.fr/fr/statistiques/fichier/3698339/ensemble.zip",
    "2019": "https://www.insee.fr/fr/statistiques/fichier/4265429/ensemble.zip",
    "2020": "https://www.insee.fr/fr/statistiques/fichier/6683035/ensemble.zip",
    "2021": "https://www.insee.fr/fr/statistiques/fichier/7739582/ensemble.zip",
}


def source_geoapi():
    print("[Source 1] geo.api.gouv.fr - population 2023...")
    r = requests.get(
        "https://geo.api.gouv.fr/communes",
        params={"fields": "code,population", "format": "json", "geometry": "none"},
        headers=HEADERS, timeout=60
    )
    r.raise_for_status()
    communes = r.json()
    index = {}
    for c in communes:
        code = c.get("code", "")
        pop  = c.get("population")
        if code and pop:
            index[code] = {"2023": int(pop)}
    print(f"  -> {len(index):,} communes")
    return index


def parse_insee_zip(content):
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        csv_files = [n for n in z.namelist() if n.endswith(".csv")]
        target = None
        for name in csv_files:
            low = name.lower()
            if "com" in low or "ensemble" in low:
                target = name
                break
        if not target:
            target = csv_files[0]
        text = z.read(target).decode("utf-8-sig", errors="replace")

    sep = ";" if text.count(";") > text.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=sep)

    result = {}
    for row in reader:
        typecom = row.get("TYPECOM", row.get("typecom", "COM"))
        if typecom not in ("COM", "ARM", ""):
            continue
        code = (row.get("COM") or row.get("CODGEO") or "").strip()
        if not code or len(code) < 5:
            continue
        pop_str = (row.get("PMUN") or row.get("pmun") or
                   row.get("Population municipale") or "").strip()
        try:
            pop = int(float(pop_str.replace(" ", "").replace("\xa0", "")))
            if pop > 0:
                result[code] = pop
        except:
            continue
    return result


def source_millesimes(index_base):
    print("\n[Source 2] Fichiers millesimes INSEE.fr...")
    for annee, url in sorted(MILLESIMES.items()):
        print(f"  Millesime {annee}... ", end="", flush=True)
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 404:
                print("404 - ignore")
                continue
            r.raise_for_status()
            data = parse_insee_zip(r.content)
            if not data:
                print("vide - ignore")
                continue
            n = 0
            for code, pop in data.items():
                if code in index_base:
                    index_base[code][annee] = pop
                    n += 1
            print(f"{n:,} communes enrichies")
            time.sleep(0.5)
        except Exception as e:
            print(f"ECHEC : {e}")
    return index_base


def main():
    print("=" * 60)
    index = source_geoapi()
    if not index:
        print("ERREUR : impossible de charger les communes.")
        sys.exit(1)

    print("\n" + "=" * 60)
    index = source_millesimes(index)

    nb_1an  = sum(1 for v in index.values() if len(v) == 1)
    nb_hist = sum(1 for v in index.values() if len(v) > 1)
    print(f"\n  Communes avec 1 annee   : {nb_1an:,}")
    print(f"  Communes avec historique: {nb_hist:,}")

    print("\n" + "=" * 60)
    print("TESTS")
    for code, nom in [("13055","Marseille"),("75056","Paris"),("69123","Lyon"),("06088","Nice")]:
        data = index.get(code, {})
        annees = sorted(data.keys())
        if annees:
            print(f"  {nom} ({code}) : {annees} -> pop {data[annees[-1]]:,}")
        else:
            print(f"  {nom} ({code}) : ABSENT")

    # Patch grandes villes (arrondissements non presents dans ZIP INSEE)
    # Populations municipales INSEE 2021 officielles
    PATCH_2021 = {
        "13055": 868277,   # Marseille
        "75056": 2145906,  # Paris
        "69123": 522228,   # Lyon
    }
    for code, pop in PATCH_2021.items():
        if code in index and "2021" not in index[code]:
            index[code]["2021"] = pop
            print(f"  Patch 2021 : {code} -> {pop:,}")

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))

    taille_ko = os.path.getsize(OUTPUT) / 1024
    print(f"\nOK : {OUTPUT}")
    print(f"   {len(index):,} communes - {taille_ko:.0f} Ko")
    print("\nRelancez app.py pour activer l'historique.")


if __name__ == "__main__":
    main()
