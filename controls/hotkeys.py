"""Small emergency-only allowlist; no OS APIs or keyboard automation."""

DEFAULT_EMERGENCY_HOTKEY = "ctrl+alt+esc"
# F12 is reserved for debuggers by RegisterHotKey's contract. Ctrl+Shift+Esc
# launches Task Manager; Win combinations and ordinary typing keys are excluded.
EMERGENCY_HOTKEYS = {
    DEFAULT_EMERGENCY_HOTKEY: (0x0003, 0x1B),
    "ctrl+shift+f9": (0x0006, 0x78),
    "ctrl+shift+f10": (0x0006, 0x79),
    "ctrl+shift+f11": (0x0006, 0x7A),
}
_SUPPORTED = ", ".join(EMERGENCY_HOTKEYS)


def normalize_hotkey(value):
    """Canonical modifier order, case-insensitive names, explicit supported keys."""
    if not isinstance(value, str):
        raise ValueError("Emergency shortcut must be a modifier+key string")
    parts = [part.strip().casefold() for part in value.split("+")]
    if "f12" in parts:
        raise ValueError("F12 is reserved for Windows debuggers; use ctrl+shift+f10 instead")
    modifiers, key = parts[:-1], parts[-1]
    if (not modifiers or len(set(parts)) != len(parts) or not all(parts)
            or any(part not in ("ctrl", "alt", "shift") for part in modifiers)):
        raise ValueError(f"Malformed emergency shortcut; choose {_SUPPORTED}")
    canonical = "+".join([part for part in ("ctrl", "alt", "shift") if part in modifiers]+[key])
    if canonical not in EMERGENCY_HOTKEYS:
        raise ValueError(f"Unsupported/reserved emergency shortcut; choose {_SUPPORTED}")
    return canonical


def display_hotkey(value):
    return "+".join(part.title() for part in normalize_hotkey(value).split("+"))
