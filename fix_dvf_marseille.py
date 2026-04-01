content = open("app.py", encoding="utf-8").read()

old = '''    dvf_path = os.path.join(DVF_INDEX_DIR, f"{code_insee}.json")
    mutations_dvf = []
    if os.path.exists(dvf_path):
        try:
            with open(dvf_path, "r", encoding="utf-8") as f:
                mutations_dvf = json.load(f)
        except:
            pass'''

new = '''    # Charger DVF - gerer arrondissements pour Paris/Lyon/Marseille
    mutations_dvf = []
    codes_dvf = ARRONDISSEMENTS.get(code_insee, [code_insee])
    for code_dvf in codes_dvf:
        dvf_path = os.path.join(DVF_INDEX_DIR, f"{code_dvf}.json")
        if os.path.exists(dvf_path):
            try:
                with open(dvf_path, "r", encoding="utf-8") as f:
                    mutations_dvf.extend(json.load(f))
            except:
                pass'''

content = content.replace(old, new)
open("app.py", "w", encoding="utf-8").write(content)
print("OK")
