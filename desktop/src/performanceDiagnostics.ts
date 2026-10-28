export function formatPerformanceDiagnosticsShortcut(shortcut: string) {
  return shortcut.replace("Control", "Ctrl").replace("Meta", "Cmd").replace("Key", "").replace("Digit", "").split("+").join(" + ");
}

export function performanceDiagnosticsShortcutFromEvent(event: { ctrlKey: boolean; metaKey: boolean; altKey: boolean; shiftKey: boolean; code: string }) {
  const modifiers = [event.ctrlKey && "Control", event.metaKey && "Meta", event.altKey && "Alt", event.shiftKey && "Shift"].filter(Boolean);
  if (modifiers.length === 0 || ["ControlLeft", "ControlRight", "ShiftLeft", "ShiftRight", "AltLeft", "AltRight", "MetaLeft", "MetaRight"].includes(event.code)) return undefined;
  return [...modifiers, event.code].join("+");
}

export function matchesPerformanceDiagnosticsShortcut(event: KeyboardEvent, shortcut: string) {
  const parts = shortcut.split("+");
  return parts.includes(event.code)
    && parts.includes("Control") === event.ctrlKey
    && parts.includes("Meta") === event.metaKey
    && parts.includes("Alt") === event.altKey
    && parts.includes("Shift") === event.shiftKey;
}
