# Himaya dashboard

The parent dashboard: React 19, TypeScript, Vite. A production build is written straight into `../hub/static`, which is where the hub serves it from, so the hub works without Node installed.

```bash
npm install
npm run dev        # http://localhost:5173, proxies the hub on :8000 (HIMAYA_HUB_URL to change)
npm test           # unit tests (vitest): status sentence, event wording, grouping, rules, domains
npm run lint       # oxlint
npm run build      # type-check + build into ../hub/static
```

Structure:

```
src/lib/        api.ts (typed client), store.tsx (live state), describe.ts (plain-language logic), rules.ts, domain.ts
src/components/ shell, rows, timeline, dialogs, tag input, chart
src/views/      Login, Home, Devices, DeviceDetail, RulesEditor, Activity, Screens, Enroll, Settings
src/styles/     tokens.css (themes), base.css, app.css
public/         icons, manifest, theme-init.js
```

Design notes are in [../docs/DESIGN.md](../docs/DESIGN.md). The logic that decides what the screen says (`describe.ts`, `rules.ts`, `domain.ts`) has no React in it and is covered by the unit tests; `domain.ts` mirrors the hub's domain normalisation so the form accepts exactly what the hub accepts.

Keep the CSP in mind: the hub forbids inline scripts, so do not add any to `index.html`.
