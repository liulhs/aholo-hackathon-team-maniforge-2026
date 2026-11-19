"""Search Wikimedia Commons files; print title, size and licence, optionally save 640 px thumbnails.

    python -I tools/commons_search.py [--save DIR] "query" ["query" ...]
"""
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "asset-research-script/1.0"}
LIMIT = 24


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as response:
        return response.read()


def main() -> None:
    args = sys.argv[1:]
    save = None
    if args and args[0] == "--save":
        save = pathlib.Path(args[1])
        save.mkdir(parents=True, exist_ok=True)
        args = args[2:]
    for q, query in enumerate(args):
        params = {"action": "query", "generator": "search", "gsrsearch": query, "gsrnamespace": 6, "gsrlimit": LIMIT,
                  "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 640, "format": "json"}
        result = json.loads(get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)))
        pages = sorted(result.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
        print(f"== {query}: {len(pages)}")
        for k, page in enumerate(pages):
            info = page["imageinfo"][0]
            if info["mime"] not in ("image/jpeg", "image/png"):
                continue
            licence = info.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "?")
            tag = f"q{q}_{k:02d}"
            print(f"{tag} | {page['title'][:70]} | {info['width']}x{info['height']} | {licence}")
            if save is not None:
                try:
                    (save / f"{tag}.jpg").write_bytes(get(info["thumburl"]))
                except Exception as error:  # noqa: BLE001 - a missing thumbnail must not stop the search
                    print(f"   thumbnail failed: {error!r}"[:100])
                time.sleep(1.0)
        time.sleep(1.0)


if __name__ == "__main__":
    main()
