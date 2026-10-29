import { Icon, uiDownload, uiPlus, uiUpload } from "@openaec/icons";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Coordinatie, ModelInfo } from "../host/BimHost";
import type { BcfCamera, Extensions, Topic } from "../model/bcf";
import { filterTopics, nieuwTopic, verlorenElementen, type IssueForm } from "../model/issues";
import { describe } from "./format";
import { IssueDetail } from "./IssueDetail";
import { Markup } from "./Markup";
import type { Weergave } from "./weergave";

type Nieuw = { camera: BcfCamera; selectie: string[]; beeld: Blob | null };

/** The issues of the project (BCF 3.0): a filtered list, one issue in detail, and a new issue from the current view. */
export function IssuesPanel({ coordinatie, weergave, modellen }: { coordinatie: Coordinatie; weergave: Weergave; modellen: ModelInfo[] }) {
  const { t } = useTranslation();
  const [topics, setTopics] = useState<Topic[] | null>(null);
  const [extensions, setExtensions] = useState<Extensions | null>(null);
  const [status, setStatus] = useState("");
  const [tekst, setTekst] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [nieuw, setNieuw] = useState<Nieuw | null>(null);
  const [melding, setMelding] = useState<string | null>(null);
  const [fout, setFout] = useState<string | null>(null);

  const laad = useCallback(async () => {
    try {
      const [e, lijst] = await Promise.all([coordinatie.instellingen(), coordinatie.issues()]);
      setExtensions(e);
      setTopics(lijst);
      setFout(null);
    } catch (e) {
      setFout(t("issues_fout", { melding: describe(e) }));
    }
  }, [coordinatie, t]);

  useEffect(() => {
    void laad();
  }, [laad]);

  const begin = async () => {
    const camera = weergave.camera();
    if (!camera) return;
    setNieuw({ camera, selectie: weergave.selectie(), beeld: await weergave.snapshot() });
    setOpen(null);
  };

  const exporteer = async (versie: "2.1" | "3.0") => {
    try {
      await coordinatie.bcfExport(versie);
      setMelding(t("export_klaar"));
    } catch (e) {
      setFout(describe(e));
    }
  };

  const importeer = async () => {
    try {
      const uit = await coordinatie.bcfImport();
      if (!uit) return;
      setMelding(t("import_klaar", { nieuw: uit.nieuw, bijgewerkt: uit.bijgewerkt }));
      await laad();
    } catch (e) {
      setFout(describe(e));
    }
  };

  const vervang = (topic: Topic) => setTopics((lijst) => (lijst ?? []).map((x) => (x.guid === topic.guid ? topic : x)));
  const geopend = topics?.find((x) => x.guid === open) ?? null;
  const mag = (actie: string) => extensions?.project_actions.includes(actie) ?? false;

  if (nieuw) {
    return (
      <NieuwIssue
        nieuw={nieuw}
        extensions={extensions}
        coordinatie={coordinatie}
        onKlaar={async (topic) => {
          setNieuw(null);
          if (topic) {
            await laad();
            setOpen(topic.guid);
          }
        }}
      />
    );
  }

  if (geopend) {
    return (
      <IssueDetail
        coordinatie={coordinatie}
        weergave={weergave}
        topic={geopend}
        extensions={extensions}
        modellen={modellen}
        onTerug={() => setOpen(null)}
        onGewijzigd={vervang}
        onVerwijderd={(guid) => {
          setOpen(null);
          setTopics((lijst) => (lijst ?? []).filter((x) => x.guid !== guid));
        }}
        onVerouderd={() => void laad()}
      />
    );
  }

  const zichtbaar = filterTopics(topics ?? [], { status: status || undefined, tekst });
  return (
    <div className="issues">
      <div className="issues__balk">
        {mag("createTopic") && (
          <button type="button" className="oa-btn oa-btn--primary oa-btn--sm" onClick={() => void begin()} disabled={!weergave.camera()}>
            <Icon svg={uiPlus} size={14} /> {t("nieuw_issue")}
          </button>
        )}
        <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" onClick={() => void exporteer("3.0")} title={t("exporteren_versie", { versie: "3.0" })}>
          <Icon svg={uiDownload} size={14} /> {t("exporteren_versie", { versie: "3.0" })}
        </button>
        <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" onClick={() => void exporteer("2.1")} title={t("exporteren_versie", { versie: "2.1" })}>
          {t("exporteren_versie", { versie: "2.1" })}
        </button>
        {mag("update") && (
          <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" onClick={() => void importeer()}>
            <Icon svg={uiUpload} size={14} /> {t("importeren")}
          </button>
        )}
      </div>
      <div className="issues__filter">
        <select className="oa-input" value={status} onChange={(e) => setStatus(e.target.value)} aria-label={t("status_veld")}>
          <option value="">{t("filter_alle")}</option>
          {(extensions?.topic_status ?? []).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <input className="oa-input" type="search" value={tekst} placeholder={t("zoeken")} onChange={(e) => setTekst(e.target.value)} />
      </div>
      {melding && <p className="viewer__hint">{melding}</p>}
      {fout && <p className="viewer__error">{fout}</p>}
      {!topics && !fout && <p className="viewer__hint">{t("issues_laden")}</p>}
      {topics && zichtbaar.length === 0 && <p className="viewer__hint">{t("geen_issues")}</p>}
      <ul className="issues__lijst">
        {zichtbaar.map((topic) => (
          <li key={topic.guid}>
            <button type="button" className="issues__item" onClick={() => setOpen(topic.guid)}>
              <strong>{topic.title}</strong>
              <span className="issues__meta">
                {topic.topic_status && <span className="oa-badge oa-badge--neutral">{topic.topic_status}</span>}
                {topic.topic_type && <span>{topic.topic_type}</span>}
                {topic.assigned_to && <span>{topic.assigned_to}</span>}
                {verlorenElementen(topic).length > 0 && (
                  <span className="oa-badge oa-badge--warning">{t("elementen_verloren", { aantal: verlorenElementen(topic).length })}</span>
                )}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function NieuwIssue({
  nieuw,
  extensions,
  coordinatie,
  onKlaar,
}: {
  nieuw: Nieuw;
  extensions: Extensions | null;
  coordinatie: Coordinatie;
  onKlaar: (topic: Topic | null) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<IssueForm>({ title: "", topic_type: extensions?.topic_type[0] ?? null });
  const [png, setPng] = useState<string | null>(null);
  const [fout, setFout] = useState<string | null>(null);
  const [bezig, setBezig] = useState(false);

  const zet = (veld: keyof IssueForm) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [veld]: e.target.value }));

  const bewaar = async () => {
    if (!form.title.trim()) return;
    setBezig(true);
    try {
      const { topic, standpunt } = nieuwTopic(form, nieuw.camera, nieuw.selectie, png ?? undefined);
      const gemaakt = await coordinatie.issueBewaar(topic);
      await coordinatie.standpuntBewaar(gemaakt.guid, standpunt);
      await onKlaar(gemaakt);
    } catch (e) {
      setFout(describe(e));
      setBezig(false);
    }
  };

  const keuze = (veld: keyof IssueForm, label: string, waarden: string[], leeg?: string) => (
    <label className="oa-field">
      <span className="oa-label">{label}</span>
      <select className="oa-input" value={form[veld] ?? ""} onChange={zet(veld)}>
        {leeg !== undefined && <option value="">{leeg}</option>}
        {waarden.map((w) => (
          <option key={w} value={w}>
            {w}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="issue issue--nieuw">
      <div className="inspector__title">
        <strong>{t("nieuw_issue")}</strong>
        <span>{t("selectie_aantal", { count: nieuw.selectie.length })}</span>
      </div>
      {nieuw.beeld && <Markup beeld={nieuw.beeld} onChange={setPng} />}
      <div className="issue__formulier">
        <label className="oa-field">
          <span className="oa-label">{t("titel_veld")}</span>
          <input className="oa-input" value={form.title} onChange={zet("title")} autoFocus />
        </label>
        {keuze("topic_type", t("soort"), extensions?.topic_type ?? [])}
        {keuze("priority", t("prioriteit"), extensions?.priority ?? [], "—")}
        {keuze("assigned_to", t("toegewezen_aan"), extensions?.users ?? [], t("niemand"))}
        <label className="oa-field">
          <span className="oa-label">{t("beschrijving")}</span>
          <textarea className="oa-input" rows={4} value={form.description ?? ""} onChange={zet("description")} />
        </label>
        {fout && <p className="viewer__error">{fout}</p>}
        <div className="issues__balk">
          <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" onClick={() => void onKlaar(null)} disabled={bezig}>
            {t("annuleren")}
          </button>
          <button type="button" className="oa-btn oa-btn--primary oa-btn--sm" onClick={() => void bewaar()} disabled={bezig || !form.title.trim()}>
            {t("opslaan")}
          </button>
        </div>
      </div>
    </div>
  );
}
