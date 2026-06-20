# Integration Guide - Vitra CSS Framework

Complete guide to integrating Vitra CSS Framework into your projects, using data attributes, JS module API, and tree-shaking.

## Overview

Vitra provides multiple integration paths depending on your project needs:

| Method | Best For | Features |
|---------|----------|----------|
| **HTML Link** | Quick start, static sites | CSS + optional JS |
| **CSS @import** | Existing CSS workflows | Cascade layers, tokens |
| **Build Tools** | Production apps, SPAs | Minification, tree-shaking |
| **data-config** | Declarative setup | Zero-JS configuration |
| **JS Module API** | Dynamic apps, SPAs | Full programmatic control |

---

## Method 1: HTML Link (Quick Start)

### Step 1: Include the CSS

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  
  <!-- Vitra CSS -->
  <link rel="stylesheet" href="path/to/vitra.css">
  
  <title>My Vitra Project</title>
</head>
<body>
  <!-- Your content -->
</body>
</html>
```

### Step 2: (Optional) Include the JS

```html
<!-- At the end of <body> -->
<script src="path/to/vitra.js"></script>
<script>
  // Initialize theme with auto-detect
  Vitra.theme.init({ defaultTheme: 'auto' });
  
  // Initialize reveal animations
  Vitra.reveal.init();
</script>
```

### Step 3: Start Using Classes

```html
<body data-theme="dark">
  <div class="vitra-container">
    <div class="vitra-card vitra-card-glass">
      <h2 class="vitra-card-title">Hello Vitra</h2>
      <p class="vitra-card-body">This is a glass card.</p>
      <button class="vitra-btn vitra-btn-glass">Click Me</button>
    </div>
  </div>
</body>
```

---

## Method 2: CSS @import

Import Vitra into your existing CSS workflow:

```css
/* Your main.css */
@import url('path/to/vitra.css');

/* Your custom styles */
.my-component {
  /* Use Vitra tokens */
  background: var(--vitra-color-surface);
  border-radius: var(--vitra-radius-md);
  padding: var(--vitra-space-3);
}
```

**Note:** `@import` can impact performance. For production, consider concatenating with your build tool.

---

## Method 3: Build Tools (Recommended for Production)

### Install Dependencies

```bash
npm install --save-dev lightningcss esbuild
```

### package.json Scripts

```json
{
  "scripts": {
    "build:css": "npx lightningcss src/vitra.css --minify --output dist/vitra.min.css",
    "build:js": "npx esbuild src/vitra.js --bundle --outfile=dist/vitra.js --format=esm",
    "build": "npm run build:css && npm run build:js",
    "dev": "npx serve ."
  }
}
```

### Build and Use

```bash
# Build for production
npm run build

# Link the minified files
<link rel="stylesheet" href="dist/vitra.min.css">
<script src="dist/vitra.js" type="module"></script>
```

---

## data-config Attribute (Declarative Configuration)

Vitra supports declarive configuration via the `data-config` attribute. No JavaScript code required!

### Basic Usage

```html
<!-- Configure Vitra with JSON in data-config -->
<div data-config='{
  "theme": { "defaultTheme": "auto" },
  "particles": { "count": 10, "color": "#6c63ff" },
  "reveal": { "threshold": 0.1, "stagger": 100 }
}'>
  <!-- Your content -->
</div>
```

### Configuration Options

```javascript
{
  "theme": {
    "defaultTheme": "auto",  // Fallback theme
    "persist": true            // Save to localStorage
  },
  "particles": {
    "count": 10,              // Number of particles
    "color": "#6c63ff",      // Particle color
    "size": 4,                // Particle size (px)
    "emoji": null              // Or emoji string like "✨"
  },
  "reveal": {
    "selector": ".vitra-reveal",  // Element selector
    "threshold": 0.1,            // Visibility threshold
    "stagger": 100,              // Stagger delay (ms)
    "scrollReveal": false        // Also watch .vitra-scroll-reveal* elements
  },
  "ripple": true,              // Initialize click ripple (true by default)
  "tooltip": true              // Initialize tooltips (true by default)
}
```

### data-config with Theme Only

```html
<!-- Just initialize theme with auto-detect -->
<div data-config='{"theme": {"defaultTheme": "auto"}}'>
  <!-- Page content -->
