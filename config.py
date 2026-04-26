#!/usr/bin/env python3
"""
 _____ _____ _____ _____ _____ _____
|   __|   | |  |  |  _  |   __|  _  \
|__   | | | |  |  |   __|   __| |_| |
|_____|_|___|__|__|__|  |_____|_____/
SNIPED  v2.3  —  Roblox Rivals Auto-Clipper
https://github.com/YOUR_USERNAME/sniped

Automatically finds and clips your kills from OBS recordings.

Detection pipeline — three independent layers:

  ┌─────────────────────────────────────────────────────────────────┐
  │  LAYER 1 — PRIMARY GATES  (confirm the win)                     │
  │                                                                 │
  │  Gate 1  Green HSV    — ALWAYS required.  ROUND WON green box   │
  │                         must be visible in the top-centre zone. │
  │                                                                 │
  │  Gate 10 Kill feed    — MAIN GATE.  EasyOCR reads the top-right │
  │                         kill feed and checks that PLAYER_        │
  │                         USERNAME appears as the eliminator.     │
  │                         Only active when PLAYER_USERNAME is set.│
  │                                                                 │
  │  Gate 7  OCR win      — EasyOCR reads "WON" inside the win zone.│
  │                                                                 │
  │  Confidence rules:                                              │
  │    Gate 10 + Gate 7 both pass  → HIGH confidence → clip saved.  │
  │    Only one of 10 / 7 passes   → run fallback Gates 3 + 4.     │
  │                                  At least one must pass.        │
  │    Neither passes (OCR off)    → run fallback Gates 3 + 4.     │
  │                                  Both must pass.                │
  │                                                                 │
  │  Gate 3  White text   — Fallback only.  Checks "WON" letters    │
  │                         are present (white pixels) in win zone. │
  │  Gate 4  Shape check  — Fallback only.  Contour must be a wide  │
  │                         filled rectangle.                       │
  └─────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────┐
  │  LAYER 2 — INDEPENDENT VETO GATES  (reject if you died)         │
  │                                                                 │
  │  Each runs on its own AFTER Layer 1 confirms the win.           │
  │  All three are protected by the POST-WIN SAFETY flag:           │
  │    • Strict 1v1: you cannot die and win simultaneously —        │
  │      any death card must be from a post-win jump-off.           │
  │    • Gate 10 confirmed your kill: same reasoning — you won,     │
  │      so any visible death is post-win.                          │
  │  When post-win safe, all three veto gates are bypassed.         │
  │                                                                 │
  │  Absolute Gate 2 (un-bypassable): fires BEFORE the safety flag  │
  │  check.  If the WIN_ZONE has ≥ WIN_RED_ABSOLUTE red pixels, the │
  │  frame is rejected even in 1v1 mode.  Catches 2v2 games on the  │
  │  Crossroads map where the portrait counter wrongly returns (1,1).│
  │                                                                 │
  │  Gate 2  Red reject   — ROUND LOST red box → reject clip.       │
  │  Gate 5  Death card   — Yellow/purple death panel → reject.     │
  │  Gate 8  OCR death    — EasyOCR reads "eliminated you" → reject.│
  │                                                                 │
  │  Lookback (Gate 6): active for team games when post-win safety  │
  │  is NOT set.  Scans earlier in the round for death cards —      │
  │  if you died BEFORE the win it was a teammate's win, not yours. │
  └─────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────┐
  │  LAYER 3 — WEAPON FILTER  (Gate 9)                              │
  │                                                                 │
  │  Completely independent last layer.  If WEAPON_FILTER is set,  │
  │  EasyOCR reads the HUD weapon name and rejects the clip if it  │
  │  does not match.  Has no interaction with any other gate.       │
  └─────────────────────────────────────────────────────────────────┘
"""

# ================================================================
#  SETTINGS  — edit these to tune behaviour
# ================================================================

WORKERS       = 0     # 0 = auto (dynamically tuned to your hardware). Or e.g. 4
N_SPLITS      = 4     # How many parallel segments to split each video into.
                      # With N_SPLITS=4 a single 1-hour video gets 4 workers
                      # scanning quarters simultaneously instead of 1 worker
                      # scanning it end-to-end.  Effective workers used =
                      # max(N_SPLITS, n_workers).  Set to 1 to disable splitting.

CLIP_BEFORE   = 9     # seconds to include BEFORE the round win
CLIP_AFTER    = 2     # seconds to include AFTER  the round win
MIN_GAP       = 14    # minimum gap in seconds between two clips

# ── 1v1 mode & teammate kills ─────────────────────────────────
# In a strict 1v1 (one player per side), ROUND WON and the death card are
# mutually exclusive — you cannot win if you died.  The only legitimate
# reason a death card appears alongside ROUND WON in a 1v1 is that the
# player jumped off the map AFTER winning the round.  To stop that from
# blocking the clip:
#   • Gate 5 (same-frame death card) is bypassed in 1v1.
#   • Gate 6 (death-card lookback) is also skipped in 1v1.
#
# In 2v2 and 3v3, Gate 10 distinguishes your kills from your teammate's:
#   • Kill feed solo entry  ("Noob1234 → victim")           → clipped ✓
#   • Kill feed team entry  ("X + Noob1234 → victim") AND kill-text confirms
#     "Eliminated [victim]" with no prefix, or "Noob1234 eliminated [victim]"  → clipped ✓
#   • Kill feed team entry  AND kill-text says "Assist" or "[Teammate] eliminated"
#     → BLOCKED — this was a teammate kill                  → not clipped ✗
#
# Set CLIP_TEAMMATE_KILLS = True to disable the teammate-kill veto entirely.
# This means any ROUND WON where OCR confirms "WON" but your name is NOT
# confirmed in the kill feed will still produce a clip.  Useful if you want
# to capture every round win regardless of who made the final kill.
CLIP_TEAMMATE_KILLS = False   # True = clip teammate wins (disables teammate veto)

# ── ROUND WON zone (top-center green box) ────────────────────
# Coordinates as fractions of screen width/height.
# Calibrated from screenshot: box is at ~41-58% width, 10-24% height.
WIN_ZONE       = (0.41, 0.10, 0.58, 0.24)

# Green fill of the ROUND WON box (medium green, not neon)
WIN_GREEN_LOW  = (50,  120, 100)
WIN_GREEN_HIGH = (85,  255, 255)
WIN_GREEN_PIX  = 100   # min green pixels to pass gate 1

# Red fill of the ROUND LOST box (same position) → reject
WIN_RED_LOW    = (0,   120, 100)
WIN_RED_HIGH   = (12,  255, 255)
WIN_RED_PIX    = 100   # min red pixels to trigger rejection
# Absolute (un-bypassable) red threshold — fires even when post_win_safe=True.
# This runs FIRST inside check_frame, before any Gate or OCR processing.
#
# Calibration — Crossroads map (the tricky case):
#   The player is often looking sideways, so the ROUND LOST banner is only
#   partially inside WIN_ZONE.  Frame analysis of confirmed false-positive clips
#   measured red pixel counts of 1 364 and 4 335 at the trigger frames.
#   A genuine ROUND WON banner produces 0 red pixels (solid green + white text).
#   Setting the threshold to 300 catches all partial-overlap ROUND LOST cases
#   while being comfortably above compression-artifact noise (~5 px) and safely
#   below the minimum red count ever measured on a valid ROUND WON frame (0 px).
WIN_RED_ABSOLUTE = 300

# ── White text gate ───────────────────────────────────────────
# "WON" text is large white letters inside the green box.
# Green jumpads and backgrounds have no white text → eliminated here.
#
# CALIBRATION NOTE — Crossroads map:
#   The Crossroads map has bright green terrain that floods the WIN_ZONE with
#   green pixels, and small amounts of white can bleed in from chat bubbles,
#   HUD edges, or the in-world "RIVALS" decorative sign (~100–900 px).
#   The actual "ROUND WON" banner text generates 3 000–12 000 white pixels at
#   1920×1080 (and 1 500+ even at 1280×720).  Raising the floor to 1 000
#   eliminates all Crossroads terrain false-positives while safely passing
#   every genuine win banner at any supported resolution.
WHITE_SAT_MAX  = 40    # max saturation to count as white (low sat = white/grey)
WHITE_VAL_MIN  = 200   # min brightness to count as white
WHITE_PIX_MIN  = 1000  # min white pixels inside WIN_ZONE to pass gate 3
                        # (raised from 60 → 1000 to reject Crossroads terrain bleed)

# ── Contour shape gate ────────────────────────────────────────
# The ROUND WON box is a filled wide rectangle (aspect ~2.5:1 to 4:1).
# Organic shapes (jumpads, backgrounds) won't match this geometry.
CONTOUR_ASPECT_MIN   = 1.8   # min width:height ratio of detected green region
CONTOUR_ASPECT_MAX   = 5.0   # max width:height ratio
CONTOUR_FILL_MIN     = 0.45  # min fraction of bounding rect that is green
# Minimum area (pixels) of the largest green contour.
# The ROUND WON banner covers most of the WIN_ZONE: ~34 000 px at 1080p,
# ~15 000 px at 720p.  Setting the floor to 3 000 rejects tiny horizon
# slivers (e.g. 200 px of terrain visible while looking at the sky) that
# coincidentally pass the aspect and fill checks.
CONTOUR_AREA_MIN     = 3000

