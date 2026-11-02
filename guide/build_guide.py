#!/usr/bin/env python3
"""Render the lab guide into app/generated/, fetching the screenshots into app/static/img.

The guide lives in the Splunky Finance repo and moves on its branch, while a deployment is pinned
to a tag, so the handout is built from the branch tip rather than from whatever the checkout
happens to be. That mismatch has bitten once already.

    python3 guide/build_guide.py                         # from ~/splunky-finance branch tip
    python3 guide/build_guide.py --markdown path/to.md   # from a file
    python3 guide/build_guide.py --no-fetch              # images already in app/static/img

Images are committed to this repo on purpose: the asset host throttles, two runs in three left a
different handful of screenshots broken, and an install that depends on it is an install that
fails in front of a room.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import overlay  # noqa: E402  (sibling module, not a package)

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "app" / "static" / "img"
GENERATED = ROOT / "app" / "generated"
ASSET = re.compile(r"https://github\.com/user-attachments/assets/([A-Za-z0-9-]+)")
DEFAULT_REPO = Path.home() / "splunky-finance"
DEFAULT_REF = "origin/build-splunky-finance"


def markdown_from_git(repo, ref):
    subprocess.run(["git", "-C", str(repo), "fetch", "-q", "origin", ref.split("/")[-1]],
                   check=False)
    result = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:docs/workshop-lab.md"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"could not read docs/workshop-lab.md at {ref}: {result.stderr.strip()}")
    revision = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", ref],
                              capture_output=True, text=True).stdout.strip()
    return result.stdout, f"{ref} ({revision})"


def fetch(asset_id):
    """Three attempts with backoff, because the asset host refuses a different handful each run."""
    url = f"https://github.com/user-attachments/assets/{asset_id}"
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": "curl/8"}), timeout=60) as response:
                return asset_id, response.read()
        except Exception as error:
            if attempt == 2:
                print(f"  failed {asset_id}: {type(error).__name__}", flush=True)
                return asset_id, None
            time.sleep(2 * (attempt + 1))
    return asset_id, None


def existing(asset_id):
    for suffix in (".png", ".jpg"):
        path = IMAGES / f"{asset_id}{suffix}"
        if path.exists():
            return path.name
    return None


def collect_images(text, allow_fetch=True):
    """Returns {asset_id: filename}. Only the ones not already on disk are fetched."""
    IMAGES.mkdir(parents=True, exist_ok=True)
    ids = sorted(set(ASSET.findall(text)))
    have = {i: existing(i) for i in ids}
    wanted = [i for i, name in have.items() if not name]
    if wanted and allow_fetch:
        print(f"fetching {len(wanted)} of {len(ids)} screenshots", flush=True)
        with ThreadPoolExecutor(max_workers=3) as pool:
            for asset_id, blob in pool.map(fetch, wanted):
                if not blob:
                    continue
                suffix = ".png" if blob[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
                path = IMAGES / f"{asset_id}{suffix}"
                path.write_bytes(blob)
                have[asset_id] = path.name
    elif wanted:
        print(f"{len(wanted)} screenshots missing and --no-fetch given", flush=True)
    missing = [i for i, name in have.items() if not name]
    return {i: name for i, name in have.items() if name}, missing


def slug(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[^\w\s-]", "", text.replace("&amp;", "and")).strip().lower()
    return re.sub(r"[\s_]+", "-", text) or "section"


def add_heading_ids(html):
    """Anchors for the sidebar, and a nav list of the h2s in document order."""
    nav = []
    seen = {}

    def anchor(match):
        level, text = match.group(1), match.group(2)
        base = slug(text)
        seen[base] = seen.get(base, 0) + 1
        ident = base if seen[base] == 1 else f"{base}-{seen[base]}"
        if level == "2":
            nav.append({"id": ident, "title": re.sub(r"<[^>]+>", "", text).strip()})
        return f'<h{level} id="{ident}">{text}</h{level}>'

    return re.sub(r"<h([23])>(.*?)</h\1>", anchor, html, flags=re.S), nav


def group_for(title):
    """Which page a section belongs on. Setup is everything up to a working trace (Steps 1 to 3);
    the lab is the evaluators and guardrails; anything upstream adds that matches neither lands on
    the lab page rather than vanishing."""
    lowered = title.lower().strip()
    if lowered.startswith("troubleshooting"):
        return "troubleshooting"
    if lowered.startswith("before you start"):
        return "briefing"
    match = re.match(r"step (\d+)", lowered)
    if match:
        return "briefing" if int(match.group(1)) <= 3 else "lab"
    return "lab"


def split_sections(html):
    """The rendered guide as an intro plus one entry per h2, so each page can take its own share.
    The document's own h1 is dropped, since every page carries its own headline, and the rules
    between sections go too: the page layout separates them."""
    parts = re.split(r'(?=<h2 id=")', html)
    intro = re.sub(r"<h1[^>]*>.*?</h1>", "", parts[0], flags=re.S)
    intro = re.sub(r"(\s*<hr\s*/?>\s*)+$", "", intro).strip()
    sections = []
    for chunk in parts[1:]:
        match = re.match(r'<h2 id="([^"]+)">(.*?)</h2>', chunk, re.S)
        if not match:
            continue
        title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        body = re.sub(r"(\s*<hr\s*/?>\s*)+$", "", chunk).strip()
        step = re.match(r"Step (\d+):\s*(.*)", title)
        sections.append({
            "id": match.group(1),
            "title": title,
            "short": step.group(2) if step else title,
            "step": int(step.group(1)) if step else None,
            "group": group_for(title),
            "html": body,
        })
    return intro, sections


def render(text):
    from markdown_it import MarkdownIt
    md = MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])
    return md.render(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--markdown", help="read the guide from this file instead of git")
    parser.add_argument("--repo", default=str(DEFAULT_REPO))
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--no-fetch", action="store_true", help="never reach for the asset host")
    parser.add_argument("--no-overlay", action="store_true", help="render the upstream doc as is")
    args = parser.parse_args()

    if args.markdown:
        text, source = Path(args.markdown).read_text(), args.markdown
    else:
        text, source = markdown_from_git(Path(args.repo), args.ref)
    print(f"guide source: {source}, {len(text.splitlines())} lines")

    if not args.no_overlay:
        text = overlay.apply(text)
        print("overlay applied: lab details card, model endpoint pointers, judge note")

    images, missing = collect_images(text, allow_fetch=not args.no_fetch)
    for asset_id, name in images.items():
        text = text.replace(f"https://github.com/user-attachments/assets/{asset_id}",
                            f"/static/img/{name}")
    if missing:
        print(f"WARNING: {len(missing)} screenshots are missing and will render as broken images")

    html, _ = add_heading_ids(render(text))
    intro, sections = split_sections(html)
    GENERATED.mkdir(parents=True, exist_ok=True)
    (GENERATED / "guide.json").write_text(json.dumps(
        {"source": source, "intro": intro, "sections": sections}, indent=1))
    groups = {}
    for section in sections:
        groups[section["group"]] = groups.get(section["group"], 0) + 1
    print(f"wrote {GENERATED / 'guide.json'} ({len(html) / 1000:.0f} kB), "
          f"{len(sections)} sections {groups}, {len(images)} screenshots")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
