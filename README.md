Sniped — The Roblox Rivals Auto-Clipper
Version 2.3
Automatically scans your Roblox Rivals recordings and extracts kill highlights.
Credits: Lollipopem and Claude :)
Support me on Youtube — https://www.youtube.com/@lollipopem
---
What it does
SNIPED watches every frame of your OBS recordings, detects your kills using a multi-layer vision + OCR pipeline, and cuts a clip around each one automatically. Drop your recordings in a folder, double-click, come back to a `clips` folder full of highlights.
---
Detection pipeline
Three independent layers. A frame must survive all three to produce a clip.
---
Layer 1 — Primary gates (confirm it's YOUR kill)
Gate	Name	What it does
1	Green HSV	Always-on entry gate. The ROUND WON green box must be visible in the top-centre zone. If this fails the frame is skipped instantly — nothing else runs.
10	Kill feed OCR	Main gate. EasyOCR reads the top-right kill feed and confirms `PLAYER_USERNAME` is the eliminator — not just a team participant. Handles solo entries (`Lollipop → victim`) and team entries (`Lollipop + teammate → victim`). In team entries it cross-checks the bottom-centre kill confirmation text to verify who actually landed the final hit. Only active when `PLAYER_USERNAME` is set.
7	Win zone OCR	EasyOCR reads "WON" directly inside the win box.
Confidence levels — when do fallback gates run?
Situation	What happens
Gate 10 ✅ + Gate 7 ✅	High confidence — clip accepted, Gates 3 and 4 are skipped entirely.
One of Gate 10 / Gate 7 passes	Partial confidence — Gates 3 and 4 run for support. At least one must pass.
Neither passes (OCR off or failing)	Visual fallback — Gates 3 and 4 both run and both must pass.

Gate	Name	What it checks
3	White text	White pixel count inside the win box — confirms "WON" letters are present. Map geometry and jumpads have no white text.
4	Shape check	The green contour must be a wide filled rectangle (aspect ≥ 3.0, fill ≥ 45%, area ≥ 3000 px). Terrain bleed and muzzle flashes fail this.
---
Layer 2 — Independent veto gates (reject if you died)
These run after Layer 1 confirms a win. Each veto is independent.
Gate	Name	What it checks
2	Red reject	ROUND LOST red box in the win zone → veto. Also has an un-bypassable absolute threshold that fires before all other gates, catching partial ROUND LOST frames (e.g. camera looking sideways on Crossroads).
5	Death card	Yellow or purple elimination panel in the bottom-right → veto.
8	OCR death	EasyOCR reads "eliminated you" in the death zone → veto.
All three share the post-win safety flag. When set, all three vetoes are bypassed — any visible death signal must be a post-win jump-off.
Post-win safety is set when:
Strict 1v1 (`CLIP_TEAMMATE_KILLS = False`): winning and dying are mutually exclusive in 1v1.
Gate 10 confirmed your kill via the kill feed.
Lookback (Gate 6) assists in team games — scans back to the start of the round for earlier death-card events. If you died before the win banner, it was a teammate's win. Skipped in 1v1 and when post-win safety is set.
---
Layer 3 — Weapon filter (Gate 9)
Completely independent last layer. If `WEAPON_FILTER` is non-empty, EasyOCR reads the bottom-right HUD weapon name and rejects the clip if it does not match.
---
Setup (one time only)
1. Install Python
Download from https://www.python.org/downloads/  
✅ Check "Add Python to PATH" during install
2. Install FFmpeg
```
winget install ffmpeg
```
Or download from https://github.com/BtbN/FFmpeg-Builds/releases  
(get `ffmpeg-master-latest-win64-gpl.zip`, extract, add `\bin` to PATH)
3. Python packages
The script installs everything automatically on first run:
`opencv-python` — frame-level visual detection
`numpy`, `scipy`, `tqdm` — core processing
`librosa` — audio analysis (only if `USE_AUDIO = True`)
`psutil` — hardware detection for auto-tuning
`easyocr` — OCR gates 7, 8, 9, 10 (downloads ~1 GB on first run — normal, one-time only)
---
Usage
Option A — Windows batch file (easiest)
Put `RUN_ME.bat` and `config.py` in the same folder
Create a `recordings` folder next to them and drop your MP4s in
Double-click `RUN_ME.bat`
Clips appear in a `clips` folder when done
Option B — Command line
```bash
python config.py --input D:\OBS\Rivals --output D:\clips
```
---
Tuning (edit the top of config.py)
Most important — set your username
```python
PLAYER_USERNAME = 'YourRobloxName'
```
This enables Gate 10, the main kill-feed gate. Without it the pipeline falls back to Gates 1 + 7 only, which is less accurate. A warning is shown at startup if this is not set.
Core settings
Setting	Default	Effect
`CLIP_BEFORE`	`9`	Seconds before kill included in clip
`CLIP_AFTER`	`2`	Seconds after kill included in clip
`MIN_GAP`	`14`	Minimum gap in seconds between two clips
`WORKERS`	`0`	Parallel workers — `0` = auto-tuned
`N_SPLITS`	`4`	Segments per video — each split scans in parallel
`FRAME_SAMPLE`	`0.5`	Fallback sample rate (overridden at runtime)
`USE_OCR`	`True`	Enable/disable all OCR gates (7, 8, 9, 10)
`DEBUG_FRAME`	`False`	Save a debug image with all detection zones drawn
Teammate kills
Setting	Default	Effect
`CLIP_TEAMMATE_KILLS`	`False`	`False` = clip only your kills. Gate 10 cross-checks the kill confirmation text to reject assists and teammate kills. `True` = clip every round win regardless of who made the kill.
How Gate 10 tells your kill from your teammate's in 3v3:
Kill feed	Kill text	Result
`Lollipop → victim` (solo)	any	✅ Your kill
`Lollipop + X → victim`	`Eliminated victim`	✅ Your kill
`Lollipop + X → victim`	`Lollipop eliminated victim`	✅ Your kill
`Lollipop + X → victim`	`Assist victim`	✗ You assisted
`Lollipop + X → victim`	`X eliminated victim`	✗ Teammate's kill
Weapon filter — Gate 9
Setting	Default	Effect
`WEAPON_FILTER`	`[]`	Empty = clip all kills (gate disabled). Add substrings to restrict. Requires `USE_OCR = True`.
`WEAPON_ZONE`	`(0.68, 0.86, 0.82, 0.96)`	Screen region for the weapon name HUD element.
```python
WEAPON_FILTER = []                      # all weapons (gate disabled)
WEAPON_FILTER = ['SNIPER']              # sniper kills only
WEAPON_FILTER = ['SNIPER', 'ROCKET']   # sniper OR rocket
```
Kill feed settings — Gate 10
Setting	Default	Effect
`PLAYER_USERNAME`	`''`	Your Roblox username. Leave empty to disable Gate 10.
`KILL_FEED_ZONE`	`(0.70, 0.03, 1.00, 0.20)`	Top-right region containing the kill feed.
`KILL_TEXT_ZONE`	`(0.20, 0.63, 0.80, 0.82)`	Bottom-centre region containing the kill confirmation text — used to identify assists vs kills in team games.
Detection thresholds
Setting	Default	Effect
`WIN_GREEN_PIX`	`100`	Min green pixels for Gate 1
`WIN_RED_PIX`	`100`	Min red pixels for Gate 2
`WIN_RED_ABSOLUTE`	`300`	Un-bypassable red threshold — catches partial ROUND LOST frames even in 1v1 mode
`WHITE_PIX_MIN`	`1000`	Min white pixels for Gate 3 (raised to reject terrain bleed)
`CONTOUR_ASPECT_MIN`	`3.0`	Min aspect ratio for Gate 4 (raised to reject muzzle flashes and in-world signs)
`DEATH_PIX`	`400`	Min coloured pixels for Gate 5 death card detection
Getting too many clips? → Raise `WIN_GREEN_PIX` to 300, or use `DEBUG_FRAME` to see what's triggering  
Missing kills? → Make sure `PLAYER_USERNAME` is set correctly; lower `WIN_GREEN_PIX` to 60 as a last resort
---
Auto-tuning
Hardware	Workers	Frame sample
32 GB+ RAM	All cores minus 2	Every 0.3 s
16 GB RAM	All cores minus 1	Every 0.3 s
8 GB RAM	Half your cores	Every 0.5 s
< 8 GB RAM	1–2 workers	Every 1.0 s
Each video is also split into `N_SPLITS` segments scanned in parallel, so even a single video uses all available workers.
---
Performance
~30–40 GB of footage takes roughly 45–90 minutes on a mid-range machine
High-end hardware (16+ cores, 32 GB+ RAM) is significantly faster
Clips are re-encoded with `libx264 ultrafast` — cutting is fast
Safe to run overnight
Progress is checkpointed to `clips/sniped_progress.json` — restart after an interruption and it picks up where it left off. Delete that file to start fresh.
---
Output
Clips are named like:
```
2024-01-15_rivals__clip001_02m34s.mp4
2024-01-15_rivals__clip002_08m11s.mp4
```
Phase 2 lists every clip as it's cut:
```
  ✓ clip 001  02:34  47 MB  2024-01-15_rivals__clip001_02m34s.mp4
  ✓ clip 002  08:11  52 MB  2024-01-15_rivals__clip002_08m11s.mp4
```
---
Debug mode
Set `DEBUG_FRAME = True` and run on a single video. A `.jpg` is saved next to the recording with every detection zone drawn:
Colour	Zone
🟩 Green	WIN ZONE (top-centre)
🟥 Red	DEATH ZONE (bottom-right)
🟧 Orange	WEAPON ZONE (bottom-right corner)
🟨 Yellow	KILL FEED ZONE (top-right)
🟪 Magenta	KILL TEXT ZONE (bottom-centre)
---
Troubleshooting
Clips from teammate kills in 3v3 — make sure `PLAYER_USERNAME` matches your exact Roblox username. Gate 10 needs this to cross-check the kill feed and kill text.
Missing kills — run `DEBUG_FRAME = True` on a missed clip to check zone alignment. If Gate 10 is off (no username), set it.
Too many false clips on Crossroads — the script has dedicated calibrations for this map (`CONTOUR_ASPECT_MIN = 3.0`, `WIN_RED_ABSOLUTE = 300`, `WHITE_PIX_MIN = 1000`). If still seeing false positives, raise `WIN_GREEN_PIX` to 300.
ETA shows "calculating…" at startup — normal for the first few seconds. ETA updates per segment (not per video), so it becomes accurate quickly even on single-video runs.
OCR download on first run — EasyOCR downloads ~1 GB of PyTorch models the first time. This is normal and only happens once.
