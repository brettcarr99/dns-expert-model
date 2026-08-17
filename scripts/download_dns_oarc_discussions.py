import os, time, urllib.request
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "data", "discussions", "dns-oarc", "dns-operations")
os.makedirs(OUT_DIR, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (dns-expert-model-builder/1.0)"}
START_YEAR, START_MONTH = 2016, 8
END_YEAR, END_MONTH = 2026, 8

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def month_range(y0, m0, y1, m1):
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def main():
    ok = skip = fail = 0
    for y, m in month_range(START_YEAR, START_MONTH, END_YEAR, END_MONTH):
        fname = f"{y:04d}-{MONTHS[m-1]}.txt.gz"
        out_path = os.path.join(OUT_DIR, fname)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            skip += 1
            continue
        url = f"https://lists.dns-oarc.net/pipermail/dns-operations/{fname}"
        req = urllib.request.Request(url, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            with open(out_path, "wb") as f:
                f.write(data)
            ok += 1
        except Exception as e:
            fail += 1
            print(f"FAILED {fname}: {e}")
        time.sleep(0.2)
    print(f"Done. ok={ok} skip={skip} fail={fail}")


if __name__ == "__main__":
    main()
