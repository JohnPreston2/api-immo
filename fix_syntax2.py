lines = open("rag_chain.py", encoding="utf-8", errors="replace").readlines()
print("Lignes 120-130:")
for i, l in enumerate(lines[118:132], 119):
    print(f"{i}: {repr(l)}")
