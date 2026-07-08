#!/usr/bin/env python3
"""Package CrossView benchmark videos from the lab NAS and upload to Hugging Face.

Run this ON A MACHINE THAT MOUNTS THE NAS (where /nas/mars/... paths resolve).
Self-contained: needs only Python 3.8+ and `pip install huggingface_hub`.

Workflow (run from the crossview-release directory, or pass --release-root):

  1. size    Stat every video in video_manifest.csv, fill the bytes/status
             columns, write video_manifest.filled.csv, and print per-dataset
             totals. RUN THIS FIRST and report the total: under 100 GB fits a
             free HF account's private storage; up to 1 TB needs PRO ($9/mo).
  2. pack    Write store-mode (uncompressed) zip shards per source dataset
             into shards/: meva-000.zip, ego-exo4d-000.zip, ... Internal zip
             paths are the manifest release_path (videos/meva/...), so the
             consumer-side fetch script can range-extract single videos.
             Also writes shards/shard_index.csv (release_path -> shard file).
  3. upload  Create a PRIVATE HF dataset repo and upload shards + filled
             manifest + shard index + annotations. Idempotent: already-
             uploaded files with matching size are skipped, so re-run after
             any interruption.

Example session:

  pip install -U huggingface_hub
  hf auth login        # paste a WRITE token from hf.co/settings/tokens
  python3 package_and_upload.py size
  python3 package_and_upload.py pack
  python3 package_and_upload.py upload --repo <hf-username>/crossview-videos

Keep the repo PRIVATE: Ego-Exo4D and nuScenes licenses do not permit
redistribution; share access only with collaborators who hold those licenses.
"""
import argparse
import csv
import hashlib
import os
import sys
import zipfile

MANIFEST = "video_manifest.csv"
FILLED = "video_manifest.filled.csv"
SHARD_DIR = "shards"
SHARD_INDEX = "shard_index.csv"


def read_manifest(root, prefer_filled=True):
    path = os.path.join(root, FILLED)
    if not prefer_filled or not os.path.exists(path):
        path = os.path.join(root, MANIFEST)
    with open(path, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("release_path")]
    print(f"manifest: {path} ({len(rows)} rows)")
    return rows


def dataset_of(release_path):
    # release_path looks like videos/<dataset>/...
    parts = release_path.split("/")
    return parts[1] if len(parts) > 1 and parts[0] == "videos" else "other"


def fmt_gb(n):
    return f"{n / 1e9:.2f} GB"


def cmd_size(args):
    rows = read_manifest(args.release_root, prefer_filled=False)
    totals, missing = {}, []
    for r in rows:
        src = r["original_path"]
        if os.path.exists(src):
            r["bytes"] = str(os.path.getsize(src))
            r["status"] = "ok"
            if args.sha256:
                h = hashlib.sha256()
                with open(src, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                r["sha256"] = h.hexdigest()
            totals.setdefault(dataset_of(r["release_path"]), [0, 0])
            totals[dataset_of(r["release_path"])][0] += int(r["bytes"])
            totals[dataset_of(r["release_path"])][1] += 1
        else:
            r["status"] = "missing"
            missing.append(src)

    out = os.path.join(args.release_root, FILLED)
    fieldnames = list(rows[0].keys())
    if args.sha256 and "sha256" not in fieldnames:
        fieldnames.append("sha256")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}")

    grand = 0
    for ds in sorted(totals):
        b, n = totals[ds]
        grand += b
        print(f"  {ds:<12} {n:>5} videos  {fmt_gb(b)}")
    print(f"  {'TOTAL':<12} {sum(t[1] for t in totals.values()):>5} videos  {fmt_gb(grand)}")
    if missing:
        mpath = os.path.join(args.release_root, "missing_videos.txt")
        with open(mpath, "w") as f:
            f.write("\n".join(missing) + "\n")
        print(f"WARNING: {len(missing)} missing videos listed in {mpath}")
    print("\nReport the TOTAL above before uploading: <100 GB = free HF account, "
          "<1 TB = HF PRO ($9/mo).")