# ── Death card zone (bottom-right) ───────────────────────────
# "[Name] eliminated you" card — yellow or purple depending on match.
#
# IMPORTANT: The bottom-centre of the screen shows a kill-confirmation line
# ("Eliminated [Name]") with the target's username highlighted in yellow.
# That yellow text was previously inside this zone and caused Gate 5 to
# incorrectly block valid clips.  The zone is now tightened to the TRUE
# death-card area (the coloured panel that appears when YOU die), which sits
# firmly in the right half of the screen and below y=0.78.
DEATH_ZONE      = (0.62, 0.78, 0.90, 0.93)
DEATH_YEL_LOW   = (18,  120, 120)
DEATH_YEL_HIGH  = (42,  255, 255)
DEATH_PUR_LOW   = (115,  60,  80)
DEATH_PUR_HIGH  = (160, 255, 255)
DEATH_PIX       = 400   # large filled card = many pixels

# ── Timer & player-count zones ───────────────────────────────
TIMER_ZONE     = (0.44, 0.01, 0.56, 0.11)
ROUND_DURATION = 90    # Rivals rounds are 1 min 30 sec

# Portrait zones: small player-avatar thumbnails on each side of the top bar.
# Used to detect whether the match is 1v1 or a team game.
PORTRAIT_ZONE_L = (0.02, 0.00, 0.42, 0.13)   # left  team portrait strip
PORTRAIT_ZONE_R = (0.58, 0.00, 0.98, 0.13)   # right team portrait strip

# ── Weapon filter (Gate 9) ────────────────────────────────────
# The name of the currently selected weapon is shown in the bottom-right HUD.
# SNIPED can read this with OCR and only save clips made with specific weapons.
#
# Leave WEAPON_FILTER as [] to clip ALL kills regardless of weapon (gate off).
# Add weapon name substrings (case-insensitive) to restrict clipping.
# Examples:
#   WEAPON_FILTER = ['Assault Rifle']                → Assault Rifle kills only
#   WEAPON_FILTER = ['SNIPER', 'RPG']      → Sniper OR RPG kills
#   WEAPON_FILTER = []                        → every kill (gate disabled)
#
# Requires USE_OCR = True.  Has no effect when USE_OCR = False.
WEAPON_FILTER = []
WEAPON_ZONE   = (0.68, 0.86, 0.82, 0.96)   # ammo count + weapon name text (bottom-right HUD)
                                             # calibrated from 1280×720 screenshot:
                                             # "5  Sniper" block sits at ~900-1010px wide, ~630-680px tall

# ── Kill feed / username gate (Gate 10) ──────────────────────
# Set PLAYER_USERNAME to your exact Roblox username (case-insensitive match).
# When set, Gate 10 OCR-reads the top-right kill feed on every candidate frame
# and checks that YOUR name appears as the KILLER (left side of the feed entry).
#
# This gate is the PRIMARY accuracy gate — it rescues clips that were wrongly
# blocked by Gate 5 or 6 due to yellow username text in the kill-confirmation
# line at the bottom of the screen being misread as a death card.
#
# Leave as '' (empty string) to disable Gate 10 entirely.
#
# Example:
#   PLAYER_USERNAME = 'Noob1234'
PLAYER_USERNAME  = ''

# Screen region for the top-right kill feed (fractions of width/height).
# In Rivals the kill feed sits in the top-right corner, roughly:
#   x: 70%–100%, y: 3%–20%
# Adjust if your resolution clips the feed differently.
KILL_FEED_ZONE   = (0.70, 0.03, 1.00, 0.20)

# Kill confirmation text zone (bottom-centre).
# When a round ends the game prints the final elimination:
#   YOUR kill:       "Eliminated [victim]"           — white text, no name prefix
#   Your ASSIST:     "Assist [victim]"
#   Teammate kill:   "[Teammate] eliminated [victim]"
#
# Gate 10 reads this zone as a secondary check when the kill feed shows a
# TEAM entry ("X + Noob1234 → victim").  In that format Noob1234 is part of
# the team label regardless of who personally made the kill, so the kill feed
# alone is not enough to confirm Noob1234 was the eliminator.
#
# Calibrated from 1920×1080 recordings — text sits at roughly:
#   x: 20%–80%, y: 63%–82%
KILL_TEXT_ZONE   = (0.20, 0.63, 0.80, 0.82)


# ── OCR gates ─────────────────────────────────────────────────
# Gates 7, 8, 9 and 10 all use EasyOCR.
# Set to False to skip all OCR (faster, but less accurate — the pipeline
# falls back to visual-only Gates 3 and 4 for primary confirmation).
USE_OCR        = True

# ── Frame sampling ────────────────────────────────────────────
# FALLBACK value — overridden at runtime by auto_tune_resources() based on
# your system specs.  0.5 = check 2 frames per second.
# ROUND WON shows for ~1-2s so this guarantees we catch it.
# Lower = more accurate, higher = faster.
FRAME_SAMPLE   = 0.5

# ── Audio (disabled — fires on teammate kills and deaths too) ─
USE_AUDIO         = False
AUDIO_SENSITIVITY = 97.5   # only used if USE_AUDIO = True

# ── Debug ─────────────────────────────────────────────────────
# Set True to save a debug image showing ALL detection zones over a mid-video
# frame (WIN, DEATH, and WEAPON zones are all drawn).
# Run on ONE video, check the image, then set back to False.
DEBUG_FRAME    = False

# ================================================================

import os, sys, json, subprocess, shutil, argparse, tempfile, time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

# ── Dependency bootstrap ──────────────────────────────────────

REQUIRED = {
    'numpy':   'numpy',
    'scipy':   'scipy',
    'tqdm':    'tqdm',
    'cv2':     'opencv-python',
    'librosa': 'librosa',
    'psutil':  'psutil',
}
if USE_OCR:
    REQUIRED['easyocr'] = 'easyocr'

def ensure_deps():
    # Install core deps — skip easyocr for now (installed separately below)
    core_missing = []
    for mod, pkg in REQUIRED.items():
        if mod == 'easyocr':
            continue
        try:
            __import__(mod)
        except ImportError:
            core_missing.append(pkg)

    if core_missing:
        print(f"Installing: {', '.join(core_missing)}")
        subprocess.check_call(
            [sys.executable, '-m', 'pip', 'install', '--quiet', '--user']
            + core_missing)
        print("Core packages ready")

    # Install easyocr separately — large (~1 GB with PyTorch), may take a while
    if USE_OCR:
        try:
            import easyocr  # noqa
        except ImportError:
            print("Installing easyocr (includes PyTorch, may take a few minutes)...")
            try:
                subprocess.check_call(
                    [sys.executable, '-m', 'pip', 'install',
                     '--quiet', '--user', 'easyocr'])
                print("easyocr installed OK")
            except Exception as e:
                print(f"WARNING: easyocr install failed: {e}")
                print("         OCR gates (7, 8, 9) will be skipped this run.")
                print("         Gates 1-5 still active — accuracy is still good.")
    print()

def check_ffmpeg():
    missing = [t for t in ('ffmpeg', 'ffprobe') if not shutil.which(t)]
    if not missing:
        return
    tool = missing[0]
    import platform
    plat = platform.system()
    if plat == 'Windows':
        hint = ('  winget install ffmpeg\n'
                '  (then restart this terminal or your PC)')
    elif plat == 'Darwin':
        hint = '  brew install ffmpeg'
    else:
        hint = ('  sudo apt update && sudo apt install ffmpeg   # Debian/Ubuntu\n'
                '  sudo dnf install ffmpeg                      # Fedora\n'
                '  sudo pacman -S ffmpeg                        # Arch')
    print(f"\nERROR: {tool} not found!\n"
          f"Install it with:\n{hint}\n")
    sys.exit(1)

# ── Dynamic resource tuning ───────────────────────────────────

