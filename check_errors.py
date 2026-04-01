import json
from pathlib import Path
from collections import Counter

progress = json.loads(Path("cache/rag_progress.json").read_text(encoding="utf-8"))
errors = progress.get("errors", [])
print(f"Total erreurs : {len(errors)}")

reasons = Counter(e.get("reason", "?") for e in errors)
for reason, count in reasons.most_common(10):
    print(f"  {count:5d} x {reason}")
