content = open("app.py", encoding="utf-8").read()

# Remplacer le loader DFI
old = '''def get_dfi_index():
    global _dfi_cache
    if _dfi_cache is None and os.path.exists(DFI_INDEX):
        with open(DFI_INDEX, "r", encoding="utf-8") as f:
            _dfi_cache = json.load(f)
    return _dfi_cache or {}'''

new = '''DFI_BY_COMMUNE = os.path.join(os.path.dirname(__file__), "cache", "dfi_by_commune.json")

def get_dfi_index():
    global _dfi_cache
    if _dfi_cache is None:
        path = DFI_BY_COMMUNE if os.path.exists(DFI_BY_COMMUNE) else DFI_INDEX
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                _dfi_cache = json.load(f)
    return _dfi_cache or {}'''

content = content.replace(old, new)

# Remplacer la logique de matching dans api_marchands
old = '''    # DFI pour la commune (divisions)
    divisions_commune = {
        k: v for k, v in dfi.items()
        if k.startswith(code_insee) or k.startswith(code_insee[2:])
    }'''

new = '''    # DFI pour la commune - utiliser dfi_by_commune structure
    # Format : {code_insee: {parcelle_mere: [parcelle_fille1, ...]}}
    if code_insee in dfi:
        # Format by_commune direct
        divisions_commune = dfi[code_insee]
    else:
        # Fallback : chercher arrondissements
        divisions_commune = {}
        codes = ARRONDISSEMENTS.get(code_insee, [code_insee])
        for code in codes:
            if code in dfi:
                divisions_commune.update(dfi[code])'''

content = content.replace(old, new)

# Fixer le matching DVF - utiliser cle courte (section+numero) car DVF id_parcelle = CCCCCPPPPSSNNNNN
old = '''    dvf_par_parcelle = {}
    for m in mutations_dvf:
        id_parc = m.get("id_parcelle", "").strip()
        if id_parc and len(id_parc) >= 6:
            # Cle courte = 6 derniers chars (section 1-2 lettres + numero 4 chiffres)
            ref_court = id_parc[-6:].lstrip("0") or id_parc[-6:]
            # Aussi stocker la version brute pour matching exact
            refs = {id_parc[-6:], id_parc[8:] if len(id_parc) >= 14 else ""}
            refs.discard("")
        else:
            refs = set()

        for ref in refs:
            if not ref:
                continue
            if ref not in dvf_par_parcelle:
                dvf_par_parcelle[ref] = []
            dvf_par_parcelle[ref].append({
                "date": m.get("date_mutation", ""),
                "valeur": m.get("valeur_fonciere", 0),
                "nature": m.get("nature_mutation", ""),
                "type_local": m.get("type_local", ""),
                "surface": m.get("surface_reelle_bati", 0) or m.get("surface_terrain", 0),
                "id_parcelle": id_parc,
            })'''

new = '''    dvf_par_parcelle = {}
    for m in mutations_dvf:
        id_parc = m.get("id_parcelle", "").strip()
        # Format DVF id_parcelle = 14 chars : CCCCC + PPP + SS + NNNN
        # ex: 132018040A0145 -> section=A numero=0145 -> cle=A0145
        # DFI parcelle_mere = section + numero ex: A0145
        if id_parc and len(id_parc) >= 14:
            # Extraire section (1-2 lettres) + numero (4 chiffres) = derniers chars apres code commune
            ref = id_parc[8:]   # retire CCCCCPPP -> garde SS+NNNN ex: 40A0145
            # Normaliser : trouver la lettre et ce qui suit
            import re as _re
            m_ref = _re.search(r"([A-Z]{1,2}\d{4})$", id_parc)
            cle = m_ref.group(1) if m_ref else id_parc[-6:]
        elif id_parc:
            cle = id_parc
        else:
            continue

        if cle not in dvf_par_parcelle:
            dvf_par_parcelle[cle] = []
        dvf_par_parcelle[cle].append({
            "date": m.get("date_mutation", ""),
            "valeur": float(m.get("valeur_fonciere") or 0),
            "nature": m.get("nature_mutation", ""),
            "type_local": m.get("type_local", ""),
            "surface": float(m.get("surface_reelle_bati") or m.get("surface_terrain") or 0),
            "id_parcelle": id_parc,
        })'''

content = content.replace(old, new)

open("app.py", "w", encoding="utf-8").write(content)
print("OK")
