content = open("app.py", encoding="utf-8", errors="replace").read()
old = '@app.route("/")\ndef index():\n    return render_template("index.html")'
new = '@app.route("/")\ndef index():\n    return render_template("index.html")\n\n@app.route("/rag")\ndef rag_page():\n    return render_template("rag.html")'
content = content.replace(old, new)
open("app.py", "w", encoding="utf-8").write(content)
print("OK" if "/rag" in content else "ECHOUE")
