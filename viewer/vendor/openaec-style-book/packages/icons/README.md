# @openaec/icons

OpenAEC-iconen. Bron: [`design/icons/`](../../design/icons/) — voeg daar iconen toe,
niet hier. `src/generated/` wordt gemaakt door `npm run generate`.

```tsx
import { Icon, editUndo } from "@openaec/icons";

<Icon svg={editUndo} size={20} title="Ongedaan maken" />
```

Iconen zijn `currentColor`: ze nemen de tekstkleur van hun omgeving over.
Dynamisch op id opzoeken (bijv. vanuit een ribbon-definitie) kan via
`import { iconsById } from "@openaec/icons/by-id"`; dat laadt wel alle iconen.

## Licenties

De OpenAEC-eigen iconen vallen onder de licentie van dit package. De iconen met
`source = "lucide"` in `design/icons/icons.toml` (de UI-basisset in het domein `ui/`)
komen uit [Lucide](https://lucide.dev) en vallen onder de ISC-licentie, deels MIT
via Feather; zie `LICENSE-lucide.txt`.
