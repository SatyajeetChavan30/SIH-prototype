/**
 * Theme selection — light, dark, or follow the operating system.
 *
 * WHY THE CHOICE IS EXPLICIT
 * --------------------------
 * The app used to be pinned to light because the panels' colours were 127
 * hardcoded light-theme literals; a machine in dark mode got native form
 * controls inverted and nothing else, which made the sidebar unreadable. Those
 * literals are tokens now and both themes are complete, so the choice can be
 * offered — but it is offered, not imposed. A presenter running a projector in
 * a bright hall wants light regardless of what their laptop is set to, and the
 * one thing worse than the wrong theme is a theme that changes by itself
 * halfway through a demo.
 *
 * WHY THE RESOLUTION HAPPENS HERE AND NOT IN CSS
 * ----------------------------------------------
 * "system" is resolved to a concrete light/dark here and written to
 * `data-theme` on <html>, so the stylesheet needs exactly ONE dark block keyed
 * on that attribute. The alternative — an attribute rule plus a
 * `prefers-color-scheme` media query — means maintaining the dark palette
 * twice, and two copies of a 30-token palette drift. The media listener below
 * is what keeps "system" honest: it re-resolves when the OS flips, and only
 * while the user is actually in system mode.
 */
import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "jalraksha.theme";
export const THEMES = ["system", "light", "dark"];

const DARK_QUERY = "(prefers-color-scheme: dark)";

function prefersDark() {
  return typeof window !== "undefined" &&
    window.matchMedia?.(DARK_QUERY).matches === true;
}

function readStored() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return THEMES.includes(stored) ? stored : "system";
  } catch {
    // Private windows and blocked site data throw on access rather than
    // returning null, so the read has to be guarded, not merely null-checked.
    return "system";
  }
}

function apply(theme) {
  const resolved = theme === "system" ? (prefersDark() ? "dark" : "light") : theme;
  document.documentElement.setAttribute("data-theme", resolved);
  return resolved;
}

export function useTheme() {
  const [theme, setThemeState] = useState(readStored);
  const [resolved, setResolved] = useState(() => apply(readStored()));

  useEffect(() => {
    setResolved(apply(theme));
    if (theme !== "system") return;
    // Only subscribed while following the system, so an explicit choice is
    // never overwritten by the OS changing underneath it.
    const mq = window.matchMedia?.(DARK_QUERY);
    if (!mq) return;
    const onChange = () => setResolved(apply("system"));
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  const setTheme = useCallback((next) => {
    setThemeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // A theme that cannot be persisted still works for this session; failing
      // to store it is not a reason to refuse to change it.
    }
  }, []);

  return { theme, resolved, setTheme };
}
