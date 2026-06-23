"""Single source of truth: import the production eval functions from
``Video-R1/src/eval_thinking.py`` instead of re-implementing them, so the
benchmark scores/samples identically to the existing harness.

Importing ``eval_thinking`` pulls in ``torch``/``tqdm`` (cheap on a login node)
but does NOT load any model — that only happens when a backend is constructed.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "Video-R1", "src"))

import eval_thinking as _et  # noqa: E402

build_messages = _et.build_messages
parse_choice = _et.parse_choice
gt_choice = _et.gt_choice
num_videos = _et.num_videos
video_paths = _et.video_paths
load_model = _et.load_model
extract_think = _et.extract_think
extract_answer = _et.extract_answer
QUESTION_TEMPLATE = _et.QUESTION_TEMPLATE

# Default video root for the CrossView subsets (both MEVA .avi and EgoExo4D .mp4
# resolve under it); mirrors run_eval_crossview.sbatch VIDEO_ROOT.
DEFAULT_VIDEO_ROOT = os.path.join(REPO, "crossview-release-annotations", "crossview-release")


def is_yesno(options):
    """Same predicate build_messages() uses to pick MC vs yes/no parsing."""
    return all(o.strip().strip(".").lower() in ("yes", "no") for o in options)
