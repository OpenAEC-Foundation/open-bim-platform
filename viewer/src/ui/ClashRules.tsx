import { Icon, uiChevronLeft } from "@openaec/icons";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Coordinatie, ModelInfo } from "../host/BimHost";
import type { ClashRule, ClashSettings, ClashSeverity } from "../model/bcf";
import { disciplineVan, mmWaarde, standaardRegels, teBewarenRegels } from "../model/clashes";
import { describe } from "./format";

const SOORTEN: ClashRule["soort"][] = ["uit", "hard", "afstand"];
const ERNSTEN: ClashSeverity[] = ["klein", "groot", "kritiek"];

type Rij = { a: string; b: string; soort: ClashRule["soort"]; mm: string; ernst: ClashSeverity | "" };

/** The rules per pair of disciplines. Only who may write in the model folder can save; others see them read-only. */
export function ClashRules({
  coordinatie,
  modellen,
  instellingen,
  onKlaar,
}: {
  coordinatie: Coordinatie;
  modellen: ModelInfo[];
  instellingen: ClashSettings;
  /** The saved settings, or null when the user leaves without saving. */
  onKlaar: (instellingen: ClashSettings | null) => Promise<void> | void;
}) {
  const { t } = useTranslation();
  const mag = instellingen.mag_wijzigen;
  const [rijen, setRijen] = useState<Rij[]>(() => {
    const disciplines = modellen.filter((m) => m.status === "klaar").map(disciplineVan);
    return standaardRegels(disciplines, instellingen.regels).map((r) => ({
      a: r.a,
      b: r.b,
      soort: r.soort,
      mm: String(r.mm),
      ernst: r.ernst ?? "",
    }));
  });
  const [fout, setFout] = useState<string | null>(null);
  const [bezig, setBezig] = useState(false);
  const loopt = useRef(false);

  const geldig = useMemo(() => rijen.every((r) => r.soort === "uit" || mmWaarde(r.mm) !== null), [rijen]);
  const zet = (i: number, wijziging: Partial<Rij>) => setRijen((lijst) => lijst.map((r, j) => (j === i ? { ...r, ...wijziging } : r)));

  const bewaar = async () => {
    if (loopt.current || !mag || !geldig) return;
    loopt.current = true;
    setBezig(true);
    setFout(null);
    try {
      // A rule that is off keeps its distance (the field is only locked); only rules that differ from the default go.
      const regels: ClashRule[] = teBewarenRegels(
        rijen.map((r) => ({
          a: r.a,
          b: r.b,
          soort: r.soort,
          mm: mmWaarde(r.mm) ?? 0,
          ernst: r.ernst === "" ? null : r.ernst,
        })),
      );
      const bewaard = await coordinatie.botsingInstellingenBewaar({ regels });
      await onKlaar(bewaard);
    } catch (e) {
      setFout(describe(e));
      loopt.current = false;
      setBezig(false);
    }
  };

  return (
    <div className="issue">
      <div className="issue__kop">
        <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" onClick={() => void onKlaar(null)} disabled={bezig}>
          <Icon svg={uiChevronLeft} size={14} /> {t("terug")}
        </button>
      </div>
      <div className="inspector__title">
        <strong>{t("regels_titel")}</strong>
        <span>{t("regels_uitleg")}</span>
      </div>
      <div className="issue__formulier">
        {!mag && <p className="viewer__hint">{t("regels_alleen_lezen")}</p>}
        {rijen.length === 0 && <p className="viewer__hint">{t("regels_geen")}</p>}
        {rijen.map((r, i) => {
          const mmFout = r.soort !== "uit" && mmWaarde(r.mm) === null;
          return (
            <fieldset key={`${r.a}\u0000${r.b}`} className="ronde__set rule">
              <legend className="oa-label">
                {r.a} × {r.b}
              </legend>
              <div className="rule__velden">
                <label className="oa-field">
                  <span className="oa-label">{t("soort")}</span>
                  <select className="oa-input" value={r.soort} disabled={!mag} onChange={(e) => zet(i, { soort: e.target.value as Rij["soort"] })}>
                    {SOORTEN.map((s) => (
                      <option key={s} value={s}>
                        {t(`regel_soort.${s}`)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="oa-field">
                  <span className="oa-label">{t("regel_mm")}</span>
                  <input
                    className="oa-input"
                    inputMode="decimal"
                    value={r.mm}
                    disabled={!mag || r.soort === "uit"}
                    aria-invalid={mmFout}
                    onChange={(e) => zet(i, { mm: e.target.value })}
                  />
                </label>
                <label className="oa-field">
                  <span className="oa-label">{t("ernst_veld")}</span>
                  <select className="oa-input" value={r.ernst} disabled={!mag} onChange={(e) => zet(i, { ernst: e.target.value as Rij["ernst"] })}>
                    <option value="">{t("ernst.auto")}</option>
                    {ERNSTEN.map((s) => (
                      <option key={s} value={s}>
                        {t(`ernst.${s}`)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </fieldset>
          );
        })}
        {!geldig && <p className="viewer__error">{t("mm_ongeldig")}</p>}
        {fout && <p className="viewer__error">{fout}</p>}
        {mag && (
          <div className="issues__balk">
            <button type="button" className="oa-btn oa-btn--primary oa-btn--sm" onClick={() => void bewaar()} disabled={bezig || !geldig}>
              {t("opslaan")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
