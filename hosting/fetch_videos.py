#!/usr/bin/env python3
"""Fetch CrossView benchmark videos from the private Hugging Face repo.

Consumer-side counterpart of package_and_upload.py. Videos are stored as
store-mode zip shards (shards/<dataset>-NNN.zip) whose internal paths are the
release-relative video paths (videos/meva/...). That lets this script pull
single videos over HTTP range requests (remotezip) without downloading whole
shards.

Needs: pip install huggingface_hub remotezip
Auth:  hf auth login   (any READ token; you must have access to the repo)

Modes:
  subset  --qa <json...>   fetch only the videos referenced by the given
                           annotation JSON(s). Day-one path for qualitative
                           failure analysis (a handful of GB, not the world).
  dataset <name>           download ALL shards of one dataset (meva,
                           ego-exo4d, agibot, nuscenes) and extract. For the
                           full-eval stage.
  verify  --qa <json...>   report which referenced videos are present/missing
                           under the release root. No network needed.

Examples (from the CVBench repo root):
  python3 hosting/fetch_videos.py --repo <user>/crossview-videos \\
      subset --qa crossview-release-annotations/crossview-release/annotations/multi-cam-dataset/meva/qa_best_camera.json
  python3 hosting/fetch_videos.py --repo <user>/crossview-videos dataset meva
  python3 hosting/fetch_videos.py verify --qa <json>
"""
import argparse
import csv
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.join(os.path.dirname(HERE),
                            "crossview-release-annotations", "crossview-release")
SHARD_DIR = "shards"
SHARD_INDEX = "shard_index.csv"


def _auth_headers():
    from huggingface_hub import get_token
    tok = get_token()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _shard_url(repo, shard):
    from huggingface_hub import hf_hub_url
    return hf_hub_url(repo, f"{SHARD_DIR}/{shard}", repo_type="dataset")


def _abs_to_release_map(root):
    """original_path -> release_path, for QA files that still carry NAS paths."""
    out = {}
    for name in ("video_manifest.filled.csv", "video_manifest.csv"):
        p = os.path.join(root, name)
        if os.path.exists(p):
            with open(p, newline="") as f:
                for r in csv.DictReader(f):
                    out[r["original_path"]] = r["release_path"]
            break
    return out


def qa_video_paths(qa_files, root):
    """Collect unique release-relative video paths from annotation JSONs.

    Handles: plain lists, nuScenes double-encoded JSON strings, and absolute
    NAS paths (mapped through the manifest when possible).
    """
    abs_map = None
    wanted, unmapped = [], []
    for qa in qa_files:
        with open(qa) as f:
            data = json.load(f)
        records = data if isinstance(data, list) else list(data.values())
        for rec in records:
            if not isinstance(rec, dict):
                continue
            vps = rec.get("video_paths") or []
            if isinstance(vps, str):  # double-encoded
                try:
                    vps = json.loads(vps)
                except json.JSONDecodeError:
                    vps = [vps]
            for vp in vps:
                if vp.startswith("/"):
                    if abs_map is None:
                        abs_map = _abs_to_release_map(root)
                    mapped = abs_map.get(vp)
                    (wanted if mapped else unmapped).append(mapped or vp)
                else:
                    wanted.append(vp)
    if unmapped:
        print(f"WARNING: {len(set(unmapped))} absolute paths not in manifest "
              f"(first: {sorted(set(unmapped))[0]})")
    return sorted(set(wanted))


def load_shard_index(repo):
    from huggingface_hub import hf_hub_download
    path = hf_hub_download(repo, f"{SHARD_DIR}/{SHARD_INDEX}", repo_type="dataset")
    with open(path, newline="") as f:
        return {r["release_path"]: r["shard"] for r in csv.DictReader(f)}


