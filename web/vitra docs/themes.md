# Themes - Vitra CSS Framework

Complete guide to using and customizing the 7 preset themes in Vitra CSS Framework.

## Overview

Vitra includes **6 preset themes** (plus `auto` for system detection) that can be applied via the `data-theme` attribute or JavaScript API. Each theme overrides the core design tokens to create a unique visual experience. All surface colors are tinted with the accent hue — no pure neutral grays.

| Theme | Name | Accent Hue | Description |
|-------|------|-----------|-------------|
| `light` | Light | 245 (purple) | Light background with subtle purple tint |
| `dark` | Dark | 245 (purple) | Dark background with subtle purple tint |
| `pastel` | Pastel | 320 (pink) | Soft muted colors with pink accents |
| `neon` | Neon | 180 (cyan) | Bright cyan accents on deep dark background |
| `ocean` | Ocean | 200 (blue) | Deep blue-toned theme with cyan accents |
| `emerald` | Emerald | 155 (green) | Rich green-toned theme with soft glows |
| `auto` | Auto-Detect | 245 (purple) | Uses `prefers-color-scheme` to detect system preference |

### Premium Color Features

Since v1.3, Vitra's theming system includes:

- **Tinted Neutrals**: Every surface carries a trace of the accent hue — inspired by Stripe, Linear, and Raycast
- **oklch() Support**: `--vitra-color-accent-oklch` for perceptually uniform color interpolation
- **Warm/Cool Variants**: `--vitra-color-bg-warm` (+30° hue shift) and `--vitra-color-bg-cool` (-30° hue shift)
- **`color-scheme` Sync**: Browser-native UI (scrollbars, form controls) automatically matches the theme

## Quick Start

### Apply a Theme via HTML

```html
<!-- Set theme on <html> element -->
<html data-theme="dark">
  <!-- Your content -->
</html>

<!-- Or apply to any container -->
<div data-theme="light">
  <p>This content uses the light theme.</p>
</div>
```

### Apply a Theme via JavaScript

```javascript
// Vitra is available as a global or ES module
const Vitra = window.Vitra; // or import from './vitra.js'

// Set a specific theme
Vitra.theme.set('dark');

// Toggle between light and dark
const newTheme = Vitra.theme.toggle();

// Get current theme
const current = Vitra.theme.get();
console.log('Current theme:', current);

// Get effective theme (resolves 'auto' to actual theme)
const effective = Vitra.theme.getEffective();
console.log('Effective theme:', effective);
```

## Theme Reference

### 1. Default (No data-theme attribute)

The default theme matches the base token values defined in `01-tokens.css`. Since v1.3, surfaces are tinted with the accent hue.

**Core Colors:**
- Background: `hsl(245, 15%, 4%)` (dark with purple tint)
- Surface: `hsl(245, 20%, 95% / 5%)` (tinted white overlay)
- Accent: `hsl(245, 100%, 70%)` — `#6c63ff` (purple)
- Text: `rgba(255, 255, 255, 0.95)` (light)

**Use case:** Dark-themed applications, matches the "dark" theme.

---

### 2. Light Theme

Bright theme with dark text on light background. Surface colors are subtly tinted with the accent hue.

**Key Tokens:**
```css
html[data-theme="light"] {
  --vitra-color-bg: hsl(245, 10%, 98%);
  --vitra-color-surface: hsl(245, 20%, 10% / 4%);
  --vitra-color-text-primary: rgba(0, 0, 0, 0.95);
  --vitra-color-accent: #6c63ff;
}
```

**Shadows:** Lighter shadows for light backgrounds.

**Use case:** Documentation sites, light-themed dashboards.

---

### 3. Dark Theme

Dark background with light text (explicit). Tinted with accent hue for cohesive premium look.

**Key Tokens:**
```css
html[data-theme="dark"] {
  --vitra-color-bg: hsl(245, 15%, 4%);
  --vitra-color-surface: hsl(245, 20%, 95% / 5%);
  --vitra-color-text-primary: rgba(255, 255, 255, 0.95);
  --vitra-color-accent: #6c63ff;
}
```

**Shadows:** Glow effects enhanced for dark theme.

**Use case:** Default for admin panels, dark-mode applications.

---

### 4. Pastel Theme

Soft, muted colors with pink accents.

**Key Tokens:**
```css
[data-theme="pastel"] {
  --vitra-color-bg: #f9f7f7;
  --vitra-color-surface: rgba(255, 182, 193, 0.15);
  --vitra-color-accent: #ffb6c1; /* Light pink */
  --vitra-color-text-primary: rgba(80, 60, 80, 0.95);
}
```

**Shadows:** Soft pastel shadows.

**Use case:** Children's apps, playful interfaces, soft UI.

---

### 5. Neon Theme

Bright cyan glow effects on deep black background.

**Key Tokens:**
```css
[data-theme="neon"] {
  --vitra-color-bg: #0a0a0f;
  --vitra-color-accent: #00ffff; /* Cyan */
  --vitra-color-text-primary: rgba(0, 255, 255, 0.95);
  --vitra-shadow-glow: 0 0 20px rgba(0, 255, 255, 0.5);
}
```