</div>
```

### data-config with Particles

```html
<!-- Initialize particles on a container -->
<div data-vitra-particles="20" 
     data-vitra-particle-color="#ff6b6b"
     data-config='{"particles": {"count": 20}}'>
  <!-- Particles will appear here -->
</div>
```

**Note:** `data-config` is processed automatically when the DOM is ready. No need to call `Vitra.init()`.

---

## JS Module API (Programmatic Control)

### ES Module Import

```javascript
// Import as ES module
import Vitra from './path/to/vitra.js';

// Use the API
Vitra.theme.set('dark');
Vitra.particles.spawn(10);
```

### Global Script Tag

```html
<script src="vitra.js"></script>
<script>
  // Vitra is available as window.Vitra
  const { theme, particles, reveal, modal, tooltip } = window.Vitra;
  
  theme.init({ defaultTheme: 'auto' });
</script>
```

---

## Module Reference

### Theme Module

```javascript
import { theme } from './vitra.js';

// Get current theme
const current = theme.get(); // 'dark', 'light', etc.

// Set theme
theme.set('neon');

// Toggle between themes
theme.toggle('light', 'dark');

// Initialize with options
theme.init({
  defaultTheme: 'auto',
  persist: true
});

// Get effective theme (resolves 'auto')
const effective = theme.getEffective();

// Clear stored preference
theme.clear();

// List valid themes
const themes = theme.getValidThemes();
```

### Particles Module

```javascript
import { particles } from './vitra.js';

// Spawn particles
const spawned = particles.spawn(10, {
  color: 'var(--vitra-color-accent)',
  size: 4,
  emoji: null,        // Or '✨' for emoji particles
  container: 'body'  // CSS selector
});

// Destroy particles
particles.destroy(5);  // Destroy 5, or all if no argument
particles.destroy();    // Destroy all

// Check limits
const limits = particles.limits();
console.log(`Active: ${limits.active}, Available: ${limits.available}`);

// Initialize from data attributes
particles.init();
```

### Reveal Module

```javascript
import { reveal } from './vitra.js';

// Initialize scroll reveal
reveal.init({
  selector: '.vitra-reveal',   // CSS selector
  threshold: 0.1,               // Visibility threshold (0-1)
  stagger: 100,                 // Delay between elements (ms)
  scrollReveal: false           // Also observe .vitra-scroll-reveal* elements
});

// Count revealed elements
const count = reveal.count();

// Reset all (for re-triggering)
reveal.reset();
```

### Modal Module

```javascript
import { modal } from './vitra.js';

// Open modal
modal.open('#my-modal', {
  closeOnOverlay: true,  // Close when clicking overlay
  closeOnEsc: true        // Close on Escape key
});

// Close modal
modal.close();

// HTML structure for modal:
/*
<div id="my-modal" class="vitra-modal-overlay" aria-hidden="true">
  <div class="vitra-modal-content">
    <div class="vitra-modal-header">
      <h2>Modal Title</h2>
      <button data-vitra-modal-close>&times;</button>
    </div>
    <div class="vitra-modal-body">
      Modal content here
    </div>
    <div class="vitra-modal-footer">
      <button class="vitra-btn" data-vitra-modal-close">Close</button>
    </div>
  </div>
</div>
*/
```

### Ripple Module

```javascript
import { ripple } from './vitra.js';

// Initialize click ripple (auto-enabled by default)
ripple.init();

// Add .vitra-ripple to any element to enable
// Click ripple is handled automatically via event delegation
```

### Toast Module

```javascript
import { toast } from './vitra.js';

// Show a toast notification
toast.show('Saved successfully!', {
  type: 'success',  // 'success' | 'error' | 'info' | 'default'
  duration: 3000    // Auto-dismiss after ms (0 = no auto-dismiss)
});

// HTML structure is created automatically — no markup needed.
// CSS classes applied: .vitra-toast, .vitra-toast-success / -error / -info
```

### Dropdown Module

```javascript
import { dropdown } from './vitra.js';

// Initialize (handles click outside, keyboard, Popover API when available)
dropdown.init();
dropdown.destroy();

