import json, os, time, urllib.request, urllib.error

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_ROOT = os.path.join(BASE, "data", "vendor_docs")

# (product_slug, github repo, branch, subpath within repo to pull, file extensions to keep)
GIT_SOURCES = [
    ("bind9",         "isc-projects/bind9",        "main",   "doc/arm",                       (".rst",)),
    ("pdns-auth",     "PowerDNS/pdns",              "master", "docs",                          (".rst",)),
    ("pdns-recursor", "PowerDNS/pdns",              "master", "pdns/recursordist/docs",         (".rst",)),
    ("dnsdist",       "PowerDNS/pdns",              "master", "pdns/dnsdistdist/docs",          (".rst",)),
    ("knot-dns",      "CZ-NIC/knot",                "master", "doc",                           (".rst",)),
    ("knot-resolver",  "CZ-NIC/knot-resolver",       "master", "doc/user",                      (".rst",)),
    ("unbound",       "NLnetLabs/unbound-manual",   "main",   "source",                        (".rst",)),
    ("nsd",           "NLnetLabs/nsd",              "master", "doc/manual",                    (".rst",)),
    ("coredns",       "coredns/coredns.io",         "master", "content/manual",                (".md",)),
    ("coredns",       "coredns/coredns.io",         "master", "content/plugins",               (".md",)),
    ("coredns",       "coredns/coredns.io",         "master", "content/explugins",             (".md",)),
]

DIRECT_SOURCES = [
    ("dnsmasq",    "https://thekelleys.org.uk/dnsmasq/doc.html", "doc.html"),
    ("technitium", "https://technitium.com/dns/help.html",       "help.html"),
]


def gh_api(url):
    req = urllib.request.Request(url, headers={"User-Agent": "dns-expert-model-builder/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def download_git_source(product, repo, branch, subpath, exts):
    tree = gh_api(f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1")
    count = 0
    for entry in tree.get("tree", []):
        path = entry["path"]
        if entry["type"] != "blob":
            continue
        if not path.startswith(subpath + "/") and path != subpath:
            continue
        if not path.endswith(exts):
            continue
        rel = path[len(subpath):].lstrip("/")
        out_path = os.path.join(OUT_ROOT, product, subpath.split("/")[-1], rel)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            continue
        raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
        req = urllib.request.Request(raw_url, headers={"User-Agent": "dns-expert-model-builder/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            with open(out_path, "wb") as f:
                f.write(data)
            count += 1
        except Exception as e:
            print(f"  FAILED {path}: {e}")
        time.sleep(0.1)
    return count


def main():
    for product, repo, branch, subpath, exts in GIT_SOURCES:
        print(f"[{product}] {repo}@{branch}:{subpath}")
        n = download_git_source(product, repo, branch, subpath, exts)
        print(f"  -> {n} files downloaded")

    for product, url, filename in DIRECT_SOURCES:
        out_path = os.path.join(OUT_ROOT, product, filename)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "dns-expert-model-builder/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        with open(out_path, "wb") as f:
            f.write(data)
        print(f"[{product}] {url} -> {len(data)} bytes")


if __name__ == "__main__":
    main()