def cmd_pack(args):
    rows = read_manifest(args.release_root)
    rows = [r for r in rows if r.get("status", "unchecked") != "missing"]
    by_ds = {}
    for r in rows:
        by_ds.setdefault(dataset_of(r["release_path"]), []).append(r)
    if args.datasets:
        by_ds = {k: v for k, v in by_ds.items() if k in args.datasets}

    shard_cap = int(args.shard_gb * 1e9)
    out_dir = os.path.join(args.release_root, SHARD_DIR)
    os.makedirs(out_dir, exist_ok=True)
    index, skipped = [], []

    for ds in sorted(by_ds):
        shard_no, shard_bytes, zf = 0, 0, None
        for r in by_ds[ds]:
            src, rel = r["original_path"], r["release_path"]
            if not os.path.exists(src):
                skipped.append(src)
                continue
            size = int(r["bytes"] or 0) or os.path.getsize(src)
            if zf is None or (shard_bytes and shard_bytes + size > shard_cap):
                if zf is not None:
                    zf.close()
                    shard_no += 1
                name = f"{ds}-{shard_no:03d}.zip"
                # store-mode (no compression): mp4 doesn't compress, and it keeps
                # HTTP range-request extraction of single members cheap
                zf = zipfile.ZipFile(os.path.join(out_dir, name), "w",
                                     compression=zipfile.ZIP_STORED, allowZip64=True)
                shard_bytes = 0
                print(f"  -> {name}")
            zf.write(src, arcname=rel)
            shard_bytes += size
            index.append((rel, f"{ds}-{shard_no:03d}.zip"))
        if zf is not None:
            zf.close()
        print(f"{ds}: {len(by_ds[ds])} videos across {shard_no + 1} shard(s)")

    with open(os.path.join(out_dir, SHARD_INDEX), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["release_path", "shard"])
        w.writerows(index)
    print(f"wrote {os.path.join(out_dir, SHARD_INDEX)} ({len(index)} entries)")
    if skipped:
        print(f"WARNING: skipped {len(skipped)} files missing on disk")


def cmd_upload(args):
    from huggingface_hub import HfApi
    api = HfApi()
    api.create_repo(args.repo, repo_type="dataset", private=True, exist_ok=True)
    print(f"repo ready: https://huggingface.co/datasets/{args.repo} (PRIVATE)")

    existing = {}
    for info in api.list_repo_tree(args.repo, repo_type="dataset", recursive=True):
        size = getattr(info, "size", None)
        if size is not None:
            existing[info.path] = size

    todo = []
    out_dir = os.path.join(args.release_root, SHARD_DIR)
    for fname in sorted(os.listdir(out_dir)):
        todo.append((os.path.join(out_dir, fname), f"{SHARD_DIR}/{fname}"))
    for extra in (FILLED, MANIFEST, "missing_videos.txt", "README.md"):
        p = os.path.join(args.release_root, extra)
        if os.path.exists(p):
            todo.append((p, extra))

    for local, remote in todo:
        size = os.path.getsize(local)
        if existing.get(remote) == size:
            print(f"  skip (already uploaded): {remote}")
            continue
        print(f"  upload {remote} ({fmt_gb(size)}) ...")
        api.upload_file(path_or_fileobj=local, path_in_repo=remote,
                        repo_id=args.repo, repo_type="dataset")

    ann = os.path.join(args.release_root, "annotations")
    if os.path.isdir(ann) and not args.skip_annotations:
        print("  upload annotations/ ...")
        api.upload_folder(folder_path=ann, path_in_repo="annotations",
                          repo_id=args.repo, repo_type="dataset")
    print("upload complete. Share repo access: settings -> 'Members' / or keep "
          "personal and add collaborators via org. Send the repo id to the team.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--release-root", default=".",
                    help="directory containing video_manifest.csv (default: .)")
    sub = ap.add_subparsers(dest="mode", required=True)

    s = sub.add_parser("size", help="fill manifest bytes/status, print totals")
    s.add_argument("--sha256", action="store_true", help="also checksum (slow)")
    s.set_defaults(func=cmd_size)

    p = sub.add_parser("pack", help="write per-dataset store-mode zip shards")
    p.add_argument("--shard-gb", type=float, default=45.0,
                   help="max shard size in GB (default 45; HF caps files at 50)")
    p.add_argument("--datasets", nargs="*",
                   help="only pack these datasets (default: all)")
    p.set_defaults(func=cmd_pack)

    u = sub.add_parser("upload", help="upload shards + manifest to private HF repo")
    u.add_argument("--repo", required=True, help="e.g. <hf-username>/crossview-videos")
    u.add_argument("--skip-annotations", action="store_true")
    u.set_defaults(func=cmd_upload)

    args = ap.parse_args()
    if not os.path.exists(os.path.join(args.release_root, MANIFEST)):
        sys.exit(f"ERROR: {MANIFEST} not found in --release-root={args.release_root}")
    args.func(args)


if __name__ == "__main__":
    main()