**Shadows:** Strong glow effects using cyan.

**Use case:** Gaming interfaces, creative portfolios, cyberpunk themes.

---

### 6. Ocean Theme

Deep blue-toned theme with cyan accents.

**Key Tokens:**
```css
html[data-theme="ocean"] {
  --vitra-color-bg: hsl(210, 30%, 4%);
  --vitra-color-surface: hsla(210, 100%, 60%, 0.05);
  --vitra-color-accent-h: 200;
  --vitra-color-accent-s: 90%;
  --vitra-color-accent-l: 55%;
  --vitra-color-text-primary: hsl(210, 100%, 95%);
}
```

**Use case:** Marine-themed interfaces, creative portfolios, data dashboards.

---

### 7. Emerald Theme

Rich green-toned theme with soft glows.

**Key Tokens:**
```css
html[data-theme="emerald"] {
  --vitra-color-bg: hsl(160, 20%, 3%);
  --vitra-color-surface: hsla(160, 100%, 50%, 0.05);
  --vitra-color-accent-h: 155;
  --vitra-color-accent-s: 80%;
  --vitra-color-accent-l: 45%;
  --vitra-color-text-primary: hsl(160, 100%, 95%);
}
```

**Use case:** Nature-themed sites, financial dashboards, premium branding.

---

### 8. Auto Theme (System Preference)

Automatically detects the user's system theme preference via `prefers-color-scheme`.

**Behavior:**
- Uses `prefers-color-scheme: dark` → Applies "dark" theme tokens
- Uses `prefers-color-scheme: light` → Applies "light" theme tokens
- Falls back to "dark" theme if detection fails

**Implementation:**
```css
html[data-theme="auto"] {
  /* Default to dark */
  --vitra-color-bg: hsl(240, 15%, 4%);
}

@media (prefers-color-scheme: light) {
  html[data-theme="auto"] {
    --vitra-color-bg: hsl(0, 0%, 100%);
    --vitra-color-surface: hsla(0, 0%, 0%, 0.04);
    --vitra-color-text-primary: hsla(0, 0%, 0%, 0.95);
    --vitra-color-text-secondary: hsla(0, 0%, 0%, 0.7);
  }
}
```

**JavaScript watches for changes:**
```javascript
// Auto theme listens for system changes
if (themeToSet === 'auto') {
  theme._watchSystemTheme();
}
```

### CSS Custom Properties Reference

Each theme defines the following `--vitra-*` properties:

| Property | Purpose | Overridden in themes? |
|----------|---------|-----------------------|
| `--vitra-color-bg` | Page background | ✅ All themes |
| `--vitra-color-surface` | Card/component background | ✅ All themes |
| `--vitra-color-surface-hover` | Hover state surface | ✅ All themes |
| `--vitra-color-surface-active` | Active state surface | ✅ All themes |
| `--vitra-color-border` | Subtle borders | ✅ All themes |
| `--vitra-color-border-hover` | Hover border state | ✅ All themes |
| `--vitra-color-text-primary` | Primary text | ✅ All themes |
| `--vitra-color-text-secondary` | Secondary/muted text | ✅ All themes |
| `--vitra-color-text-tertiary` | Tertiary/disabled text | ✅ All themes |
| `--vitra-color-text-inverse` | Text on accent backgrounds | ✅ All themes |
| `--vitra-shadow-*` | Shadow levels | ✅ Dark/light, ⚠️ decorative (fallback to dark) |
| `--vitra-glass-bg` | Glass background | ✅ All themes |
| `--vitra-color-accent-h` | Accent hue | ✅ Decorative themes override |
| `--vitra-color-accent-s` | Accent saturation | ✅ Decorative themes override |
| `--vitra-color-accent-l` | Accent lightness | ✅ Decorative themes override |
| `--vitra-color-bg-warm` | Warm background variant | ✅ Dark/light |
| `--vitra-color-bg-cool` | Cool background variant | ✅ Dark/light |
| `--vitra-color-accent-oklch` | Perceptual color space | ✅ Dark/light |
| `--vitra-border-glow-angle` | Animated border start angle | ✅ Dark/light |

**Note:** Decorative themes (pastel, neon, ocean, emerald) inherit shadow and premium token values from the default dark theme unless explicitly overridden.

**Use case:** Respecting user's OS-level theme preference automatically.

---

## JavaScript API Reference

### Vitra.theme Methods

#### `Vitra.theme.get()`
Returns the current theme name from the DOM.

```javascript
const theme = Vitra.theme.get();
// Returns: 'dark', 'light', 'auto', etc.
// If no data-theme is set, returns 'auto'
```

#### `Vitra.theme.set(themeName)`
Sets the theme on the document element.

```javascript
const success = Vitra.theme.set('neon');
// Returns: true if successful, false if invalid theme

// Persists to localStorage automatically
```

#### `Vitra.theme.toggle()`
Toggles between light and dark themes. If currently in a special theme (pastel, neon, etc.), defaults to light.

```javascript
// Toggle between light and dark
const newTheme = Vitra.theme.toggle();
// Returns: 'light' or 'dark' depending on the new state
```

