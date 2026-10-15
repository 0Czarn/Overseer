"""Combat log for every country (2026-10-15, user's request: losses of all countries, not only the player's).

The game logs equipment and manpower losses (NCombatLog::CManager, [game state + 0x880]) only for countries a gate
function accepts: hoi4.exe+0xCDF8F0 (1.19.3.0.c01a) walks the player list ([game state + 0xF8], count + 0x104,
entries of 0xA0, country + 0x70) and returns true for a player's country (or the same country under another tag).
Its 7 callers all only fetch the country's CManager for logging (combat, attrition, recovered equipment, manpower,
division templates), and skip the gate when [game state + 0x520] <= 0. POL 1936 at war with SOV: only POL logged.

The patch makes the gate return true ("mov al, 1; ret") so every country keeps a log: the debugger then reads
everyone's losses. Only statistics change, not the game - but the logs grow the saves and the game's memory, so it is
opt-in, single player only, and undone by restoring the original bytes (or by restarting the game).
"""

from __future__ import annotations

GATE_RVA = 0xCDF8F0
ORIGINAL = bytes.fromhex("48895c2418")   # mov [rsp+0x18], rbx
PATCHED = bytes.fromhex("b001c39090")    # mov al, 1; ret; nop; nop


def state(memory, module_base: int) -> str:
    """"on" | "off" | "unknown" (other bytes: another game build or another tool's change)."""
    current = memory.read(module_base + GATE_RVA, len(ORIGINAL))
    return "on" if current == PATCHED else "off" if current == ORIGINAL else "unknown"
