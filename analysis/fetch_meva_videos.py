#!/usr/bin/env python3
"""Download the MEVA videos referenced by a CrossView subset into the release root.

MEVA is public (CC-BY-4.0) on the open S3 bucket `mevadata-public-01`, served over
plain HTTPS (no AWS account / credentials needed). Ground-camera clips live at
  drops-123-r13/<date>/<hour>/<name>.avi
but the hour sub-dir does not map cleanly from the filename, so for each needed
date we LIST drops-123-r13/<date>/ and match clips by basename.

The release QA paths are like `videos/meva/mp4_resized/<date>/<hour>/<slot>/<name>.EXT`.
Source files are `.avi`. If the subset was built with `--meva-video-ext avi`
(recommended) the .avi is saved directly. If the path ends in `.mp4`, the .avi is
transcoded with ffmpeg (must be installed).

Run (no GPU; needs internet):
  python3 analysis/fetch_meva_videos.py --subset analysis/crossview_subset.json
  python3 analysis/fetch_meva_videos.py --subset analysis/crossview_subset.json --limit 2   # smoke
  python3 analysis/fetch_meva_videos.py --all-referenced --jobs 10   # complete the MEVA tree
"""
import argparse
import concurrent.futures as cf
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from convert_crossview import MAX_SLOTS  # how many video_i slots a record carries

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_ROOT = os.path.join(REPO, "crossview-release-annotations", "crossview-release")
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


def _dedupe(paths):
    seen, uniq = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p); uniq.append(p)
    return uniq


def meva_dest_paths(subset_path):
    import json
    out = []
    for r in json.load(open(subset_path)):
        for i in range(1, MAX_SLOTS + 1):
            vp = r.get(f"video_{i}")
            if vp and "/meva/" in vp:
                out.append(vp)
    return _dedupe(out)


def meva_referenced_paths(ann_root, ext="avi"):
    """Every MEVA clip any qa_*.json references, bypassing the converter's cap.

    The release ships 1312 of these 2227 files, so a subset-driven fetch only ever
    repairs the questions that subset happened to include. Use this to complete the
    whole MEVA tree — the cap belongs at conversion time, not at download time.

    QA paths all spell `.mp4` while the release and the upstream bucket both carry
    `.avi` under a directory still named `mp4_resized`; `ext` rewrites the suffix.
    """
    import glob
    import json
    out = []
    for f in sorted(glob.glob(os.path.join(ann_root, "meva", "qa_*.json"))):
        if "pre_regenerate" in f:      # superseded qa_best_camera snapshot
            continue
        for r in json.load(open(f)):
            for vp in (r.get("video_paths") or []):
                if "/meva/" in vp:
                    out.append(vp.rsplit(".", 1)[0] + "." + ext if ext else vp)
    return _dedupe(out)


def stem_and_date(dest_path):
    base = os.path.basename(dest_path)
    stem = base.rsplit(".", 1)[0]          # strip .avi/.mp4
    date = stem.split(".")[0]              # YYYY-MM-DD
    return stem, date


def list_date(bucket, prefix, date):
    """Return {stem: key} for all .avi clips under <prefix>/<date>/ (paginated)."""
    out, token = {}, None
    base = f"https://{bucket}.s3.amazonaws.com/"
    while True:
        q = {"list-type": "2", "prefix": f"{prefix}/{date}/"}
        if token:
            q["continuation-token"] = token
        url = base + "?" + urllib.parse.urlencode(q)
        with urllib.request.urlopen(url, timeout=60) as r:
            root = ET.fromstring(r.read())
        for c in root.findall(f"{S3_NS}Contents"):
            key = c.find(f"{S3_NS}Key").text
            if key.endswith(".avi"):
                out[os.path.basename(key)[:-4]] = key
        if (root.findtext(f"{S3_NS}IsTruncated") or "false") == "true":
            token = root.findtext(f"{S3_NS}NextContinuationToken")
        else:
            break
    return out


def download(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, length=1 << 20)
    os.replace(tmp, dest)
    return os.path.getsize(dest)


