# Vitra CSS Framework

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)](https://github.com/DesvoSoft/Vitra)
[![Version](https://img.shields.io/badge/version-1.7.1-blue)](https://github.com/DesvoSoft/Vitra)
[![License](https://img.shields.io/badge/license-ISC-blue)](https://github.com/DesvoSoft/Vitra)
[![Bundle Size](https://img.shields.io/badge/css-10.8%20KB%20brotlied-brightgreen)](https://github.com/DesvoSoft/Vitra)
[![Tests](https://img.shields.io/badge/tests-60%20passing-brightgreen)](https://github.com/DesvoSoft/Vitra)

Vitra is a high-performance, premium CSS framework engineered for modern web applications. It specializes in Glassmorphism, Motion Design, Interactive Particles, and Cinematic Visual Effects, providing a sophisticated aesthetic out of the box with zero external dependencies.

---

## Why Vitra?

Unlike generic utility-first frameworks, Vitra is built with a specific aesthetic philosophy: **Depth, Motion, and Life**. It eliminates CSS boilerplate while enforcing a strict, maintainable architecture.

-   **Glass-First Design**: Optimized backdrop-filter effects with robust `@supports` fallbacks for all browsers.
-   **Strict @layer Architecture**: Predictable cascade management using modern CSS layers.
-   **Motion Engine**: 25+ choreographed keyframes that automatically respect `prefers-reduced-motion`.
-   **Particle System**: Native CSS/JS hybrid particles with built-in performance limits (15 mobile / 40 desktop).
-   **Cinematic Effects**: Animated mesh gradients, floating glow orbs, gradient text, spinning border glows, page-enter animation, 3D tilt cards, aurora background, text reveal, stagger system.
-   **Shader Effects**: Pure-CSS shader effects — noise overlay, shape morphing, progress rings, gradient rotate borders, scroll-driven reveals, material ripple.
-   **Modern CSS Features**: Container Queries, `@starting-style`, Popover API — all with fallbacks.
-   **Premium Color System**: All surfaces tinted with accent hue — no pure neutral grays. Warm/cool/oklch variants.
-   **Smart Theming**: 7 themes (light, dark, auto, pastel, neon, ocean, emerald) with system-level sync.

---

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/DesvoSoft/Vitra.git
cd Vitra

# Install dependencies and build
npm install
npm run build
```

### 2. Basic Setup

You can use Vitra by installing it locally, or via a free CDN (jsDelivr) for instant global delivery.

#### Option A: Via CDN (Recommended for production)

Use jsDelivr to load the minified files. We strongly recommend using a fixed version and including Subresource Integrity (SRI) hashes to guarantee security and stability.

```html
<!-- High-performance CSS (Fixed version with SRI) -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/DesvoSoft/Vitra@v1.7.2/dist/vitra.min.css" integrity="sha256-..." crossorigin="anonymous">

<!-- Optional: Modular JS Engine (Fixed version with SRI) -->
<script src="https://cdn.jsdelivr.net/gh/DesvoSoft/Vitra@v1.7.2/dist/vitra.min.js" integrity="sha256-..." crossorigin="anonymous" defer></script>
```

> **Note:** Always use a pinned version (e.g., `@v1.7.2`) for production. The SRI hashes are generated during build and stored in `dist/SRI.txt`.

#### Option B: Local Assets

```html
<!-- High-performance CSS -->
<link rel="stylesheet" href="dist/vitra.min.css">

<!-- Optional: Modular JS Engine -->
<script src="dist/vitra.min.js" defer></script>
```

---

## Architecture

Vitra uses a strict @layer cascade to prevent specificity leaks and ensure consistent styling across large projects.

1.  tokens: Immutable design primitives (colors, spacing, shadows).
2.  glass: The core glassmorphism engine.
3.  particles: Background effects and glow systems.
4.  layout: Structural utilities (Flex, Grid, Container).
5.  motion: Animation engine and reveal logic.
6.  components: Premium UI elements (Buttons, Cards, Forms).
7.  utilities: High-precedence helper classes.

---

## Themes & Glassmorphism

Vitra supports three core theme modes: light, dark, and auto. It also includes several premium variants: Pastel, Neon, Ocean, and Emerald.

```html
<!-- Apply a theme -->
<html data-theme="dark">

<!-- Apply the signature Glass effect -->
<div class="vitra-glass vitra-glass-md">
  <h2>Premium Content</h2>
  <p>Seamlessly integrated with backdrop-filter.</p>
</div>
```

---

## JS API

The Vitra JS API is modular and declarative. You can configure it via data-config on the script tag or use the global Vitra object.

### Theme Control
```javascript
Vitra.theme.set('neon');          // Switch to neon theme
Vitra.theme.toggle();             // Flip between light/dark
Vitra.theme.getEffective();       // Resolve 'auto' to actual theme
```

### Particle Engine
```javascript
Vitra.particles.spawn(15, {
  color: 'var(--vitra-color-accent)',
  size: 5,
  container: '#hero-section'
});
```

### Cinematic Effects (CSS-only, no JS needed)
```html
<!-- Animated mesh gradient background -->
<div class="vitra-gradient-bg"></div>

<!-- Floating glow orbs -->
<div class="vitra-glow-orb vitra-glow-orb-1"></div>
<div class="vitra-glow-orb vitra-glow-orb-2"></div>

<!-- Animated gradient text -->
<h1 class="vitra-gradient-text">Premium Heading</h1>

<!-- Spinning border glow -->
<div class="vitra-border-glow">
  <div class="vitra-card">Content</div>
</div>
```

---

## Project Structure

```text
Vitra/
├── src/
│   ├── 00-themes.css      # 7 themes (light, dark, auto, pastel, neon, ocean, emerald)
│   ├── 01-tokens.css      # Foundation tokens (colors, spacing, typography, shadows)
│   ├── 02-glass.css       # Glassmorphism engine with @supports fallbacks
│   ├── 03-particles.css   # Particle systems with device-aware limits
│   ├── 04-motion.css      # Motion engine + cinematic effects (gradient, glow, border, stagger, tilt, aurora, reveal)
│   ├── 05-layout.css      # Grid, container, hero, flex, responsive utilities
│   ├── 06-components.css  # 17 component systems (buttons, cards, modals, tables, etc.)
│   ├── 07-utilities.css   # Spacing, display, width/height, z-index, responsive variants
│   └── vitra.js           # 9 modules: theme, particles, reveal, ripple, modal, tooltip, toast, dropdown, spotlight
├── dist/                  # Production builds + source maps + SRI hashes
├── docs/                  # Theming, integration, compatibility, audit
└── tests/                 # 60 vitest tests
```

---

## Modern CSS Features

Vitra leverages cutting-edge CSS for progressive enhancement:

| Feature | Usage | Browser Support |
|---------|-------|-----------------|
| **`@layer`** | Cascade ordering (tokens < components < utilities) | Chrome 88+, FF 97+, Safari 15.4+ |
| **`@container`** | Responsive table card layout | Chrome 105+, FF 110+, Safari 16+ |
| **`@starting-style`** | Entry animations for modals, toasts, dropdowns | Chrome 117+, FF 128+, Safari 17.4+ |
| **`popover` API** | Native dropdown with JS fallback | Chrome 114+, FF 125+, Safari 17.4+ |
| **`:has()`** | Parent-aware component states | All modern browsers |
| **`clamp()`** | Fluid spacing and typography | Chrome 79+, FF 75+ |
| **`oklch()`** | Premium color space alternative | Chrome 111+, FF 113+, Safari 15.4+ |

---

## Accessibility & Performance

-   **Reduced Motion**: All transitions and animations auto-disable if `prefers-reduced-motion` is detected. Supported at CSS (`0.01ms !important`) and JS levels.
-   **Resource Safety**: Particle counts capped (15 mobile, 40 desktop) for 60fps on all devices.
-   **Screen Reader Support**: `aria-live` announcer on theme changes, `aria-describedby` on tooltips, `role="dialog"` + `aria-modal` on modals, `.vitra-sr-only` utilities.
-   **Bundle Size**: CSS ~100 KB minified (~10.8 KB brotlied), JS ~14.1 KB minified (~4.2 KB brotlied). Monitored via `size-limit`.

---

## Documentation

| Document | Description |
|----------|-------------|
| [Theming Guide](docs/themes.md) | Theme reference, customization, persistence |
| [Integration & API](docs/integration.md) | CDN, JS API, data-config, tree-shaking |
| [Browser Compatibility](docs/compatibility.md) | Support matrix, fallback strategies |
| [Audit & Roadmap](docs/AUDIT-2026.md) | Full codebase audit, gaps, future plans |

---

Developed and maintained by DesvoSoft.  
Released under the ISC License.
