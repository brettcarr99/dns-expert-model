import json, re, xml.etree.ElementTree as ET

SCRATCH = "/private/tmp/claude-501/-Users-brettcarr-Library-Mobile-Documents-com-apple-CloudDocs-ai-claude/e0d9bfa9-3b7d-48f4-8685-33f3c912ec46/scratchpad"

with open(f"{SCRATCH}/dns-rfc-annotations.json") as f:
    ann = json.load(f)

wanted = set()
for key in ann:
    m = re.match(r"rfc0*(\d+)", key)
    if m:
        wanted.add(int(m.group(1)))

print(f"Total DNS RFCs from dns-camel: {len(wanted)}")

ns = {"r": "https://www.rfc-editor.org/rfc-index"}
tree = ET.parse(f"{SCRATCH}/rfc-index.xml")
root = tree.getroot()

results = {}
for entry in root.findall("r:rfc-entry", ns):
    docid = entry.find("r:doc-id", ns).text  # e.g. RFC1035
    num = int(docid[3:])
    if num not in wanted:
        continue
    title_el = entry.find("r:title", ns)
    title = title_el.text if title_el is not None else ""
    status_el = entry.find("r:current-status", ns)
    status = status_el.text if status_el is not None else "UNKNOWN"
    obsoleted_by = entry.find("r:obsoleted-by", ns)
    is_obsoleted = obsoleted_by is not None and len(list(obsoleted_by)) > 0
    date_el = entry.find("r:date", ns)
    year = None
    if date_el is not None:
        y = date_el.find("r:year", ns)
        year = y.text if y is not None else None
    results[num] = {
        "title": title,
        "status": status,
        "is_obsoleted": is_obsoleted,
        "year": year,
    }

found = set(results.keys())
missing = wanted - found
if missing:
    print(f"WARNING: {len(missing)} RFCs not found in index: {sorted(missing)}")

excluded_historic = [n for n in results if results[n]["status"] == "HISTORIC"]
excluded_obsoleted = [n for n in results if results[n]["is_obsoleted"] and results[n]["status"] != "HISTORIC"]
kept = [n for n in results if results[n]["status"] != "HISTORIC" and not results[n]["is_obsoleted"]]

print(f"Excluded (historic): {len(excluded_historic)}")
print(f"Excluded (obsoleted, non-historic status): {len(excluded_obsoleted)}")
print(f"Kept: {len(kept)}")

# status breakdown of kept set
from collections import Counter
c = Counter(results[n]["status"] for n in kept)
print("Status breakdown of kept RFCs:", dict(c))

out = []
for n in sorted(kept):
    r = results[n]
    out.append({"rfc": n, "title": r["title"].strip(), "status": r["status"], "year": r["year"]})

with open(f"{SCRATCH}/dns_rfcs_filtered.json", "w") as f:
    json.dump(out, f, indent=2)

print(f"\nWrote {len(out)} entries to dns_rfcs_filtered.json")
