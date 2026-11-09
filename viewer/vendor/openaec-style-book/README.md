# OpenAEC-stijlbook (overgenomen)

Deze map bevat de pakketten `@openaec/design-tokens`, `@openaec/shell`, `@openaec/icons` en `@openaec/i18n` (0.1.0)
uit [OpenAEC-style-book](https://github.com/OpenAEC-Foundation/OpenAEC-style-book), commit `1e21b1b`, met de gebouwde
`packages/tokens/dist/`, en `themes/themes.css` uit `project-templates/Tauri+React/src/` (de `--theme-*`-variabelen die
`@openaec/shell` gebruikt), en het symbool `logos/openaec-symbol-transparent.svg` als favicon tot de app een eigen
pictogram in `design/apps.toml` heeft. Ze staan nog niet op npm; de viewer verwijst ernaar met `file:`-paden.

Niet hier aanpassen: wijzigingen horen in het stijlbook. Zodra de pakketten gepubliceerd zijn, vervangen we deze map
door gewone afhankelijkheden (`npm install @openaec/design-tokens@0.1.0 …`).

Licenties: zie `LICENSE` van het stijlbook, `packages/tokens/package.json` (MIT) en `packages/icons/LICENSE-lucide.txt`.
