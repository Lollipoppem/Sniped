<div align="center">

```
 _____ _____ _____ _____ _____ _____
|   __|   | |  |  |  _  |   __|  _  \
|__   | | | |  |  |   __|   __| |_| |
|_____|_|___|__|__|__|  |_____|_____/
```

# SNIPED v2.4 — The Headshot Update

**Automatic kill-clip extractor for Roblox Rivals OBS recordings**

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?logo=windows)](https://www.microsoft.com/windows)

</div>

---

Drop your OBS recordings in a folder. Double-click. Come back to a `clips` folder full of your kills — automatically cut, named, and ready to edit.

No manual scrubbing. No missed moments. Just highlights.

---

## Features

- Scans your recordings and clips every kill automatically
- Reads your username directly from the kill feed — clips your kills, not your teammate's
- Filters by weapon — sniper only, RPG only, whatever you want
- Headshot-only mode
- Runs on all your CPU cores at once — fast even on big recording sessions
- Pause and resume mid-scan with Ctrl+P
- Safe to interrupt — picks up where it left off

---

## Quick start

**Requirements:** Python 3.8+, FFmpeg, Windows

```bash
# 1. Clone
git clone https://github.com/your-username/sniped.git
cd sniped

# 2. Open config.py and set your username
PLAYER_USERNAME = 'YourRobloxName'

# 3. Drop your recordings in the recordings/ folder

# 4. Run
python config.py
```

All dependencies install automatically on first run. EasyOCR downloads ~1 GB of models the first time — one-time only.

---

## Settings

Everything is at the top of `config.py`:

```python
PLAYER_USERNAME     = ''                # your Roblox username
CLIP_TEAMMATE_KILLS = False             # True = clip all round wins
HEADSHOT_ONLY       = False             # True = headshots only
WEAPON_FILTER       = []               # e.g. ['SNIPER'] for sniper only
CLIP_BEFORE         = 9                # seconds before the kill
CLIP_AFTER          = 2                # seconds after the kill
```

For the full setup guide see [READ_ME.md](READ_ME.md).
