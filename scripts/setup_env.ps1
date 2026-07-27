# Dot-source this (do not execute directly): `. .\scripts\setup_env.ps1`
# Sets the environment variables DaVinci Resolve's scripting bridge needs.
# Windows defaults shown - edit for your machine. See docs/CONFIG.md.

$env:RESOLVE_SCRIPT_API = "C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
$env:RESOLVE_SCRIPT_LIB = "C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
$env:PYTHONPATH = "$env:PYTHONPATH;$env:RESOLVE_SCRIPT_API\Modules\"

Write-Host "Resolve scripting environment variables set for this shell session."
