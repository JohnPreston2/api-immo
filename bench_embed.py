import requests, time

text = "Commune : Marseille | Code INSEE : 13055 | Departement : 13\nMARCHE APPARTEMENTS Marseille\nNombre de ventes : 1500\nPrix au m2 moyen : 3200 euros\nPrix au m2 median : 3050 euros"

times = []
for i in range(5):
    t = time.time()
    r = requests.post("http://localhost:11434/api/embeddings",
        json={"model": "nomic-embed-text", "prompt": text}, timeout=60)
    elapsed = time.time() - t
    times.append(elapsed)
    print(f"  Embed {i+1} : {elapsed:.2f}s")

avg = sum(times)/len(times)
print(f"\nMoyenne : {avg:.2f}s par embedding")
print(f"133 communes x 8 chunks x {avg:.2f}s = {133*8*avg/60:.0f} min estimees")
