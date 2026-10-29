/**
 * @openaec/design-tokens — tailwind.preset.js
 * Auto-gegenereerd door build.js. Niet handmatig bewerken.
 *
 * Gebruik in je Tailwind project:
 *   // tailwind.config.ts
 *   import oaPreset from "@openaec/design-tokens/tailwind";
 *   export default { presets: [oaPreset], content: [...] };
 *
 * Dark mode staat ingesteld op 'class' via [data-theme="dark"] selector.
 */
/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
            "amber": "#D97706",
            "deep-forge": "#36363E",
            "signal-orange": "#EA580C",
            "warm-gold": "#F59E0B",
            "scaffold-gray": "#A1A1AA",
            "blueprint-white": "#FAFAF9",
            "concrete": "#F5F5F4",
            "night-build": "#2A2A32",
            "primary": "#D97706",
            "primary-hover": "#EA580C",
            "accent": "#EA580C",
            "neutral": {
                  "0": "#FFFFFF",
                  "50": "#FAFAF9",
                  "100": "#F5F5F4",
                  "200": "#E7E5E4",
                  "300": "#D6D3D1",
                  "400": "#A1A1AA",
                  "500": "#71717A",
                  "600": "#57534E",
                  "700": "#3F3F46",
                  "800": "#27272A",
                  "900": "#2A2A32",
                  "950": "#36363E"
            },
            "success": "#16A34A",
            "error": "#DC2626",
            "danger": "#DC2626",
            "warning": "#F59E0B",
            "info": "#2563EB",
            "surface": "var(--color-surface-bg)",
            "panel": "var(--color-surface-panel)",
            "text-primary": "var(--color-text-primary)",
            "text-secondary": "var(--color-text-secondary)",
            "text-muted": "var(--color-text-muted)",
            "border-default": "var(--color-border-default)"
      },
      fontFamily: {
            "heading": [
                  "Space Grotesk",
                  "system-ui",
                  "-apple-system",
                  "Segoe UI",
                  "sans-serif"
            ],
            "body": [
                  "Inter",
                  "system-ui",
                  "-apple-system",
                  "Segoe UI",
                  "sans-serif"
            ],
            "mono": [
                  "JetBrains Mono",
                  "Fira Code",
                  "Consolas",
                  "Menlo",
                  "monospace"
            ],
            "sans": [
                  "Inter",
                  "system-ui",
                  "-apple-system",
                  "Segoe UI",
                  "sans-serif"
            ]
      },
      fontSize: {
            "xs": "0.75rem",
            "sm": "0.875rem",
            "base": "1rem",
            "lg": "1.125rem",
            "xl": "1.25rem",
            "2xl": "1.5rem",
            "3xl": "2rem",
            "4xl": "2.5rem"
      },
      lineHeight: {
            "tight": "1.2",
            "snug": "1.3",
            "normal": "1.5",
            "relaxed": "1.6",
            "loose": "1.7"
      },
      letterSpacing: {
            "tight": "-0.02em",
            "snug": "-0.01em",
            "normal": "0",
            "wide": "0.05em",
            "wider": "0.1em"
      },
      spacing: {
            "0": "0",
            "1": "0.25rem",
            "2": "0.5rem",
            "3": "0.75rem",
            "4": "1rem",
            "5": "1.25rem",
            "6": "1.5rem",
            "8": "2rem",
            "10": "2.5rem",
            "12": "3rem",
            "16": "4rem",
            "20": "5rem",
            "24": "6rem",
            "sidebar-width": "280px",
            "topbar-height": "48px",
            "ribbon-height": "96px"
      },
      borderRadius: {
            "none": "0",
            "sm": "4px",
            "md": "8px",
            "lg": "12px",
            "full": "9999px"
      },
      boxShadow: {
            "sm": "0 1px 2px 0 rgba(0, 0, 0, 0.05)",
            "md": "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -2px rgba(0, 0, 0, 0.1)",
            "lg": "0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -4px rgba(0, 0, 0, 0.1)",
            "focus": "0 0 0 3px rgba(217, 119, 6, 0.35)"
      }
    }
  }
};
