# @openaec/i18n

Gedeelde OpenAEC-termen in het Nederlands en Engels. Bron:
[`design/i18n/`](../../design/i18n/); `src/generated/` wordt gemaakt door
`npm run generate`.

```ts
import i18next from "i18next";
import { openaecResources } from "@openaec/i18n";

i18next.init({ resources: openaecResources, ns: ["openaec", "app"] });
i18next.t("openaec:action.copy"); // "Kopiëren"
```
