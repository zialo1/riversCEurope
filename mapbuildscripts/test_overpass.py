import urllib.request, urllib.parse, json

def q(name_q):
    q = f'[out:json][timeout:90];relation["waterway"="river"]["name"~"{name_q}",i];out tags;'
    body = urllib.parse.urlencode({"data": q}).encode()
    req = urllib.request.Request("https://overpass-api.de/api/interpreter", data=body, headers={"User-Agent": "t/1.0"})
    r = urllib.request.urlopen(req, timeout=90)
    d = json.loads(r.read())
    return [e.get("tags", {}).get("name") for e in d.get("elements", [])]

out = []
for pat in ["Rhône", "Po"]:
    try:
        res = q(pat)
    except Exception as e:
        res = "ERR " + repr(e)
    out.append(f"{pat!r} -> {res}")
with open("test_out.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("done")
