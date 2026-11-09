import { Icon, uiPlus } from "@openaec/icons";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Coordinatie, ModelInfo } from "../host/BimHost";
import type { ClashRound as RondeGegevens, ClashSettings } from "../model/bcf";
import { voortgangProcent } from "../model/clashes";
import { ClashRound } from "./ClashRound";
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
  const [rondes, setRondes] = useState<RondeGegevens[] | null>(null);
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
        onKlaar={async (ronde) => {
          setNieuw(false);
          // Cancelled: nothing changed, so the list does not need to come again.
          if (ronde) await laad();
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
  if (ronde) {
    return (
      <ClashRound
        coordinatie={coordinatie}
        weergave={weergave}
        ronde={ronde}
        modellen={modellen}
        instellingen={instellingen ?? GEEN_INSTELLINGEN}
        onInstellingen={setInstellingen}
        onVerouderd={() => void laad()}
        onTerug={() => setOpen(null)}
      />
    );
  }

  const klaar = modellen.filter((m) => m.status === "klaar");
  return (
    <div className="issues">
      <div className="issues__balk">
        {instellingen?.mag_wijzigen && (
          <button type="button" className="oa-btn oa-btn--primary oa-btn--sm" onClick={() => setNieuw(true)} disabled={klaar.length === 0}>
            <Icon svg={uiPlus} size={14} /> {t("ronde_nieuw")}
          </button>
        )}
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
