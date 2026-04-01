content = open("app.py", encoding="utf-8", errors="replace").read()
idx = content.find("codes_dvf") 
if idx == -1:
    idx = content.find("mutations_dvf = []")
print("TROUVE A INDEX:", idx)
print(content[idx:idx+500])
