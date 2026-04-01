content = open("rag_chain.py", encoding="utf-8").read()

old = '        r = req.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)\n        r.raise_for_status()\n        return r.json().get("message", {}).get("content", "")'
new = '''        r = req.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
        r.raise_for_status()
        msg = r.json().get("message", {})
        content = msg.get("content", "").strip()
        # Qwen3 mode thinking : reponse dans "thinking" si content vide
        if not content:
            thinking = msg.get("thinking", "")
            import re as _re
            # Extraire la reponse finale apres le raisonnement
            match = _re.search(r"(?:Final Output|Final Selection|Drafting|Bonjour|Réponse|Answer)[^\n]*\n+(.*?)$", thinking, _re.DOTALL | _re.IGNORECASE)
            content = match.group(1).strip() if match else thinking.split("\n")[-1].strip()
        # Nettoyer balises think residuelles
        import re as _re2
        content = _re2.sub(r"<think>.*?</think>", "", content, flags=_re2.DOTALL).strip()
        return content'''

content = content.replace(old, new)
open("rag_chain.py", "w", encoding="utf-8").write(content)
print("OK")
