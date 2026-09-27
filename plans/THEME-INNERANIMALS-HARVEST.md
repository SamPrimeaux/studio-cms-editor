# Inner Animals Theme / Layout Harvest

## Goal

Turn the useful visual/layout language in this donor into a reusable theme/preset candidate without making the donor repo or its content the runtime authority.

Potential destination:

`packages/theme-inneranimals-site`

Potential gallery destination:

`apps/theme-gallery-preview/themes/inneranimals-site`

## Preserve

Preserve source-level evidence for:

- section ordering
- navigation patterns
- hero treatment
- typography hierarchy
- spacing rhythm
- palette/token choices
- footer patterns
- content widths
- responsive behavior
- section visibility
- section-specific styling
- page metadata patterns
- reusable component/template ideas

The harvest export intentionally copies the original editor source and CSS intact so no layout behavior is lost before normalization.

## Normalize later

The real theme implementation should separate:

### Theme contract

- tokens
- typography
- colors
- radii
- spacing
- motion defaults
- container rules
- section presets

### Content bindings

- nav links
- hero eyebrow/title/body
- CTAs
- logo/client names
- services
- projects
- testimonials
- contact CTA
- footer links

### CMS blocks

If the old source is not truly block-oriented, do not fake it during harvest.

Normalize during implementation into explicit blocks such as:

- navigation
- hero
- logo cloud
- feature/service grid
- gallery
- testimonial
- CTA
- footer

## Content rule

Historical Inner Animal Media copy may be useful for a live historical preview, but should not silently become generic scaffold copy for unrelated customer sites.

The reusable package should distinguish:

- design/layout preset,
- sample/demo content,
- customer content.

## Side-effect rule

Installing or previewing the theme must not:

- publish it,
- sync it,
- upload assets,
- overwrite an active customer theme,
- change a CMS publication.

A future theme command should keep these steps distinct:

```
inspect
preview
install/stage
apply
sync
publish
```

Only the explicitly invoked mutating step may alter its declared target.

## Gallery value

Keep the historical donor as a real showcase example.

A future gallery entry should communicate:

- historical source/provenance
- available pages/surfaces
- whether the item is previewable
- whether it is installable
- whether it has been normalized into CMS blocks
- which capabilities are real versus visual/demo-only

This lets AgentSam advertise real prior systems without misrepresenting prototype behavior as production capability.
