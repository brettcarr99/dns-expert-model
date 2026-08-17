import os, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "data", "discussions", "ripe", "dns-wg")
os.makedirs(OUT_DIR, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (dns-expert-model-builder/1.0)"}
START_YEAR, END_YEAR = 2016, 2026  # full mbox pulled per-year, filtered to last 10y at parse time


def main():
    ok = skip = fail = 0
    for year in range(START_YEAR, END_YEAR + 1):
        fname = f"dns-wg@ripe.net-{year}.mbox.gz"
        out_path = os.path.join(OUT_DIR, fname)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            skip += 1
            continue
        url = f"https://mailman.ripe.net/archives/list/dns-wg@ripe.net/export/{fname}?start={year}-01-01&end={year+1}-01-01"
        req = urllib.request.Request(url, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            with open(out_path, "wb") as f:
                f.write(data)
            ok += 1
            print(f"{fname}: {len(data)} bytes")
        except Exception as e:
            fail += 1
            print(f"FAILED {fname}: {e}")
    print(f"Done. ok={ok} skip={skip} fail={fail}")


if __name__ == "__main__":
    main()
