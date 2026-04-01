from pathlib import Path
files = list(Path("cache/dvf").glob("*.json"))
big = [f for f in files if f.stat().st_size > 3000]
print(f"Total : {len(files)} communes")
print(f"> 20 ventes : {len(big)} communes")
dept13 = [f for f in big if f.stem.startswith("13")]
print(f"Dept 13 > 20 ventes : {len(dept13)} communes")