// HTML structure:
/*
<div class="vitra-dropdown">
  <button data-vitra-dropdown-toggle>Options</button>
  <div class="vitra-dropdown-menu">
    <button class="vitra-dropdown-item">Edit</button>
    <button class="vitra-dropdown-item">Delete</button>
  </div>
</div>

// Right-aligned variant:
<div class="vitra-dropdown-menu vitra-dropdown-menu-end">...</div>

// Popover API (modern browsers) — add popover attribute:
<div class="vitra-dropdown-menu" popover>...</div>
*/
```

### Spotlight Module

```javascript
import { spotlight } from './vitra.js';

// Initialize — tracks mouse position and applies spotlight to .vitra-spotlight elements
spotlight.init();
spotlight.destroy();

// HTML: add .vitra-spotlight to any card or container
/*
<div class="vitra-card vitra-spotlight">
  Content with radial gradient following cursor
</div>
*/
```

### destroyAll

```javascript
// Tear down all modules (removes listeners, resets state)
Vitra.destroyAll();
```

### Tooltip Module

```javascript
import { tooltip } from './vitra.js';

// Show tooltip
tooltip.show('#target-element', 'Tooltip text', {
  position: 'top',  // 'top', 'bottom', 'left', 'right'
  delay: 0          // Delay before show (ms)
});

// Hide tooltip
tooltip.hide('#target-element');
tooltip.hide();  // Hide active tooltip

// Initialize from data attributes
tooltip.init();

// HTML for data-attribute tooltips:
/*
<button data-vitra-tooltip="Click to save" 
        data-vitra-tooltip-position="top">
  Save
</button>
*/
```

---

## Tree-Shaking (Only Import What You Need)

If you're using ES modules and a bundler like esbuild or webpack, you can tree-shake unused modules.

### Method 1: Import Only What You Need

```javascript
// Only import theme module (smallest bundle)
import { theme } from './vitra.js';

theme.init({ defaultTheme: 'auto' });
```

### Method 2: Build with esbuild (Automatic Tree-Shaking)

```bash
# esbuild automatically tree-shakes unused code
npx esbuild src/vitra.js --bundle --outfile=dist/vitra.js --format=esm --tree-shaking=true
```

### Module Sizes (Approximate)

| Module | Size (minified) | Features |
|---------|-------------------|----------|
| `theme` | ~2 KB | Theme toggle, auto-detect, persistence |
| `particles` | ~3 KB | Particle spawn, destroy, limits |
| `reveal` | ~2 KB | Scroll reveal, stagger |
| `ripple` | ~0.5 KB | Click ripple effect |
| `modal` | ~2 KB | Modal open/close, focus trap |
| `tooltip` | ~2 KB | Tooltip show/hide, positioning |
| `toast` | ~1 KB | Toast notifications |
| `dropdown` | ~1 KB | Dropdown menus with Popover API support |
| `spotlight` | ~1 KB | Mouse-tracking radial gradient effect |
| **Full `Vitra`** | ~15 KB | All modules combined |

---

## Data Attributes Reference

Vitra uses data attributes for declaritive configuration without JavaScript.

### Theme

| Attribute | Value | Description |
|-----------|-------|-------------|
| `data-theme` | Theme name | Apply theme to element (inherits to children) |

```html
<html data-theme="dark">
```

### Particles

| Attribute | Value | Description |
|-----------|-------|-------------|
| `data-vitra-particles` | Count | Number of particles to spawn |
| `data-vitra-particle-color` | Color | Particle color |
| `data-vitra-particle-emoji` | Emoji | Use emoji instead of dots |

```html
<div data-vitra-particles="10" data-vitra-particle-color="#ff6b6b"></div>
<div data-vitra-particles="5" data-vitra-particle-emoji="✨"></div>
```

### Tooltips

| Attribute | Value | Description |
|-----------|-------|-------------|
| `data-vitra-tooltip` | Text | Tooltip text content |
| `data-vitra-tooltip-position` | Position | 'top', 'bottom', 'left', 'right' |
| `data-vitra-tooltip-delay` | Ms | Delay before show (e.g., "100") |

```html
<button data-vitra-tooltip="Save changes" data-vitra-tooltip-position="top">
  Save
