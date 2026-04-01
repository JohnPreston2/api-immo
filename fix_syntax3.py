lines = open("rag_chain.py", encoding="utf-8", errors="replace").readlines()
clean = []
skip_lines = {124, 125, 126, 127}  # 1-indexed
for i, line in enumerate(lines, 1):
    if i in skip_lines:
        continue
    # Remplacer la ligne 123 par le code correct
    if i == 123:
        clean.append('            # Extraire derniere ligne du thinking comme reponse\n')
        continue
    clean.append(line)
open("rag_chain.py", "w", encoding="utf-8").writelines(clean)
print(f"OK - {len(lines)} -> {len(clean)} lignes")
