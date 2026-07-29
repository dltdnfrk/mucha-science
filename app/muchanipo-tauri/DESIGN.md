# Mucha Science Design System

## 0. Reference contract

- Primary reference: the user-supplied ChatGPT/Codex desktop-app screenshot captured on 2026-07-28.
- Product direction: a desktop web research assistant whose primary surface is a conversation. Research stages, provider activity, citations, quality gates, and artifacts appear as compact event logs or optional side output rather than as the page architecture.
- Execution reference: `redesign-skill.md` for a focused retrofit of the existing React UI. The Vercel reference contributes restrained monochrome surfaces, three-weight typography, and precise focus treatment; the supplied ChatGPT/Codex screenshot remains the visual source of truth.
- Scope: laptop/desktop web at 1280px and 1440px wide. Mobile layouts and Tauri-native presentation are not product requirements.
- Fidelity boundary: reproduce layout density, hierarchy, spacing, and interaction patterns without copying OpenAI logos, proprietary icons, or branded assets.

## 1. Atmosphere & identity

Mucha Science feels like a quiet AI workbench. The interface recedes so the research conversation, evidence, and decisions remain primary. It should be immediately familiar to a ChatGPT/Codex user:

`conversation list → transcript → composer`

An optional output tray may expose sources, artifacts, and validation. The research cycle is not a navigation model. It is a trace inside each assistant turn.

The interface is:

- conversational, compact, and desktop-native;
- neutral and low-contrast until an action, warning, or focus state needs emphasis;
- transparent about work through readable event rows and elapsed time;
- fail-closed when evidence quality is insufficient.

The interface is not:

- a three-column analytics dashboard;
- a paper manuscript, scientific folio, or marketing hero;
- a wizard exposing six research stages as primary navigation;
- a grid of nested cards and technical badges.

## 2. Color

### Desktop dark palette

| Role | Token | Value | Usage |
|---|---|---:|---|
| Canvas | `--ms-canvas` | `#171717` | Main application background |
| Transcript | `--ms-paper` | `#1e1e1e` | Conversation surface |
| Raised surface | `--ms-paper-raised` | `#2b2b2b` | Composer, selected rows, controls |
| Sidebar | `--ms-rail-surface` | `#202020` | Conversation rail |
| Output tray | `--ms-output-surface` | `#2a2a2a` | Optional research output |
| Hover | `--ms-surface-hover` | `#292929` | Hovered rows and controls |
| Active | `--ms-surface-active` | `#303030` | Current conversation and pressed tools |
| Primary text | `--ms-ink` | `#ececec` | Headings and important values |
| Secondary text | `--ms-graphite` | `#c8c8c8` | Transcript and descriptions |
| Muted text | `--ms-annotation` | `#909090` | Metadata, helper copy, inactive icons |
| Divider | `--ms-rule-quiet` | `#333333` | App structure |
| Control boundary | `--ms-control-boundary` | `#4a4a4a` | Input and disclosure boundaries |
| Focus/accent | `--ms-blue` | `#8f82ff` | Focus, links, current activity only |
| Accent hover | `--ms-blue-hover` | `#a59aff` | Hovered links |
| Accent wash | `--ms-blue-wash` | `#302d43` | Selected accented state |
| Error | `--ms-error` | `#ff9b93` | Error text |
| Error wash | `--ms-error-wash` | `#3a211f` | Error background |
| Success | `--ms-success` | `#72c894` | Confirmed source or quality outcome |
| Warning | `--ms-warning` | `#e2b866` | Review-required quality outcome |

### Rules

- Neutral grays carry the UI. Purple is functional and sparse.
- Status always includes readable text; color is never the only signal.
- No decorative gradients, glow, glassmorphism, or multi-accent status rainbow.
- New workspace CSS uses declared tokens. Raw colors are limited to token declarations.

## 3. Typography

The workspace uses the operating system UI font so Korean and Latin text feel native beside ChatGPT/Codex.

| Role | Token | Size / line-height | Weight | Usage |
|---|---|---:|---:|---|
| Empty-state heading | `--ms-type-empty` | `1.5rem / 1.25` | 600 | One restrained prompt |
| Section heading | `--ms-type-section` | `1rem / 1.4` | 600 | Output sections |
| Transcript | `--ms-type-body-large` | `0.9375rem / 1.65` | 400 | Assistant answer |
| UI body | `--ms-type-body` | `0.875rem / 1.5` | 400 | Navigation and controls |
| UI emphasis | — | `0.875rem / 1.5` | 500–600 | Active rows and labels |
| Support | `--ms-type-support` | `0.8125rem / 1.45` | 400–500 | Secondary control copy |
| Metadata | `--ms-type-meta` | `0.75rem / 1.4` | 400–500 | Runtime and event counts |