def auto_tune_resources(requested_workers: int) -> tuple:
    """
    Inspect CPU core count and available RAM, then return
    (n_workers, frame_sample, ram_gb, cpu_cores) tuned for maximum throughput.

    Philosophy: prioritise processing speed over resource conservation.
    Use as many cores as the machine can sustain without swapping, and the
    finest frame-sample rate the CPU budget allows.
    """
    cpu_cores = os.cpu_count() or 4

    try:
        import psutil
        ram_gb   = psutil.virtual_memory().total / 1e9
        avail_gb = psutil.virtual_memory().available / 1e9
    except Exception:
        # psutil unavailable — fall back to conservative defaults
        ram_gb   = 8.0
        avail_gb = 4.0

    # ── Workers ───────────────────────────────────────────────
    if requested_workers > 0:
        n_workers = requested_workers
    else:
        if ram_gb >= 32:
            # High-end: saturate all-but-two cores (OS + UI stay responsive)
            n_workers = max(1, cpu_cores - 2)
        elif ram_gb >= 16:
            n_workers = max(1, cpu_cores - 1)
        elif ram_gb >= 8:
            # Mid-range: half the cores to leave room for OCR and ffmpeg
            n_workers = max(1, cpu_cores // 2)
        else:
            # Low RAM — cap at 2 workers to avoid swapping
            n_workers = min(2, max(1, cpu_cores // 4))

    # ── Frame sampling ────────────────────────────────────────
    # Finer sample = less chance of missing a brief win banner.
    # We allow finer rates on machines that have the headroom.
    if ram_gb >= 16 and cpu_cores >= 8:
        fs = 0.3   # ~3 frames/s — catches even very brief banners
    elif ram_gb >= 8:
        fs = 0.5   # default — ~2 frames/s
    else:
        fs = 1.0   # ~1 frame/s — light on CPU/RAM

    return n_workers, fs, ram_gb, cpu_cores

# ── FFmpeg helpers ────────────────────────────────────────────

def get_duration(path: Path) -> float:
    r = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
         '-of', 'json', str(path)],
        capture_output=True, text=True, check=True)
    return float(json.loads(r.stdout)['format']['duration'])

def get_video_info(path: Path) -> tuple:
    """
    Return (duration_seconds, fps) via ffprobe.
    Falls back to (duration, 30.0) if the frame-rate stream entry is missing.
    Used for segment splitting so we don't have to open the video with OpenCV.
    """
    r = subprocess.run(
        ['ffprobe', '-v', 'quiet',
         '-show_entries', 'stream=r_frame_rate:format=duration',
         '-of', 'json', str(path)],
        capture_output=True, text=True, check=True)
    data     = json.loads(r.stdout)
    duration = float(data['format']['duration'])
    fps      = 30.0
    for s in data.get('streams', []):
        rfr = s.get('r_frame_rate', '')
        if '/' in rfr:
            num, den = rfr.split('/')
            if int(den) > 0:
                fps = int(num) / int(den)
                break
    return duration, fps

def extract_audio(video: Path, wav: Path):
    subprocess.run(
        ['ffmpeg', '-y', '-i', str(video),
         '-ac', '1', '-ar', '22050', '-vn', str(wav)],
        capture_output=True, check=True)

def cut_clip(video: Path, out: Path, ts: float, duration: float):
    start  = max(0.0, ts - CLIP_BEFORE)
    length = min(ts + CLIP_AFTER, duration) - start
    subprocess.run(
        ['ffmpeg', '-y',
         '-ss', f'{start:.3f}', '-i', str(video),
         '-t',  f'{length:.3f}',
         '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18',
         '-c:a', 'aac', '-b:a', '192k',
         str(out)],
        capture_output=True, check=True)

# ── Checkpoint (Windows-safe) ─────────────────────────────────

def save_checkpoint(checkpoint_path: Path, result: dict):
    data = {}
    if checkpoint_path.exists():
        try:
            data = json.loads(checkpoint_path.read_text(encoding='utf-8'))
        except Exception:
            pass
    data[result['video']] = result
    tmp = checkpoint_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    try:
        tmp.replace(checkpoint_path)
    except Exception:
        shutil.copy2(str(tmp), str(checkpoint_path))
        try: tmp.unlink()
        except Exception: pass

def load_checkpoint(checkpoint_path: Path) -> dict:
    if not checkpoint_path.exists():
        return {}
    try:
        return json.loads(checkpoint_path.read_text(encoding='utf-8'))
    except Exception:
        return {}

# ── Timestamp clustering ──────────────────────────────────────

def cluster(timestamps: list, gap: float = None) -> list:
    if not timestamps:
        return []
    g  = gap or MIN_GAP
    ts = sorted(set(round(t, 2) for t in timestamps))
    out, group = [], [ts[0]]
    for t in ts[1:]:
        if t - group[-1] < g:
            group.append(t)
        else:
            out.append(group[-1])
            group = [t]
    out.append(group[-1])
    return out

# ── OCR reader (cached per worker process) ───────────────────

_ocr_reader = None

def get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None and USE_OCR:
        try:
            import warnings
            # PyTorch fires a noisy warning about "pin_memory" when no GPU is
            # present. It just means OCR is running on your CPU instead of a
            # graphics card — everything still works fine, it's just a bit slower.
            warnings.filterwarnings(
                'ignore',
                message='.*pin_memory.*',
                category=UserWarning)
            import easyocr
            _ocr_reader = easyocr.Reader(['en'], verbose=False)
        except Exception:
            pass  # easyocr unavailable — gates 1-5 still active
    return _ocr_reader

# ── Timer OCR helper ─────────────────────────────────────────

def read_timer_elapsed(frame, w, h, reader) -> int:
    """
    Read the in-game countdown timer (top-center) and return how many
    seconds have elapsed in this round  (= ROUND_DURATION - remaining).
    Falls back to ROUND_DURATION (maximum window) if OCR fails.
    """
    import re
    tx1, ty1 = int(TIMER_ZONE[0]*w), int(TIMER_ZONE[1]*h)
    tx2, ty2 = int(TIMER_ZONE[2]*w), int(TIMER_ZONE[3]*h)
    roi = frame[ty1:ty2, tx1:tx2]
    if not roi.size or reader is None:
        return ROUND_DURATION
    try:
        results  = reader.readtext(roi, detail=0, paragraph=False)
        text     = ' '.join(str(r) for r in results)
        m        = re.search(r'(\d):?(\d{2})', text)
        if m:
            remaining = int(m.group(1)) * 60 + int(m.group(2))
            return max(1, ROUND_DURATION - remaining)
    except Exception:
        pass
    return ROUND_DURATION   # safe fallback

# ── Player-count helper ───────────────────────────────────────

def count_team_players(frame, w, h) -> tuple:
    """
    Estimate the number of players on each team by counting distinct
    portrait thumbnails in the left and right scoreboard strips.

    Returns (left_count, right_count).
    Defaults to (2, 2) when uncertain — safe: keeps lookback active.
    """
    import cv2, numpy as np

    def count_portraits(zone):
        x1, y1 = int(zone[0]*w), int(zone[1]*h)
        x2, y2 = int(zone[2]*w), int(zone[3]*h)
        roi = frame[y1:y2, x1:x2]
        if not roi.size:
            return 2

        roi_h = roi.shape[0]
        hsv   = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        # We need to detect two kinds of player indicator:
        #   • Coloured avatar thumbnails (high saturation) — alive players
        #   • White skull icons (☠, near-zero saturation) — dead players on Crossroads
        # The original threshold (S > 30) excluded white/grey pixels entirely,
        # causing skull icons to be invisible to the counter.
        # Solution: combine a low-saturation bright mask (white/grey icons) with the
        # original colorful-avatar mask so both are captured.
        bright_color = cv2.inRange(hsv,
                                   np.array([0,  30,  80], dtype=np.uint8),
                                   np.array([180, 255, 255], dtype=np.uint8))
        bright_grey  = cv2.inRange(hsv,
                                   np.array([0,   0, 160], dtype=np.uint8),
                                   np.array([180, 30, 255], dtype=np.uint8))
        bright = cv2.bitwise_or(bright_color, bright_grey)

        # Horizontal projection: total bright pixels per column
        col_proj = np.sum(bright, axis=0).astype(float)
        if col_proj.max() == 0:
            return 1

        # Tighter kernel — use 1/3 portrait height so two closely-packed
        # avatars (e.g. the 2v2 scoreboard on Crossroads) are counted
        # as two separate peaks rather than merging into one.
        portrait_w = max(1, roi_h // 3)
        kernel     = np.ones(portrait_w) / portrait_w
        smoothed   = np.convolve(col_proj, kernel, mode='same')

        # Count peaks: each portrait = one contiguous above-threshold cluster
        threshold = smoothed.max() * 0.25
        count, in_peak = 0, False
        for val in smoothed:
            if val > threshold and not in_peak:
                count += 1
                in_peak = True
            elif val <= threshold:
                in_peak = False

        return max(1, count)

    try:
        left  = count_portraits(PORTRAIT_ZONE_L)
        right = count_portraits(PORTRAIT_ZONE_R)
        return left, right
    except Exception:
        return 2, 2   # safe default — assume team game

# ── Per-frame detection gates ─────────────────────────────────

def check_frame(frame, zx1, zy1, zx2, zy2,
                dx1, dy1, dx2, dy2,
                g_lo, g_hi, r_lo, r_hi,
                dy_lo, dy_hi, dp_lo, dp_hi,
                wx1, wy1, wx2, wy2,
                kx1, ky1, kx2, ky2,
                label, t, is_1v1=False) -> tuple:
    """
    Run all per-frame detection gates on a single frame.
    Returns (passed: bool, reason: str, kill_feed_confirmed: bool).

    ── LAYER 1: Primary gates ──────────────────────────────────────────────
    Gate 1  (green HSV)   ALWAYS required — entry gate.
    Gate 10 (kill feed)   MAIN gate — EasyOCR finds PLAYER_USERNAME as killer.
    Gate 7  (OCR WON)     Primary OCR confirmer — EasyOCR reads "WON" in win zone.

    Confidence:
      Gate 10 + Gate 7 both pass  → high confidence  → skip fallback gates.
      One of 10 / 7 passes        → partial conf      → run Gates 3+4; ≥1 must pass.
      Neither passes (OCR off)    → no OCR conf       → run Gates 3+4; both must pass.

    Gate 3 (white text) and Gate 4 (shape) are FALLBACK only — they do not
    run at all when high confidence is established.

    ── LAYER 2: Independent veto gates ────────────────────────────────────
    Absolute Gate 2 (un-bypassable red check) runs FIRST — before Gate 1,
    before any OCR, before post_win_safe is computed.  It is never bypassed.

    Gate 2 (red reject), Gate 5 (death card), Gate 8 (OCR death) each run
    independently AFTER Layer 1 confirms the win.  All three are protected
    by the POST-WIN SAFETY flag:

      post_win_safe = strict 1v1  OR  kill_feed_confirmed
      → when True, all three veto gates are bypassed (post-win jump-off cannot
        produce a legitimate "you died" signal).

    Gate 6 (lookback) assists these vetoes from detect_visual: if kill_feed
    confirmed your kill, lookback is also bypassed for team games.

    ── LAYER 3: Weapon filter ──────────────────────────────────────────────
    Gate 9 runs last, completely independently.  Has no interaction with any
    other gate.
    """
    import cv2, numpy as np

    roi = frame[zy1:zy2, zx1:zx2]
    if not roi.size:
        return False, 'empty_roi', False

    hsv      = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    green_px = cv2.countNonZero(cv2.inRange(hsv, g_lo, g_hi))

    # ── Absolute Gate 2 — runs FIRST, before any other gate or OCR ───────
    # ROUND LOST produces red pixels in WIN_ZONE even when only partially
    # visible (e.g. Crossroads camera angle).  Reject immediately so we never
    # waste OCR time on a ROUND LOST frame, and so no downstream gate or safety
    # flag can accidentally override this check.
    abs_red_px = cv2.countNonZero(cv2.inRange(hsv, r_lo, r_hi))
    if abs_red_px >= WIN_RED_ABSOLUTE:
        return False, f'round_lost_absolute(red={abs_red_px})', False

    # ════════════════════════════════════════════════════════════════
    #  LAYER 1 — Primary gates
    # ════════════════════════════════════════════════════════════════

    # Gate 1: green pixels in win zone — ALWAYS required, entry gate.
    if green_px < WIN_GREEN_PIX:
        return False, 'no_green', False

    # Get OCR reader once for all OCR operations this frame.
    reader = get_ocr_reader() if USE_OCR else None

    # Gate 10: kill feed — MAIN GATE.
    # EasyOCR reads the top-right kill feed and checks that PLAYER_USERNAME
    # appears as the actual eliminator — not just as a team participant.
    #
    # ── Kill feed formats in Rivals ─────────────────────────────────────────
    #   Solo kill  (1v1 or single-player round win):
    #     [Noob1234]  --icon--  [victim]
    #     → Noob1234 is the only name on the left → confirmed solo kill.
    #
    #   Team kill  (2v2, 3v3 — BOTH teammates participated):
    #     [vnam_hero + Noob1234]  --icon--  [victim]
    #     → The ENTIRE TEAM is shown on the left regardless of who landed the
    #       final blow.  "Noob1234" being in the left half is NOT enough to
    #       confirm Noob1234 was the killer — vnam_hero may have made the kill
    #       and Noob1234 only assisted.
    #
    # ── Two-step confirmation for team entries ───────────────────────────────
    #   Step 1  Kill feed (top-right):
    #     • No "+" on the left side  → solo kill → g10_pass = True immediately.
    #     • "+" found on the left    → team entry → needs Step 2 confirmation.
    #
    #   Step 2  Kill confirmation text (bottom-centre):
    #     The game prints the outcome of the eliminating hit:
    #       "Eliminated [victim]"           — YOU made the kill (no name prefix)
    #       "[Noob1234] eliminated [victim]"— YOU made the kill (explicit prefix)
    #       "Assist [victim]"               — you assisted, teammate made the kill
    #       "[Teammate] eliminated [victim]"— teammate made the kill entirely
    #     If "ASSIST" is present → not your kill → g10_pass stays False.
    #     If "ELIMINATED" is present:
    #       • Nothing before it (or only noise)  → your kill → g10_pass = True
    #       • PLAYER_USERNAME before it          → your kill → g10_pass = True
    #       • Someone else's name before it      → teammate kill → g10_pass = False
    #
    # Only active when PLAYER_USERNAME is set.
    g10_pass = False
    if PLAYER_USERNAME and reader is not None:
        try:
            kf_roi = frame[ky1:ky2, kx1:kx2]
            if kf_roi.size:
                roi_w      = kf_roi.shape[1]
                kf_results = reader.readtext(kf_roi, detail=1, paragraph=False)
                uname_up   = PLAYER_USERNAME.upper()

                # Collect all words whose centre is in the LEFT half (killer side)
                left_words = [
                    (bbox, text, prob) for (bbox, text, prob) in kf_results
                    if sum(pt[0] for pt in bbox) / 4 < roi_w * 0.5
                ]
                left_text_joined = ' '.join(r[1] for r in left_words).upper()

                found_in_left = any(uname_up in r[1].upper() for r in left_words)

                if found_in_left:
                    if '+' not in left_text_joined:
                        # ── Solo format: Noob1234 is the only name → confirmed ──
                        g10_pass = True
                    else:
                        # ── Team format: need kill-text confirmation ──────────
                        # Check the bottom-centre kill confirmation line.
                        _fh, _fw = frame.shape[:2]
                        ktx1 = int(KILL_TEXT_ZONE[0] * _fw)
                        kty1 = int(KILL_TEXT_ZONE[1] * _fh)
                        ktx2 = int(KILL_TEXT_ZONE[2] * _fw)
                        kty2 = int(KILL_TEXT_ZONE[3] * _fh)
                        kt_roi = frame[kty1:kty2, ktx1:ktx2]
                        if kt_roi.size:
                            try:
                                kt_res  = reader.readtext(kt_roi,
                                                          detail=0, paragraph=True)
                                kt_text = ' '.join(kt_res).upper().strip()

                                if 'ASSIST' in kt_text:
                                    # You only assisted — teammate made the kill
                                    g10_pass = False

                                elif 'ELIMINATED' in kt_text:
                                    elim_idx    = kt_text.index('ELIMINATED')
                                    before_elim = kt_text[:elim_idx].strip()
                                    # "before_elim" is what precedes the word
                                    # "ELIMINATED" in the kill text.
                                    # Strip punctuation/noise: if it's empty or
                                    # very short it means there was no player name.
                                    if len(before_elim) < 4:
                                        # Nothing before "Eliminated" → your kill
                                        g10_pass = True
                                    elif uname_up in before_elim:
                                        # "Noob1234 eliminated …" → your kill
                                        g10_pass = True
                                    else:
                                        # "[Teammate] eliminated …" → not your kill
                                        g10_pass = False
                                # else: neither keyword found in kill text →
                                # cannot confirm → g10_pass stays False (safe)
                            except Exception:
                                pass  # kill-text OCR fail → g10_pass stays False

        except Exception:
            pass  # kill-feed OCR fail → g10_pass stays False

    # Gate 7: win zone OCR — primary OCR confirmer.
    # Uses detail=1 so we get per-word confidence scores.
    # Sets g7_pass when "WON" is found, and issues an un-bypassable hard-veto
    # when "LOST" is found.  A failed OCR read (e.g. partial text, stylised
    # fonts, low-resolution frames) falls through to the visual fallback gates
    # (3 and 4) — OCR failure alone never rejects a legitimate win.
    g7_pass = False
    if reader is not None:
        try:
            results  = reader.readtext(roi, detail=1, paragraph=False)
            all_text = ' '.join(r[1] for r in results).upper()
            g7_pass  = 'WON' in all_text
            # Hard-veto: if OCR clearly reads "LOST" in the win zone, reject
            # immediately — this is belt-and-suspenders on top of WIN_RED_ABSOLUTE.
            # Uses a lower confidence bar on purpose: OCR reading "LOST" is a
            # clear signal even when partially occluded (e.g. "RD LOST", "OUND
            # LOST").  Un-bypassable — post_win_safe does NOT override this.
            if 'LOST' in all_text:
                return False, f'ocr_round_lost(text:{all_text[:30]})', False
        except Exception:
            pass  # OCR fail → g7_pass stays False, visual fallback takes over

    # ── Confidence assessment ─────────────────────────────────────
    # High confidence: both primary OCR gates confirmed.
    # Partial confidence: exactly one confirmed.
    # No OCR confidence: OCR disabled or both failed.
    username_gate_active = bool(PLAYER_USERNAME)

    if username_gate_active:
        high_confidence = g7_pass and g10_pass
        some_confidence = g7_pass or g10_pass

        # ── Teammate kill veto ────────────────────────────────────
        # When CLIP_TEAMMATE_KILLS is False:
        #   "WON" confirmed (g7) + your kill NOT confirmed (g10 False)
        #   → your TEAMMATE won the round, not you → reject.
        #
        # This fires regardless of what the portrait counter says about
        # 1v1 vs team mode, because:
        #   • In a real 1v1 that YOU won, the kill feed shows YOUR name
        #     → g10_pass=True → the veto does not fire.
        #   • If OCR fails on the kill feed in 1v1, one clip may be missed —
        #     this is an acceptable trade-off vs flooding the output folder
        #     with teammate clips on Crossroads (which is a very common map).
        if not CLIP_TEAMMATE_KILLS and g7_pass and not g10_pass:
            return (False,
                    'teammate_kill(won_confirmed_by_ocr,killer_unconfirmed)',
                    False)
    elif reader is not None:
        # Gate 10 inactive — Gate 7 alone sets confidence,
        # paired with a strong Gate 1 signal.
        g1_strong       = green_px >= WIN_GREEN_PIX * 2
        high_confidence = g7_pass and g1_strong
        some_confidence = g7_pass
    else:
        # OCR fully disabled — visual fallback only.
        high_confidence = False
        some_confidence = False

    # ── Fallback gates (3 and 4) — only when not high confidence ──
    if not high_confidence:
        # Gate 3: white pixels inside win zone confirm "WON" text.
        white_mask = cv2.inRange(hsv,
            np.array([0,   0,            WHITE_VAL_MIN], dtype=np.uint8),
            np.array([180, WHITE_SAT_MAX, 255],           dtype=np.uint8))
        white_px = cv2.countNonZero(white_mask)
        g3_pass  = white_px >= WHITE_PIX_MIN

        # Gate 4: contour must be a wide filled rectangle.
        green_mask = cv2.inRange(hsv, g_lo, g_hi)
        contours, _ = cv2.findContours(green_mask,
                                       cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        g4_pass = False
        if contours:
            largest        = max(contours, key=cv2.contourArea)
            area           = cv2.contourArea(largest)
            bx, by, bw, bh = cv2.boundingRect(largest)
            if bh > 0:
                aspect  = bw / bh
                fill    = area / (bw * bh) if bw * bh > 0 else 0
                g4_pass = (CONTOUR_ASPECT_MIN <= aspect <= CONTOUR_ASPECT_MAX
                           and fill >= CONTOUR_FILL_MIN
                           and area >= CONTOUR_AREA_MIN)

        if some_confidence:
            # Partial primary confidence — at least one visual fallback must pass.
            if not g3_pass and not g4_pass:
                return (False,
                        f'partial_conf_fallback_failed'
                        f'(g7={g7_pass},g10={g10_pass},'
                        f'white={white_px},shape={g4_pass})',
                        False)
        elif username_gate_active:
            # PLAYER_USERNAME is configured but NEITHER Gate 7 ("WON" text) NOR
            # Gate 10 (your name in the kill feed) fired.
            #
            # Two reasons this can happen:
            #   (a) The green pixels are from map terrain (Crossroads, etc.) and
            #       there is no win banner at all — the most common false positive.
            #   (b) OCR genuinely failed on a real win frame.
            #
            # Behaviour depends on CLIP_TEAMMATE_KILLS:
            #
            #   CLIP_TEAMMATE_KILLS = False (default):
            #     Require at least one OCR signal.  Crossroads terrain can satisfy
            #     Gates 3 and 4 visually (wide green contour + sky white pixels)
            #     without any on-screen text — OCR is the only discriminator.
            #     Block here; it is better to miss one win than flood the output
            #     with terrain false positives.
            #
            #   CLIP_TEAMMATE_KILLS = True:
            #     The user has explicitly opted in to clip ALL round wins, including
            #     those where Gate 10 can't confirm the killer.  In this mode we
            #     cannot use "no OCR signal" as a hard block because that would
            #     silently prevent clips whenever OCR degrades (e.g. stylised fonts,
            #     low resolution, motion blur on the kill feed).
            #     Fall through to visual fallback (Gates 3 + 4, both must pass) —
            #     this mirrors the behaviour when PLAYER_USERNAME is not set.
            if not CLIP_TEAMMATE_KILLS:
                return (False,
                        f'username_active_no_ocr_signal'
                        f'(g7={g7_pass},g10={g10_pass},'
                        f'green={green_px},white_px_est=unknown)',
                        False)
            # else: CLIP_TEAMMATE_KILLS=True → fall through to visual gates below
        else:
            # No username configured, no OCR confidence — visual fallback only.
            # Both Gate 3 and Gate 4 must pass.
            if not g3_pass:
                return False, f'no_white_text(white_px={white_px})', False
            if not g4_pass:
                return False, 'bad_shape(no_ocr_fallback)', False

    # ════════════════════════════════════════════════════════════════
    #  POST-WIN SAFETY FLAG
    #  When True, all Layer-2 veto gates are bypassed.
    #  Conditions:
    #    (a) Strict 1v1: ROUND WON and death are mutually exclusive —
    #        any visible death card must be post-win (jump-off).
    #    (b) Kill feed confirmed your kill: you definitely won, so
    #        any death card on this frame is post-win.
    # ════════════════════════════════════════════════════════════════
    post_win_safe = (is_1v1 and not CLIP_TEAMMATE_KILLS) or g10_pass

    # ════════════════════════════════════════════════════════════════
    #  LAYER 2 — Independent veto gates
    #  Each gate runs on its own.  All are bypassed when post_win_safe.
    # ════════════════════════════════════════════════════════════════

    if not post_win_safe:

        # Gate 2: red box in win zone = ROUND LOST → veto.
        red_px = cv2.countNonZero(cv2.inRange(hsv, r_lo, r_hi))
        if red_px >= WIN_RED_PIX:
            return False, 'round_lost', False

        # Gate 5: yellow/purple death card in death zone → veto.
        d_roi = frame[dy1:dy2, dx1:dx2]
        if d_roi.size:
            d_hsv    = cv2.cvtColor(d_roi, cv2.COLOR_BGR2HSV)
            yel_hits = cv2.countNonZero(cv2.inRange(d_hsv, dy_lo, dy_hi))
            pur_hits = cv2.countNonZero(cv2.inRange(d_hsv, dp_lo, dp_hi))
            if (yel_hits + pur_hits) >= DEATH_PIX:
                return False, 'death_card', False

        # Gate 8: OCR reads "eliminated you" in death zone → veto.
        if reader is not None:
            try:
                d_results = reader.readtext(frame[dy1:dy2, dx1:dx2],
                                            detail=0, paragraph=True)
                d_text    = ' '.join(d_results).upper()
                if 'ELIMINATED YOU' in d_text:
                    return False, f'ocr_death({d_text[:40]})', False
            except Exception:
                pass  # OCR fail → let through

    # ════════════════════════════════════════════════════════════════
    #  LAYER 3 — Weapon filter  (Gate 9)
    #  Completely independent last layer.  No interaction with anything.
    # ════════════════════════════════════════════════════════════════
    if WEAPON_FILTER and reader is not None:
        try:
            w_roi = frame[wy1:wy2, wx1:wx2]
            if w_roi.size:
                w_results = reader.readtext(w_roi, detail=0, paragraph=True)
                w_text    = ' '.join(w_results).upper()
                if not w_text.strip():
                    # OCR read the zone successfully but found no text at all —
                    # the weapon name is not visible (e.g. the HUD is hidden,
                    # the zone is miscalibrated, or the resolution is very low).
                    # Cannot confirm the weapon → block the clip.
                    return False, 'weapon_zone_empty(no_text_read)', g10_pass
                if not any(wf.upper() in w_text for wf in WEAPON_FILTER):
                    return False, f'weapon_filtered(got:{w_text[:30]})', g10_pass
        except Exception:
            # OCR threw an exception — the weapon zone could not be read at all.
            # Cannot confirm the weapon → block the clip rather than silently
            # letting a non-matching weapon through.
            return False, 'weapon_ocr_exception', g10_pass

    conf_tag = 'high' if high_confidence else ('partial' if some_confidence else 'visual')
    kf_tag   = '+killfeed' if g10_pass else ''
    return True, f'ok({conf_tag}{kf_tag})', g10_pass

# ── Visual detection ──────────────────────────────────────────

def detect_visual(video: Path, label: str, frame_sample: float = None,
                  start_sec: float = 0.0, end_sec: float = None,
                  lookback_sec: float = None) -> tuple:
    """
    Scans video frames every frame_sample seconds.
    Each candidate frame runs through all detection gates.
    Returns (timestamps, wins_found, frames_rejected).

    start_sec / end_sec define which TIME RANGE of the video this call is
    responsible for reporting wins.  lookback_sec (≤ start_sec) defines how
    far back death-card scanning begins so that Gate 6's round-duration lookback
    has data even at the very start of a segment.  Timestamps reported are
    always within [start_sec, end_sec).

    frame_sample is passed in from the main process after auto-tuning so that
    worker subprocesses (which re-import the module on Windows) use the same
    dynamically computed value rather than the module-level fallback.
    """
    import cv2, numpy as np

    fs = frame_sample if frame_sample is not None else FRAME_SAMPLE

    cap          = cv2.VideoCapture(str(video))
    fps          = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # ── Segment range setup ───────────────────────────────────
    # scan_from_frame: where we start reading frames (may be before start_sec
    #                  so that Gate 6 lookback has death-card history).
    # report_from_frame: where we start accepting win timestamps for output.
    # stop_at_frame: where we stop (None = end of file).
    scan_from_frame   = int((lookback_sec if lookback_sec is not None
                             else start_sec) * fps)
    report_from_frame = int(start_sec * fps)
    stop_at_frame     = int(end_sec * fps) if end_sec is not None else total_frames

    # Clamp to valid range
    scan_from_frame   = max(0, min(scan_from_frame,   total_frames))
    report_from_frame = max(0, min(report_from_frame, total_frames))
    stop_at_frame     = max(report_from_frame, min(stop_at_frame, total_frames))

    # Seek to scan_from_frame so we capture lookback deaths even for the
    # first win candidate in this segment.
    if scan_from_frame > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, scan_from_frame)

    zx1, zy1 = int(WIN_ZONE[0]*w),       int(WIN_ZONE[1]*h)
    zx2, zy2 = int(WIN_ZONE[2]*w),       int(WIN_ZONE[3]*h)
    dx1, dy1 = int(DEATH_ZONE[0]*w),     int(DEATH_ZONE[1]*h)
    dx2, dy2 = int(DEATH_ZONE[2]*w),     int(DEATH_ZONE[3]*h)
    wx1, wy1 = int(WEAPON_ZONE[0]*w),    int(WEAPON_ZONE[1]*h)
    wx2, wy2 = int(WEAPON_ZONE[2]*w),    int(WEAPON_ZONE[3]*h)
    kx1, ky1 = int(KILL_FEED_ZONE[0]*w), int(KILL_FEED_ZONE[1]*h)
    kx2, ky2 = int(KILL_FEED_ZONE[2]*w), int(KILL_FEED_ZONE[3]*h)
    ltx1, lty1 = int(KILL_TEXT_ZONE[0]*w), int(KILL_TEXT_ZONE[1]*h)
    ltx2, lty2 = int(KILL_TEXT_ZONE[2]*w), int(KILL_TEXT_ZONE[3]*h)

    g_lo  = np.array(WIN_GREEN_LOW,   dtype=np.uint8)
    g_hi  = np.array(WIN_GREEN_HIGH,  dtype=np.uint8)
    r_lo  = np.array(WIN_RED_LOW,     dtype=np.uint8)
    r_hi  = np.array(WIN_RED_HIGH,    dtype=np.uint8)
    dy_lo = np.array(DEATH_YEL_LOW,   dtype=np.uint8)
    dy_hi = np.array(DEATH_YEL_HIGH,  dtype=np.uint8)
    dp_lo = np.array(DEATH_PUR_LOW,   dtype=np.uint8)
    dp_hi = np.array(DEATH_PUR_HIGH,  dtype=np.uint8)

    step = max(1, int(fps * fs))
    # Milestone percentages are relative to THIS segment's frame range so the
    # 25/50/75/100% progress reports make sense for partial-video scans.
    seg_frames    = max(1, stop_at_frame - scan_from_frame)
    total_samples = max(1, seg_frames // step)
    milestones    = {max(1, int(total_samples * p)): int(p * 100)
                     for p in (0.25, 0.5, 0.75, 1.0)}

    timestamps   = []
    last_detect  = -MIN_GAP
    wins_found   = 0
    rejected     = 0
    frame_idx    = scan_from_frame   # track absolute frame index
    sample_count = 0
    death_times  = []   # timestamps where death card was seen (for Gate 6 lookback)

    # Player-count cache.
    # Refreshed every 30 s of video time — the HUD never changes mid-match,
    # but sampling every frame would add unnecessary overhead.
    _cached_player_count   = None   # (left_count, right_count)
    _player_check_interval = max(1, int(fps * 30))   # frames between refreshes
    _last_player_check_frm = -_player_check_interval  # force check on first candidate

    # ── Debug frame ───────────────────────────────────────────
    # Only drawn for the first segment (seg 1/N) to avoid duplicate files.
    if DEBUG_FRAME and scan_from_frame == 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total_frames * 0.3))
        ret_d, frame_d = cap.read()
        if ret_d:
            cv2.rectangle(frame_d, (zx1, zy1), (zx2, zy2), (0, 255,   0), 3)
            cv2.rectangle(frame_d, (dx1, dy1), (dx2, dy2), (0,   0, 255), 3)
            cv2.rectangle(frame_d, (wx1, wy1), (wx2, wy2), (255, 165,  0), 3)
            cv2.rectangle(frame_d, (kx1, ky1), (kx2, ky2), (255, 255,  0), 3)
            cv2.rectangle(frame_d, (ltx1, lty1), (ltx2, lty2), (255, 0, 255), 3)
            cv2.putText(frame_d, "WIN ZONE",
                        (zx1, max(zy1-8, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.putText(frame_d, "DEATH ZONE",
                        (dx1, max(dy1-8, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            cv2.putText(frame_d, "WEAPON ZONE",
                        (wx1, max(wy1-8, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 165, 0), 2)
            cv2.putText(frame_d, "KILL FEED ZONE",
                        (kx1, max(ky1-8, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            cv2.putText(frame_d, "KILL TEXT ZONE",
                        (ltx1, max(lty1-8, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)
            dbg = str(video.parent / f"DEBUG_{video.stem}.jpg")
            cv2.imwrite(dbg, frame_d)
            print(f"  [{label}] DEBUG saved: {dbg}", flush=True)
        cap.set(cv2.CAP_PROP_POS_FRAMES, scan_from_frame)

    # ── Main scan loop ────────────────────────────────────────
    while True:
        try:
            ret, frame = cap.read()
        except Exception:
            frame_idx += 1
            continue
        if not ret or frame_idx >= stop_at_frame:
            break

        if frame_idx % step == 0:
            sample_count += 1
            t = frame_idx / fps

            # Always scan for death cards on every sampled frame so that the
            # lookback history is complete even for frames that are skipped
            # by the MIN_GAP guard below.
            d_roi_scan = frame[dy1:dy2, dx1:dx2]
            if d_roi_scan.size:
                import cv2 as _cv2, numpy as _np
                _dhsv = _cv2.cvtColor(d_roi_scan, _cv2.COLOR_BGR2HSV)
                _yhit = _cv2.countNonZero(_cv2.inRange(_dhsv, dy_lo, dy_hi))
                _phit = _cv2.countNonZero(_cv2.inRange(_dhsv, dp_lo, dp_hi))
                if (_yhit + _phit) >= DEATH_PIX:
                    death_times.append(t)

            # Only check for wins from report_from_frame onwards.
            # Frames in [scan_from_frame, report_from_frame) are scanned for
            # death cards only — they belong to the previous segment's win range.
            if frame_idx >= report_from_frame and (t - last_detect) >= MIN_GAP:

                # Refresh player-count cache every 30 s of video.
                # Computed BEFORE check_frame so that is_1v1 can be passed in
                # and Gate 5 can be correctly bypassed when appropriate.
                if (_cached_player_count is None or
                        (frame_idx - _last_player_check_frm) >= _player_check_interval):
                    _lc, _rc = count_team_players(frame, w, h)
                    _cached_player_count    = (_lc, _rc)
                    _last_player_check_frm  = frame_idx

                lc, rc  = _cached_player_count
                is_1v1  = (lc == 1 and rc == 1)

                passed, reason, kf_confirmed = check_frame(
                    frame,
                    zx1, zy1, zx2, zy2,
                    dx1, dy1, dx2, dy2,
                    g_lo, g_hi, r_lo, r_hi,
                    dy_lo, dy_hi, dp_lo, dp_hi,
                    wx1, wy1, wx2, wy2,
                    kx1, ky1, kx2, ky2,
                    label, t, is_1v1=is_1v1)

                if passed:
                    # ── Gate 6: death-card lookback ───────────────────────
                    # Scans earlier in the current round for death-card events.
                    # If you died BEFORE the win banner, it was a teammate's
                    # win — not yours — so the clip is rejected.
                    #
                    # Skipped when post-win safety applies:
                    #   • Strict 1v1: dying and winning are mutually exclusive.
                    #   • Kill feed confirmed YOUR kill (kf_confirmed=True):
                    #     you definitely made this kill, so any earlier death
                    #     card in the lookback window is from a PREVIOUS round,
                    #     not this one.
                    #
                    # Active for team games when neither condition holds.
                    _is_team      = (not is_1v1) or CLIP_TEAMMATE_KILLS
                    _post_win_g6  = (is_1v1 and not CLIP_TEAMMATE_KILLS) or kf_confirmed
                    if _is_team and not _post_win_g6:
                        _reader        = get_ocr_reader() if USE_OCR else None
                        _elapsed       = read_timer_elapsed(frame, w, h, _reader)
                        _recent_deaths = [dt for dt in death_times
                                          if (t - _elapsed) <= dt <= t]
                        if _recent_deaths:
                            passed = False
                            reason = (f'death_in_lookback('
                                      f'{len(_recent_deaths)}x, '
                                      f'window={_elapsed}s, '
                                      f'teams={lc}v{rc})')

                if passed:
                    timestamps.append(t)
                    last_detect = t
                    wins_found += 1
                elif reason not in ('no_green', 'empty_roi'):
                    # Count rejections that cleared Gate 1 (green pixels found).
                    # 'no_green' and 'empty_roi' are pre-Gate-1 and not false positives.
                    rejected += 1

            if sample_count in milestones:
                pct = milestones[sample_count]
                print(f"  [{label}] {pct:3d}%  kills={wins_found}  "
                      f"skipped={rejected}", flush=True)

        frame_idx += 1

    cap.release()
    return timestamps, wins_found, rejected

# ── Audio detection (optional) ────────────────────────────────

def detect_audio(wav: Path) -> list:
    import librosa, numpy as np
    from scipy.signal import find_peaks

    y, sr    = librosa.load(str(wav), sr=22050, mono=True)
    min_dist = max(1, int(sr / 512 * 2))

    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
    times     = librosa.times_like(onset_env, sr=sr, hop_length=512)
    peaks, _  = find_peaks(onset_env,
                            height=np.percentile(onset_env, AUDIO_SENSITIVITY),
                            distance=min_dist)
    ts1 = [float(times[p]) for p in peaks]

    rms       = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    rms_times = librosa.times_like(rms, sr=sr, hop_length=512)
    rms_pk, _ = find_peaks(rms,
                            height=np.percentile(rms, AUDIO_SENSITIVITY),
                            distance=min_dist)
    ts2 = [float(rms_times[p]) for p in rms_pk]

    return ts1 + ts2

# ── Worker (runs in subprocess) ───────────────────────────────

def analyze_video(task: tuple) -> dict:
    """
    Entry point for each parallel worker.
    task = (video_str, tmp_str, checkpoint_str, frame_sample,
            start_sec, end_sec, lookback_sec, seg_idx, n_segs)

    start_sec/end_sec define which portion of the video this worker scans for
    wins.  lookback_sec (≤ start_sec) is how far back death-card scanning
    begins so Gate 6 lookback has data at the very start of the segment.

    frame_sample is passed explicitly so that the auto-tuned value from the
    main process is used — worker subprocesses on Windows re-import the module
    from scratch and would otherwise fall back to the module-level default.
    """
    (video_str, tmp_str, checkpoint_str, frame_sample,
     start_sec, end_sec, lookback_sec, seg_idx, n_segs) = task

    video           = Path(video_str)
    tmp_dir         = Path(tmp_str)
    checkpoint_path = Path(checkpoint_str)

    # Label includes segment indicator so concurrent workers don't stomp each other
    stem  = video.stem[:22]
    label = f"{stem} s{seg_idx+1}/{n_segs}" if n_segs > 1 else stem[:28]

    result = dict(video=video_str, seg_idx=seg_idx, n_segs=n_segs,
                  timestamps=[], duration=0.0,
                  n_visual=0, n_audio=0, n_deaths=0, error=None)

    try:
        result['duration'] = end_sec - start_sec if end_sec else 0.0
    except Exception:
        pass

    all_ts = []

    # Visual
    try:
        print(f"  [{label}] starting visual scan "
              f"({start_sec/60:.1f}min — "
              f"{(end_sec or 0)/60:.1f}min)...", flush=True)
        v_ts, nk, nd = detect_visual(
            video, label, frame_sample=frame_sample,
            start_sec=start_sec, end_sec=end_sec, lookback_sec=lookback_sec)
        all_ts.extend(v_ts)
        result['n_visual'] = nk
        result['n_deaths'] = nd
    except Exception as e:
        print(f"  [{label}] visual error: {e}", flush=True)
        print(f"  [{label}] saving {len(all_ts)} partial timestamps", flush=True)

    # Audio — only run for the full video (seg_idx==0, n_segs==1) to avoid
    # overlapping extracts.  Audio detection doesn't benefit from splitting.
    if USE_AUDIO and seg_idx == 0 and n_segs == 1:
        wav = tmp_dir / f"_aud_{video.stem}_{os.getpid()}.wav"
        try:
            print(f"  [{label}] audio extract...", flush=True)
            extract_audio(video, wav)
            print(f"  [{label}] audio analyse...", flush=True)
            a_ts = detect_audio(wav)
            all_ts.extend(a_ts)
            result['n_audio'] = len(a_ts)
            print(f"  [{label}] audio done ({len(a_ts)} spikes)", flush=True)
        except Exception as e:
            print(f"  [{label}] audio error: {e}", flush=True)
        finally:
            try: wav.unlink(missing_ok=True)
            except Exception: pass
    elif USE_AUDIO and not (seg_idx == 0 and n_segs == 1):
        pass   # audio merged from seg 0 result in main()
    else:
        if seg_idx == 0:
            print(f"  [{label}] audio skipped", flush=True)

    result['timestamps'] = all_ts
    # Segment results are NOT individually checkpointed — the main process
    # merges all segments and writes one checkpoint entry per video.
    return result

# ── Main ──────────────────────────────────────────────────────

def main():
    import random

    # ── Easter egg: startup quotes ────────────────────────────
    _QUOTES = [
        '"One shot, one clip."',
        '"They never heard it coming."',
        '"Scope up. Breathe out. Fire."',
        '"The enemy team is about to become content."',
        '"Collateral? More like collatERROR — for them."',
        '"Patience is a virtue. So is a 1200m headshot."',
        '"No cap, that clip is going in the montage."',
        '"They called it luck. The killcam said otherwise."',
        '"Tap in. They\'re not tapping back."',
        '"Another day, another highlight reel."',
    ]

    ap = argparse.ArgumentParser(description='SNIPED v2.3 — Roblox Rivals Auto-Clipper')
    ap.add_argument('--input',   '-i', default='./recordings',
                    help='Folder containing MP4 recordings (default: ./recordings)')
    ap.add_argument('--output',  '-o', default='./clips',
                    help='Output folder for clips (default: ./clips)')
    ap.add_argument('--workers', '-w', type=int, default=WORKERS,
                    help='Parallel workers (0 = auto)')
    args = ap.parse_args()

    in_dir  = Path(args.input).resolve()
    out_dir = Path(args.output).resolve()
    tmp_dir = Path(tempfile.mkdtemp(prefix='sniped_'))

    W = 54   # banner width

    print()
    print("┌" + "─" * W + "┐")
    print("│" + " _____ _____ _____ _____ _____ _____       ".center(W) + "│")
    print("│" + "|   __|   | |  |  |  _  |   __|  _  \\     ".center(W) + "│")
    print("│" + "|__   | | | |  |  |   __|   __| |_| |     ".center(W) + "│")
    print("│" + "|_____|_|___|__|__|__|  |_____|_____/      ".center(W) + "│")
    print("│" + "".center(W) + "│")
    print("│" + "v2.3  —  Roblox Rivals Auto-Clipper".center(W) + "│")
    print("│" + "by Lollipopem  •  youtube.com/@lollipopem".center(W) + "│")
    print("│" + "".center(W) + "│")
    # Easter egg: username greeting
    if PLAYER_USERNAME.lower() == '':
        print("│" + "👑  Welcome back, king.".center(W) + "│")
        print("│" + "".center(W) + "│")
    print("│" + random.choice(_QUOTES).center(W) + "│")
    print("└" + "─" * W + "┘")
    print()

    check_ffmpeg()
    ensure_deps()

    from tqdm import tqdm

    if not in_dir.exists():
        print(f"  ERROR: input folder not found: {in_dir}")
        sys.exit(1)

    # Deduplicate MP4s (Windows case-insensitive filesystem safe)
    seen, videos = set(), []
    for v in sorted(in_dir.iterdir()):
        if v.suffix.lower() == '.mp4':
            key = os.path.normcase(str(v.resolve()))
            if key not in seen:
                seen.add(key)
                videos.append(v)

    if not videos:
        print(f"  ERROR: no MP4 files found in {in_dir}")
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Dynamic resource tuning ───────────────────────────────
    n_workers, dynamic_fs, ram_gb, cpu_cores = auto_tune_resources(args.workers)

    n_splits    = max(1, N_SPLITS)
    eff_workers = max(n_workers, n_splits)

    # ── Checkpoint resume ─────────────────────────────────────
    checkpoint_path = out_dir / 'sniped_progress.json'
    checkpoint      = load_checkpoint(checkpoint_path)

    already_done = {v for v in checkpoint
                    if checkpoint[v].get('timestamps') is not None
                    and not checkpoint[v].get('error')}
    todo_videos  = [v for v in videos if str(v) not in already_done]

    total_gb  = sum(v.stat().st_size for v in videos) / 1e9
    todo_gb   = sum(v.stat().st_size for v in todo_videos) / 1e9

    # ── Config summary box ────────────────────────────────────
    def _row(key, val):
        line = f"  {key:<14} {val}"
        print("│" + line.ljust(W) + "│")

    print("┌" + "─" * W + "┐")
    print("│" + "  CONFIG".ljust(W) + "│")
    print("├" + "─" * W + "┤")
    _row("Input",    str(in_dir)[:W-18] + ("…" if len(str(in_dir)) > W-18 else ""))
    _row("Output",   str(out_dir)[:W-18] + ("…" if len(str(out_dir)) > W-18 else ""))
    _row("Videos",   f"{len(videos)} file(s)  ({total_gb:.1f} GB)")
    _row("System",   f"{cpu_cores} cores  /  {ram_gb:.0f} GB RAM")
    _row("Workers",  f"{eff_workers}  ({n_workers} auto  +  {n_splits} splits/video)")
    _row("Sampling", f"every {dynamic_fs:.1f}s  (auto-tuned)")
    _row("Clip",     f"-{CLIP_BEFORE}s … +{CLIP_AFTER}s around each kill")
    _row("OCR",      "enabled" if USE_OCR else "DISABLED (visual fallback)")
    _row("Username", f"'{PLAYER_USERNAME}'  (Gate 10 ON)" if PLAYER_USERNAME
                     else "NOT SET  ← set PLAYER_USERNAME for best accuracy")
    _row("Teammates", "clip all wins" if CLIP_TEAMMATE_KILLS
                      else "your kills only")
    _row("Weapon",   ', '.join(WEAPON_FILTER) if WEAPON_FILTER else "all weapons")
    if ram_gb < 8:
        print("├" + "─" * W + "┤")
        print("│" + "  ⚠  Low RAM — workers & sampling reduced.".ljust(W) + "│")
        print("│" + "     Close other apps for best results.".ljust(W) + "│")
    if not PLAYER_USERNAME:
        print("├" + "─" * W + "┤")
        print("│" + "  ⚠  Gate 10 is OFF.  Accuracy is lower without it.".ljust(W) + "│")
        print("│" + "     Set PLAYER_USERNAME = 'YourName' to enable.".ljust(W) + "│")
    if already_done:
        prior_clips = sum(
            len(cluster(checkpoint[v]['timestamps']))
            for v in already_done if checkpoint[v].get('timestamps'))
        print("├" + "─" * W + "┤")
        print("│" + (f"  ↩  Resuming: {len(already_done)} done, "
                     f"{len(todo_videos)} remaining  "
                     f"({prior_clips} clips already found)").ljust(W) + "│")
        print("│" + (f"     Delete {checkpoint_path.name} to start fresh").ljust(W) + "│")
    print("└" + "─" * W + "┘")
    print()

    # ── PHASE 1: parallel analysis ────────────────────────────
    total_segments = len(todo_videos) * n_splits
    print("┌" + "─" * W + "┐")
    print("│" + (f"  PHASE 1/2  —  Scanning  "
                 f"({len(todo_videos)} video(s) × {n_splits} seg = "
                 f"{total_segments} tasks)").ljust(W) + "│")
    print("└" + "─" * W + "┘")
    print()

    results   = dict(checkpoint)
    t_start   = time.time()

    if todo_videos:
        tasks = []
        video_durations = {}
        for v in todo_videos:
            try:
                duration, _fps = get_video_info(v)
            except Exception:
                try:
                    duration = get_duration(v)
                except Exception:
                    duration = 0.0
            video_durations[str(v)] = duration

            seg_len = duration / n_splits if n_splits > 1 else duration
            for i in range(n_splits):
                s_start    = i * seg_len
                s_end      = (i + 1) * seg_len if i < n_splits - 1 else duration
                s_lookback = max(0.0, s_start - ROUND_DURATION)
                tasks.append((
                    str(v), str(tmp_dir), str(checkpoint_path),
                    dynamic_fs,
                    s_start, s_end, s_lookback,
                    i, n_splits,
                ))

        from collections import defaultdict
        seg_results      = defaultdict(list)
        sizes_gb         = {str(v): v.stat().st_size / 1e9 for v in todo_videos}
        # ── ETA fix: track GB per segment so single-video ETA works ──────
        # Each segment represents 1/n_splits of its video's file size.
        # We credit partial GB as each segment finishes so the ETA is live
        # even when there is only one video being processed.
        seg_gb           = {str(v): sizes_gb[str(v)] / n_splits for v in todo_videos}
        completed_seg_gb = 0.0   # increments per segment, not per video

        with ProcessPoolExecutor(max_workers=eff_workers) as executor:
            future_map = {executor.submit(analyze_video, t): t[0] for t in tasks}

            with tqdm(total=total_segments, unit='seg',
                      bar_format='  Scanning [{bar}] {n}/{total} segments  '
                                 'elapsed={elapsed}') as pbar:
                for future in as_completed(future_map):
                    video_str = future_map[future]
                    try:
                        res = future.result()
                    except Exception as e:
                        res = dict(video=video_str, seg_idx=0, n_segs=n_splits,
                                   timestamps=[], duration=0,
                                   n_visual=0, n_audio=0, n_deaths=0, error=str(e))
                        print(f"\n  ✗ ERROR on {Path(video_str).name}: {e}", flush=True)

                    seg_results[video_str].append(res)

                    # ── ETA: credit this segment immediately ──────────────
                    completed_seg_gb += seg_gb.get(video_str, 0)
                    elapsed          = time.time() - t_start
                    rate_gb          = completed_seg_gb / elapsed if elapsed > 0 else 0
                    remaining_gb     = todo_gb - completed_seg_gb
                    eta_s            = remaining_gb / rate_gb if rate_gb > 0 else 0
                    eta_str          = (f"{int(eta_s//60)}m{int(eta_s%60):02d}s"
                                       if eta_s > 0 and completed_seg_gb > 0
                                       else "calculating…")
                    speed_str        = (f"{rate_gb * 60:.1f} GB/hr"
                                       if rate_gb > 0 else "")

                    # When ALL segments for a video are done, merge + checkpoint
                    if len(seg_results[video_str]) == n_splits:
                        segs = sorted(seg_results[video_str],
                                      key=lambda r: r.get('seg_idx', 0))
                        merged = dict(
                            video      = video_str,
                            timestamps = [ts for s in segs for ts in s['timestamps']],
                            duration   = video_durations.get(video_str, 0.0),
                            n_visual   = sum(s['n_visual']  for s in segs),
                            n_audio    = sum(s['n_audio']   for s in segs),
                            n_deaths   = sum(s['n_deaths']  for s in segs),
                            error      = next((s['error'] for s in segs
                                              if s.get('error')), None),
                        )
                        results[video_str] = merged
                        try:
                            save_checkpoint(checkpoint_path, merged)
                        except Exception as ce:
                            print(f"\n  WARNING: checkpoint save failed: {ce}",
                                  flush=True)

                        n_clips = len(cluster(merged['timestamps']))
                        kills   = merged['n_visual']
                        # Easter egg: milestone kill counts
                        if kills >= 30:
                            tqdm.write(f"  🔥 {Path(video_str).name[:28]}: "
                                       f"{kills} kills — INSANE session!")
                        elif kills >= 15:
                            tqdm.write(f"  💥 {Path(video_str).name[:28]}: "
                                       f"{kills} kills — great session!")
                        elif kills == 0:
                            tqdm.write(f"  🎯 {Path(video_str).name[:28]}: "
                                       f"no kills found — tough one.")
                        else:
                            tqdm.write(f"  ✓ {Path(video_str).name[:28]}: "
                                       f"{kills} kills → {n_clips} clip(s)")

                    pbar.set_postfix_str(f"ETA {eta_str}  {speed_str}")
                    pbar.update(1)
    else:
        print("  All videos already analysed — jumping to clipping!\n")

    # ── PHASE 2: cut clips ────────────────────────────────────
    print()
    print("┌" + "─" * W + "┐")
    print("│" + "  PHASE 2/2  —  Cutting clips".ljust(W) + "│")
    print("└" + "─" * W + "┘")
    print()

    current_video_strs = {str(v) for v in videos}
    total_clips        = 0
    total_kills_found  = 0
    total_skipped      = 0

    for video_str, res in results.items():
        if video_str not in current_video_strs:
            continue
        video    = Path(video_str)
        duration = res['duration']
        final_ts = cluster(res['timestamps'])
        kills    = res['n_visual']
        skipped  = res['n_deaths']
        total_kills_found += kills

        print(f"  {video.name}")
        print(f"  {'─' * (W - 2)}")
        print(f"  kills found : {kills}   skipped : {skipped}   "
              f"clips : {len(final_ts)}")

        if not final_ts:
            print("  (nothing to cut)")
            print()
            continue

        with tqdm(total=len(final_ts), unit='clip', leave=True,
                  bar_format='  [{bar}] {n}/{total} clips  {elapsed}<{remaining}') as cbar:
            for i, ts in enumerate(final_ts, 1):
                mm, ss = int(ts // 60), int(ts % 60)
                name   = f"{video.stem}__clip{i:03d}_{mm:02d}m{ss:02d}s.mp4"
                out    = out_dir / name
                try:
                    cut_clip(video, out, ts, duration)
                    size = out.stat().st_size if out.exists() else 0
                    if size < 50_000:
                        tqdm.write(f"  ✗ clip {i:03d}  {mm:02d}:{ss:02d}  "
                                   f"skipped (output {size} bytes — FFmpeg issue)")
                        if out.exists(): out.unlink()
                        total_skipped += 1
                    else:
                        mb = size / 1_000_000
                        tqdm.write(f"  ✓ clip {i:03d}  {mm:02d}:{ss:02d}  {mb:.0f} MB  {name}")
                        cbar.set_postfix_str(f"{mm:02d}:{ss:02d}  {mb:.0f} MB")
                        total_clips += 1
                except subprocess.CalledProcessError as e:
                    tqdm.write(f"  ✗ clip {i:03d}  {mm:02d}:{ss:02d}  "
                               f"FFmpeg error: "
                               f"{e.stderr.decode('utf-8', errors='replace')[-200:]}")
                except Exception as e:
                    tqdm.write(f"  ✗ clip {i:03d}  {mm:02d}:{ss:02d}  failed: {e}")
                cbar.update(1)
        print()

    shutil.rmtree(tmp_dir, ignore_errors=True)

    elapsed   = time.time() - t_start
    hrs       = int(elapsed // 3600)
    mins      = int((elapsed % 3600) // 60)
    secs      = int(elapsed % 60)
    elapsed_h = elapsed / 3600
    gb_hr     = todo_gb / elapsed_h if elapsed_h > 0 else 0

    # ── Final summary box ─────────────────────────────────────
    print("┌" + "─" * W + "┐")
    print("│" + "  DONE".ljust(W) + "│")
    print("├" + "─" * W + "┤")
    _row("Kills found",  str(total_kills_found))
    _row("Clips saved",  str(total_clips))
    _row("Output",       str(out_dir)[:W-18] + ("…" if len(str(out_dir)) > W-18 else ""))
    _row("Time taken",   f"{hrs}h {mins}m {secs}s  ({gb_hr:.1f} GB/hr)")
    if total_skipped:
        _row("Skipped",  f"{total_skipped} (FFmpeg errors — check log above)")
    print("├" + "─" * W + "┤")

    # Easter egg: end-of-run reactions
    if total_clips == 0:
        msg = "No clips this run. The highlight reel can wait. 🎯"
    elif total_clips >= 50:
        msg = "50+ clips?! Are you even human?? 🤖🔥"
    elif total_clips >= 25:
        msg = "That's a BANGER session. Post the montage. 🎬"
    elif total_clips >= 10:
        msg = "Solid haul. Editor's gonna love this. 💪"
    elif total_clips == 1:
        msg = "One clip. Make it count. 🎯"
    else:
        msg = "Clips are ready. Time to cook the montage. ✂️"
    print("│" + f"  {msg}".ljust(W) + "│")
    print("└" + "─" * W + "┘")
    print()


# Required on Windows for multiprocessing
if __name__ == '__main__':
    main()