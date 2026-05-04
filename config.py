#!/usr/bin/env python3
"""
 _____ _____ _____ _____ _____ _____
|   __|   | |  |  |  _  |   __|  _  \\
|__   | | | |  |  |   __|   __| |_| |
|_____|_|___|__|__|__|  |_____|_____/
SNIPED  v2.4  —  Roblox Rivals Auto-Clipper

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
  │                         Assist detection (two checks):          │
  │                           A) Kill text says "Assist"            │
  │                           B) '+' in feed AND kill text does NOT │
  │                              name your username before "elim-   │
  │                              inated"                            │
  │                         Kill text is parsed as "[Name] elimi-   │
  │                         nated [Victim]" and Name is fuzzy-      │
  │                         matched against PLAYER_USERNAME.        │
  │                         OCR-garbled username fallback: if kill  │
  │                         text says "[YourName] eliminated [X]"   │
  │                         and feed had any left-side text,        │
  │                         treated as confirmed player kill.       │
  │                         Only active when PLAYER_USERNAME is set.│
  │                                                                 │
  │  Gate 7  OCR win      — EasyOCR reads "WON" inside the win zone.│
  │                                                                 │
  │  Confidence rules:                                              │
  │    Gate 10 passes            → HIGH confidence → clip saved.   │
  │    Gate 7 only (no Gate 10)  → partial conf → fallback G3+G4.  │
  │                                At least one must pass.          │
  │    Neither passes (OCR off)  → run fallback Gates 3 + 4.       │
  │                                Both must pass.                  │
  │                                                                 │
  │  Gate 3  White text   — Fallback only.                          │
  │  Gate 4  Shape check  — Fallback only.                          │
  └─────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────┐
  │  LAYER 2 — INDEPENDENT VETO GATES  (reject if you died)         │
  │                                                                 │
  │  Gate 2  Red reject   — ROUND LOST red box → reject clip.       │
  │  Gate 5  Death card   — Yellow/purple death panel → reject.     │
  │  Gate 8  OCR death    — EasyOCR reads "eliminated you" → reject.│
  │  Gate 6  Lookback     — death before win = teammate win.        │
  └─────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────┐
  │  LAYER 3 — WEAPON FILTER  (Gate 9)                              │
  │                                                                 │
  │  EasyOCR reads the HUD weapon name (bottom-right) on every      │
  │  confirmed kill.  If WEAPON_FILTER is set, kills with           │
  │  non-matching weapons are rejected.                             │
  │                                                                 │
  │  HEADSHOT DETECTION: the game places a skull icon (☠) between   │
  │  the weapon icon and the victim's name in the kill feed.        │
  │  Detected by counting distinct white pixel clusters in the gap: │
  │    1 cluster  = weapon icon only  → normal kill                 │
  │    2 clusters = weapon + skull    → headshot                    │
  └─────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────┐
  │  PAUSE / RESUME                                                 │
  │                                                                 │
  │  Press  Ctrl + P  at any time to pause scanning.               │
  │  Press  Ctrl + P  again to resume.                             │
  │  Workers check the pause state every ~5 seconds.               │
  └─────────────────────────────────────────────────────────────────┘
"""

# ================================================================
#  USER SETTINGS  —  the only section you need to edit
# ================================================================

# ── Who are you? ──────────────────────────────────────────────
PLAYER_USERNAME = ''  # Set this to your Roblox username to enable Gate 10

# ── What to clip ──────────────────────────────────────────────
CLIP_TEAMMATE_KILLS = False
HEADSHOT_ONLY       = False  # True = only clip headshot kills (skull in kill feed)

# ── Weapon filter ─────────────────────────────────────────────
# Leave empty to clip kills with any weapon.
# EasyOCR reads the weapon name from the HUD bottom-right.
# Examples:
#   WEAPON_FILTER = ['sniper']         -> sniper kills only
#   WEAPON_FILTER = ['sniper', 'rpg']  -> sniper OR RPG kills
#   WEAPON_FILTER = []                 -> every kill (gate disabled)
WEAPON_FILTER = []

# ── Clip timing ───────────────────────────────────────────────
CLIP_BEFORE = 9
CLIP_AFTER  = 2
MIN_GAP     = 14

# ── Performance ───────────────────────────────────────────────
WORKERS  = 0
N_SPLITS = 4

# ── Features ──────────────────────────────────────────────────
USE_OCR     = True
DEBUG_FRAME = False

# ================================================================
#  INTERNAL CONSTANTS
# ================================================================

WIN_ZONE       = (0.41, 0.10, 0.58, 0.24)
WIN_GREEN_LOW  = (50,  120, 100)
WIN_GREEN_HIGH = (85,  255, 255)
WIN_GREEN_PIX  = 800  # raised from 100 – map grass/terrain only produces ~100-400 px, real ROUND WON banner fills zone with 1000+
WIN_GOLD_LOW   = (8,   150, 150)  # orange/gold MVP / draw banner (H≈10-19 measured from recordings)
WIN_GOLD_HIGH  = (22,  255, 255)
WIN_GOLD_PIX   = 800  # same threshold as green – gold banner saturates the zone just as hard
WIN_RED_LOW    = (0,   120, 100)
WIN_RED_HIGH   = (12,  255, 255)
WIN_RED_PIX    = 100
WIN_RED_ABSOLUTE = 300

WHITE_SAT_MAX  = 40
WHITE_VAL_MIN  = 200
WHITE_PIX_MIN  = 1000

CONTOUR_ASPECT_MIN    = 1.8
CONTOUR_ASPECT_MAX    = 5.0
CONTOUR_FILL_MIN      = 0.45
CONTOUR_AREA_MIN      = 5000
WIN_GREEN_DENSITY_MIN = 0.20

DEATH_ZONE        = (0.62, 0.78, 0.90, 0.93)
DEATH_YEL_LOW     = (18,  120, 120)
DEATH_YEL_HIGH    = (42,  255, 255)
DEATH_PUR_LOW     = (115,  60,  80)
DEATH_PUR_HIGH    = (160, 255, 255)
DEATH_BLOB_MIN    = 4000
DEATH_BLOB_ASPECT = 3.5
DEATH_BLOB_FILL   = 0.55

TIMER_ZONE     = (0.44, 0.01, 0.56, 0.11)
ROUND_DURATION = 90

PORTRAIT_ZONE_L = (0.02, 0.00, 0.42, 0.13)
PORTRAIT_ZONE_R = (0.58, 0.00, 0.98, 0.13)

WEAPON_ZONE    = (0.65, 0.86, 0.84, 0.96)
KILL_FEED_ZONE = (0.70, 0.05, 1.00, 0.12)  # bottom raised from 0.18 → 0.12 to exclude spectator/party bar
KILL_TEXT_ZONE = (0.20, 0.63, 0.80, 0.82)

FRAME_SAMPLE      = 0.5
USE_AUDIO         = False
AUDIO_SENSITIVITY = 97.5

# ── Headshot detection ────────────────────────────────────────
# Min area (px²) for a white blob to count as a real icon vs noise.
# At 1080p the skull is ~15×15 = 225 px²; weapon icons ~20×20+.
HEADSHOT_BLOB_MIN_AREA = 20

# ── Pause feature ─────────────────────────────────────────────
# Pressing Ctrl+P toggles a pause flag file.
# Workers check for it every PAUSE_CHECK_INTERVAL samples (~5 s).
PAUSE_CHECK_INTERVAL = 10

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

    # pynput for Ctrl+P pause listener
    try:
        import pynput  # noqa
    except ImportError:
        try:
            subprocess.check_call(
                [sys.executable, '-m', 'pip', 'install',
                 '--quiet', '--user', 'pynput'])
            print("pynput installed OK")
        except Exception:
            print("WARNING: pynput not available — Ctrl+P pause disabled.")
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
                '  (then close and reopen this terminal window before re-running)')
    elif plat == 'Darwin':
        hint = '  brew install ffmpeg'
    else:
        hint = ('  sudo apt update && sudo apt install ffmpeg   # Debian/Ubuntu\n'
                '  sudo dnf install ffmpeg                      # Fedora\n'
                '  sudo pacman -S ffmpeg                        # Arch')
    print(f"\nERROR: {tool} not found!\nInstall it with:\n{hint}\n")
    sys.exit(1)


# ── Pause feature (file-based IPC) ───────────────────────────
# _PAUSE_FILE is set by main() before spawning workers.
# Workers call check_paused() periodically inside detect_visual().

_PAUSE_FILE = None


def check_paused():
    """Block until the pause flag is cleared.  No-op if _PAUSE_FILE is None.
    Workers call this — they silently wait.  Only the main-process
    listener announces PAUSED / RESUMED to avoid duplicate messages."""
    global _PAUSE_FILE
    if _PAUSE_FILE is None:
        return
    pf = Path(_PAUSE_FILE)
    while pf.exists():
        time.sleep(0.5)


def _start_pause_listener(pause_file: Path):
    """
    Start a background thread listening for Ctrl+P.
    Toggles pause_file on/off.  Returns the listener or None.
    """
    try:
        from pynput import keyboard as _kb

        _state = {'paused': False}

        def _on_activate():
            if _state['paused']:
                try:
                    pause_file.unlink(missing_ok=True)
                except Exception:
                    try:
                        pause_file.unlink()
                    except Exception:
                        pass
                _state['paused'] = False
                print("\n  ▶  RESUMED\n", flush=True)
            else:
                pause_file.touch()
                _state['paused'] = True
                print("\n  ⏸  PAUSED — press Ctrl+P again to resume…", flush=True)

        hotkey = _kb.GlobalHotKeys({'<ctrl>+p': _on_activate})
        hotkey.start()
        return hotkey
    except Exception as e:
        print(f"  ⚠  Ctrl+P pause unavailable ({e}). "
              f"Scanning will run uninterrupted.\n", flush=True)
        return None


