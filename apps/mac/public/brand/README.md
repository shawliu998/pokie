# Qurio brand assets

Qurio is the current product and UI brand. This directory is the only canonical source for product-facing logo and wordmark assets.

## Canonical assets

| Asset | Use |
|---|---|
| `qurio-icon-color.svg` | Product icon, favicon, and source for generated application icons |
| `qurio-wordmark.svg` | Navy wordmark for light backgrounds |
| `qurio-wordmark-inverse.svg` | Light wordmark for the dark Qurio product shell |

The two wordmark files share identical vector geometry. They differ only in the primary letter color. The blue accent is `#0059FE`.

## Rules

- Use only the files listed above for new product UI, documentation, screenshots, packaging, and marketing exports.
- Do not recreate the wordmark with a font or substitute another Q shape.
- Do not use PNG wordmarks as a source of truth.
- Do not add PokieQuant-named logo or wordmark files to a product-facing directory. PokieQuant is retained only as a repository and implementation-history name.
- Generated Tauri assets live in `apps/mac/src-tauri/icons`; their editable source is `qurio-icon-color.svg`, with `qurio-source.png` retained as the raster packaging source.
