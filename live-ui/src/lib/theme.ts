import { useCallback, useEffect, useState } from "react";

export type Theme = "system" | "light" | "dark";

const STORAGE_KEY = "aba-live-theme";
const ORDER: Theme[] = ["system", "light", "dark"];

export function readStoredTheme(storage: Pick<Storage, "getItem"> | null): Theme {
  try {
    const value = storage?.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

export function nextTheme(theme: Theme): Theme {
  return ORDER[(ORDER.indexOf(theme) + 1) % ORDER.length]!;
}

function browserStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** The viewer's theme: follows the system until a light or dark one is picked. */
export function useTheme(): { theme: Theme; cycle: () => void } {
  const [theme, setTheme] = useState<Theme>(() => readStoredTheme(browserStorage()));
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") delete root.dataset.theme;
    else root.dataset.theme = theme;
    try {
      if (theme === "system") browserStorage()?.removeItem(STORAGE_KEY);
      else browserStorage()?.setItem(STORAGE_KEY, theme);
    } catch {
      // A blocked store only means the choice is not remembered.
    }
  }, [theme]);
  const cycle = useCallback(() => setTheme(nextTheme), []);
  return { theme, cycle };
}
