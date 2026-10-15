// Keyboard shortcuts of the app (Options > Keyboard shortcuts). shortcutAction maps a key event to what to do;
// app.js carries it out.

export const SHORTCUTS = [
  ['Ctrl+1 … Ctrl+9', 'Open the 1st … 9th tab of the sidebar'],
  ['Ctrl+Tab / Ctrl+Shift+Tab', 'Next / previous tab'],
  ['F5', 'Read the open tab again'],
  ['Ctrl+,', 'Options'],
  ['Ctrl+= / Ctrl+- / Ctrl+0', 'Larger / smaller / normal text'],
  ['Alt+Up / Alt+Down', 'Move the focused sidebar tab'],
];

/** {type: 'tab', index} | {type: 'step', by} | {type: 'reload'} | {type: 'options'} | {type: 'text', by | reset} | null */
export function shortcutAction(e) {
  const ctrl = e.ctrlKey && !e.altKey && !e.metaKey;
  if (e.key === 'F5' && !e.ctrlKey && !e.altKey) return { type: 'reload' };
  if (!ctrl) return null;
  if (/^[1-9]$/.test(e.key) && !e.shiftKey) return { type: 'tab', index: Number(e.key) - 1 };
  if (e.key === 'Tab') return { type: 'step', by: e.shiftKey ? -1 : 1 };
  if (e.key === ',') return { type: 'options' };
  if (e.key === '=' || e.key === '+') return { type: 'text', by: 10 };
  if (e.key === '-' || e.key === '_') return { type: 'text', by: -10 };
  if (e.key === '0' && !e.shiftKey) return { type: 'text', reset: true };
  return null;
}
