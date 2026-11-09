import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Coordinatie, ModelInfo } from "../host/BimHost";
import type { ClashCheck, ClashSettings } from "../model/bcf";
import { bijnaMet, mmWaarde, nietGereed, overlapWaarschuwing, rondeTitel, voorinstellingen } from "../model/clashes";
import { describe } from "./format";

const BIJNA_STANDAARD_MM = "50";
const ZELF = "zelf";

/** The models a check names, to compare their boxes. */
function modellenVan(set: ClashCheck["set_a"], modellen: ModelInfo[]): ModelInfo[] {
  const namen = new Set(set.map((s) => s.bestand));
  return modellen.filter((m) => namen.has(m.bron.sleutel));
}

/** Start a clash round: pick a quick choice, or set it up yourself. `onKlaar` gets the new round, or null on cancel. */
export function ClashStart({
  coordinatie,
  modellen,
  instellingen,
  onKlaar,
}: {
  coordinatie: Coordinatie;
  modellen: ModelInfo[];
  instellingen: ClashSettings;
  onKlaar: (ronde: string | null) => Promise<void> | void;
}) {
  const { t, i18n } = useTranslation();
  const klaar = modellen.filter((m) => m.status === "klaar");
  const ontbreekt = nietGereed(modellen);
  const keuzes = voorinstellingen(modellen, instellingen.regels);
  const [gekozen, setGekozen] = useState<string>(() => keuzes.find((k) => k.beschikbaar)?.id ?? ZELF);
  const [bijnaMm, setBijnaMm] = useState(BIJNA_STANDAARD_MM);
  const [setA, setSetA] = useState<Set<string>>(new Set());
  const [setB, setSetB] = useState<Set<string>>(new Set());
  const [soort, setSoort] = useState<"hard" | "afstand">("hard");
  const [mm, setMm] = useState("10");
  const [fout, setFout] = useState<string | null>(null);
  const [bezig, setBezig] = useState(false);
  // Set before the first await, so a double click cannot start two rounds.
  const loopt = useRef(false);

  const wissel = (set: Set<string>, sleutel: string) => {
    const volgende = new Set(set);
    if (volgende.has(sleutel)) volgende.delete(sleutel);
    else volgende.add(sleutel);
    return volgende;
  };

  const voorinstelling = keuzes.find((k) => k.id === gekozen) ?? null;
  const bijnaWaarde = mmWaarde(bijnaMm);
  const zelfWaarde = mmWaarde(mm);

  let controles: ClashCheck[] = [];
  let geldig = false;
  if (gekozen === ZELF) {
    const naar = (set: Set<string>) => [...set].map((bestand) => ({ bestand }));
    geldig = setA.size > 0 && setB.size > 0 && zelfWaarde !== null;
    if (geldig) controles = [{ set_a: naar(setA), set_b: naar(setB), soort, tolerantie: (zelfWaarde as number) / 1000 }];
  } else if (voorinstelling?.beschikbaar) {
    if (voorinstelling.instelbaar) {
      geldig = bijnaWaarde !== null;
      if (geldig) controles = bijnaMet(bijnaWaarde as number, modellen);
    } else {
      geldig = true;
      controles = voorinstelling.controles;
    }
  }

  const mmFout = gekozen === ZELF ? zelfWaarde === null : voorinstelling?.instelbaar === true && bijnaWaarde === null;
  const waarschuwing =
    controles.length > 0 &&
    controles.every((c) => overlapWaarschuwing(modellenVan(c.set_a, klaar), modellenVan(c.set_b, klaar)));

  const start = async () => {
    if (loopt.current || !geldig) return;
    loopt.current = true;
    setBezig(true);
    setFout(null);
    try {
      const titel = rondeTitel(t(`voorinstelling.${gekozen}.titel`), new Date(), i18n.language);
      const { ronde } = await coordinatie.botsingsrondeControles(controles, gekozen === ZELF ? null : gekozen, titel);
      await onKlaar(ronde);
    } catch (e) {
      setFout(describe(e));
      loopt.current = false;
      setBezig(false);
    }
  };

  const kies = (titel: string, set: Set<string>, zet: (s: Set<string>) => void) => (
    <fieldset className="ronde__set">
      <legend className="oa-label">{titel}</legend>
      {klaar.map((m) => (
        <label key={m.bron.sleutel} className="model-list__toggle">
          <input type="checkbox" checked={set.has(m.bron.sleutel)} onChange={() => zet(wissel(set, m.bron.sleutel))} />
          <span className="model-list__name">{m.naam}</span>
        </label>
      ))}
    </fieldset>
  );

  const kaart = (id: string, beschikbaar: boolean, reden: string | null, inhoud?: React.ReactNode) => (
    <label key={id} className="start-card" data-disabled={!beschikbaar} aria-current={gekozen === id}>
      <span className="start-card__kop">
        <input type="radio" name="voorinstelling" checked={gekozen === id} disabled={!beschikbaar} onChange={() => setGekozen(id)} />
        <strong>{t(`voorinstelling.${id}.titel`)}</strong>
      </span>
      <span className="start-card__uitleg">{t(`voorinstelling.${id}.uitleg`)}</span>
      {reden && <span className="start-card__reden">{t(reden)}</span>}
      {inhoud}
    </label>
  );

  return (
    <div className="issue issue--nieuw">
      <div className="inspector__title">
        <strong>{t("ronde_nieuw")}</strong>
        <span>{t("start_uitleg")}</span>
      </div>
      <div className="issue__formulier">
        <div className="start-cards">
          {keuzes.map((k) =>
            kaart(
              k.id,
              k.beschikbaar,
              k.reden,
              k.instelbaar && gekozen === k.id ? (
                <span className="oa-field">
                  <span className="oa-label">{t("bijna_mm")}</span>
                  <input
                    className="oa-input"
                    inputMode="decimal"
                    value={bijnaMm}
                    // The card is the label of its radio button: without its own name the field would have none.
                    aria-label={t("bijna_mm")}
                    aria-invalid={bijnaWaarde === null}
                    onChange={(e) => setBijnaMm(e.target.value)}
                  />
                </span>
              ) : undefined,
            ),
          )}
          {kaart(ZELF, true, null)}
        </div>
        {gekozen === ZELF && (
          <>
            {kies(t("set_a"), setA, setSetA)}
            {kies(t("set_b"), setB, setSetB)}
            <fieldset className="ronde__set">
              <legend className="oa-label">{t("soort")}</legend>
              {(["hard", "afstand"] as const).map((s) => (
                <label key={s} className="model-list__toggle">
                  <input type="radio" name="soort" checked={soort === s} onChange={() => setSoort(s)} />
                  <span>{t(`soort_${s}_uitleg`)}</span>
                </label>
              ))}
            </fieldset>
            <label className="oa-field">
              <span className="oa-label">{t("tolerantie_mm")}</span>
              <input className="oa-input" inputMode="decimal" value={mm} aria-invalid={zelfWaarde === null} onChange={(e) => setMm(e.target.value)} />
            </label>
          </>
        )}
        {mmFout && <p className="viewer__error">{t("mm_ongeldig")}</p>}
        {waarschuwing && <p className="issue__waarschuwing">{t("overlap_waarschuwing")}</p>}
        {ontbreekt.length > 0 && (
          <p className="issue__waarschuwing" data-melding="niet-gereed">
            {t("niet_gereed", { count: ontbreekt.length, namen: ontbreekt.join(", ") })}
          </p>
        )}
        {fout && <p className="viewer__error">{fout}</p>}
        <div className="issues__balk">
          <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" onClick={() => void onKlaar(null)} disabled={bezig}>
            {t("annuleren")}
          </button>
          <button type="button" className="oa-btn oa-btn--primary oa-btn--sm" onClick={() => void start()} disabled={bezig || !geldig}>
            {t("ronde_starten")}
          </button>
        </div>
      </div>
    </div>
  );
}
