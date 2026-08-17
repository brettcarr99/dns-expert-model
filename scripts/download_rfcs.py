import json, time, urllib.request, urllib.error, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META = os.path.join(BASE, "data", "rfcs", "metadata", "dns_rfcs_filtered.json")
OUT_DIR = os.path.join(BASE, "data", "rfcs", "raw")

with open(META) as f:
    rfcs = json.load(f)

failed = []
for i, r in enumerate(rfcs, 1):
    num = r["rfc"]
    out_path = os.path.join(OUT_DIR, f"rfc{num}.txt")
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        continue
    url = f"https://www.rfc-editor.org/rfc/rfc{num}.txt"
    req = urllib.request.Request(url, headers={"User-Agent": "dns-expert-model-builder/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        with open(out_path, "wb") as f:
            f.write(data)
        print(f"[{i}/{len(rfcs)}] RFC{num} OK ({len(data)} bytes)")
    except urllib.error.HTTPError as e:
        print(f"[{i}/{len(rfcs)}] RFC{num} FAILED: {e}")
        failed.append(num)
    except Exception as e:
        print(f"[{i}/{len(rfcs)}] RFC{num} FAILED: {e}")
        failed.append(num)
    time.sleep(0.3)  # be polite to rfc-editor.org

print(f"\nDone. {len(rfcs) - len(failed)} succeeded, {len(failed)} failed.")
if failed:
    print("Failed RFC numbers:", failed)
