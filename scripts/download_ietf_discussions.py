import os, re, time, urllib.request, urllib.error
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_ROOT = os.path.join(BASE, "data", "discussions", "ietf")

LISTS = ["dnsop", "dns-privacy", "dd"]  # dnsop, dprive, deleg
START_YEAR, START_MONTH = 2016, 8
END_YEAR, END_MONTH = 2026, 8

UA = {"User-Agent": "Mozilla/5.0 (dns-expert-model-builder/1.0)"}
MSG_LINK_RE = re.compile(r'href="/arch/msg/([a-zA-Z0-9_-]+)/([A-Za-z0-9_-]+)/"')
META_REDIRECT_RE = re.compile(r'''<meta\s+http-equiv=["']refresh["']\s+content=["']0;URL=['"]([^'"]+)['"]''', re.IGNORECASE)
YEAR_PAGE_RE = re.compile(r'/arch/browse/static/[^/]+/(\d{4})/$')


def extract_hashes(html, list_name):
    hashes = set()
    for m in MSG_LINK_RE.finditer(html):
        if m.group(1) == list_name:
            hashes.add(m.group(2))
    return hashes


def month_range(y0, m0, y1, m1):
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


MAX_BACKOFF = 45      # cap on a single short backoff wait
COOLDOWN = 300         # 5 min pause if we're getting sustained/persistent 429s
COOLDOWN_THRESHOLD = 3  # consecutive 429s before we assume a hard block, not a blip


def fetch(url, timeout=30, max_retries=20):
    req = urllib.request.Request(url, headers=UA)
    consecutive_429 = 0
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                consecutive_429 += 1
                if consecutive_429 >= COOLDOWN_THRESHOLD:
                    print(f"    persistent 429s, cooling down {COOLDOWN}s ({url})")
                    time.sleep(COOLDOWN)
                    consecutive_429 = 0
                    continue
                retry_after = e.headers.get("Retry-After")
                try:
                    wait = min(MAX_BACKOFF, float(retry_after)) if retry_after else min(MAX_BACKOFF, 2 ** attempt * 2)
                except ValueError:
                    wait = min(MAX_BACKOFF, 2 ** attempt * 2)
                print(f"    429, waiting {wait:.0f}s ({url})")
                time.sleep(wait)
                continue
            if e.code == 404:
                raise
            time.sleep(min(MAX_BACKOFF, 2 ** attempt))
        except Exception:
            if attempt == max_retries - 1:
                raise
            time.sleep(min(MAX_BACKOFF, 2 ** attempt))
    raise RuntimeError(f"exceeded retries for {url}")


def get_month_hashes(list_name, year, month, done_years):
    if year in done_years:
        return []  # this list groups by year and we already pulled that year's page
    url = f"https://mailarchive.ietf.org/arch/browse/static/{list_name}/{year:04d}-{month:02d}/"
    try:
        html = fetch(url).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise

    redirect = META_REDIRECT_RE.search(html)
    if redirect:
        target = redirect.group(1)
        if target.startswith("/"):
            target = "https://mailarchive.ietf.org" + target
        year_match = YEAR_PAGE_RE.search(target.split("?")[0])
        html = fetch(target).decode("utf-8", errors="replace")
        if year_match:
            done_years.add(int(year_match.group(1)))
            print(f"    {list_name} uses year-level grouping; pulled {target} once, skipping rest of {year_match.group(1)}")

    return sorted(extract_hashes(html, list_name))


def download_message(list_name, msg_hash, out_dir):
    out_path = os.path.join(out_dir, f"{msg_hash}.eml")
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return "skip"
    url = f"https://mailarchive.ietf.org/arch/msg/{list_name}/{msg_hash}/download/"
    try:
        data = fetch(url)
    except Exception as e:
        return f"fail:{e}"
    with open(out_path, "wb") as f:
        f.write(data)
    time.sleep(1.2)  # fixed, respectful pacing between requests
    return "ok"


def main():
    for list_name in LISTS:
        try:
            process_list(list_name)
        except Exception as e:
            print(f"{list_name}: ABORTED with unexpected error: {e}")
    print("\nAll lists processed.")


def process_list(list_name):
        out_dir = os.path.join(OUT_ROOT, list_name)
        os.makedirs(out_dir, exist_ok=True)

        print(f"\n=== {list_name}: collecting message hashes ===")
        all_hashes = []
        done_years = set()
        for y, m in month_range(START_YEAR, START_MONTH, END_YEAR, END_MONTH):
            try:
                hashes = get_month_hashes(list_name, y, m, done_years)
            except Exception as e:
                print(f"  {y:04d}-{m:02d}: FAILED collecting hashes: {e}")
                hashes = []
            if hashes:
                all_hashes.extend(hashes)
            time.sleep(0.4)
        all_hashes = sorted(set(all_hashes))
        print(f"{list_name}: {len(all_hashes)} unique messages found across date range")

        ok = skip = fail = 0
        for i, h in enumerate(all_hashes, 1):
            result = download_message(list_name, h, out_dir)
            if result == "ok":
                ok += 1
            elif result == "skip":
                skip += 1
            else:
                fail += 1
                print(f"  {h}: {result}")
            if i % 200 == 0:
                print(f"  progress: {i}/{len(all_hashes)} (ok={ok} skip={skip} fail={fail})")

        print(f"{list_name}: done. ok={ok} skip={skip} fail={fail}")


if __name__ == "__main__":
    main()
