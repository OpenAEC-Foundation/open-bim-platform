import { Icon, uiChevronLeft, uiDelete } from "@openaec/icons";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { BimHost, Coordinatie, ElementProperties, ModelInfo } from "../host/BimHost";
import type { Comment, Extensions, Topic, Viewpoint } from "../model/bcf";
import { elementVragen } from "../model/issues";
import { describe } from "./format";
import type { Weergave } from "./weergave";

type Props = {
  host: BimHost;
  coordinatie: Coordinatie;
  weergave: Weergave;
  topic: Topic;
  extensions: Extensions | null;
  modellen: ModelInfo[];
  onTerug: () => void;
  onGewijzigd: (topic: Topic) => void;
  onVerwijderd: (guid: string) => void;
  /** Reload the list (after a conflict: someone else changed the topic). */
  onVerouderd: () => void;
};

/** One issue: its fields and status, the elements (followed to the version in view), viewpoints and comments. */
export function IssueDetail({ host, coordinatie, weergave, topic, extensions, modellen, onTerug, onGewijzigd, onVerwijderd, onVerouderd }: Props) {
  const { t } = useTranslation();
  const [comments, setComments] = useState<Comment[]>([]);
  const [viewpoints, setViewpoints] = useState<Viewpoint[]>([]);
  const [snapshots, setSnapshots] = useState<Record<string, string>>({});
  const [reactie, setReactie] = useState("");
  const [melding, setMelding] = useState<string | null>(null);
  const [bezig, setBezig] = useState(false);
  const [gegevens, setGegevens] = useState<Record<string, ElementProperties>>({});

  const mag = (actie: string) => topic.authorization.topic_actions.includes(actie);
  const elementen = (topic.elementen ?? []).map((e) => ({ bestand: e.bestand, globalid: e.ifc_guid }));
  const elementenSleutel = (topic.elementen ?? []).map((e) => `${e.bestand}@${e.versie}:${e.ifc_guid}`).join(",");

  // The names of the elements, from the property index of the version in view. Without them the GlobalId remains.
  useEffect(() => {
    let cancelled = false;
    setGegevens({});
    for (const { bron, globalids } of elementVragen(topic.elementen ?? [])) {
      host
        .eigenschappen(bron, globalids)
        .then((gevonden) => {
          if (cancelled) return;
          setGegevens((huidig) => {
            const nieuw = { ...huidig };
            for (const [globalid, eigenschappen] of Object.entries(gevonden)) {
              nieuw[`${bron.sleutel}:${globalid}`] = eigenschappen;
            }
            return nieuw;
          });
        })
        .catch(() => undefined);
    }
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the elements themselves, not the object around them
  }, [host, elementenSleutel]);

  const laad = useCallback(async () => {
    const [c, v] = await Promise.all([coordinatie.reacties(topic.guid), coordinatie.standpunten(topic.guid)]);
    setComments(c);
    setViewpoints(v);
    const beelden: Record<string, string> = {};
    for (const vp of v) {
      if (!vp.guid || !vp.snapshot) continue;
      const s = await coordinatie.snapshot(topic.guid, vp.guid);
      beelden[vp.guid] = `data:image/${s.snapshot_type === "jpg" ? "jpeg" : "png"};base64,${s.snapshot_data}`;
    }
    setSnapshots(beelden);
    return v;
  }, [coordinatie, topic.guid]);

  // Opening an issue puts its first viewpoint back and marks its elements.
  useEffect(() => {
    let cancelled = false;
    laad()
      .then((v) => {
        if (!cancelled) void weergave.toon(v[0] ?? null, elementen);
      })
      .catch((e: unknown) => {
        if (!cancelled) setMelding(describe(e));
      });
    return () => {
      cancelled = true;
    };
    // Only when another topic is opened (laad depends on its guid); the elements belong to that topic.
  }, [laad]);

  const bewaar = async (velden: Partial<Topic>) => {
    setBezig(true);
    try {
      onGewijzigd(await coordinatie.issueBewaar({ guid: topic.guid, modified_date: topic.modified_date, ...velden }));
      setMelding(null);
    } catch (e) {
      if ((e as { fout?: { error_code?: string } | null }).fout?.error_code === "issue_verouderd") {
        setMelding(t("issue_verouderd"));
        onVerouderd();
      } else setMelding(describe(e));
    } finally {
      setBezig(false);
    }
  };

  const plaats = async () => {
    if (!reactie.trim()) return;
    setBezig(true);
    try {
      await coordinatie.reactieBewaar(topic.guid, { comment: reactie.trim() });
      setReactie("");
      await laad();
    } catch (e) {
      setMelding(describe(e));
    } finally {
      setBezig(false);
    }
  };

  const verwijder = async () => {
    if (!window.confirm(t("issue_verwijderen_vraag", { titel: topic.title }))) return;
    try {
      await coordinatie.issueVerwijder(topic.guid);
      onVerwijderd(topic.guid);
    } catch (e) {
      setMelding(describe(e));
    }
  };

  const getoondeVersie = (bestand: string | null) => modellen.find((m) => m.bron.sleutel === bestand)?.bron.versie ?? "?";
  const statussen = topic.authorization.topic_status.length ? topic.authorization.topic_status : (extensions?.topic_status ?? []);

  /** Een veld met keuzes uit de projectinstellingen: te wijzigen voor wie het issue mag bijwerken, anders alleen te lezen. */
  const keuze = (veld: "topic_type" | "priority" | "assigned_to", label: string, waarden: string[], leeg?: string) => {
    const waarde = topic[veld];
    if (!mag("update")) return waarde ? <Rij label={label} waarde={waarde} /> : null;
    const opties = waarde && !waarden.includes(waarde) ? [waarde, ...waarden] : waarden;
    return (
      <div className="inspector__row">
        <dt>{label}</dt>
        <dd>
          <select
            className="oa-input issue__select"
            aria-label={label}
            value={waarde ?? ""}
            disabled={bezig}
            onChange={(e) => void bewaar({ [veld]: e.target.value || null })}
          >
            {(leeg !== undefined || !waarde) && <option value="">{leeg ?? "—"}</option>}
            {opties.map((w) => (
              <option key={w} value={w}>
                {w}
              </option>
            ))}
          </select>
        </dd>
      </div>
    );
  };

  return (
    <div className="issue">
      <div className="issue__kop">
        <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" onClick={onTerug}>
          <Icon svg={uiChevronLeft} size={14} /> {t("terug")}
        </button>
        {mag("delete") && (
          <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" onClick={() => void verwijder()} aria-label={t("verwijderen")}>
            <Icon svg={uiDelete} size={14} />
          </button>
        )}
      </div>
      <div className="inspector__title">
        <strong>{topic.title}</strong>
        <span>{t("door_op", { auteur: topic.creation_author, datum: topic.creation_date.slice(0, 10) })}</span>
      </div>
      {melding && <p className="viewer__error">{melding}</p>}
      <section className="inspector__section">
        <dl className="inspector__rows">
          <div className="inspector__row">
            <dt>{t("status_veld")}</dt>
            <dd>
              {mag("update") && statussen.length ? (
                <select
                  className="oa-input issue__select"
                  value={topic.topic_status ?? ""}
                  disabled={bezig}
                  onChange={(e) => void bewaar({ topic_status: e.target.value })}
                >
                  {statussen.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              ) : (
                topic.topic_status
              )}
            </dd>
          </div>
          {keuze("topic_type", t("soort"), extensions?.topic_type ?? [])}
          {keuze("priority", t("prioriteit"), extensions?.priority ?? [], "—")}
          {keuze("assigned_to", t("toegewezen_aan"), extensions?.users ?? [], t("niemand"))}
          {topic.due_date && <Rij label={t("vervaldatum")} waarde={topic.due_date} />}
          {topic.labels.length > 0 && <Rij label={t("labels")} waarde={topic.labels.join(", ")} />}
        </dl>
        {topic.description && <p className="issue__tekst">{topic.description}</p>}
      </section>
      {(topic.elementen ?? []).length > 0 && (
        <section className="inspector__section">
          <h3 className="inspector__section-title">{t("elementen")}</h3>
          <ul className="issue__lijst">
            {(topic.elementen ?? []).map((e) => {
              const gegeven = gegevens[`${e.bestand}:${e.ifc_guid}`];
              const model = modellen.find((m) => m.bron.sleutel === e.bestand)?.naam;
              return (
                <li key={`${e.bestand}:${e.ifc_guid}`}>
                  {gegeven && (
                    <>
                      <span className="issue__element">{gegeven.naam ?? gegeven.klasse}</span>
                      <span className="issue__meta">{[gegeven.klasse, model].filter(Boolean).join(" · ")}</span>
                    </>
                  )}
                  <code className="oa-code">{e.ifc_guid}</code>
                  {!e.teruggevonden && (
                    <span className="issue__waarschuwing">
                      {e.bestand ? t("niet_teruggevonden", { versie: getoondeVersie(e.bestand) }) : t("niet_teruggevonden_onbekend")}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {viewpoints.length > 0 && (
        <section className="inspector__section">
          <h3 className="inspector__section-title">{t("standpunten")}</h3>
          {viewpoints.map((vp) => (
            <button
              key={vp.guid}
              type="button"
              className="issue__standpunt"
              onClick={() => void weergave.toon(vp, elementen)}
              title={t("standpunt_tonen")}
            >
              {vp.guid && snapshots[vp.guid] ? <img src={snapshots[vp.guid]} alt={t("standpunt_tonen")} /> : t("standpunt_tonen")}
            </button>
          ))}
        </section>
      )}
      <section className="inspector__section">
        <h3 className="inspector__section-title">{t("reacties")}</h3>
        {comments.length === 0 && <p className="viewer__hint">{t("geen_reacties")}</p>}
        <ul className="issue__lijst">
          {comments.map((c) => (
            <li key={c.guid} className="issue__reactie">
              <span className="issue__meta">{t("door_op", { auteur: c.author, datum: c.date.slice(0, 16).replace("T", " ") })}</span>
              <span>{c.comment}</span>
            </li>
          ))}
        </ul>
        {mag("createComment") && (
          <div className="issue__nieuw">
            <textarea
              className="oa-input"
              rows={3}
              value={reactie}
              placeholder={t("reactie_placeholder")}
              onChange={(e) => setReactie(e.target.value)}
            />
            <button type="button" className="oa-btn oa-btn--primary oa-btn--sm" disabled={bezig || !reactie.trim()} onClick={() => void plaats()}>
              {t("reactie_plaatsen")}
            </button>
          </div>
        )}
      </section>
    </div>
  );
}

function Rij({ label, waarde }: { label: string; waarde: string }) {
  return (
    <div className="inspector__row">
      <dt>{label}</dt>
      <dd>{waarde}</dd>
    </div>
  );
}