- UI stack: `-apple-system`, `BlinkMacSystemFont`, `"SF Pro Text"`, `"Apple SD Gothic Neo"`, `"Noto Sans KR"`, `system-ui`, `sans-serif`.
- Use only 400, 500, and 600 for product UI.
- Headings use slight negative tracking (`-0.01em` to `-0.02em`); body and UI labels use normal tracking.
- Transcript measure is `58–72ch`; event metadata stays short and single-line when space permits.
- Monospace is reserved for machine identifiers or code, not for decorative uppercase labels.

## 4. Spacing & layout

### Spacing scale

All spacing follows a 4px base:

| Token | Value |
|---|---:|
| `--ms-space-1` | `0.25rem` |
| `--ms-space-2` | `0.5rem` |
| `--ms-space-3` | `0.75rem` |
| `--ms-space-4` | `1rem` |
| `--ms-space-5` | `1.25rem` |
| `--ms-space-6` | `1.5rem` |
| `--ms-space-8` | `2rem` |
| `--ms-space-10` | `2.5rem` |

### Desktop shell

- Left rail: `clamp(14.5rem, 18vw, 16.5rem)`.
- Compact rail: `3.25rem`.
- App header: `3.25rem`.
- Output tray: `clamp(18rem, 21vw, 20rem)` with a 12px outer inset.
- Transcript and composer: maximum `48rem`, centered in the remaining workspace.
- Transcript owns vertical scrolling. The rail and output tray own independent scrolling only for their lists.
- At the supported 1280px minimum, the conversation remains primary; secondary copy may truncate before transcript width is reduced below a readable measure.

## 5. Components

### Conversation rail

- Compact brand row, 36–40px actions, and 36–44px history rows.
- Current conversation uses a quiet tonal fill, not a colored stripe.
- Conversation initials are 24px neutral circles; previews truncate to one line.
- Source and validation links remain at the bottom as research utilities.

### Workspace header

- 52px high with the active conversation title on the left.
- Runtime is small muted supporting text.
- Source, validation, and output controls are 36px targets with visible labels only where useful.
- A single hairline separates header from transcript.

### Transcript

- User messages align right in a compact neutral bubble.
- Assistant answers are open text, not cards.
- A research turn is `user message → work disclosure → assistant answer`.
- Adjacent turns use whitespace and one quiet divider.

### Work disclosure

- Summary language leads with elapsed time: `1분 42초 동안 작업했습니다`.
- Counts such as logs, sources, and artifacts are muted metadata.
- The closed state is a flat event row; opening reveals grouped provider, route, evidence, claim, counter-search, and quality records.
- Nested validation detail is collapsed by default.

### Composer

- Centered floating surface with 24px radius and subtle ambient shadow.
- Placeholder is the primary affordance; the visible label remains available to assistive technology.
- Text area starts as one comfortable line and grows within a bounded height.
- Circular send/stop action is 32px. Runtime and source readiness appear as quiet helper text.

### Output tray

- Optional, inset, and rounded like the Codex output tray.
- Header remains compact; content uses sections separated by hairlines.
- It summarizes the current turn and hosts source/validation settings without becoming the main page.

## 6. Motion & interaction

| Type | Duration | Usage |
|---|---:|---|
| Press | `100ms` | 1px translation or `scale(0.98)` |
| Hover/focus | `140ms` | Surface and text changes |
| Disclosure | `180ms` | Opacity/transform only |
| Follow latest turn | `220ms` | Smooth scroll while the user remains near the end |

- `prefers-reduced-motion: reduce` disables non-essential transitions and smooth scrolling.
- Keyboard and pointer interactions expose equivalent states.
- Escape closes an open disclosure first, then the output tray.

## 7. Depth & surface

Strategy: tonal separation plus hairlines, with shadows reserved for floating surfaces.

| Level | Treatment | Usage |
|---|---|---|
| 0 | Solid canvas | Transcript and rail |
| 1 | Tonal shift | Selected rows and work disclosures |
| 2 | 1px boundary | Controls and output tray |
| 3 | Soft dark ambient shadow | Composer and output tray only |

- Avoid nested cards. Group with alignment, whitespace, and dividers first.
- Control radius: 8px; row radius: 10px; message bubble: 18px; composer: 24px; output tray: 18px.

## 8. Accessibility constraints & accepted scope

### Constraints

- WCAG 2.2 AA contrast for text and controls.
- Every interactive element is keyboard reachable with a visible 2px focus ring.
- Desktop controls are at least 32px and spaced to avoid accidental activation.
- Dynamic research state is announced without repeating every streamed token.
- Progress, quality, and failure states never depend on color alone.
- The transcript supports 200% zoom at the supported desktop widths without horizontal page scrolling.
- Reduced-motion and forced-colors preferences are respected.

### Accepted scope

| Item | Decision |
|---|---|
| Mobile and tablet layouts | Not a product requirement; no mobile visual QA or mobile-specific redesign is performed. |
| Native Tauri presentation | Not a product requirement; the browser web app is authoritative. |
| OpenAI proprietary assets | Not copied; familiarity comes from layout, density, and interaction patterns. |
