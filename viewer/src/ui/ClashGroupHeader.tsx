import { Icon, uiChevronDown, uiChevronRight } from "@openaec/icons";
import { useTranslation } from "react-i18next";
import { GROEPSACTIE_MAX } from "../model/clashes";
import { RedenVeld } from "./ClashRow";

/** A decision for all open rows of one group, waiting for its confirmation. */
export type GroepsActie = { sleutel: string; status: "geaccepteerd" | "genegeerd" };

/** The head of a group in a round: open or close the group, and decide all its open rows at once after a confirmation. */
export function ClashGroupHeader({
  sleutel,
  titel,
  aantal,
  open,
  dicht,
  mag,
  bezig,
  actie,
  fout,
  onWissel,
  onActie,
  onBeslis,
}: {
  sleutel: string;
  /** The name of the group as shown. */
  titel: string;
  /** All rows of the group. */
  aantal: number;
  /** The rows that still wait for a decision. */
  open: number;
  dicht: boolean;
  mag: boolean;
  bezig: boolean;
  /** The group action of this group that waits for its confirmation, if any. */
  actie: GroepsActie | null;
  fout: string | null;
  onWissel: () => void;
  onActie: (actie: GroepsActie | null) => void;
  onBeslis: (status: GroepsActie["status"], reden: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <>
      <h3 className="inspector__section-title botsing__groepkop" data-groep={sleutel}>
        <button type="button" className="botsing__groepknop" aria-expanded={!dicht} onClick={onWissel}>
          <Icon svg={dicht ? uiChevronRight : uiChevronDown} size={12} /> {titel} ({aantal})
        </button>
      </h3>
      {mag && open > 0 && !actie && (
        <div className="botsing__acties">
          <button
            type="button"
            className="oa-btn oa-btn--secondary oa-btn--sm"
            data-actie="groep-afwijzen"
            disabled={bezig || open > GROEPSACTIE_MAX}
            onClick={() => onActie({ sleutel, status: "genegeerd" })}
          >
            {t("groep_alles_afwijzen")}
          </button>
          <button
            type="button"
            className="oa-btn oa-btn--secondary oa-btn--sm"
            data-actie="groep-accepteren"
            disabled={bezig || open > GROEPSACTIE_MAX}
            onClick={() => onActie({ sleutel, status: "geaccepteerd" })}
          >
            {t("groep_alles_accepteren")}
          </button>
        </div>
      )}
      {mag && open > GROEPSACTIE_MAX && <p className="viewer__hint">{t("groep_te_veel", { max: GROEPSACTIE_MAX, count: open })}</p>}
      {actie && (
        <div className="botsing__bevestig" data-sectie="groepsactie">
          <p>{t(actie.status === "genegeerd" ? "groep_vraag_afwijzen" : "groep_vraag_accepteren", { count: open })}</p>
          {actie.status === "genegeerd" ? (
            <RedenVeld disabled={bezig} onBevestig={(reden) => onBeslis(actie.status, reden)} onAnnuleer={() => onActie(null)} />
          ) : (
            <div className="botsing__acties">
              <button type="button" className="oa-btn oa-btn--primary oa-btn--sm" data-actie="groep-bevestig" disabled={bezig} onClick={() => onBeslis(actie.status, "")}>
                {t("actie.accepteren")}
              </button>
              <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" data-actie="groep-annuleer" disabled={bezig} onClick={() => onActie(null)}>
                {t("annuleren")}
              </button>
            </div>
          )}
          {fout && <p className="viewer__error">{fout}</p>}
        </div>
      )}
    </>
  );
}
