# Mucha Science Browser UI Design System

## Product surface

The browser is the authoritative Mucha Science product surface. It is a
conversation-first local research workspace: research activity, source
decisions, provider state, quality gates, and artifacts support the active
conversation rather than becoming separate product modes.

## Visual language

- Dark, low-contrast graphite surfaces with restrained white borders.
- One high-contrast action per view; supporting controls remain compact.
- Clear three-level typography: white headings, muted secondary copy, subtle
  metadata.
- Compact rail navigation for conversations and research utilities.
- Keyboard focus states must remain visible on every interactive control.

## Execution settings

Provider, model, and research-effort controls are product-critical settings:

- They must be reachable from the scientific workspace without a hidden URL.
- API credentials are session-only and never presented as persisted.
- Provider/model preferences and research effort persist locally.
- “Research effort” means pipeline research depth, not an unsupported generic
  model-reasoning parameter.
- Offline/demo execution is not offered as a normal browser workflow.

## Browser constraints

- Support the existing desktop research workspace at 1280px and 1440px.
- Do not introduce Tauri-specific UI behavior or platform-only navigation.
- Use semantic buttons, links, labels, and visible accessible names.
