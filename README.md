Sniped — Roblox Rivals Auto-Clipper

Version 2.3

Automatically scans Roblox Rivals recordings and extracts kill highlights using a multi-layer vision + OCR pipeline.

Credits: Lollipopem, Claude
YouTube: https://www.youtube.com/@lollipopem

Overview

Sniped processes your OBS recordings frame-by-frame, detects confirmed kills, and automatically generates clips around those moments.

Workflow:

Place recordings in a folder
Run the script
Retrieve highlights from the clips folder
Detection Pipeline

Sniped uses three layers of validation. A frame must pass all required checks to produce a clip.

Layer 1 — Primary Gates (Kill Confirmation)

Ensures the detected event is your kill, not just a round win.

Gates
Gate	Name	Description
1	Green HSV	Detects the ROUND WON green box in the top-center. If this fails, the frame is discarded immediately.
10	Kill Feed OCR	Reads the top-right kill feed using EasyOCR and verifies that PLAYER_USERNAME is the eliminator. Handles solo and team entries.
7	Win Zone OCR	Detects the word "WON" inside the green box.
Confidence Logic
Condition	Result
Gate 10 + Gate 7 pass	High confidence → clip accepted
Only one passes	Partial → fallback gates required
Neither passes	Full fallback mode
Fallback Gates
Gate	Name	Description
3	White Text	Confirms presence of white pixels forming "WON" text
4	Shape Check	Ensures green box is a valid rectangle (aspect ≥ 3.0, fill ≥ 45%, area ≥ 3000 px)
Layer 2 — Veto Gates (Death Rejection)

Rejects clips where the player died.

Gate	Name	Description
2	Red Reject	Detects ROUND LOST (includes absolute threshold for partial frames)
5	Death Card	Detects elimination panel in bottom-right
8	OCR Death	Reads "eliminated you" using OCR
Post-Win Safety

Veto gates are bypassed if:

1v1 mode (death impossible after win)
Kill feed confirms your kill
Verified post-win scenario
Lookback (Gate 6)

Scans earlier frames in team modes:

Detects if you died earlier in the round
Prevents teammate wins from being clipped

Skipped when:

1v1 mode
Post-win safety is active
Layer 3 — Weapon Filter (Optional)

Filters clips based on weapon used.

Gate	Name	Description
9	Weapon OCR	Reads weapon name and matches against filter list
Installation
1. Install Python

Download: https://www.python.org/downloads/

Enable: Add Python to PATH

2. Install FFmpeg
Option A (Recommended)
winget install ffmpeg
Option B (Manual)

Download:
https://github.com/BtbN/FFmpeg-Builds/releases

Extract and add /bin to system PATH.

3. Python Dependencies

Installed automatically on first run:

opencv-python
numpy
scipy
tqdm
librosa (if audio enabled)
psutil
easyocr (~1GB model download on first run)
Usage
Option A — Batch File (Recommended)
Place RUN_ME.bat and config.py in the same folder
Create a recordings folder
Add video files
Run RUN_ME.bat

Output appears in clips/

Option B — Command Line
python config.py --input D:\OBS\Rivals --output D:\clips
Configuration

Edit config.py

Required Setting
PLAYER_USERNAME = 'YourRobloxName'

Enables kill verification via Gate 10.

Core Settings
Setting	Default	Description
CLIP_BEFORE	9	Seconds before kill
CLIP_AFTER	2	Seconds after kill
MIN_GAP	14	Minimum gap between clips
WORKERS	0	Auto CPU usage
N_SPLITS	4	Parallel segments
FRAME_SAMPLE	0.5	Frame sampling rate
USE_OCR	True	Enable OCR
DEBUG_FRAME	False	Save debug image
Teammate Kill Handling
CLIP_TEAMMATE_KILLS = False
Mode	Behavior
False	Only your kills
True	All round wins
Weapon Filter
WEAPON_FILTER = []
WEAPON_FILTER = ['SNIPER']
WEAPON_FILTER = ['SNIPER', 'ROCKET']
Detection Zones
Setting	Description
KILL_FEED_ZONE	Top-right kill feed
KILL_TEXT_ZONE	Bottom-center confirmation
WEAPON_ZONE	Bottom-right weapon HUD
Thresholds
Setting	Default
WIN_GREEN_PIX	100
WIN_RED_PIX	100
WIN_RED_ABSOLUTE	300
WHITE_PIX_MIN	1000
CONTOUR_ASPECT_MIN	3.0
DEATH_PIX	400
Auto-Tuning
Hardware	Workers	Sampling
32GB+ RAM	All cores - 2	0.3s
16GB RAM	All cores - 1	0.3s
8GB RAM	Half cores	0.5s
<8GB RAM	1–2 workers	1.0s
Performance
30–40GB footage: ~45–90 minutes
Faster on high-core CPUs
Uses libx264 ultrafast encoding
Safe for overnight runs

Progress saved in:

clips/sniped_progress.json
Output Format
2024-01-15_rivals__clip001_02m34s.mp4
2024-01-15_rivals__clip002_08m11s.mp4

Console output:

✓ clip 001  02:34  47 MB
✓ clip 002  08:11  52 MB
Debug Mode

Enable:

DEBUG_FRAME = True

Overlay colors:

Color	Zone
Green	Win zone
Red	Death zone
Orange	Weapon zone
Yellow	Kill feed
Magenta	Kill text
Troubleshooting
Too many clips
Increase WIN_GREEN_PIX (e.g., 300)
Missing kills
Verify PLAYER_USERNAME
Lower WIN_GREEN_PIX (e.g., 60)
Use debug mode
Teammate clips appearing
Ensure username matches exactly
Crossroads false positives
Already calibrated
Increase thresholds if needed
OCR downloading (~1GB)
Happens once on first run
Notes
Pipeline is designed for high precision over recall
Best results achieved with OCR enabled and username set
Fully restartable without data loss
