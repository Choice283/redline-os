#!/usr/bin/env bash
# Source this (do not execute): `source scripts/setup_env.sh`
# Sets the environment variables DaVinci Resolve's scripting bridge needs.
# macOS defaults shown — edit for your machine, or set these in your shell
# profile / .env instead. See docs/CONFIG.md.

export RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
export RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
export PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules/"

echo "Resolve scripting environment variables set for this shell session."
