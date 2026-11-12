---
name: frontend-design
description: Design distinctive, purposeful, accessible frontends grounded in the product's audience, subject, and real data.
---

# Frontend design

Treat each interface as a designed product, not a reskinned template. Before implementation, identify the audience and the main job the screen should help them complete. If that is unclear, ask the product owner before choosing a direction.

## Plan before building

Write a short design proposal containing:

- A named palette of four to six colors, with roles for surfaces, text, emphasis, and status.
- One or two type families and their roles, selected for the product rather than habit.
- A one-sentence layout concept and a small ASCII sketch for each important view.
- A few principles that explain how the subject matter shapes the interface.

Review the proposal against the brief. Replace choices that could fit any generic dashboard or landing page with choices tied to this product's audience and content. Keep one memorable visual idea and make the rest support it.

## Design and implementation

- Make hierarchy and alignment serve the user's task. Use labels, dividers, and numbering only when they convey real meaning.
- Prefer concise, concrete, active copy. Empty and error states should explain what happened and what the user can do next.
- Use real API data for findings, status, counts, and progress. Distinguish observed evidence from interpretation; never invent activity or certainty.
- Follow the existing framework, component patterns, and local asset conventions. Avoid unnecessary dependencies and decorative gradients, badges, cards, and animations.
- Keep keyboard focus visible, contrast readable, layouts responsive, and motion respectful of `prefers-reduced-motion`.
- Use semantic HTML and accessible names. Render untrusted data as text; do not inject it as markup.

## Review

Build the smallest relevant target and exercise the core interaction with representative local or mocked data. When browser tooling is available, inspect the initial and result states at desktop and mobile widths. Remove visual elements that do not improve orientation, comprehension, or action.