</button>
```

### Modal

| Attribute | Value | Description |
|-----------|-------|-------------|
| `data-vitra-modal-close` | (none) | Close button inside modal |

```html
<button data-vitra-modal-close>Close</button>
```

---

## Integration Examples

### Example 1: Simple Landing Page (No Build)

```html
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <link rel="stylesheet" href="vitra.css">
</head>
<body>
  <div class="vitra-container vitra-mt-5">
    <h1 class="vitra-text-4xl vitra-text-center">Welcome to My Site</h1>
    <div class="vitra-flex vitra-justify-center vitra-mt-4">
      <button class="vitra-btn vitra-btn-glass">Get Started</button>
    </div>
  </div>
  
  <script src="vitra.js"></script>
  <script>
    Vitra.theme.init({ defaultTheme: 'auto' });
  </script>
</body>
</html>
```

### Example 2: SPA with ES Modules

```javascript
// main.js
import Vitra from './vitra.js';

// Initialize everything
Vitra.theme.init({ defaultTheme: 'auto' });
Vitra.reveal.init();
Vitra.tooltip.init();

// Dynamic theme toggle
document.getElementById('theme-toggle').addEventListener('click', () => {
  Vitra.theme.toggle('light', 'dark');
});

// Spawn particles on an event
document.getElementById('party-btn').addEventListener('click', () => {
  Vitra.particles.spawn(20, { emoji: '🎉' });
});
```

### Example 3: Static Site with data-config

```html
<!-- No JavaScript code needed! -->
<div data-config='{
  "theme": { "init": true, "options": { "defaultTheme": "auto" } },
  "reveal": { "init": true }
}'>
  <div class="vitra-container">
    <div class="vitra-reveal vitra-reveal-up">
      <h2>Section 1</h2>
      <p>This fades in on scroll.</p>
    </div>
    <div class="vitra-reveal vitra-reveal-up vitra-delay-200">
      <h2>Section 2</h2>
      <p>This appears after a delay.</p>
    </div>
  </div>
  
  <script src="vitra.js"></script>
</div>
```

---

## Build Optimization Tips

### 1. Only Load What You Need

```html
<!-- If you only need CSS, skip the JS -->
<link rel="stylesheet" href="vitra.css">

<!-- If you need only theme toggle, use a custom build -->
<!-- (Advanced: modify vitra.js to export only theme module) -->
```

### 2. Minify for Production

```bash
# Minify CSS with lightningcss
npx lightningcss vitra.css --minify --output vitra.min.css

# Minify JS with esbuild
npx esbuild vitra.js --bundle --minify --outfile=vitra.min.js
```

### 3. Use CDN for Hosted Version (Future)

```html
<!-- Example if hosted on CDN -->
<link rel="stylesheet" href="https://cdn.example.com/vitra/1.0.0/vitra.min.css">
<script src="https://cdn.example.com/vitra/1.0.0/vitra.min.js"></script>
```

---

## Troubleshooting

### Vitra is not defined (JS)

- Ensure `vitra.js` is loaded before calling `Vitra.*` methods
- Check that the script tag is not `type="module"` without proper import
- For ES modules: use `import Vitra from './vitra.js'`

### Theme not applying

- Check that `data-theme` is set on `<html>` or a parent container
- Verify the theme name is valid (see `Vitra.theme.getValidThemes()`)
- Ensure `00-themes.css` is included in your CSS

### Particles not showing

- Check browser console for errors
- Verify `prefers-reduced-motion` is not enabled (particles skip if enabled)
- Check particle limits: `Vitra.particles.limits()`

### data-config not working

- Ensure the JSON is valid (no trailing commas)
- Check browser console for parse errors
- Verify `vitra.js` is loaded (data-config is processed on DOMContentLoaded)

---

## Migration Guide

### From v1.x to v2.x (Example)

```javascript
// Old API (v1.x)
Vitra.setTheme('dark');

// New API (v2.x)
Vitra.theme.set('dark');
```

---

**Related Documentation:**
- [README.md](../README.md) - Quick start guide
- [docs/themes.md](themes.md) - Theme reference
- [docs/compatibility.md](compatibility.md) - Browser support
