"""
fix3.py - Rend _cache_load robuste aux fichiers JSON corrompus
Lance avec : python fix3.py
"""

path = "app.py"
content = open(path, encoding="utf-8").read()
original = content

old = '''def _cache_load(code_insee):
    """Charge depuis RAM, puis fichier, sinon None"""
    with _cache_lock:
        if code_insee in _mem_cache:
            return _mem_cache[code_insee]
    path = _cache_path(code_insee)
    if _cache_valid(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        with _cache_lock:
            _mem_cache[code_insee] = data
        return data
    return None'''

new = '''def _cache_load(code_insee):
    """Charge depuis RAM, puis fichier, sinon None. Supprime le cache si JSON corrompu."""
    with _cache_lock:
        if code_insee in _mem_cache:
            return _mem_cache[code_insee]
    path = _cache_path(code_insee)
    if _cache_valid(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with _cache_lock:
                _mem_cache[code_insee] = data
            return data
        except Exception as e:
            print(f"[CACHE] JSON corrompu {path}, suppression : {e}")
            try:
                os.remove(path)
            except:
                pass
    return None'''

if old in content:
    content = content.replace(old, new, 1)
    print("OK : _cache_load robuste aux JSON corrompus")
else:
    print("SKIP : déjà appliqué ou pattern non trouvé")

if content != original:
    open(path, "w", encoding="utf-8").write(content)
    print("app.py mis à jour.")
else:
    print("Aucune modification.")
