content = open("app.py", encoding="utf-8", errors="replace").read()

old = 'if __name__ == "__main__":'
new = '''from rag_chain import register_rag_routes
register_rag_routes(app)

if __name__ == "__main__":'''

content = content.replace(old, new)
open("app.py", "w", encoding="utf-8").write(content)
print("OK" if "register_rag_routes" in content else "PATCH ECHOUE")