# ── Dynamic resource tuning ───────────────────────────────────

def auto_tune_resources(requested_workers: int) -> tuple:
    cpu_cores = os.cpu_count() or 4
    try:
        import psutil
        ram_gb   = psutil.virtual_memory().total     / 1e9
        avail_gb = psutil.virtual_memory().available / 1e9
    except Exception:
        ram_gb   = 8.0
        avail_gb = 4.0

    if requested_workers > 0:
        n_workers = requested_workers
    else:
        ram_per_worker = 1.5 if USE_OCR else 0.4
        RAM_RESERVE    = 2.0
        budget_gb      = max(0.0, avail_gb - RAM_RESERVE)
        ram_safe       = max(1, int(budget_gb / ram_per_worker))
        if ram_gb >= 32:
            cpu_cap = max(1, cpu_cores - 2)
        elif ram_gb >= 16:
            cpu_cap = max(1, cpu_cores - 1)
        else:
            cpu_cap = max(1, cpu_cores // 2)
        n_workers = min(ram_safe, cpu_cap)
        n_workers = max(1, min(n_workers, cpu_cores))

    if avail_gb >= 10 and cpu_cores >= 8:
        fs = 0.3
    elif avail_gb >= 5:
        fs = 0.5
    else:
        fs = 1.0

    return n_workers, fs, ram_gb, avail_gb, cpu_cores


# ── FFmpeg helpers ────────────────────────────────────────────

def get_duration(path: Path) -> float:
    r = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
         '-of', 'json', str(path)],
        capture_output=True, text=True, check=True)
    return float(json.loads(r.stdout)['format']['duration'])


def get_video_info(path: Path) -> tuple:
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


def cut_clip_copy(video: Path, out: Path, ts: float, duration: float):
    start  = max(0.0, ts - CLIP_BEFORE)
    length = min(ts + CLIP_AFTER, duration) - start
    subprocess.run(
        ['ffmpeg', '-y',
         '-ss', f'{start:.3f}', '-i', str(video),
         '-t',  f'{length:.3f}',
         '-c', 'copy',
         str(out)],
        capture_output=True, check=True)


# ── Checkpoint ────────────────────────────────────────────────

def save_checkpoint(checkpoint_path: Path, result: dict, key: str = None):
    data = {}
    if checkpoint_path.exists():
        try:
            data = json.loads(checkpoint_path.read_text(encoding='utf-8'))
        except Exception:
            pass
    data[key if key is not None else result['video']] = result
    tmp = checkpoint_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    try:
        tmp.replace(checkpoint_path)
    except Exception:
        shutil.copy2(str(tmp), str(checkpoint_path))
        try:
            tmp.unlink()
        except Exception:
            pass


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
            warnings.filterwarnings('ignore', message='.*pin_memory.*',
                                    category=UserWarning)
            import easyocr
            _ocr_reader = easyocr.Reader(['en'], verbose=False)
        except Exception:
            pass
    return _ocr_reader


# ── Timer OCR helper ─────────────────────────────────────────

def read_timer_elapsed(frame, w, h, reader) -> int:
    import re
    tx1, ty1 = int(TIMER_ZONE[0]*w), int(TIMER_ZONE[1]*h)
    tx2, ty2 = int(TIMER_ZONE[2]*w), int(TIMER_ZONE[3]*h)
    roi = frame[ty1:ty2, tx1:tx2]
    if not roi.size or reader is None:
        return ROUND_DURATION
    try:
        results = reader.readtext(roi, detail=0, paragraph=False)
        text    = ' '.join(str(r) for r in results)
        m       = re.search(r'(\d):?(\d{2})', text)
        if m:
            remaining = int(m.group(1)) * 60 + int(m.group(2))
            return max(1, ROUND_DURATION - remaining)
    except Exception:
        pass
    return ROUND_DURATION


# ── Player-count helper ───────────────────────────────────────

