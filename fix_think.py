content = open("rag_chain.py", encoding="utf-8").read()

old = '        else:\n            response = call_llm(system_prompt, user_prompt, stream=False)'
new = '''        else:
            response = call_llm(system_prompt, user_prompt, stream=False)
            # Filtrer le bloc <think>...</think> genere par qwen
            import re as _re
            response = _re.sub(r"<think>.*?</think>", "", response, flags=_re.DOTALL).strip()'''

content = content.replace(old, new)
open("rag_chain.py", "w", encoding="utf-8").write(content)
print("OK" if "<think>" in content else "PATCH ECHOUE")
