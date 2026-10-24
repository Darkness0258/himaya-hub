# Dashboard design notes

**Purpose.** A parent checks, in a few seconds and often from a phone, whether the family's devices are okay, and can act in one tap.

**Tone.** Calm and trustworthy, not a security cockpit. A night-lapis dark theme with gold and a quiet star pattern; a matching light theme. Plain sentences instead of metrics: the Home screen opens with "Everything looks good." or "2 things need a look." and the detail line explains it.

**The mark.** The eight-point star (khatam) in gold on lapis. It is drawn from one function in `dashboard/src/components/Brand.tsx` and the same geometry builds the favicon, the app icons and the Android icon, so they always match.

## Type

| Use | Face | Why |
| --- | --- | --- |
| Headlines, section titles | Fraunces (variable) | A warm serif with character, used only where the page speaks in sentences |
| Interface | Figtree (variable) | Friendly and legible at small sizes |
| PIN, commands | The system monospace | Codes need fixed-width digits |

Both fonts are bundled with the app (`@fontsource-variable`), so the dashboard works offline and nothing is requested from a font CDN.

## Colour

Defined once in `dashboard/src/styles/tokens.css`. Status colours are never the only signal: every state also has a word, an icon or a shape.

All text and control colours were measured for WCAG contrast in both themes. Every pair used for text meets AA (4.5:1; the large PIN needs 3:1):

| Pair | Dark | Light |
| --- | --- | --- |
| Body text on page | 16.2 | 15.6 |
| Body text on panel | 14.7 | 17.1 |
| Secondary text on panel | 8.9 | 8.3 |
| Muted text on panel | 6.1 | 5.8 |
| Muted text on raised surface | 4.8 | 5.1 |
| Link / brand colour on panel | 7.2 | 6.4 |
| Button label on brand colour | 8.0 | 6.4 |
| Status colours on their tinted chip | 5.8 to 7.4 | 4.6 to 5.2 |
| Gold wordmark on the side rail | 11.5 | 5.4 |
| Gold PIN on panel (large text) | 10.1 | 6.4 |
| Alert badge text on red | 8.4 | 5.8 |

(The contrast check caught two light-theme failures, now fixed: the red alert badge and the small gold wordmark.)

## Layout and behaviour

* Left rail on desktop, bottom tab bar on phones. Device rows carry a coloured state edge; the timeline is a vertical rail because it really is a sequence.
* Runs of blocked-site events collapse into one row so a VPN alert is never buried.
* Dialogs use the native `<dialog>` element (focus trap, Escape, focus return). The lightbox is rendered in a portal so it covers the whole viewport.
* `prefers-reduced-motion` turns animation off. Touch targets are at least 44 px on phones.
* The Content Security Policy forbids inline scripts, so the theme is set by `public/theme-init.js` before first paint.

## Checks run on the built dashboard

Headless Chromium at 1440x900 and 390x844 (touch, 2x), both themes, with the strict CSP on. Checked: no console errors, no failed requests, no horizontal overflow on any phone page, no truncated device names on the phone Home screen. Flows driven: sign in, wrong key, adding a blocked site, an invalid site, saving rules, lock and unlock, sending a message, the erase confirmation (button disabled until the name is typed), the screenshot lightbox (closed with Escape), expanding a collapsed timeline group, and switching theme.

Not covered by an automated check: screen-reader behaviour and keyboard-only navigation. The markup uses real buttons, links, labels, a skip link, `aria-pressed` / `aria-checked` states and a text summary for the chart, but it has not been tested with assistive technology.
