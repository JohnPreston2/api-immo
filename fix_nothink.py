content = open("rag_chain.py", encoding="utf-8").read()

old = '        "options": {\n            "num_predict": MAX_TOKENS,\n            "temperature": 0.2,       # faible pour réponses factuelles\n            "top_p": 0.9,\n        },'
new = '        "options": {\n            "num_predict": MAX_TOKENS,\n            "temperature": 0.2,\n            "top_p": 0.9,\n        },\n        "think": False,'

content = content.replace(old, new)
open("rag_chain.py", "w", encoding="utf-8").write(content)
print("OK" if '"think": False' in content else "PATCH ECHOUE")
