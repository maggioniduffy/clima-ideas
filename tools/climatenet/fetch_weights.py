"""Download the pretrained ClimateNet (CGNet) weights into a directory as ``weights.pth`` + ``source.json``.

Usage: python fetch_weights.py --url URL --out model/ [--name FILE]

``--url`` is either a direct link to a .pth/.pt file or an index page (HTML directory listing) that links to one.
The README of andregraubner/ClimateNet only points at https://portal.nersc.gov/project/ClimateNet/ without naming the
file, so with an index page every link found is printed; if more than one weights file is linked, ``--name`` must pick
one. Nothing is guessed: the run fails when no weights file is found.
"""

from __future__ import annotations

import argparse
import os
import hashlib
import json
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

WEIGHT_EXTS = (".pth", ".pt")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def find_links(html: str, base_url: str) -> list[str]:
    """Absolute URLs of every <a href> in ``html`` (fragments and queries dropped, order kept, no duplicates)."""
    parser = _Links()
    parser.feed(html)
    seen: dict[str, None] = {}
    for href in parser.links:
        url = urljoin(base_url, href).split("#")[0].split("?")[0]
        seen.setdefault(url)
    return list(seen)


def pick_weights(links: list[str], name: str | None = None) -> str:
    """The one weights link among ``links``; ``name`` (file name) disambiguates. Raises ValueError otherwise."""
    cands = [u for u in links if urlparse(u).path.lower().endswith(WEIGHT_EXTS)]
    if name:
        cands = [u for u in cands if urlparse(u).path.rsplit("/", 1)[-1] == name]
    if not cands:
        raise ValueError(
            "no weights file (.pth/.pt) linked" + (f" with name {name!r}" if name else "")
        )
    if len(cands) > 1:
        raise ValueError("several weights files linked, pass --name: " + ", ".join(cands))
    return cands[0]


def _get(url: str, retries: int = 3) -> bytes:
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                return resp.read()
        except Exception as exc:
            print(f"GET {url} attempt {attempt} failed: {exc}", file=sys.stderr, flush=True)
            if attempt == retries:
                raise
            time.sleep(10 * attempt)
    raise AssertionError("unreachable")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--name", default=None, help="weights file name when the index links several"
    )
    args = parser.parse_args(argv)

    url = args.url
    if not urlparse(url).path.lower().endswith(WEIGHT_EXTS):
        links = find_links(_get(url).decode("utf-8", "replace"), url)
        print("links found:\n  " + "\n  ".join(links), flush=True)
        url = pick_weights(links, args.name)
    print(f"downloading {url}", flush=True)
    data = _get(url)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "weights.pth").write_bytes(data)
    info = {
        "index_url": args.url,
        "weights_url": url,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }
    # The config published next to these weights (weights.pth -> config.json, weights_new.pth -> config_new.json)
    # carries the input fields, normalisation stats and labels the weights were trained with.
    from climatenet_core import config_name_for

    cfg_name = config_name_for(urlparse(url).path.rsplit("/", 1)[-1])
    cfg_url = url.rsplit("/", 1)[0] + "/" + cfg_name
    try:
        (args.out / "config.json").write_bytes(_get(cfg_url))
        info["config_url"] = cfg_url
        print(f"config {cfg_url}:\n" + (args.out / "config.json").read_text(), flush=True)
    except Exception as exc:
        print(f"no config next to the weights ({cfg_url}): {exc}", flush=True)
    (args.out / "source.json").write_text(json.dumps(info, indent=2) + "\n")
    print(json.dumps(info), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