#### `Vitra.theme.init(options)`
Initializes theme from localStorage or system preference.

```javascript
Vitra.theme.init({
  defaultTheme: 'auto',  // Fallback if nothing stored (default: 'auto')
  persist: true            // Whether to persist theme (default: true)
});

// Behavior:
// 1. Try to restore from localStorage
// 2. If nothing stored, use defaultTheme
// 3. Apply the theme
// 4. If persist is true and no stored theme, save defaultTheme
// 5. If theme is 'auto', watch for system changes
```

#### `Vitra.theme.getEffective()`
Gets the effective theme (resolves 'auto' to actual theme).

```javascript
Vitra.theme.set('auto');
const effective = Vitra.theme.getEffective();
// Returns: 'dark' or 'light' based on system preference
```

#### `Vitra.theme.clear()`
Clears the stored theme preference.

```javascript
Vitra.theme.clear();
// Removes 'vitra-theme' from localStorage
```

#### `Vitra.theme.getValidThemes()`
Returns an array of valid theme names.

```javascript
const themes = Vitra.theme.getValidThemes();
// Returns: ['light', 'dark', 'auto', 'pastel', 'neon', 'ocean', 'emerald']
```

---

## Creating a Theme Toggle

### Simple Toggle Button

```html
<button onclick="toggleTheme()">Toggle Theme</button>

<script>
function toggleTheme() {
  Vitra.theme.toggle('light', 'dark');
}
</script>
```

### Theme Selector Dropdown

```html
<select onchange="Vitra.theme.set(this.value)">
  <option value="light">Light</option>
  <option value="dark" selected>Dark</option>
  <option value="pastel">Pastel</option>
  <option value="neon">Neon</option>
  <option value="ocean">Ocean</option>
  <option value="emerald">Emerald</option>
  <option value="auto">Auto (System)</option>
</select>
```

### Theme Toggle with Icons (CSS-only)

```html
<button class="vitra-btn vitra-btn-ghost" onclick="toggleTheme()">
  <span data-theme-icon="dark">🌙</span>
  <span data-theme-icon="light" style="display:none;">☀️</span>
</button>

<script>
function toggleTheme() {
  const newTheme = Vitra.theme.toggle('light', 'dark');
  
  // Update icons
  document.querySelectorAll('[data-theme-icon]').forEach(el => {
    el.style.display = el.getAttribute('data-theme-icon') === newTheme ? 'inline' : 'none';
  });
}
</script>
```

---

## Theme Persistence

When using `Vitra.theme.set()` or `Vitra.theme.init()`, the theme is automatically saved to `localStorage` under the key `vitra-theme`.

**To disable persistence:**
```javascript
Vitra.theme.init({
  persist: false
});
```

**To clear stored preference:**
```javascript
Vitra.theme.clear();
```

---

## Custom Theme Creation

You can create custom themes by adding a new `[data-theme="custom-name"]` block in your CSS.

```css
/* Custom theme example */
html[data-theme="brand"] {
  --vitra-color-bg: #your-bg-color;
  --vitra-color-surface: rgba(...);
  --vitra-color-accent: #your-accent;
  --vitra-color-text-primary: rgba(...);
  --vitra-color-text-secondary: rgba(...);
  --vitra-color-border: rgba(...);
  --vitra-shadow-glow: 0 0 20px rgba(...);
}
```

**Note:** Custom themes are not included in `Vitra.theme.getValidThemes()` unless you modify the `VALID_THEMES` array in `vitra.js`.

---

## Theme-Specific Component Styling

Components automatically adapt to the current theme through CSS cascade.

```html
<!-- This card will use the current theme's tokens -->
<div class="vitra-card">
  <h3 class="vitra-card-title">Themed Card</h3>
  <p class="vitra-card-body">This card uses the active theme's colors.</p>
</div>
```

No additional work needed — all components use `var(--vitra-color-*)` tokens that are overridden by the theme.

---

## Best Practices

1. **Always use tokens:** Reference `var(--vitra-color-*)` in your custom CSS, not hard-coded colors
2. **Test all themes:** Verify your UI looks good in all 8 presets
3. **Use auto theme for new users:** Set `defaultTheme: 'auto'` in `Vitra.theme.init()`
4. **Respect persistence:** Let users override the system preference if they want
5. **Test with prefers-color-scheme:** Use DevTools to simulate system theme changes

---

## Troubleshooting

### Theme not applying?
- Ensure `data-theme` is set on `<html>` or a parent container
- Check that `00-themes.css` is included in your CSS bundle
- Verify the theme name is spelled correctly (case-sensitive)

### localStorage not working?
- Check if localStorage is available: `Vitra.theme._isLocalStorageAvailable()`
- Some browsers disable localStorage in private/incognito mode

### Auto theme not detecting system preference?
- Ensure browser supports `prefers-color-scheme` (Chrome 76+, Firefox 67+)
- Check with: `window.matchMedia('(prefers-color-scheme: dark)').matches`

---

**Related Documentation:**
- [docs/integration.md](integration.md) - JS module API and data-config
- [docs/compatibility.md](compatibility.md) - Browser support for themes
- [README.md](../README.md) - Quick start guide
