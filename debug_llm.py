import requests, json

payload = {
    "model": "qwen4b-64k",
    "stream": False,
    "options": {"num_predict": 500, "temperature": 0.2},
    "messages": [
        {"role": "system", "content": "Tu es un expert immobilier. Reponds en francais."},
        {"role": "user", "content": "Quel est le prix moyen au m2 a Marseille ?"}
    ]
}

r = requests.post("http://localhost:11434/api/chat", json=payload, timeout=120)
data = r.json()
print("STATUS:", r.status_code)
print("KEYS:", list(data.keys()))
print("MESSAGE:", data.get("message"))
print("CONTENT:", repr(data.get("message", {}).get("content", "")))
