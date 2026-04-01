content = open("app.py", encoding="utf-8", errors="replace").read()
# Trouver le bloc de chargement DVF dans api_marchands
idx_start = content.find("def api_marchands")
idx_end = content.find("\n@app.route", idx_start + 1)
bloc = content[idx_start:idx_end]
# Chercher la partie DVF
for keyword in ["dvf_path", "mutations_dvf", "DVF_INDEX", "json.load"]:
    idx = bloc.find(keyword)
    if idx != -1:
        print(f"=== {keyword} ===")
        print(bloc[max(0,idx-50):idx+200])
        print()
