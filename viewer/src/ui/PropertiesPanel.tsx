import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { BimHost, ElementProperties } from "../host/BimHost";
import type { Selection } from "../model/selection";
import { describe, formatValue } from "./format";

type State =
  | { status: "leeg" }
  | { status: "laden" }
  | { status: "geen" }
  | { status: "fout"; melding: string }
  | { status: "klaar"; element: ElementProperties; storey: string | null };

/** The properties of the selected element, from the property index of its model version. */
export function PropertiesPanel({ host, selection }: { host: BimHost; selection: Selection | null }) {
  const { t } = useTranslation();
  const [state, setState] = useState<State>({ status: "leeg" });

  useEffect(() => {
    if (!selection) {
      setState({ status: "leeg" });
      return;
    }
    let cancelled = false;
    setState({ status: "laden" });
    (async () => {
      const found = await host.eigenschappen(selection.bron, [selection.globalid]);
      const element = found[selection.globalid];
      let storey: string | null = null;
      if (element?.verdieping && element.verdieping !== selection.globalid) {
        const storeys = await host.eigenschappen(selection.bron, [element.verdieping]);
        storey = storeys[element.verdieping]?.naam ?? element.verdieping;
      }
      if (!cancelled) setState(element ? { status: "klaar", element, storey } : { status: "geen" });
    })().catch((error: unknown) => {
      if (!cancelled) setState({ status: "fout", melding: describe(error) });
    });
    return () => {
      cancelled = true;
    };
  }, [host, selection]);

  return (
    <aside className="inspector" aria-label={t("eigenschappen")}>
      <div className="oa-sidebar__header">
        <span className="oa-sidebar__section-label">{t("eigenschappen")}</span>
      </div>
      {state.status === "leeg" && <p className="viewer__hint">{t("selecteer")}</p>}
      {state.status === "laden" && <p className="viewer__hint">{t("laden")}</p>}
      {state.status === "geen" && <p className="viewer__hint">{t("geen_eigenschappen")}</p>}
      {state.status === "fout" && <p className="viewer__error">{t("eigenschappen_fout", { melding: state.melding })}</p>}
      {state.status === "klaar" && selection && (
        <Properties element={state.element} storey={state.storey} globalid={selection.globalid} />
      )}
    </aside>
  );
}

function Properties({ element, storey, globalid }: { element: ElementProperties; storey: string | null; globalid: string }) {
  const { t } = useTranslation();
  return (
    <div className="inspector__body">
      <div className="inspector__title">
        <strong>{element.naam || element.klasse}</strong>
        <span>{element.klasse}</span>
      </div>
      <Section title={t("algemeen")}>
        <Row label={t("globalid")} value={globalid} />
        <Row label={t("klasse")} value={element.klasse} />
        {element.naam && <Row label={t("naam")} value={element.naam} />}
        {storey && <Row label={t("verdieping")} value={storey} />}
        {element.type && <Row label={t("type")} value={element.type} />}
      </Section>
      {Object.entries(element.psets).map(([name, values]) => (
        <Section key={`pset:${name}`} title={name}>
          <Values values={values} />
        </Section>
      ))}
      {Object.entries(element.hoeveelheden).map(([name, values]) => (
        <Section key={`qto:${name}`} title={`${t("hoeveelheden")}: ${name}`}>
          <Values values={values} />
        </Section>
      ))}
      {element.materialen.length > 0 && (
        <Section title={t("materialen")}>
          {element.materialen.map((material) => (
            <Row key={material} label="" value={material} />
          ))}
        </Section>
      )}
      {element.classificaties.length > 0 && (
        <Section title={t("classificaties")}>
          {element.classificaties.map((c) => (
            <Row
              key={`${c.systeem}:${c.code}`}
              label={c.systeem ?? ""}
              value={c.naam ? `${c.code} ${c.naam}` : c.code}
            />
          ))}
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="inspector__section">
      <h3 className="inspector__section-title">{title}</h3>
      <dl className="inspector__rows">{children}</dl>
    </section>
  );
}

function Values({ values }: { values: Record<string, unknown> }) {
  const { t, i18n } = useTranslation();
  const yes = t("openaec:action.yes");
  const no = t("openaec:action.no");
  return (
    <>
      {Object.entries(values).map(([name, value]) => (
        <Row key={name} label={name} value={formatValue(value, i18n.language, yes, no)} />
      ))}
    </>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="inspector__row">
      <dt title={label}>{label}</dt>
      <dd title={value}>{value}</dd>
    </div>
  );
}