def cmd_subset(args):
    from remotezip import RemoteZip
    wanted = qa_video_paths(args.qa, args.release_root)
    todo = [w for w in wanted
            if not os.path.exists(os.path.join(args.release_root, w))]
    print(f"{len(wanted)} videos referenced; {len(wanted) - len(todo)} present; "
          f"{len(todo)} to fetch -> {args.release_root}")
    if not todo:
        return
    index = load_shard_index(args.repo)
    by_shard, missing = {}, []
    for w in todo:
        shard = index.get(w)
        (by_shard.setdefault(shard, []) if shard else missing).append(w)
    if missing:
        print(f"WARNING: {len(missing)} videos not in shard index (not uploaded?)")
        for m in missing[:10]:
            print("   -", m)

    total_mb, fetched = 0.0, 0
    for shard in sorted(by_shard):
        members = by_shard[shard]
        print(f"shard {shard}: {len(members)} videos")
        with RemoteZip(_shard_url(args.repo, shard), headers=_auth_headers()) as z:
            for i, m in enumerate(members, 1):
                z.extract(m, args.release_root)
                sz = os.path.getsize(os.path.join(args.release_root, m)) / 1e6
                total_mb += sz
                fetched += 1
                print(f"  [{i}/{len(members)}] {m} ({sz:.1f} MB)")
    print(f"\nFetched {fetched} videos ({total_mb / 1000:.2f} GB)")


def cmd_dataset(args):
    from huggingface_hub import HfApi, hf_hub_download
    api = HfApi()
    shards = sorted(p for p in api.list_repo_files(args.repo, repo_type="dataset")
                    if p.startswith(f"{SHARD_DIR}/{args.name}-") and p.endswith(".zip"))
    if not shards:
        sys.exit(f"ERROR: no shards matching '{args.name}-*.zip' in {args.repo}")
    print(f"{len(shards)} shard(s) for {args.name}")
    for s in shards:
        print(f"downloading {s} ...")
        local = hf_hub_download(args.repo, s, repo_type="dataset")
        print(f"extracting -> {args.release_root}")
        with zipfile.ZipFile(local) as z:
            z.extractall(args.release_root)
    print("done.")


def cmd_verify(args):
    wanted = qa_video_paths(args.qa, args.release_root)
    missing = [w for w in wanted
               if not os.path.exists(os.path.join(args.release_root, w))]
    print(f"unique videos referenced: {len(wanted)}")
    print(f"present: {len(wanted) - len(missing)}")
    print(f"MISSING: {len(missing)}")
    for w in missing[:25]:
        print("   -", w)
    if len(missing) > 25:
        print(f"   ... and {len(missing) - 25} more")
    raise SystemExit(0 if not missing else 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.environ.get("CROSSVIEW_HF_REPO"),
                    help="HF dataset repo id, e.g. <user>/crossview-videos "
                         "(or set CROSSVIEW_HF_REPO)")
    ap.add_argument("--release-root", default=DEFAULT_ROOT,
                    help=f"release root for videos/ and manifest (default: {DEFAULT_ROOT})")
    sub = ap.add_subparsers(dest="mode", required=True)

    s = sub.add_parser("subset", help="fetch only videos referenced by QA json(s)")
    s.add_argument("--qa", nargs="+", required=True)
    s.set_defaults(func=cmd_subset, needs_repo=True)

    d = sub.add_parser("dataset", help="download a whole dataset's shards")
    d.add_argument("name", choices=["meva", "ego-exo4d", "agibot", "nuscenes"])
    d.set_defaults(func=cmd_dataset, needs_repo=True)

    v = sub.add_parser("verify", help="check referenced videos exist locally")
    v.add_argument("--qa", nargs="+", required=True)
    v.set_defaults(func=cmd_verify, needs_repo=False)

    args = ap.parse_args()
    if args.needs_repo and not args.repo:
        sys.exit("ERROR: pass --repo <user>/crossview-videos or set CROSSVIEW_HF_REPO")
    args.func(args)


if __name__ == "__main__":
    main()
