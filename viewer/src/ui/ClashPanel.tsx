import { Icon, uiChevronLeft, uiPlus } from "@openaec/icons";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Coordinatie, ModelInfo } from "../host/BimHost";
import type { Clash, ClashRound, ClashSettings, ClashStatus } from "../model/bcf";
import { STATUSSEN, groepeer, telStatussen, voortgangProcent } from "../model/clashes";
import { ClashRules } from "./ClashRules";
import { ClashStart } from "./ClashStart";
import { describe } from "./format";
import type { Weergave } from "./weergave";

const POLL_MS = 5000;
/** Used while the settings are not loaded (or could not be): no rules, read-only. */
const GEEN_INSTELLINGEN: ClashSettings = { regels: [], weergaven: [], mag_wijzigen: false };

/** Clash rounds of the project: start one between two sets of models, follow it, and work through the results. */
export function ClashPanel({ coordinatie, weergave, modellen }: { coordinatie: Coordinatie; weergave: Weergave; modellen: ModelInfo[] }) {
  const { t } = useTranslation();
  const [rondes, setRondes] = useState<ClashRound[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [nieuw, setNieuw] = useState(false);
  const [regels, setRegels] = useState(false);
  const [instellingen, setInstellingen] = useState<ClashSettings | null>(null);
  const [fout, setFout] = useState<string | null>(null);

  const laad = useCallback(async () => {
    try {
      setRondes(await coordinatie.botsingsrondes());
      setFout(null);
    } catch (e) {
      setFout(t("botsingen_fout", { melding: describe(e) }));
    }
  }, [coordinatie, t]);

  useEffect(() => {
    void laad();
  }, [laad]);

  useEffect(() => {
    let cancelled = false;
    coordinatie
      .botsingInstellingen()
      .then((i) => {
        if (!cancelled) setInstellingen(i);
      })
      .catch((e: unknown) => {
        if (!cancelled) setFout(t("botsingen_fout", { melding: describe(e) }));
      });
    return () => {
      cancelled = true;
    };
  }, [coordinatie, t]);

  // While a round runs at the kern, ask again now and then.
  const lopend = rondes?.some((r) => r.status === "wacht" || r.status === "bezig") ?? false;
  useEffect(() => {
    if (!lopend) return;
    const timer = window.setInterval(() => void laad(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [lopend, laad]);

  const ronde = rondes?.find((r) => r.naam === open) ?? null;
  if (nieuw) {
    return (
      <ClashStart
        coordinatie={coordinatie}
        modellen={modellen}
        instellingen={instellingen ?? GEEN_INSTELLINGEN}
        onKlaar={async () => {
          setNieuw(false);
          await laad();
        }}
      />
    );
  }
  if (regels && instellingen) {
    return (
      <ClashRules
        coordinatie={coordinatie}
        modellen={modellen}
        instellingen={instellingen}
        onKlaar={(bewaard) => {
          if (bewaard) setInstellingen(bewaard);
          setRegels(false);
        }}
      />
    );
  }
  if (ronde) return <Ronde coordinatie={coordinatie} weergave={weergave} ronde={ronde} modellen={modellen} onTerug={() => setOpen(null)} />;

  const klaar = modellen.filter((m) => m.status === "klaar");
  return (
    <div className="issues">
      <div className="issues__balk">
        <button type="button" className="oa-btn oa-btn--primary oa-btn--sm" onClick={() => setNieuw(true)} disabled={klaar.length === 0}>
          <Icon svg={uiPlus} size={14} /> {t("ronde_nieuw")}
        </button>
        <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" onClick={() => setRegels(true)} disabled={!instellingen}>
          {t("regels_knop")}
        </button>
      </div>
      {fout && <p className="viewer__error">{fout}</p>}
      {!rondes && !fout && <p className="viewer__hint">{t("laden")}</p>}
      {rondes && rondes.length === 0 && <p className="viewer__hint">{t("geen_rondes")}</p>}
      <ul className="issues__lijst">
        {(rondes ?? []).map((r) => (
          <li key={r.naam}>
            <button type="button" className="issues__item" onClick={() => setOpen(r.naam)}>
              <strong>{r.titel}</strong>
              <span className="issues__meta">
                <span className={`oa-badge ${r.status === "fout" ? "oa-badge--danger" : r.status === "klaar" ? "oa-badge--success" : "oa-badge--info"}`}>
                  {t(`ronde_status.${r.status}`)}
                </span>
                {(r.status === "wacht" || r.status === "bezig") && r.voortgang != null && (
                  <span>{t("ronde_voortgang", { procent: voortgangProcent(r.voortgang) })}</span>
                )}
                {r.status === "klaar" && <span>{t("aantal_botsingen", { count: r.aantal })}</span>}
                <span>{t(`soort_${r.soort}`)}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Ronde({
  coordinatie,
  weergave,
  ronde,
  modellen,
  onTerug,
}: {
  coordinatie: Coordinatie;
  weergave: Weergave;
  ronde: ClashRound;
  modellen: ModelInfo[];
  onTerug: () => void;
}) {
  const { t } = useTranslation();
  const [botsingen, setBotsingen] = useState<Clash[] | null>(null);
  const [actief, setActief] = useState<string | null>(null);
  const [verberg, setVerberg] = useState(true);
  const [melding, setMelding] = useState<string | null>(null);

  useEffect(() => {
    if (ronde.status !== "klaar") return;
    let cancelled = false;
    coordinatie
      .botsingen(ronde.naam)
      .then((lijst) => {
        if (!cancelled) setBotsingen(lijst);
      })
      .catch((e: unknown) => {
        if (!cancelled) setMelding(describe(e));
      });
    return () => {
      cancelled = true;
    };
  }, [coordinatie, ronde.naam, ronde.status]);

  const vervang = (b: Clash) => setBotsingen((lijst) => (lijst ?? []).map((x) => (x.naam === b.naam ? b : x)));
  const toon = (b: Clash) => {
    setActief(b.naam);
    void weergave.isoleer(
      { bestand: b.element_a.bestand, globalid: b.element_a.globalid },
      { bestand: b.element_b.bestand, globalid: b.element_b.globalid },
      b.punt,
    );
  };
  const zetStatus = async (b: Clash, status: ClashStatus) => {
    try {
      vervang(await coordinatie.botsingStatus(b.naam, status));
    } catch (e) {
      setMelding(describe(e));
    }
  };
  const naarIssue = async (b: Clash) => {
    try {
      const topic = await coordinatie.botsingNaarIssue(b.naam);
      vervang({ ...b, issue: topic.guid });
      setMelding(t("issue_gemaakt", { titel: topic.title }));
    } catch (e) {
      setMelding(describe(e));
    }
  };

  const naam = (sleutel: string) => modellen.find((m) => m.bron.sleutel === sleutel)?.naam ?? sleutel;
  const zichtbaar = (botsingen ?? []).filter((b) => !verberg || (b.status !== "opgelost" && b.status !== "genegeerd"));
  const tel = telStatussen(botsingen ?? []);

  return (
    <div className="issue">
      <div className="issue__kop">
        <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" onClick={onTerug}>
          <Icon svg={uiChevronLeft} size={14} /> {t("terug")}
        </button>
      </div>
      <div className="inspector__title">
        <strong>{ronde.titel}</strong>
        <span>
          {t(`soort_${ronde.soort}`)} · {t("tolerantie_waarde", { mm: Math.round(ronde.tolerantie * 1000) })} ·{" "}
          {Object.entries(ronde.bron_versies)
            .map(([bestand, versie]) => `${naam(bestand)} v${versie}`)
            .join(", ")}
        </span>
      </div>
      {ronde.status !== "klaar" && (
        <p className={ronde.status === "fout" ? "viewer__error" : "viewer__hint"}>
          {ronde.status === "fout" ? (ronde.fout?.melding ?? t("ronde_status.fout")) : t(`ronde_status.${ronde.status}`)}
        </p>
      )}
      {melding && <p className="viewer__hint">{melding}</p>}
      {botsingen && (
        <>
          <p className="issues__meta ronde__tel">
            {STATUSSEN.map((s) => (
              <span key={s}>{t(`botsing_status.${s}`)}: {tel[s]}</span>
            ))}
          </p>
          <label className="model-list__toggle ronde__verberg">
            <input type="checkbox" checked={verberg} onChange={(e) => setVerberg(e.target.checked)} />
            <span>{t("verberg_afgehandeld")}</span>
          </label>
          {zichtbaar.length === 0 && <p className="viewer__hint">{t("geen_botsingen")}</p>}
          {groepeer(zichtbaar).map(({ groep, botsingen: lijst }) => (
            <section key={groep ?? ""} className="inspector__section">
              <h3 className="inspector__section-title">
                {groep ?? ""} ({lijst.length})
              </h3>
              <ul className="issue__lijst">
                {lijst.map((b) => (
                  <li key={b.naam} className="botsing" aria-current={actief === b.naam}>
                    <button type="button" className="botsing__toon" onClick={() => toon(b)}>
                      {t("botsing_afstand", { mm: Math.round(b.afstand * 1000) })}
                      <code className="oa-code">{b.element_a.globalid}</code>
                      <code className="oa-code">{b.element_b.globalid}</code>
                    </button>
                    <div className="botsing__acties">
                      <select
                        className="oa-input"
                        value={b.status}
                        onChange={(e) => void zetStatus(b, e.target.value as ClashStatus)}
                        aria-label={t("status_veld")}
                      >
                        {STATUSSEN.map((s) => (
                          <option key={s} value={s}>
                            {t(`botsing_status.${s}`)}
                          </option>
                        ))}
                      </select>
                      {b.issue ? (
                        <span className="oa-badge oa-badge--info">{t("heeft_issue")}</span>
                      ) : (
                        <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" onClick={() => void naarIssue(b)}>
                          {t("naar_issue")}
                        </button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </>
      )}
    </div>
  );
}
