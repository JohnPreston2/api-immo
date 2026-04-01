content = open("build_dfi_index.py", encoding="utf-8").read()

# Remplacer la logique de cle
old = """        if mere not in index:
                index[mere] = []
            # Eviter doublons (liste peut grandir)
            if len(index[mere]) < 20:  # cap par mere
                index[mere].append(fille)"""

new = """        # Cle complete = code_insee + parcelle pour eviter collisions inter-communes
            code_insee = row.get("code_insee", "").strip()
            if not code_insee:
                continue
            cle_mere  = f"{code_insee}_{mere}"
            cle_fille = f"{code_insee}_{fille}"
            if cle_mere not in index:
                index[cle_mere] = []
            if len(index[cle_mere]) < 20:
                index[cle_mere].append(cle_fille)"""

content = content.replace(old, new)
open("build_dfi_index.py", "w", encoding="utf-8").write(content)
print("OK")
