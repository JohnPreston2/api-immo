from pathlib import Path

files = list(Path("cache/dvf").glob("*.json"))
big = [f for f in files if f.stat().st_size > 3000]
print(f"Communes eligibles : {len(big)}")

chunks_par_commune = 8
temps_par_chunk = 0.01
total_sec = len(big) * chunks_par_commune * temps_par_chunk
print(f"Estimation embedding seul : {total_sec/60:.0f} min")
print(f"Estimation avec IO/ChromaDB (x3) : {total_sec*3/60:.0f} min")
