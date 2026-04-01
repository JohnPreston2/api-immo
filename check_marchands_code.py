content = open("app.py", encoding="utf-8").read()
idx = content.find("def api_marchands")
print(content[idx:idx+800])
