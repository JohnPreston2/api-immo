import re

content = open("rag_chain.py", encoding="utf-8", errors="replace").read()

# Trouver et remplacer le bloc non-streaming de call_llm
old = """        r = req.post(f\"{OLLAMA_URL}/api/chat\", json=payload, timeout=120)
        r.raise_for_status()
        return r.json().get(\"message\", {}).get(\"content\", \"\")"""

new = """        r = req.post(f\"{OLLAMA_URL}/api/chat\", json=payload, timeout=120)
        r.raise_for_status()
        msg = r.json().get(\"message\", {})
        content = msg.get(\"content\", \"\").strip()
        if not content:
            content = msg.get(\"thinking\", \"\").split(\"\\n\")[-1].strip()
        return re.sub(r\"<think>.*?</think>\", \"\", content, flags=re.DOTALL).strip()"""

# Aussi desactiver le mode think
old2 = '        "think": False,'
if old2 not in content:
    content = content.replace(
        '"top_p": 0.9,\n        },',
        '"top_p": 0.9,\n        },\n        "think": False,'
    )

content = content.replace(old, new)
open("rag_chain.py", "w", encoding="utf-8").write(content)
print("OK")