def count_team_players(frame, w, h) -> tuple:
    import cv2, numpy as np

    def count_portraits(zone):
        x1, y1 = int(zone[0]*w), int(zone[1]*h)
        x2, y2 = int(zone[2]*w), int(zone[3]*h)
        roi = frame[y1:y2, x1:x2]
        if not roi.size:
            return 2
        roi_h, roi_w = roi.shape[:2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        bright_color = cv2.inRange(hsv,
                                   np.array([0,  30,  80], dtype=np.uint8),
                                   np.array([180, 255, 255], dtype=np.uint8))
        bright_grey  = cv2.inRange(hsv,
                                   np.array([0,   0, 160], dtype=np.uint8),
                                   np.array([180,  30, 255], dtype=np.uint8))
        bright = cv2.bitwise_or(bright_color, bright_grey)
        kernel      = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        bright_open = cv2.morphologyEx(bright, cv2.MORPH_OPEN, kernel)
        num_labels, _, stats, _ = cv2.connectedComponentsWithStats(
            bright_open, connectivity=8)
        min_blob_area = max(100, int((roi_h * 0.30) ** 2))
        max_blob_area = int(roi_h * roi_w * 0.45)
        count = 0
        for i in range(1, num_labels):
            area   = int(stats[i, cv2.CC_STAT_AREA])
            bw     = int(stats[i, cv2.CC_STAT_WIDTH])
            bh     = int(stats[i, cv2.CC_STAT_HEIGHT])
            aspect = bw / max(bh, 1)
            if min_blob_area <= area <= max_blob_area and 0.25 <= aspect <= 4.0:
                count += 1
        return max(1, count)

    try:
        left  = count_portraits(PORTRAIT_ZONE_L)
        right = count_portraits(PORTRAIT_ZONE_R)
        return left, right
    except Exception:
        return 2, 2


# ── Headshot detection ────────────────────────────────────────

def detect_headshot_in_killfeed(kf_roi, killer_right: float,
                                 victim_left: float,
                                 row_y1: float, row_y2: float) -> bool:
    """
    Detect a headshot skull by counting distinct white pixel clusters in
    the icon gap between the killer's name and the victim's name.

    The Rivals kill feed always shows:
        [Killer name box]  [weapon icon]  [optional skull ☠]  [Victim name box]

    Both the weapon icon and the skull are white silhouettes on a dark
    background, forming distinct connected components.

        Normal kill  → 1 white blob  (weapon only)
        Headshot     → 2 white blobs (weapon + skull)

    Returns True if ≥ 2 significant white blobs are found in the gap.
    """
    import cv2 as _cv2, numpy as _np

    x1 = max(0, int(killer_right) + 1)
    x2 = min(kf_roi.shape[1], int(victim_left) - 1)
    y1 = max(0, int(row_y1))
    y2 = min(kf_roi.shape[0], int(row_y2))

    if x2 <= x1 + 4 or y2 <= y1 + 2:
        return False

    gap = kf_roi[y1:y2, x1:x2]
    if not gap.size:
        return False

    gray = _cv2.cvtColor(gap, _cv2.COLOR_BGR2GRAY)
    _, white_mask = _cv2.threshold(gray, 170, 255, _cv2.THRESH_BINARY)

    kernel = _np.ones((2, 2), dtype=_np.uint8)
    white_mask = _cv2.morphologyEx(white_mask, _cv2.MORPH_OPEN, kernel)

    num_labels, _, stats, _ = _cv2.connectedComponentsWithStats(
        white_mask, connectivity=8)

    significant = [
        i for i in range(1, num_labels)
        if stats[i, _cv2.CC_STAT_AREA] >= HEADSHOT_BLOB_MIN_AREA
    ]

    return len(significant) >= 2


# ── Per-frame detection gates ─────────────────────────────────

def check_frame(frame, zx1, zy1, zx2, zy2,
                dx1, dy1, dx2, dy2,
                g_lo, g_hi, r_lo, r_hi,
                dy_lo, dy_hi, dp_lo, dp_hi,
                wx1, wy1, wx2, wy2,
                kx1, ky1, kx2, ky2,
                label, t, is_1v1=False) -> tuple:
    """
    Run all per-frame detection gates.

    Returns:
        (passed, reason, kill_feed_confirmed, headshot, kf_gap_info)

    kf_gap_info is (killer_right, victim_left, row_y1, row_y2) in
    kill-feed ROI coordinates — used by the caller for headshot detection.
    """
    import cv2, numpy as np

    roi = frame[zy1:zy2, zx1:zx2]
    if not roi.size:
        return False, 'empty_roi', False, False, None

    hsv      = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    green_px = cv2.countNonZero(cv2.inRange(hsv, g_lo, g_hi))
    gold_px  = cv2.countNonZero(cv2.inRange(hsv,
                   np.array(WIN_GOLD_LOW,  dtype=np.uint8),
                   np.array(WIN_GOLD_HIGH, dtype=np.uint8)))

    # ── Absolute Gate 2 — top-60% spatial red check ───────────
    # Restricting to top 60% of WIN_ZONE prevents lava/terrain map
    # backgrounds from triggering a false ROUND LOST veto while a
    # genuine ROUND WON banner is fully visible.
    _roi_h     = zy2 - zy1
    _top60_y2  = zy1 + int(_roi_h * 0.60)
    _top60_roi = frame[zy1:_top60_y2, zx1:zx2]
    if _top60_roi.size:
        _t60_hsv   = cv2.cvtColor(_top60_roi, cv2.COLOR_BGR2HSV)
        abs_red_px = cv2.countNonZero(cv2.inRange(_t60_hsv, r_lo, r_hi))
    else:
        abs_red_px = cv2.countNonZero(cv2.inRange(hsv, r_lo, r_hi))
    # Suppress abs-red veto only when the gold/orange MVP banner clearly dominates
    # the win zone AND the red reading is not also catastrophically high.
    # A genuine gold/MVP banner (H=10-19) will produce minimal red bleed (<3000).
    # A ROUND LOST red banner with orange glow/text will push both gold_px ≥ 800
    # AND abs_red_px into the tens of thousands — so we must NOT suppress in that
    # case.  Requiring abs_red_px < WIN_RED_ABSOLUTE * 10 (= 3000) as the condition
    # for suppression separates the two cases cleanly in practice.
    _gold_suppresses_red = (gold_px >= WIN_GOLD_PIX
                            and abs_red_px < WIN_RED_ABSOLUTE * 10)
    if abs_red_px >= WIN_RED_ABSOLUTE and not _gold_suppresses_red:
        return False, f'round_lost_absolute(red={abs_red_px})', False, False, None

    # ── Gate 1: green pixels (ROUND WON) or gold pixels (MVP/draw banner) ──
    if green_px < WIN_GREEN_PIX and gold_px < WIN_GOLD_PIX:
        return False, 'no_green', False, False, None

    reader = get_ocr_reader() if USE_OCR else None

    # ── Gate 10: kill feed ────────────────────────────────────
    g10_pass               = False
    g10_teammate_confirmed = False
    _kf_gap_info           = None

    if PLAYER_USERNAME and reader is not None:
        try:
            kf_roi = frame[ky1:ky2, kx1:kx2]
            if kf_roi.size:
                roi_w      = kf_roi.shape[1]
                kf_results = reader.readtext(kf_roi, detail=1, paragraph=False)
                uname_up   = PLAYER_USERNAME.upper()

                left_words = [
                    (bbox, text, prob) for (bbox, text, prob) in kf_results
                    if sum(pt[0] for pt in bbox) / 4 < roi_w * 0.5
                ]
                left_text_joined = ' '.join(r[1] for r in left_words).upper()
                # Exact match first; fall back to fuzzy (SequenceMatcher ≥ 0.70)
                # to handle OCR misreads of stylised game fonts (e.g. "L0LLIPOP",
                # "LOLLLPOP").  Only exact OR fuzzy-close tokens count as a match;
                # this prevents unrelated short names from scoring ≥ 0.70.
                import difflib as _dl
                def _fuzzy_match(uname, ocr_word):
                    if uname in ocr_word:
                        return True
                    if len(ocr_word) < max(3, len(uname) - 2):
                        return False
                    return _dl.SequenceMatcher(None, uname, ocr_word).ratio() >= 0.70
                found_in_left = any(
                    _fuzzy_match(uname_up, r[1].upper()) for r in left_words
                )

                # Lobby guard — no coloured HUD strip = lobby/menus
                if found_in_left:
                    kf_hsv   = cv2.cvtColor(kf_roi, cv2.COLOR_BGR2HSV)
                    _pur_pix = cv2.countNonZero(cv2.inRange(kf_hsv,
                        np.array([115, 40,  60], dtype=np.uint8),
                        np.array([160, 255, 255], dtype=np.uint8)))
                    _yel_pix = cv2.countNonZero(cv2.inRange(kf_hsv,
                        np.array([18,  100, 100], dtype=np.uint8),
                        np.array([42,  255, 255], dtype=np.uint8)))
                    _kf_area = kf_roi.shape[0] * kf_roi.shape[1]
                    _has_hud = ((_pur_pix + _yel_pix) / max(1, _kf_area)) >= 0.02
                    if not _has_hud:
                        found_in_left = False

                any_name_left = len(left_text_joined.strip()) >= 3
                if any_name_left and not found_in_left:
                    # OCR read something on the left but couldn't fuzzy-match
                    # PLAYER_USERNAME (common with stylised kill-feed fonts).
                    # Before treating this as a teammate kill, check the kill-text
                    # zone — "Eliminated [name]" is shown *only* on the screen of
                    # the player who made the kill.  If that text is present and
                    # the feed had something on the left, this is almost certainly
                    # our player's kill with a garbled username in the feed OCR.
                    _kt_elim_fallback = False
                    try:
                        _fh_fb, _fw_fb = frame.shape[:2]
                        _ktfbx1 = int(KILL_TEXT_ZONE[0] * _fw_fb)
                        _ktfby1 = int(KILL_TEXT_ZONE[1] * _fh_fb)
                        _ktfbx2 = int(KILL_TEXT_ZONE[2] * _fw_fb)
                        _ktfby2 = int(KILL_TEXT_ZONE[3] * _fh_fb)
                        _ktfb_roi = frame[_ktfby1:_ktfby2, _ktfbx1:_ktfbx2]
                        if _ktfb_roi.size:
                            _ktfb_res  = reader.readtext(
                                _ktfb_roi, detail=0, paragraph=True)
                            _ktfb_text = ' '.join(_ktfb_res).upper().strip()
                            # Must say "[YourName] eliminated [X]" — not just "eliminated".
                            # Kill text is shown to the WHOLE team so a teammate kill also
                            # triggers "eliminated"; we must confirm PLAYER_USERNAME appears
                            # specifically BEFORE "eliminated" in the sentence.
                            if ('ELIMINATED' in _ktfb_text
                                    and 'ASSIST' not in _ktfb_text):
                                _fb_elim_idx  = _ktfb_text.index('ELIMINATED')
                                _fb_before    = _ktfb_text[:_fb_elim_idx]
                                _fb_words     = [
                                    ''.join(c for c in w if c.isalnum() or c == '_')
                                    for w in _fb_before.split()
                                ]
                                for _fbw in _fb_words:
                                    if _fbw and _fuzzy_match(uname_up, _fbw):
                                        _kt_elim_fallback = True
                                        break
                    except Exception:
                        pass
                    if _kt_elim_fallback:
                        # Promote to found_in_left so the full assist-check
                        # block below runs (and can still catch a real assist
                        # via Check B if the kill text was a fluke).
                        found_in_left = True
                    else:
                        g10_teammate_confirmed = True

                if found_in_left:
                    # ── Assist detection ─────────────────────────────────────
                    # Two checks, either one is enough to reject as an assist:
                    #
                    # Check A — OCR '+' in the kill-feed row (fast, but OCR often
                    #           drops the + symbol so this alone is not reliable).
                    # Check B — Kill text zone OCR: the large centre-screen text
                    #           always clearly says "Assist" or "Eliminated".
                    #           This is the PRIMARY reliable signal.
                    _plus_in_row = False
                    for (_b2, _t2, _p2) in left_words:
                        if _fuzzy_match(uname_up, _t2.upper()):
                            _cy2   = sum(pt[1] for pt in _b2) / 4
                            _rh2   = max(pt[1] for pt in _b2) - min(pt[1] for pt in _b2)
                            _row_t = ' '.join(
                                t3 for (b3, t3, _) in left_words
                                if abs(sum(pt[1] for pt in b3) / 4 - _cy2) <= max(12, _rh2)
                            ).upper()
                            if '+' in _row_t:
                                _plus_in_row = True
                            break

                    # Check B — ALWAYS read the kill text zone to catch assists
                    # that OCR missed the '+' for (the most common failure mode).
                    #
                    # Kill text format in Rivals: "[KillerName] eliminated [VictimName]"
                    # This text is shown to ALL players on the winning team (assister,
                    # spectator, observer) — not only to the player who scored the kill.
                    # Checking for bare "ELIMINATED" is therefore insufficient; we must
                    # verify that PLAYER_USERNAME is the name appearing BEFORE "eliminated".
                    _kt_is_assist         = False
                    _kt_player_primary    = False   # "[YourName] eliminated [X]" confirmed
                    _kt_text_checked      = ''
                    try:
                        _fh2, _fw2 = frame.shape[:2]
                        _ktx1 = int(KILL_TEXT_ZONE[0] * _fw2)
                        _kty1 = int(KILL_TEXT_ZONE[1] * _fh2)
                        _ktx2 = int(KILL_TEXT_ZONE[2] * _fw2)
                        _kty2 = int(KILL_TEXT_ZONE[3] * _fh2)
                        _kt_roi = frame[_kty1:_kty2, _ktx1:_ktx2]
                        if _kt_roi.size:
                            _kt_res = reader.readtext(_kt_roi, detail=0, paragraph=True)
                            _kt_text_checked = ' '.join(_kt_res).upper().strip()
                            if 'ASSIST' in _kt_text_checked:
                                _kt_is_assist = True
                            elif 'ELIMINATED' in _kt_text_checked:
                                # Rivals shows kill text in TWO different forms:
                                #   • To the killer:   "Eliminated [Victim]"
                                #                      (no killer name prefix)
                                #   • To teammates:    "[KillerName] eliminated [Victim]"
                                #
                                # A bare "Eliminated X" (nothing / <4 chars before it)
                                # is definitive proof THIS player scored the kill.
                                _elim_idx  = _kt_text_checked.index('ELIMINATED')
                                _kt_before = _kt_text_checked[:_elim_idx].strip()
                                if len(_kt_before) < 4:
                                    # Bare "Eliminated X" — killer's own notification
                                    _kt_player_primary = True
                                else:
                                    # Teammate form "[Name] eliminated X":
                                    # fuzzy-match to see if the killer is PLAYER_USERNAME
                                    _kt_words = [
                                        ''.join(c for c in w if c.isalnum() or c == '_')
                                        for w in _kt_before.split()
                                    ]
                                    for _ktw in _kt_words:
                                        if _ktw and _fuzzy_match(uname_up, _ktw):
                                            _kt_player_primary = True
                                            break
                    except Exception:
                        pass

                    # Rejection logic:
                    #   • Kill text says "Assist"                   → reject (explicit assist)
                    #   • '+' in feed AND PLAYER_USERNAME is NOT confirmed as the named killer
                    #     in the kill text                          → reject (you assisted
                    #     another player, or kill text unreadable)
                    #
                    # When '+' IS in the feed but kill text names PLAYER_USERNAME as the killer
                    # (e.g. "YourName + 00Anonymous ▽ victim" → "YourName eliminated victim")
                    # the '+' is an assist BY someone else → keep the clip.
                    if _kt_is_assist or (_plus_in_row and not _kt_player_primary):
                        # Confirmed assist — player was not the primary eliminator
                        g10_pass = False
                        g10_teammate_confirmed = True
                    else:
                        g10_pass = True

                # ── Capture gap coordinates for headshot detection ────
                if g10_pass and kf_results:
                    try:
                        _uw = None
                        for (b2, t2, _) in kf_results:
                            if _fuzzy_match(uname_up, t2.upper()):
                                _uw = b2
                                break
                        if _uw is not None:
                            _u_right = max(pt[0] for pt in _uw)
                            _u_ytop  = min(pt[1] for pt in _uw)
                            _u_ybot  = max(pt[1] for pt in _uw)
                            _row_mid = (_u_ytop + _u_ybot) / 2
                            _row_h   = max(8, int(_u_ybot - _u_ytop))

                            def _wmy(b):
                                return (min(p[1] for p in b) +
                                        max(p[1] for p in b)) / 2

                            _rw = [(b, t, p) for (b, t, p) in kf_results
                                   if abs(_wmy(b) - _row_mid) <= _row_h]
                            _split = _u_right + 4
                            _lw = [(b, t, p) for (b, t, p) in _rw
                                   if max(pt[0] for pt in b) <= _split]
                            _rw2 = [(b, t, p) for (b, t, p) in _rw
                                    if min(pt[0] for pt in b) > _split]
                            _kr = (max(max(pt[0] for pt in b) for (b, t, p) in _lw)
                                   if _lw else _u_right)
                            _vl = (min(min(pt[0] for pt in b) for (b, t, p) in _rw2)
                                   if _rw2 else kf_roi.shape[1] * 0.80)
                            _ky1_r = max(0,               int(_u_ytop) - 2)
                            _ky2_r = min(kf_roi.shape[0], int(_u_ybot) + 2)
                            _kf_gap_info = (_kr, _vl, _ky1_r, _ky2_r)
                    except Exception:
                        pass

        except Exception:
            pass

    # ── Gate 7: win zone OCR ──────────────────────────────────
    g7_pass = False
    if reader is not None:
        try:
            results  = reader.readtext(roi, detail=1, paragraph=False)
            all_text = ' '.join(r[1] for r in results).upper()
            g7_pass  = 'WON' in all_text
            if 'LOST' in all_text:
                return (False,
                        f'ocr_round_lost(text:{all_text[:30]})',
                        False, False, None)
        except Exception:
            pass

    # ── Confidence assessment ─────────────────────────────────
    username_gate_active = bool(PLAYER_USERNAME)

    if username_gate_active:
        # Gate 10 alone is HIGH confidence — it confirmed your username in the
        # kill feed.  Gate 7 is a useful extra signal but is not required when
        # Gate 10 has already verified the kill.
        high_confidence = g10_pass
        some_confidence = g7_pass or g10_pass
        if not CLIP_TEAMMATE_KILLS and g10_teammate_confirmed:
            return (False, 'teammate_kill(teammate_confirmed_by_ocr)',
                    False, False, None)
        # Gate 10 is MANDATORY when OCR + username are active.
        # A ROUND WON banner + shape/white (G7/G3/G4) alone cannot confirm
        # it was YOUR kill — those all trigger on a teammate round win too.
        # If OCR can't see your name in the kill feed (and no teammate signal),
        # the feed is empty → almost certainly a teammate kill with faded feed.
        if reader is not None and not g10_pass:
            return (False,
                    f'killfeed_no_confirm(g7={g7_pass},kf_empty)',
                    False, False, None)
    elif reader is not None:
        g1_strong       = (green_px >= WIN_GREEN_PIX * 2) or (gold_px >= WIN_GOLD_PIX * 2)
        high_confidence = g7_pass and g1_strong
        some_confidence = g7_pass
    else:
        high_confidence = False
        some_confidence = False

    # ── Fallback gates 3 + 4 ─────────────────────────────────
    if not high_confidence:
        white_mask = cv2.inRange(hsv,
            np.array([0,   0,            WHITE_VAL_MIN], dtype=np.uint8),
            np.array([180, WHITE_SAT_MAX, 255],           dtype=np.uint8))
        white_px = cv2.countNonZero(white_mask)
        g3_pass  = white_px >= WHITE_PIX_MIN

        green_mask    = cv2.inRange(hsv, g_lo, g_hi)
        zone_area     = (zx2 - zx1) * (zy2 - zy1)
        green_density = green_px / max(1, zone_area)
        contours, _   = cv2.findContours(green_mask,
                                         cv2.RETR_EXTERNAL,
                                         cv2.CHAIN_APPROX_SIMPLE)
        g4_pass = False
        if contours and green_density >= WIN_GREEN_DENSITY_MIN:
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
            if not g3_pass and not g4_pass:
                return (False,
                        f'partial_conf_fallback_failed'
                        f'(g7={g7_pass},g10={g10_pass},'
                        f'white={white_px},shape={g4_pass})',
                        False, False, None)
        elif username_gate_active:
            if not g3_pass or not g4_pass:
                return (False,
                        f'no_ocr_signal_visual_only'
                        f'(g3={g3_pass},g4={g4_pass},'
                        f'white={white_px},green={green_px})',
                        False, False, None)
        else:
            if not g3_pass:
                return (False,
                        f'no_white_text(white_px={white_px})',
                        False, False, None)
            if not g4_pass:
                return False, 'bad_shape(no_ocr_fallback)', False, False, None

    # ── Post-win safety ───────────────────────────────────────
    post_win_safe = (is_1v1 and not CLIP_TEAMMATE_KILLS) or g10_pass

    # ── Layer 2: veto gates ───────────────────────────────────
    if not post_win_safe:
        red_px = cv2.countNonZero(cv2.inRange(hsv, r_lo, r_hi))
        if red_px >= WIN_RED_PIX:
            return False, 'round_lost', False, False, None

        d_roi = frame[dy1:dy2, dx1:dx2]
        if d_roi.size:
            d_hsv    = cv2.cvtColor(d_roi, cv2.COLOR_BGR2HSV)
            _yel_m   = cv2.inRange(d_hsv, dy_lo, dy_hi)
            _pur_m   = cv2.inRange(d_hsv, dp_lo, dp_hi)
            _dc_mask = cv2.bitwise_or(_yel_m, _pur_m)
            _dc_cnts, _ = cv2.findContours(
                _dc_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for _dc_c in _dc_cnts:
                _dc_area = cv2.contourArea(_dc_c)
                if _dc_area < DEATH_BLOB_MIN:
                    continue
                _dc_x, _dc_y, _dc_w, _dc_h = cv2.boundingRect(_dc_c)
                _dc_aspect = _dc_w / max(_dc_h, 1)
                _dc_fill   = _dc_area / max(_dc_w * _dc_h, 1)
                if _dc_aspect >= DEATH_BLOB_ASPECT and _dc_fill >= DEATH_BLOB_FILL:
                    return (False,
                            f'death_card(area={_dc_area:.0f}'
                            f',asp={_dc_aspect:.1f},fill={_dc_fill:.2f})',
                            False, False, None)

        if reader is not None:
            try:
                d_results = reader.readtext(frame[dy1:dy2, dx1:dx2],
                                            detail=0, paragraph=True)
                d_text    = ' '.join(d_results).upper()
                if 'ELIMINATED YOU' in d_text:
                    return (False,
                            f'ocr_death({d_text[:40]})',
                            False, False, None)
            except Exception:
                pass

    conf_tag = 'high' if high_confidence else ('partial' if some_confidence else 'visual')
    kf_tag   = '+killfeed' if g10_pass else ''
    return True, f'ok({conf_tag}{kf_tag})', g10_pass, False, _kf_gap_info


# ── Visual detection ──────────────────────────────────────────

def detect_visual(video: Path, label: str, frame_sample: float = None,
                  start_sec: float = 0.0, end_sec: float = None,
                  lookback_sec: float = None,
                  pause_file: str = None) -> tuple:
    """
    Scan video frames and return confirmed kill timestamps.
    Returns (timestamps, wins_found, frames_rejected, ts_weapons, rejection_counts).
    """
    import cv2, numpy as np

    global _PAUSE_FILE
    if pause_file:
        _PAUSE_FILE = pause_file

    fs = frame_sample if frame_sample is not None else FRAME_SAMPLE

    cap          = cv2.VideoCapture(str(video))
    fps          = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    scan_from_frame   = int((lookback_sec if lookback_sec is not None
                             else start_sec) * fps)
    report_from_frame = int(start_sec * fps)
    stop_at_frame     = int(end_sec * fps) if end_sec is not None else total_frames

    scan_from_frame   = max(0, min(scan_from_frame,   total_frames))
    report_from_frame = max(0, min(report_from_frame, total_frames))
    stop_at_frame     = max(report_from_frame, min(stop_at_frame, total_frames))

    if scan_from_frame > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, scan_from_frame)

    zx1, zy1   = int(WIN_ZONE[0]*w),        int(WIN_ZONE[1]*h)
    zx2, zy2   = int(WIN_ZONE[2]*w),        int(WIN_ZONE[3]*h)
    dx1, dy1   = int(DEATH_ZONE[0]*w),      int(DEATH_ZONE[1]*h)
    dx2, dy2   = int(DEATH_ZONE[2]*w),      int(DEATH_ZONE[3]*h)
    wx1, wy1   = int(WEAPON_ZONE[0]*w),     int(WEAPON_ZONE[1]*h)
    wx2, wy2   = int(WEAPON_ZONE[2]*w),     int(WEAPON_ZONE[3]*h)
    kx1, ky1   = int(KILL_FEED_ZONE[0]*w),  int(KILL_FEED_ZONE[1]*h)
    kx2, ky2   = int(KILL_FEED_ZONE[2]*w),  int(KILL_FEED_ZONE[3]*h)
    ltx1, lty1 = int(KILL_TEXT_ZONE[0]*w),  int(KILL_TEXT_ZONE[1]*h)
    ltx2, lty2 = int(KILL_TEXT_ZONE[2]*w),  int(KILL_TEXT_ZONE[3]*h)

    g_lo  = np.array(WIN_GREEN_LOW,   dtype=np.uint8)
    g_hi  = np.array(WIN_GREEN_HIGH,  dtype=np.uint8)
    r_lo  = np.array(WIN_RED_LOW,     dtype=np.uint8)
    r_hi  = np.array(WIN_RED_HIGH,    dtype=np.uint8)
    dy_lo = np.array(DEATH_YEL_LOW,   dtype=np.uint8)
    dy_hi = np.array(DEATH_YEL_HIGH,  dtype=np.uint8)
    dp_lo = np.array(DEATH_PUR_LOW,   dtype=np.uint8)
    dp_hi = np.array(DEATH_PUR_HIGH,  dtype=np.uint8)

    step          = max(1, int(fps * fs))
    seg_frames    = max(1, stop_at_frame - scan_from_frame)
    total_samples = max(1, seg_frames // step)
    milestones    = {max(1, int(total_samples * p)): int(p * 100)
                     for p in (0.25, 0.5, 0.75, 1.0)}

    timestamps       = []
    last_detect      = -MIN_GAP
    wins_found       = 0
    rejected         = 0
    rejection_counts = {}
    frame_idx        = scan_from_frame
    sample_count     = 0
    death_times      = []
    ts_weapons       = {}

    _cached_player_count   = None
    _player_check_interval = max(1, int(fps * 30))
    _last_player_check_frm = -_player_check_interval

    # ── Debug frame ───────────────────────────────────────────
    if DEBUG_FRAME and scan_from_frame == 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total_frames * 0.3))
        ret_d, frame_d = cap.read()
        if ret_d:
            cv2.rectangle(frame_d, (zx1, zy1),   (zx2, zy2),   (0, 255,   0), 3)
            cv2.rectangle(frame_d, (dx1, dy1),   (dx2, dy2),   (0,   0, 255), 3)
            cv2.rectangle(frame_d, (wx1, wy1),   (wx2, wy2),   (255, 165,  0), 3)
            cv2.rectangle(frame_d, (kx1, ky1),   (kx2, ky2),   (255, 255,  0), 3)
            cv2.rectangle(frame_d, (ltx1, lty1), (ltx2, lty2), (255,   0, 255), 3)
            for txt, xy, col in [
                ("WIN ZONE",   (zx1, max(zy1-8, 12)),   (0, 255, 0)),
                ("DEATH ZONE", (dx1, max(dy1-8, 12)),   (0, 0, 255)),
                ("WEAPON ZONE",(wx1, max(wy1-8, 12)),   (255, 165, 0)),
                ("KILL FEED",  (kx1, max(ky1-8, 12)),   (255, 255, 0)),
                ("KILL TEXT",  (ltx1, max(lty1-8, 12)), (255, 0, 255)),
            ]:
                cv2.putText(frame_d, txt, xy,
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
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

            # Pause check
            if sample_count % PAUSE_CHECK_INTERVAL == 0:
                check_paused()

            # Death-card scan (always, for Gate 6 lookback)
            d_roi_scan = frame[dy1:dy2, dx1:dx2]
            if d_roi_scan.size:
                import cv2 as _cv2, numpy as _np
                _dhsv  = _cv2.cvtColor(d_roi_scan, _cv2.COLOR_BGR2HSV)
                _ym    = _cv2.inRange(_dhsv, dy_lo, dy_hi)
                _pm    = _cv2.inRange(_dhsv, dp_lo, dp_hi)
                _dcm   = _cv2.bitwise_or(_ym, _pm)
                _cnts2, _ = _cv2.findContours(
                    _dcm, _cv2.RETR_EXTERNAL, _cv2.CHAIN_APPROX_SIMPLE)
                _dc_seen = False
                for _c2 in _cnts2:
                    _a2 = _cv2.contourArea(_c2)
                    if _a2 < DEATH_BLOB_MIN:
                        continue
                    _, _, _w2, _h2 = _cv2.boundingRect(_c2)
                    if (_w2 / max(_h2, 1) >= DEATH_BLOB_ASPECT
                            and _a2 / max(_w2 * _h2, 1) >= DEATH_BLOB_FILL):
                        _dc_seen = True
                        break
                if _dc_seen:
                    death_times.append(t)

            if frame_idx >= report_from_frame and (t - last_detect) >= MIN_GAP:

                if (_cached_player_count is None or
                        (frame_idx - _last_player_check_frm) >= _player_check_interval):
                    _lc, _rc = count_team_players(frame, w, h)
                    _cached_player_count   = (_lc, _rc)
                    _last_player_check_frm = frame_idx

                lc, rc = _cached_player_count
                is_1v1 = (lc == 1 and rc == 1)

                passed, reason, kf_confirmed, _, kf_gap_info = check_frame(
                    frame,
                    zx1, zy1, zx2, zy2,
                    dx1, dy1, dx2, dy2,
                    g_lo, g_hi, r_lo, r_hi,
                    dy_lo, dy_hi, dp_lo, dp_hi,
                    wx1, wy1, wx2, wy2,
                    kx1, ky1, kx2, ky2,
                    label, t, is_1v1=is_1v1)

                if passed:
                    # ── Gate 6: death-card lookback ───────────────────
                    _is_team     = (not is_1v1) or CLIP_TEAMMATE_KILLS
                    _post_win_g6 = (is_1v1 and not CLIP_TEAMMATE_KILLS) or kf_confirmed
                    if _is_team and not _post_win_g6:
                        _reader       = get_ocr_reader() if USE_OCR else None
                        _elapsed      = read_timer_elapsed(frame, w, h, _reader)
                        _recent_deaths = [dt for dt in death_times
                                          if (t - _elapsed) <= dt <= t]
                        if _recent_deaths:
                            passed = False
                            reason = (f'death_in_lookback('
                                      f'{len(_recent_deaths)}x,'
                                      f'window={_elapsed}s,'
                                      f'teams={lc}v{rc})')

                if passed:
                    # ════════════════════════════════════════════════
                    #  LAYER 3 — Gate 9: HUD weapon name (OCR) +
                    #                   headshot detection (pixel clusters)
                    # ════════════════════════════════════════════════

                    # ── Step A: Read weapon name from HUD bottom-right ─
                    _hud_weapon_raw  = ''
                    _hud_weapon_slug = ''
                    if USE_OCR:
                        _reader_w = get_ocr_reader()
                        if _reader_w is not None:
                            try:
                                import re as _re
                                _w_roi = frame[wy1:wy2, wx1:wx2]
                                if _w_roi.size:
                                    # Lower 55% = weapon name row
                                    _wh       = _w_roi.shape[0]
                                    _name_row = _w_roi[int(_wh * 0.45):, :]
                                    _w_res    = _reader_w.readtext(
                                        _name_row, detail=0, paragraph=True)
                                    _w_raw    = ' '.join(_w_res).strip()

                                    _UI_BLOCK = {
                                        'settings', 'backpack', 'weapons',
                                        'tasks', 'shop', 'pass', 'emote',
                                        'scoreboard', 'melee', 'utility',
                                        'quick', 'searching', 'players',
                                        'bounced', 'playtime', 'eliminations',
                                    }
                                    _clean = []
                                    for _tok in _w_raw.split():
                                        _af = sum(c.isalpha() for c in _tok) / max(1, len(_tok))
                                        if _af < 0.60:
                                            continue
                                        _tok = _re.sub(r'^[^A-Za-z]+', '', _tok)
                                        _tok = _re.sub(r'[^A-Za-z]',   '', _tok)
                                        if len(_tok) >= 3 and _tok.lower() not in _UI_BLOCK:
                                            _clean.append(_tok)
                                    if _clean:
                                        _full = '_'.join(
                                            ww for ww in _clean if len(ww) >= 3
                                        )[:24]
                                        if len(_full) >= 3:
                                            _hud_weapon_raw  = _full.replace('_', ' ')
                                            _hud_weapon_slug = _full.lower()
                            except Exception:
                                pass

                    # ── Step B: Headshot detection ────────────────────
                    # kf_gap_info = (killer_right, victim_left, ry1, ry2)
                    # in kill-feed ROI coordinates, set by Gate 10 above.
                    is_headshot = False
                    if kf_gap_info is not None:
                        try:
                            _kr, _vl, _ry1, _ry2 = kf_gap_info
                            kf_roi_hs = frame[ky1:ky2, kx1:kx2]
                            is_headshot = detect_headshot_in_killfeed(
                                kf_roi_hs, _kr, _vl, _ry1, _ry2)
                        except Exception:
                            is_headshot = False

                    # ── Step C: HEADSHOT_ONLY gate ────────────────────
                    if HEADSHOT_ONLY:
                        if not USE_OCR or not PLAYER_USERNAME:
                            if wins_found == 0:
                                print(
                                    "\n  ⚠  HEADSHOT_ONLY=True has no effect because "
                                    + ("USE_OCR=False" if not USE_OCR
                                       else "PLAYER_USERNAME is empty") + ".\n"
                                    "     Headshot detection requires both USE_OCR=True "
                                    "and PLAYER_USERNAME set.\n"
                                    "     All kills will be clipped this run.\n",
                                    flush=True)
                        elif not is_headshot:
                            passed = False
                            reason = 'not_headshot'
                            rejected += 1

                    # ── Step D: Weapon filter ─────────────────────────
                    if passed and WEAPON_FILTER:
                        if _hud_weapon_slug:
                            if not any(wf.lower() in _hud_weapon_slug
                                       for wf in WEAPON_FILTER):
                                passed = False
                                reason = f'weapon_filtered(hud:{_hud_weapon_raw[:30]})'
                                rejected += 1
                        else:
                            passed = False
                            reason = 'weapon_unreadable(no_ocr)'
                            rejected += 1

                if passed:
                    timestamps.append(t)
                    last_detect = t
                    wins_found += 1

                    _weapon_label = _hud_weapon_slug if _hud_weapon_slug else ''
                    if is_headshot and _weapon_label:
                        _weapon_label = _weapon_label + '_hs'
                    elif is_headshot:
                        _weapon_label = 'headshot'
                    ts_weapons[round(t, 2)] = _weapon_label

                elif reason not in ('no_green', 'empty_roi',
                                    'not_headshot', 'weapon_filtered',
                                    'weapon_unreadable'):
                    rejected += 1
                    _rk = reason.split('(')[0]
                    rejection_counts[_rk] = rejection_counts.get(_rk, 0) + 1

            if sample_count in milestones:
                pct = milestones[sample_count]
                try:
                    from tqdm import tqdm as _tqdm
                    _tqdm.write(f"  [{label}] {pct:3d}%  kills={wins_found}  "
                                f"skipped={rejected}")
                except Exception:
                    print(f"  [{label}] {pct:3d}%  kills={wins_found}  "
                          f"skipped={rejected}", flush=True)

        frame_idx += 1

    cap.release()
    return timestamps, wins_found, rejected, ts_weapons, rejection_counts


# ── Audio detection (optional) ────────────────────────────────

def detect_audio(wav: Path) -> list:
    import librosa, numpy as np
    from scipy.signal import find_peaks

    y, sr     = librosa.load(str(wav), sr=22050, mono=True)
    min_dist  = max(1, int(sr / 512 * 2))

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
            start_sec, end_sec, lookback_sec, seg_idx, n_segs, pause_file_str)
    """
    (video_str, tmp_str, checkpoint_str, frame_sample,
     start_sec, end_sec, lookback_sec, seg_idx, n_segs,
     pause_file_str) = task

    video           = Path(video_str)
    tmp_dir         = Path(tmp_str)
    checkpoint_path = Path(checkpoint_str)

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

    try:
        v_ts, nk, nd, v_weapons, v_rejections = detect_visual(
            video, label, frame_sample=frame_sample,
            start_sec=start_sec, end_sec=end_sec, lookback_sec=lookback_sec,
            pause_file=pause_file_str)
        all_ts.extend(v_ts)
        result['n_visual']         = nk
        result['n_deaths']         = nd
        result['ts_weapons']       = v_weapons
        result['rejection_counts'] = v_rejections
    except Exception as e:
        print(f"  [{label}] visual error: {e}", flush=True)

    result['timestamps'] = all_ts
    return result


# ── Main ──────────────────────────────────────────────────────

def main():
    import random

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

    ap = argparse.ArgumentParser(
        description='SNIPED v2.4 — Roblox Rivals Auto-Clipper')
    ap.add_argument('--input',   '-i', default='./recordings',
                    help='Folder containing MP4 recordings (default: ./recordings)')
    ap.add_argument('--output',  '-o', default='./clips',
                    help='Output folder for clips (default: ./clips)')
    ap.add_argument('--workers', '-w', type=int, default=WORKERS,
                    help='Parallel workers (0 = auto)')
    ap.add_argument('--dry-run', '-n', action='store_true',
                    help='Detect kills, print what would be clipped, skip FFmpeg')
    args = ap.parse_args()

    in_dir  = Path(args.input).resolve()
    out_dir = Path(args.output).resolve()
    tmp_dir = Path(tempfile.mkdtemp(prefix='sniped_'))

    import logging as _logging
    _out_dir_created = not out_dir.exists()
    out_dir.mkdir(parents=True, exist_ok=True)
    _log_path = out_dir / f"sniped_run_{time.strftime('%Y%m%d_%H%M%S')}.log"
    _logging.basicConfig(
        level=_logging.INFO,
        format='%(asctime)s  %(message)s',
        datefmt='%H:%M:%S',
        handlers=[_logging.FileHandler(_log_path, encoding='utf-8')],
    )
    _log = _logging.getLogger('sniped')

    W = 54

    print()
    print("┌" + "─" * W + "┐")
    print("│" + " _____ _____ _____ _____ _____ _____       ".center(W) + "│")
    print("│" + "|   __|   | |  |  |  _  |   __|  _  \\     ".center(W) + "│")
    print("│" + "|__   | | | |  |  |   __|   __| |_| |     ".center(W) + "│")
    print("│" + "|_____|_|___|__|__|__|  |_____|_____/      ".center(W) + "│")
    print("│" + "".center(W) + "│")
    print("│" + "v2.4  —  Roblox Rivals Auto-Clipper".center(W) + "│")
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

    n_workers, dynamic_fs, ram_gb, avail_gb, cpu_cores = \
        auto_tune_resources(args.workers)

    if FRAME_SAMPLE < 0.3 and ram_gb < 8:
        print(f"  ⚠  WARNING: FRAME_SAMPLE={FRAME_SAMPLE} on {ram_gb:.0f} GB RAM.")
        print()

    n_splits = max(1, N_SPLITS)
    if n_splits > n_workers:
        n_splits = n_workers
    eff_workers = n_workers

    # ── Pause file ────────────────────────────────────────────
    _pause_file = tmp_dir / '.sniped_paused'
    global _PAUSE_FILE
    _PAUSE_FILE = str(_pause_file)
    _listener   = _start_pause_listener(_pause_file)

    # ── Checkpoint ────────────────────────────────────────────
    checkpoint_path = out_dir / 'sniped_progress.json'
    checkpoint      = load_checkpoint(checkpoint_path)

    already_done = {v for v in checkpoint
                    if checkpoint[v].get('timestamps') is not None
                    and not checkpoint[v].get('error')}
    todo_videos  = [v for v in videos if str(v) not in already_done]

    total_gb = sum(v.stat().st_size for v in videos) / 1e9
    todo_gb  = sum(v.stat().st_size for v in todo_videos) / 1e9

    def _row(key, val):
        line = f"  {key:<14} {val}"
        print("│" + line.ljust(W) + "│")

    print("┌" + "─" * W + "┐")
    print("│" + "  CONFIG".ljust(W) + "│")
    print("├" + "─" * W + "┤")
    _row("Input",    str(in_dir)[:W-18] + ("…" if len(str(in_dir)) > W-18 else ""))
    _row("Output",   str(out_dir)[:W-18] + ("…" if len(str(out_dir)) > W-18 else ""))
    _vid_word = "video" if len(videos) == 1 else "videos"
    _row("Videos",   f"{len(videos)} {_vid_word}  ({total_gb:.1f} GB)")
    _row("System",   f"{cpu_cores} cores  /  {ram_gb:.0f} GB RAM")
    _row("Workers",  f"{eff_workers}  ({n_splits} splits/video)")
    if n_splits < N_SPLITS:
        print("├" + "─" * W + "┤")
        print("│" + (f"  ⚠  N_SPLITS={N_SPLITS} reduced to {n_splits} "
                     f"({avail_gb:.1f} GB available).").ljust(W) + "│")
        print("│" + "     Close other apps or set WORKERS manually to restore.".ljust(W) + "│")
        print("├" + "─" * W + "┤")
    _row("Sampling", f"every {dynamic_fs:.1f}s  (auto-tuned)")
    _row("Clip",     f"-{CLIP_BEFORE}s … +{CLIP_AFTER}s around each kill")
    _row("OCR",      "enabled" if USE_OCR else "DISABLED (visual fallback)")
    _row("Username", f"'{PLAYER_USERNAME}'  (Gate 10 ON)" if PLAYER_USERNAME
                     else "NOT SET  ← set PLAYER_USERNAME for best accuracy")
    _row("Teammates","clip all wins" if CLIP_TEAMMATE_KILLS else "your kills only")
    _hs_str = ("headshots only (pixel-cluster detector)"
               if HEADSHOT_ONLY else "all kills")
    _row("Headshots", _hs_str)
    _wep_str = ', '.join(WEAPON_FILTER) if WEAPON_FILTER else "all weapons (OCR)"
    _row("Weapon",   _wep_str)
    _row("Pause",    "Ctrl+P to pause / resume"
                     if _listener else "unavailable (install pynput)")
    if ram_gb < 8:
        print("├" + "─" * W + "┤")
        print("│" + "  ⚠  Low RAM — workers & sampling reduced.".ljust(W) + "│")
    if not PLAYER_USERNAME:
        print("├" + "─" * W + "┤")
        print("│" + ("  ⚠  Gate 10 is OFF.  "
                     "Set PLAYER_USERNAME for best accuracy.").ljust(W) + "│")
    if _out_dir_created:
        print("├" + "─" * W + "┤")
        print("│" + f"  ✓  Created output folder: "
                    f"{str(out_dir)[:W-24]}".ljust(W) + "│")
    if already_done:
        prior_clips = sum(
            len(cluster(checkpoint[v]['timestamps']))
            for v in already_done if checkpoint[v].get('timestamps'))
        print("├" + "─" * W + "┤")
        print("│" + (f"  ↩  Resuming: {len(already_done)} done, "
                     f"{len(todo_videos)} remaining  "
                     f"({prior_clips} clips already found)").ljust(W) + "│")
        print("│" + (f"     Delete {checkpoint_path.name} to start fresh"
                     ).ljust(W) + "│")
    print("└" + "─" * W + "┘")
    print()

    _log.info("=== SNIPED v2.4 run started ===")
    _log.info(f"input={in_dir}  output={out_dir}")
    _log.info(f"username={PLAYER_USERNAME!r}  ocr={USE_OCR}  "
              f"headshot_only={HEADSHOT_ONLY}  weapon={WEAPON_FILTER}")
    _log.info(f"workers={eff_workers}  sample={dynamic_fs:.2f}s  "
              f"clip_before={CLIP_BEFORE}s  clip_after={CLIP_AFTER}s")
    if args.dry_run:
        _log.info("DRY-RUN mode — no clips will be written")
        print("  ── DRY-RUN mode — detection only, no FFmpeg cuts ──")
        print()

    # ── PHASE 1: parallel analysis ────────────────────────────
    total_segments = len(todo_videos) * n_splits
    _ph1_vid = "video" if len(todo_videos) == 1 else "videos"
    print("┌" + "─" * W + "┐")
    print("│" + "  PHASE 1/2  —  Scanning".ljust(W) + "│")
    print("│" + (f"  {len(todo_videos)} {_ph1_vid} × {n_splits} segments"
                 f" = {total_segments} tasks").ljust(W) + "│")
    print("└" + "─" * W + "┘")
    print()

    results = dict(checkpoint)
    t_start = time.time()

    if todo_videos:
        _SEG_PFX = '__seg__'
        seg_done_cache = {}
        for ck, cv in checkpoint.items():
            if ck.startswith(_SEG_PFX):
                rest = ck[len(_SEG_PFX):]
                sep  = rest.rfind('__')
                if sep >= 0:
                    v_key = rest[:sep]
                    try:
                        sidx = int(rest[sep+2:])
                        seg_done_cache.setdefault(v_key, {})[sidx] = cv
                    except ValueError:
                        pass

        tasks = []
        video_durations = {}
        from collections import defaultdict
        seg_results = defaultdict(list)

        for v in todo_videos:
            v_str = str(v)
            try:
                duration, _fps = get_video_info(v)
            except Exception:
                try:
                    duration = get_duration(v)
                except Exception:
                    duration = 0.0
            video_durations[v_str] = duration

            seg_len   = duration / n_splits if n_splits > 1 else duration
            done_segs = seg_done_cache.get(v_str, {})

            for i in range(n_splits):
                if i in done_segs:
                    seg_results[v_str].append(done_segs[i])
                else:
                    s_start    = i * seg_len
                    s_end      = ((i + 1) * seg_len
                                  if i < n_splits - 1 else duration)
                    s_lookback = max(0.0, s_start - ROUND_DURATION)
                    tasks.append((
                        v_str, str(tmp_dir), str(checkpoint_path),
                        dynamic_fs,
                        s_start, s_end, s_lookback,
                        i, n_splits,
                        str(_pause_file),
                    ))

        # Merge already-cached segments
        for v in todo_videos:
            v_str = str(v)
            if len(seg_results[v_str]) == n_splits:
                segs = sorted(seg_results[v_str],
                              key=lambda r: r.get('seg_idx', 0))
                merged_weapons    = {}
                merged_rejections = {}
                for s in segs:
                    merged_weapons.update(s.get('ts_weapons', {}))
                    for rk, rc in s.get('rejection_counts', {}).items():
                        merged_rejections[rk] = merged_rejections.get(rk, 0) + rc
                _raw_ts   = [ts for s in segs for ts in s['timestamps']]
                _dedup_ts = sorted(set(round(t, 2) for t in _raw_ts))
                merged = dict(
                    video            = v_str,
                    timestamps       = _dedup_ts,
                    duration         = video_durations.get(v_str, 0.0),
                    n_visual         = sum(s['n_visual']  for s in segs),
                    n_audio          = sum(s['n_audio']   for s in segs),
                    n_deaths         = sum(s['n_deaths']  for s in segs),
                    ts_weapons       = merged_weapons,
                    rejection_counts = merged_rejections,
                    error            = next((s['error'] for s in segs
                                            if s.get('error')), None),
                )
                results[v_str] = merged
                try:
                    save_checkpoint(checkpoint_path, merged)
                except Exception:
                    pass
                kills  = merged['n_visual']
                n_c    = len(cluster(merged['timestamps']))
                _emoji = ('🔥' if kills >= 30 else
                          '💥' if kills >= 15 else
                          '🎯' if kills == 0 else '✓')
                print(f"  {_emoji} {Path(v_str).name[:28]} (resumed): "
                      f"{kills} kills → {n_c} clip(s)", flush=True)

        actual_total = len(tasks)
        if actual_total == 0:
            print("  All segments already completed — jumping to clipping!\n")
        else:
            sizes_gb         = {str(v): v.stat().st_size / 1e9 for v in todo_videos}
            seg_gb           = {str(v): sizes_gb[str(v)] / n_splits
                                for v in todo_videos}
            completed_seg_gb = 0.0
            _ema_rate_gbs = 0.0
            _ema_alpha    = 0.4
            _seg_t_prev   = time.time()

            # Rolling-window speed tracker for accurate ETA.
            # Each entry is (wall_time, cumulative_gb_done) recorded when a
            # segment completes.  We keep the last SPEED_WINDOW entries and
            # blend the windowed rate with the overall rate — the blend shifts
            # toward the window rate as more samples arrive.  This prevents the
            # huge ETA swings seen when the first segment is slow but later ones
            # are fast (or vice-versa).
            SPEED_WINDOW  = 12          # max segments in rolling window
            BLEND_FULL_AT = 6           # number of samples where window gets
                                        # 100% weight; below this the overall
                                        # rate is mixed in to stabilise the ETA
            _speed_log    = []          # [(t, cum_gb), …]
            _prev_eta_s   = None        # for dampening big jumps

            with ProcessPoolExecutor(max_workers=eff_workers) as executor:
                future_map = {executor.submit(analyze_video, t): t[0]
                              for t in tasks}

                with tqdm(total=actual_total, unit='seg',
                          bar_format='  Scanning [{bar}] {n}/{total} segs  '
                                     'elapsed={elapsed}  {postfix}') as pbar:
                    for future in as_completed(future_map):
                        video_str = future_map[future]
                        try:
                            res = future.result()
                        except Exception as e:
                            res = dict(video=video_str, seg_idx=0,
                                       n_segs=n_splits,
                                       timestamps=[], duration=0,
                                       n_visual=0, n_audio=0, n_deaths=0,
                                       ts_weapons={}, rejection_counts={},
                                       error=str(e))
                            print(f"\n  ✗ ERROR {Path(video_str).name}: {e}",
                                  flush=True)

                        seg_results[video_str].append(res)

                        _seg_key = (f"{_SEG_PFX}{video_str}__"
                                    f"{res.get('seg_idx', 0)}")
                        try:
                            save_checkpoint(checkpoint_path, res, key=_seg_key)
                        except Exception:
                            pass

                        completed_seg_gb += seg_gb.get(video_str, 0)
                        now = time.time()

                        # Log data point and trim window
                        _speed_log.append((now, completed_seg_gb))
                        if len(_speed_log) > SPEED_WINDOW:
                            _speed_log = _speed_log[-SPEED_WINDOW:]

                        elapsed_total = max(0.001, now - t_start)
                        overall_rate  = completed_seg_gb / elapsed_total  # GB/s

                        # Window rate: slope over the kept entries
                        if len(_speed_log) >= 2:
                            _dt = _speed_log[-1][0] - _speed_log[0][0]
                            _dg = _speed_log[-1][1] - _speed_log[0][1]
                            window_rate = _dg / _dt if _dt > 0 else overall_rate
                        else:
                            window_rate = overall_rate

                        # Blend: ramp window weight from 0→1 over the first
                        # BLEND_FULL_AT samples; before that the overall rate
                        # anchors the estimate so early segments can't spike it.
                        n_samples   = len(_speed_log)
                        blend_w     = min(1.0, n_samples / BLEND_FULL_AT)
                        rate_gb     = blend_w * window_rate + (1.0 - blend_w) * overall_rate

                        rem_gb  = max(0.0, todo_gb - completed_seg_gb)
                        raw_eta = rem_gb / rate_gb if rate_gb > 0 else 0

                        # Dampen large swings: cap ETA change to ±60% per update
                        # once we have a previous estimate.
                        if _prev_eta_s is not None and _prev_eta_s > 0 and raw_eta > 0:
                            max_eta = _prev_eta_s * 1.6
                            min_eta = _prev_eta_s * 0.4
                            eta_s   = max(min_eta, min(raw_eta, max_eta))
                        else:
                            eta_s = raw_eta
                        _prev_eta_s = eta_s

                        # Format ETA as Xh Ym Zs when > 1 hour, else Xm Ys
                        if eta_s > 0 and completed_seg_gb > 0:
                            _eh = int(eta_s // 3600)
                            _em = int((eta_s % 3600) // 60)
                            _es = int(eta_s % 60)
                            if _eh > 0:
                                eta_str = f"{_eh}h {_em:02d}m {_es:02d}s"
                            else:
                                eta_str = f"{_em}m {_es:02d}s"
                        else:
                            eta_str = "calculating…"

                        # GB/hr  (rate_gb is GB/s → multiply by 3600)
                        spd_str = (f"{rate_gb * 3600:.1f} GB/hr"
                                   if rate_gb > 0 else "")

                        if len(seg_results[video_str]) == n_splits:
                            segs = sorted(seg_results[video_str],
                                          key=lambda r: r.get('seg_idx', 0))
                            mw, mr = {}, {}
                            for s in segs:
                                mw.update(s.get('ts_weapons', {}))
                                for rk, rc in s.get('rejection_counts', {}).items():
                                    mr[rk] = mr.get(rk, 0) + rc
                            _raw   = [ts for s in segs for ts in s['timestamps']]
                            _dedup = sorted(set(round(t, 2) for t in _raw))
                            merged = dict(
                                video            = video_str,
                                timestamps       = _dedup,
                                duration         = video_durations.get(video_str, 0.0),
                                n_visual         = sum(s['n_visual']  for s in segs),
                                n_audio          = sum(s['n_audio']   for s in segs),
                                n_deaths         = sum(s['n_deaths']  for s in segs),
                                ts_weapons       = mw,
                                rejection_counts = mr,
                                error            = next((s['error'] for s in segs
                                                        if s.get('error')), None),
                            )
                            results[video_str] = merged
                            try:
                                save_checkpoint(checkpoint_path, merged)
                            except Exception as ce:
                                print(f"\n  WARNING checkpoint failed: {ce}",
                                      flush=True)

                            kills = merged['n_visual']
                            n_c   = len(cluster(merged['timestamps']))
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
                                           f"{kills} kills → {n_c} clip(s)")

                        pbar.set_postfix_str(f"ETA {eta_str}  {spd_str}")
                        pbar.update(1)

    else:
        print("  All videos already analysed — jumping to clipping!\n")

    # ── Audio detection (main process) ────────────────────────
    if USE_AUDIO:
        print("┌" + "─" * W + "┐")
        print("│" + "  AUDIO  —  Scanning for sound spikes".ljust(W) + "│")
        print("└" + "─" * W + "┘")
        print()
        for v in todo_videos:
            v_str = str(v)
            if v_str not in results:
                continue
            wav = tmp_dir / f"_aud_{v.stem}.wav"
            try:
                print(f"  {v.name[:40]}  extracting audio…", flush=True)
                extract_audio(v, wav)
                a_ts = detect_audio(wav)
                results[v_str]['timestamps'].extend(a_ts)
                results[v_str]['n_audio'] = len(a_ts)
                print(f"  → {len(a_ts)} audio spikes merged", flush=True)
                _log.info(f"audio  {v.name}  spikes={len(a_ts)}")
            except Exception as ae:
                print(f"  ✗ audio error on {v.name}: {ae}", flush=True)
                _log.warning(f"audio error  {v.name}  {ae}")
            finally:
                try:
                    wav.unlink(missing_ok=True)
                except Exception:
                    pass
        print()

    # ── PHASE 2: cut clips ────────────────────────────────────
    print()
    print("┌" + "─" * W + "┐")
    _p2_label = ("  PHASE 2/2  —  DRY RUN (no files written)"
                 if args.dry_run else "  PHASE 2/2  —  Cutting clips")
    print("│" + _p2_label.ljust(W) + "│")
    print("└" + "─" * W + "┘")
    print()

    from datetime import datetime as _dt

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
        tw       = res.get('ts_weapons', {})
        total_kills_found += kills

        try:
            rec_date = _dt.fromtimestamp(
                video.stat().st_mtime).strftime('%Y-%m-%d')
        except Exception:
            rec_date = _dt.now().strftime('%Y-%m-%d')

        print(f"  {video.name}")
        print(f"  {'─' * (W - 2)}")
        print(f"  kills found : {kills}   skipped : {skipped}   "
              f"clips : {len(final_ts)}")
        _log.info(f"video  {video.name}  kills={kills}  skipped={skipped}  "
                  f"clips={len(final_ts)}")
        _rcs = res.get('rejection_counts', {})
        if _rcs:
            _rc_str = '  '.join(f"{k}={v}" for k, v in sorted(_rcs.items()))
            _log.info(f"rejections  {video.name}  {_rc_str}")

        if not final_ts:
            print("  (nothing to cut)")
            print()
            continue

        with tqdm(total=len(final_ts), unit='clip', leave=True,
                  bar_format='  [{bar}] {n}/{total} clips  '
                             '{elapsed}<{remaining}') as cbar:
            for i, ts in enumerate(final_ts, 1):
                mm, ss = int(ts // 60), int(ts % 60)

                weapon_raw  = tw.get(round(ts, 2), '')
                import re as _re2
                weapon_slug = _re2.sub(
                    r'[^A-Za-z0-9]+', '_', weapon_raw).strip('_').lower()
                name = (f"{rec_date}_{mm:02d}m{ss:02d}s_{weapon_slug}.mp4"
                        if weapon_slug
                        else f"{rec_date}_{mm:02d}m{ss:02d}s.mp4")
                out = out_dir / name

                if args.dry_run:
                    tqdm.write(f"  [dry] clip {i:03d}  {mm:02d}:{ss:02d}"
                               + (f"  [{weapon_raw}]" if weapon_raw else "")
                               + f"  → {name}")
                    _log.info(f"dry  {mm:02d}:{ss:02d}  {name}")
                    cbar.update(1)
                    total_clips += 1
                    continue

                try:
                    cut_clip(video, out, ts, duration)
                    size = out.stat().st_size if out.exists() else 0

                    if size < 50_000:
                        tqdm.write(f"  ↺ clip {i:03d}  {mm:02d}:{ss:02d}  "
                                   f"{size} B — retrying -c copy…")
                        _log.warning(f"retry  {mm:02d}:{ss:02d}  {name}  "
                                     f"re-encode={size}B")
                        if out.exists():
                            out.unlink()
                        cut_clip_copy(video, out, ts, duration)
                        size = out.stat().st_size if out.exists() else 0

                    if size < 50_000:
                        tqdm.write(f"  ✗ clip {i:03d}  {mm:02d}:{ss:02d}  "
                                   f"skipped ({size} B — FFmpeg issue)")
                        _log.error(f"skip  {mm:02d}:{ss:02d}  {name}  "
                                   f"final_size={size}B")
                        if out.exists():
                            out.unlink()
                        total_skipped += 1
                    else:
                        mb = size / 1_000_000
                        tqdm.write(f"  ✓ clip {i:03d}  {mm:02d}:{ss:02d}  "
                                   f"{mb:.0f} MB  {name}")
                        cbar.set_postfix_str(f"{mm:02d}:{ss:02d}  {mb:.0f} MB")
                        _log.info(f"cut  {mm:02d}:{ss:02d}  {name}  {mb:.1f}MB")
                        total_clips += 1
                except subprocess.CalledProcessError as e:
                    err_tail = e.stderr.decode('utf-8', errors='replace')[-200:]
                    tqdm.write(f"  ✗ clip {i:03d}  {mm:02d}:{ss:02d}  "
                               f"FFmpeg error: {err_tail}")
                    _log.error(f"ffmpeg_error  {mm:02d}:{ss:02d}  {name}  "
                               f"{err_tail.strip()}")
                    total_skipped += 1
                except Exception as e:
                    tqdm.write(f"  ✗ clip {i:03d}  {mm:02d}:{ss:02d}  "
                               f"failed: {e}")
                    _log.error(f"error  {mm:02d}:{ss:02d}  {name}  {e}")
                    total_skipped += 1
                cbar.update(1)
        print()

    # Cleanup
    shutil.rmtree(tmp_dir, ignore_errors=True)
    if _listener:
        try:
            _listener.stop()
        except Exception:
            pass

    elapsed   = time.time() - t_start
    hrs       = int(elapsed // 3600)
    mins      = int((elapsed % 3600) // 60)
    secs      = int(elapsed % 60)
    elapsed_h = elapsed / 3600
    gb_hr     = todo_gb / elapsed_h if elapsed_h > 0 else 0

    print("┌" + "─" * W + "┐")
    print("│" + "  DONE".ljust(W) + "│")
    print("├" + "─" * W + "┤")
    _row("Kills found", str(total_kills_found))
    _row("Clips saved", str(total_clips) + ("  (dry run)" if args.dry_run else ""))
    _row("Output",      str(out_dir)[:W-18] + ("…" if len(str(out_dir)) > W-18 else ""))
    _row("Time taken",  f"{hrs}h {mins}m {secs}s  ({gb_hr:.1f} GB/hr)")
    _row("Log file",    _log_path.name)
    if total_skipped:
        _row("Skipped", f"{total_skipped} (FFmpeg errors — see {_log_path.name})")
    print("├" + "─" * W + "┤")

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
    _log.info(f"=== run complete  kills={total_kills_found}  "
              f"clips={total_clips}  skipped={total_skipped}  "
              f"time={hrs}h{mins}m{secs}s ===")


if __name__ == '__main__':
    main()