content = open("app.py", encoding="utf-8", errors="replace").read()

old = """    # Mutations DVF pour la commune
    dvf_path = os.path.join(DVF_INDEX_DIR, f"{code_insee}.json")
    mutations_dvf = _cache_load(code_insee) or []
    if not mutations_dvf and os.path.exists(dvf_path):
        try:
            with open(dvf_path, "r", encoding="utf-8") as f:
                mutations_dvf = json.load(f)
            _cache_save(code_insee, mutations_dvf)
        except Exception as e:
            print(f"[MARCHANDS] Erreur lecture DVF: {e}")"""

new = """    # Mutations DVF pour la commune (gere arrondissements Paris/Lyon/Marseille)
    mutations_dvf = _cache_load(code_insee) or []
    if not mutations_dvf:
        codes_dvf = ARRONDISSEMENTS.get(code_insee, [code_insee])
        for code_dvf in codes_dvf:
            dvf_path = os.path.join(DVF_INDEX_DIR, f"{code_dvf}.json")
            if os.path.exists(dvf_path):
                try:
                    with open(dvf_path, "r", encoding="utf-8") as f:
                        mutations_dvf.extend(json.load(f))
                except Exception as e:
                    print(f"[MARCHANDS] Erreur lecture DVF {code_dvf}: {e}")
        if mutations_dvf:
            _cache_save(code_insee, mutations_dvf)"""

content = content.replace(old, new)
open("app.py", "w", encoding="utf-8").write(content)
print("OK" if "codes_dvf = ARRONDISSEMENTS" in content else "PATCH ECHOUE")
