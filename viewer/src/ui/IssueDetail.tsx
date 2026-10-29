import { Icon, uiChevronLeft, uiDelete } from "@openaec/icons";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Coordinatie, ModelInfo } from "../host/BimHost";
import type { Comment, Extensions, Topic, Viewpoint } from "../model/bcf";
import { describe } from "./format";
import type { Weergave } from "./weergave";

type Props = {
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
export function IssueDetail({ coordinatie, weergave, topic, extensions, modellen, onTerug, onGewijzigd, onVerwijderd, onVerouderd }: Props) {
  const { t } = useTranslation();
  const [comments, setComments] = useState<Comment[]>([]);
  const [viewpoints, setViewpoints] = useState<Viewpoint[]>([]);
  const [snapshots, setSnapshots] = useState<Record<string, string>>({});
  const [reactie, setReactie] = useState("");
  const [melding, setMelding] = useState<string | null>(null);
  const [bezig, setBezig] = useState(false);

  const mag = (actie: string) => topic.authorization.topic_actions.includes(actie);
  const elementen = (topic.elementen ?? []).map((e) => ({ bestand: e.bestand, globalid: e.ifc_guid }));

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
          {topic.topic_type && <Rij label={t("soort")} waarde={topic.topic_type} />}
          {topic.priority && <Rij label={t("prioriteit")} waarde={topic.priority} />}
          {topic.assigned_to && <Rij label={t("toegewezen_aan")} waarde={topic.assigned_to} />}
          {topic.due_date && <Rij label={t("vervaldatum")} waarde={topic.due_date} />}
          {topic.labels.length > 0 && <Rij label={t("labels")} waarde={topic.labels.join(", ")} />}
        </dl>
        {topic.description && <p className="issue__tekst">{topic.description}</p>}
      </section>
      {(topic.elementen ?? []).length > 0 && (
        <section className="inspector__section">
          <h3 className="inspector__section-title">{t("elementen")}</h3>
          <ul className="issue__lijst">
            {(topic.elementen ?? []).map((e) => (
              <li key={`${e.bestand}:${e.ifc_guid}`}>
                <code className="oa-code">{e.ifc_guid}</code>
                {!e.teruggevonden && (
                  <span className="issue__waarschuwing">
                    {e.bestand ? t("niet_teruggevonden", { versie: getoondeVersie(e.bestand) }) : t("niet_teruggevonden_onbekend")}
                  </span>
                )}
              </li>
            ))}
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
