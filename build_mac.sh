#!/bin/bash
# Builds RotationTracker.app from rotation_tracker.py on a Mac.
# Requires Python 3 from python.org (it includes Tk). Run:  bash build_mac.sh
set -e
cd "$(dirname "$0")"
python3 -m pip install --upgrade pyinstaller
python3 -m PyInstaller --windowed --onedir --noconfirm --name RotationTracker \
  --osx-bundle-identifier io.github.xion0014.rotationtracker rotation_tracker.py
codesign --force --deep --sign - dist/RotationTracker.app
echo
echo "Done! The app is at dist/RotationTracker.app - drag it into Applications."
