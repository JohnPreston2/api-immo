lines = open("rag_chain.py", encoding="utf-8", errors="replace").readlines()
clean = []
skip_next = False
for line in lines:
    if "Final Output|Final Selection|Drafting" in line:
        skip_next = True
        continue
    if skip_next and ("content = match" in line or "content = thinking" in line):
        skip_next = False
        continue
    skip_next = False
    clean.append(line)
open("rag_chain.py", "w", encoding="utf-8").writelines(clean)
print(f"OK - {len(lines)} -> {len(clean)} lignes")
