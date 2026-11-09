/**
 * Stand-in for `@tauri-apps/api/window` (see vite.config.ts): the viewer runs in a browser, where the shell's title
 * bar has no window to control. The title bar only imports this when window controls are enabled.
 */
export function getCurrentWindow(): never {
  throw new Error("No desktop window in the browser.");
}