def fetch_one(vp, key, release_root, bucket, have_ffmpeg):
    """(status, vp, bytes) for one clip. status: ok | need-ffmpeg | fail."""
    dest = os.path.join(release_root, vp)
    url = f"https://{bucket}.s3.amazonaws.com/{urllib.parse.quote(key)}"
    try:
        if vp.endswith(".avi"):
            return "ok", vp, download(url, dest)
        if not have_ffmpeg:
            return "need-ffmpeg", vp, 0
        tmp = dest + ".avi"
        download(url, tmp)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, dest], check=True)
        os.remove(tmp)
        return "ok", vp, os.path.getsize(dest)
    except Exception as e:                                    # noqa: BLE001
        return "fail", f"{vp}: {type(e).__name__} {e}", 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", default=os.path.join(HERE, "crossview_subset.json"))
    ap.add_argument("--all-referenced", action="store_true",
                    help="ignore --subset and fetch every MEVA clip any qa_*.json "
                         "references (2227 files, ~215 GB total, ~100 GB if the "
                         "shipped 1312 are already present)")
    ap.add_argument("--release-root", default=DEFAULT_ROOT)
    ap.add_argument("--bucket", default="mevadata-public-01")
    ap.add_argument("--prefix", default="drops-123-r13")
    ap.add_argument("--jobs", type=int, default=8, help="parallel downloads")
    ap.add_argument("--limit", type=int, default=0, help="only fetch first N (smoke)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.all_referenced:
        ann = os.path.join(args.release_root, "annotations", "multi-cam-dataset")
        dests = meva_referenced_paths(ann)
        src = "all qa_*.json"
    else:
        dests = meva_dest_paths(args.subset)
        src = os.path.basename(args.subset)
    if args.limit:
        dests = dests[: args.limit]
    print(f"{len(dests)} MEVA videos referenced by {src}")

    # Resolve S3 keys first (serial: one LIST per date, cached), then fetch in
    # parallel — the listing is cheap and the transfer is what takes the hours.
    have_ffmpeg = shutil.which("ffmpeg") is not None
    date_cache, done, miss, todo = {}, 0, [], []
    for vp in dests:
        dest = os.path.join(args.release_root, vp)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            done += 1; continue
        stem, date = stem_and_date(vp)
        if date not in date_cache:
            date_cache[date] = list_date(args.bucket, args.prefix, date)
        key = date_cache[date].get(stem)
        if not key:
            miss.append(vp); print(f"  MISSING on S3: {stem}.avi"); continue
        todo.append((vp, key))

    print(f"  already present: {done} | to fetch: {len(todo)} | missing on S3: {len(miss)}")
    if args.dry_run:
        for vp, key in todo[:20]:
            print(f"  would fetch {key} -> {vp}")
        if len(todo) > 20:
            print(f"  ... and {len(todo) - 20} more")
        sys.exit(1 if miss else 0)

    fetched, transcode_needed, failed, mb = 0, [], [], 0.0
    with cf.ThreadPoolExecutor(args.jobs) as ex:
        futs = [ex.submit(fetch_one, vp, key, args.release_root, args.bucket, have_ffmpeg)
                for vp, key in todo]
        for f in cf.as_completed(futs):
            status, what, size = f.result()
            if status == "ok":
                fetched += 1; mb += size / 1e6
                if fetched % 25 == 0 or fetched == len(todo):
                    print(f"  {fetched}/{len(todo)}  {mb/1000:.1f} GB", flush=True)
            elif status == "need-ffmpeg":
                transcode_needed.append(what)
            else:
                failed.append(what); print(f"  FAIL {what}", file=sys.stderr, flush=True)

    print(f"\nMEVA videos: {len(dests)} referenced | already had: {done} | "
          f"downloaded: {fetched} ({mb/1000:.2f} GB) | missing-on-s3: {len(miss)} | "
          f"need-ffmpeg: {len(transcode_needed)} | failed: {len(failed)}")
    if transcode_needed:
        print("  -> install ffmpeg (conda install -n cvbench -c conda-forge ffmpeg) "
              "or rebuild the subset with --meva-video-ext avi to skip transcoding.")
    sys.exit(1 if (miss or transcode_needed or failed) else 0)


if __name__ == "__main__":
    main()
