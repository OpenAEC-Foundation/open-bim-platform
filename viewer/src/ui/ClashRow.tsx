import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { Clash, ClashElement, ClashSeverity, ClashStatus } from "../model/bcf";
import { REDEN_MAX, elementNaam, rijActies } from "../model/clashes";

const ERNST_BADGE: Record<ClashSeverity, string> = { klein: "neutral", groot: "warning", kritiek: "danger" };
const STATUS_BADGE: Record<ClashStatus, string> = {
  nieuw: "info",
  actief: "info",
  bevestigd: "warning",
  geaccepteerd: "success",
  genegeerd: "neutral",
  opgelost: "success",
};

/** The input line of a rejection: Enter confirms (the reason may be empty), Escape cancels. */
export function RedenVeld({ onBevestig, onAnnuleer, disabled }: { onBevestig: (reden: string) => void; onAnnuleer: () => void; disabled: boolean }) {
  const { t } = useTranslation();
  const [tekst, setTekst] = useState("");
  return (
    <div className="botsing__reden">
      <input
        className="oa-input"
        data-reden=""
        autoFocus
        maxLength={REDEN_MAX}
        aria-label={t("reden_veld")}
        placeholder={t("reden_veld")}
        value={tekst}
        disabled={disabled}
        onChange={(e) => setTekst(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            onBevestig(tekst.trim());
          } else if (e.key === "Escape") {
            e.preventDefault();
            onAnnuleer();
          }
        }}
      />
      <button type="button" className="oa-btn oa-btn--danger oa-btn--sm" data-actie="afwijzen-bevestig" disabled={disabled} onClick={() => onBevestig(tekst.trim())}>
        {t("actie.afwijzen")}
      </button>
      <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" data-actie="afwijzen-annuleer" disabled={disabled} onClick={onAnnuleer}>
        {t("annuleren")}
      </button>
    </div>
  );
}

export type ClashRowProps = {
  b: Clash;
  /** The selected row: open, and shown in 3D. */
  open: boolean;
  /** Deciding is allowed (write permission). */
  mag: boolean;
  /** A save is under way. */
  bezig: boolean;
  /** The reject input is open on this row. */
  afwijzen: boolean;
  fout: string | null;
  /** The names of the elements that could not be found in the view. */
  nietInBeeld: string[];
  onKies: () => void;
  onBeslis: (status: ClashStatus, reden?: string) => void;
  onAfwijzen: (open: boolean) => void;
  onNaar: (e: ClashElement) => void;
  onAllesTonen: () => void;
};

/** One clash in the list; the selected one opens with its details and buttons. */
export function ClashRow({ b, open, mag, bezig, afwijzen, fout, nietInBeeld, onKies, onBeslis, onAfwijzen, onNaar, onAllesTonen }: ClashRowProps) {
  const { t } = useTranslation();
  const { beslissen, heropenen } = rijActies(b, mag);
  const detail: [string, string | null][] = [
    [t("veld.afstand"), t("botsing_afstand", { mm: Math.round(b.afstand * 1000) })],
    [t("veld.disciplines"), b.disciplines],
    [t("veld.raster"), b.raster],
    [t("veld.ruimte"), b.ruimte],
    [t("veld.globalid_a"), b.element_a.globalid],
    [t("veld.globalid_b"), b.element_b.globalid],
    [t("veld.reden"), b.reden],
    [t("veld.beoordeeld"), b.beoordeeld_door],
  ];
  return (
    <li className="botsing" data-botsing={b.naam} data-geselecteerd={open} aria-current={open}>
      <button type="button" className="botsing__toon" aria-expanded={open} onClick={onKies}>
        <span className="botsing__titel">
          {b.nummer != null && <strong>#{b.nummer}</strong>} {elementNaam(b.element_a)} × {elementNaam(b.element_b)}
        </span>
        <span className="issues__meta">
          {b.ernst && <span className={`oa-badge oa-badge--${ERNST_BADGE[b.ernst]}`}>{t(`ernst.${b.ernst}`)}</span>}
          <span className={`oa-badge oa-badge--${STATUS_BADGE[b.status]}`}>{t(`botsing_status.${b.status}`)}</span>
          {b.issue && <span className="oa-badge oa-badge--info">{t("heeft_issue")}</span>}
          {b.verdieping && <span>{b.verdieping}</span>}
          {b.ontwikkeling && <span>{t(`ontwikkeling.${b.ontwikkeling}`)}</span>}
        </span>
      </button>
      {open && (
        <div className="botsing__detail">
          <dl className="inspector__rows">
            {detail
              .filter(([, waarde]) => waarde)
              .map(([naam, waarde]) => (
                <div key={naam} className="inspector__row">
                  <dt>{naam}</dt>
                  <dd>{naam.startsWith("GlobalId") ? <code className="oa-code">{waarde}</code> : waarde}</dd>
                </div>
              ))}
          </dl>
          {fout && <p className="viewer__error">{fout}</p>}
          {nietInBeeld.length > 0 && (
            <p className="viewer__hint" data-melding="niet-in-beeld">
              {t("niet_in_beeld", { namen: nietInBeeld.join(", ") })}
            </p>
          )}
          {beslissen && !afwijzen && (
            <div className="botsing__acties">
              <button type="button" className="oa-btn oa-btn--primary oa-btn--sm" data-actie="bevestigen" disabled={bezig} onClick={() => onBeslis("bevestigd")}>
                {t("actie.bevestigen")}
              </button>
              <button type="button" className="oa-btn oa-btn--secondary oa-btn--sm" data-actie="accepteren" disabled={bezig} onClick={() => onBeslis("geaccepteerd")}>
                {t("actie.accepteren")}
              </button>
              <button type="button" className="oa-btn oa-btn--secondary oa-btn--sm" data-actie="afwijzen" disabled={bezig} onClick={() => onAfwijzen(true)}>
                {t("actie.afwijzen")}
              </button>
            </div>
          )}
          {beslissen && afwijzen && (
            <RedenVeld disabled={bezig} onBevestig={(reden) => onBeslis("genegeerd", reden)} onAnnuleer={() => onAfwijzen(false)} />
          )}
          {heropenen && (
            <div className="botsing__acties">
              <button type="button" className="oa-btn oa-btn--secondary oa-btn--sm" data-actie="heropenen" disabled={bezig} onClick={() => onBeslis("actief")}>
                {t("actie.heropenen")}
              </button>
            </div>
          )}
          <div className="botsing__acties">
            <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" data-actie="naar-a" onClick={() => onNaar(b.element_a)}>
              {t("actie.naar_a")}
            </button>
            <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" data-actie="naar-b" onClick={() => onNaar(b.element_b)}>
              {t("actie.naar_b")}
            </button>
            <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" data-actie="alles-tonen" onClick={onAllesTonen}>
              {t("actie.alles_tonen")}
            </button>
          </div>
        </div>
      )}
    </li>
  );
}
