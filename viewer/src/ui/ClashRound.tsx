import { Icon, uiChevronDown, uiChevronLeft, uiChevronRight, uiHelp } from "@openaec/icons";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Coordinatie, ModelInfo } from "../host/BimHost";
import type { Clash, ClashBucket, ClashElement, ClashFilter, ClashGroupBy, ClashRound as RondeGegevens, ClashSettings, ClashStatus } from "../model/bcf";
import {
  GROEPSACTIE_MAX,
  type SneltoetsActie,
  emmerTelling,
  filter as filterRijen,
  groepeer,
  houdVast,
  isZichtbaar,
  leegFilter,
  rondeTelling,
  sneltoets,
  sprongNaBesluit,
  teBeslissen,
  volgende,
  vorige,
  voortgangProcent,
} from "../model/clashes";
import { ClashFilters } from "./ClashFilters";
import { ClashRow, RedenVeld } from "./ClashRow";
import { ClashTrends } from "./ClashTrends";
import { describe } from "./format";
import type { Weergave } from "./weergave";

const EMMERS: ClashBucket[] = ["beoordelen", "contact", "aangrenzend"];
const PER_KEER = 100;
const TOETSEN: [string, SneltoetsActie][] = [
  ["J, ↓", "volgende"],
  ["K, ↑", "vorige"],
  ["B", "bevestigen"],
  ["A", "accepteren"],
  ["X", "afwijzen"],
  ["Esc", "alles_tonen"],
  ["?", "hulp"],
];

type GroepsActie = { sleutel: string; status: "geaccepteerd" | "genegeerd" };

/** The view is not awaited: the app reports its own failures. */
function wis(belofte: Promise<void>) {
  belofte.catch(() => undefined);
}

/** A round as a worklist: buckets, filters, groups, rows with their decisions, and the shortcuts. */
export function ClashRound({
  coordinatie,
  weergave,
  ronde,
  modellen,
  instellingen,
  onInstellingen,
  onTerug,
}: {
  coordinatie: Coordinatie;
  weergave: Weergave;
  ronde: RondeGegevens;
  modellen: ModelInfo[];
  instellingen: ClashSettings;
  onInstellingen: (instellingen: ClashSettings) => void;
  onTerug: () => void;
}) {
  const { t } = useTranslation();
  const mag = instellingen.mag_wijzigen;
  const [botsingen, setBotsingen] = useState<Clash[] | null>(null);
  const [laadFout, setLaadFout] = useState<string | null>(null);
  const [filter, setFilter] = useState<ClashFilter>(leegFilter);
  const [groep, setGroep] = useState<ClashGroupBy>("klassen");
  const [gekozen, setGekozen] = useState<string | null>(null);
  const [vast, setVast] = useState<string | null>(null);
  const [afwijzen, setAfwijzen] = useState<string | null>(null);
  const [rijFout, setRijFout] = useState<{ naam: string; melding: string } | null>(null);
  const [bezig, setBezig] = useState(false);
  const [ingeklapt, setIngeklapt] = useState<Set<string>>(new Set());
  const [limieten, setLimieten] = useState<Record<string, number>>({});
  const [groepsActie, setGroepsActie] = useState<GroepsActie | null>(null);
  const [groepFout, setGroepFout] = useState<string | null>(null);
  const [hulp, setHulp] = useState(false);
  const loopt = useRef(false);
  const isoleerd = useRef(false);
  const scrollen = useRef(false);
  const lijstRef = useRef<HTMLDivElement>(null);
  const handler = useRef<(e: KeyboardEvent) => void>(() => undefined);

  useEffect(() => {
    if (ronde.status !== "klaar") return;
    let cancelled = false;
    coordinatie
      .botsingen(ronde.naam)
      .then((lijst) => {
        if (!cancelled) setBotsingen(lijst);
      })
      .catch((e: unknown) => {
        if (!cancelled) setLaadFout(describe(e));
      });
    return () => {
      cancelled = true;
    };
  }, [coordinatie, ronde.naam, ronde.status]);

  // Leaving the round ends the isolated view.
  useEffect(
    () => () => {
      if (isoleerd.current) wis(weergave.herstel());
    },
    [weergave],
  );

  // Shortcuts live as long as this screen; the panel is only mounted while the Botsingen tab is open.
  useEffect(() => {
    const luister = (e: KeyboardEvent) => handler.current(e);
    window.addEventListener("keydown", luister);
    return () => window.removeEventListener("keydown", luister);
  }, []);

  useEffect(() => {
    if (!gekozen || !scrollen.current) return;
    scrollen.current = false;
    lijstRef.current?.querySelector(`[data-botsing="${CSS.escape(gekozen)}"]`)?.scrollIntoView({ block: "nearest" });
  }, [gekozen]);

  const alle = useMemo(() => botsingen ?? [], [botsingen]);
  const emmers = useMemo(() => emmerTelling(alle), [alle]);
  const tel = useMemo(() => rondeTelling(alle), [alle]);
  const getoond = useMemo(() => houdVast(filterRijen(alle, filter), alle, vast), [alle, filter, vast]);
  const groepen = useMemo(() => groepeer(getoond, groep), [getoond, groep]);
  const sleutelVan = (g: string | null) => g ?? "";
  const zichtbaar = groepen.flatMap((g) => (ingeklapt.has(sleutelVan(g.groep)) ? [] : g.botsingen.slice(0, limieten[sleutelVan(g.groep)] ?? PER_KEER)));
  const zichtbaarGekozen = isZichtbaar(zichtbaar, gekozen);
  const rij = zichtbaarGekozen ? (zichtbaar.find((b) => b.naam === gekozen) ?? null) : null;
  const gekozenRef = useRef<string | null>(null);
  gekozenRef.current = gekozen;
  const zetGroepsActie = (actie: GroepsActie | null) => {
    setGroepFout(null);
    setGroepsActie(actie);
  };

  const vervang = (nieuw: Clash[]) =>
    setBotsingen((lijst) => (lijst ?? []).map((x) => nieuw.find((n) => n.naam === x.naam) ?? x));

  const kies = (b: Clash, opties: { auto?: boolean; scroll?: boolean } = {}) => {
    if (!opties.auto) setVast(null);
    scrollen.current = opties.scroll === true;
    isoleerd.current = true;
    setGekozen(b.naam);
    setAfwijzen(null);
    setRijFout(null);
    wis(weergave.isoleer({ bestand: b.element_a.bestand, globalid: b.element_a.globalid }, { bestand: b.element_b.bestand, globalid: b.element_b.globalid }, b.punt));
  };
  const toonAlles = () => {
    isoleerd.current = false;
    setGekozen(null);
    setAfwijzen(null);
    wis(weergave.herstel());
  };
  // A selected row that leaves the shown list (filter, collapsed group) ends the selection.
  useEffect(() => {
    if (gekozen !== null && !zichtbaarGekozen) toonAlles();
  }, [gekozen, zichtbaarGekozen]);
  const beweeg = (richting: 1 | -1) => {
    const naam = (richting === 1 ? volgende : vorige)(zichtbaar, gekozen);
    const b = zichtbaar.find((x) => x.naam === naam);
    if (b && b.naam !== gekozen) kies(b, { scroll: true });
  };

  const beslis = async (b: Clash, status: ClashStatus, reden?: string) => {
    if (!mag || loopt.current) return;
    loopt.current = true;
    setBezig(true);
    setRijFout(null);
    try {
      vervang([await coordinatie.botsingStatus(b.naam, status, reden)]);
      setAfwijzen(null);
      setVast(b.naam);
      const naam = status === "actief" ? null : sprongNaBesluit(zichtbaar, b.naam, gekozenRef.current);
      const volgt = zichtbaar.find((x) => x.naam === naam);
      if (volgt) kies(volgt, { auto: true, scroll: true });
    } catch (e) {
      setRijFout({ naam: b.naam, melding: describe(e) });
    } finally {
      loopt.current = false;
      setBezig(false);
    }
  };

  const beslisGroep = async (rijen: Clash[], status: GroepsActie["status"], reden: string) => {
    const namen = teBeslissen(rijen).map((b) => b.naam);
    if (!mag || loopt.current || namen.length === 0 || namen.length > GROEPSACTIE_MAX) return;
    loopt.current = true;
    setBezig(true);
    setGroepFout(null);
    try {
      vervang(await coordinatie.botsingStatusVeel(namen, status, reden || undefined));
      zetGroepsActie(null);
    } catch (e) {
      setGroepFout(describe(e));
    } finally {
      loopt.current = false;
      setBezig(false);
    }
  };

  handler.current = (e) => {
    if (!botsingen) return;
    const actie = sneltoets(e);
    if (!actie) return;
    const beslisbaar = mag && rij !== null && teBeslissen([rij]).length === 1;
    if (actie === "volgende" || actie === "vorige") {
      e.preventDefault();
      beweeg(actie === "volgende" ? 1 : -1);
    } else if (actie === "bevestigen" && beslisbaar) void beslis(rij, "bevestigd");
    else if (actie === "accepteren" && beslisbaar) void beslis(rij, "geaccepteerd");
    else if (actie === "afwijzen" && beslisbaar) setAfwijzen(rij.naam);
    else if (actie === "hulp") setHulp((h) => !h);
    else if (actie === "alles_tonen") {
      if (afwijzen !== null) setAfwijzen(null);
      else if (groepsActie !== null) zetGroepsActie(null);
      else toonAlles();
    }
  };

  const naam = (sleutel: string) => modellen.find((m) => m.bron.sleutel === sleutel)?.naam ?? sleutel;
  const groepNaam = (waarde: string | null) => {
    if (waarde === null) return t("groep_onbekend");
    if (groep === "ernst") return t(`ernst.${waarde}`, waarde);
    if (groep === "ontwikkeling") return t(`ontwikkeling.${waarde}`, waarde);
    return waarde;
  };
  const inFilter = (emmer: ClashFilter["emmer"]) => setFilter({ ...filter, emmer });
  const naarElement = (e: ClashElement) => wis(weergave.naarElement({ bestand: e.bestand, globalid: e.globalid }));
  const lopend = ronde.status === "wacht" || ronde.status === "bezig";

  return (
    <div className="issue" data-isoleer={gekozen ?? ""}>
      <div className="issue__kop">
        <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" onClick={onTerug}>
          <Icon svg={uiChevronLeft} size={14} /> {t("terug")}
        </button>
        <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" data-actie="sneltoetsen" aria-pressed={hulp} onClick={() => setHulp(!hulp)}>
          <Icon svg={uiHelp} size={14} /> {t("sneltoetsen_knop")}
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
          {lopend && ronde.voortgang != null && ` ${t("ronde_voortgang", { procent: voortgangProcent(ronde.voortgang) })}`}
        </p>
      )}
      {laadFout && <p className="viewer__error">{laadFout}</p>}
      {hulp && (
        <dl className="botsing__hulp" data-sectie="sneltoetsen" aria-label={t("sneltoetsen_titel")}>
          {TOETSEN.map(([toets, actie]) => (
            <div key={actie} className="inspector__row">
              <dt>
                <kbd className="oa-code">{toets}</kbd>
              </dt>
              <dd>{t(`sneltoets.${actie}`)}</dd>
            </div>
          ))}
        </dl>
      )}
      {ronde.status === "klaar" && !botsingen && !laadFout && <p className="viewer__hint">{t("laden")}</p>}
      {botsingen && (
        <>
          <div className="botsing__emmers" role="group" aria-label={t("emmers_label")}>
            {EMMERS.map((emmer) => (
              <button
                key={emmer}
                type="button"
                className="botsing__emmer"
                data-emmer={emmer}
                aria-pressed={filter.emmer === emmer}
                title={t(`emmer_uitleg.${emmer}`)}
                onClick={() => inFilter(emmer)}
              >
                <strong>{emmers[emmer]}</strong> {t(`emmer.${emmer}`)}
              </button>
            ))}
          </div>
          <p className="issues__meta ronde__tel">
            <span>{t("tel_open", { count: tel.open })}</span>
            <span>{t("tel_nieuw", { count: tel.nieuw })}</span>
            <button type="button" className="botsing__weg" data-emmer="weg" aria-pressed={filter.emmer === "weg"} onClick={() => inFilter("weg")}>
              {t("tel_weg", { count: tel.weg })}
            </button>
          </p>
          {ronde.samenvatting?.regels_gewijzigd && <p className="viewer__hint ronde__tel">{t("regels_gewijzigd_uitleg")}</p>}
          <ClashTrends coordinatie={coordinatie} ronde={ronde.naam} />
          <ClashFilters
            coordinatie={coordinatie}
            botsingen={alle}
            filter={filter}
            onFilter={setFilter}
            groep={groep}
            onGroep={setGroep}
            instellingen={instellingen}
            onInstellingen={onInstellingen}
          />
          {!mag && <p className="viewer__hint ronde__tel">{t("beoordelen_alleen_lezen")}</p>}
          {alle.length === 0 && <p className="viewer__hint ronde__tel">{t("ronde_leeg")}</p>}
          {alle.length > 0 && getoond.length === 0 && (
            <div className="botsing__leeg">
              <p className="viewer__hint">{t("leeg_emmer")}</p>
              <button type="button" className="oa-btn oa-btn--secondary oa-btn--sm" data-actie="filters-wissen" onClick={() => setFilter({ ...leegFilter(), emmer: filter.emmer })}>
                {t("filters_wissen")}
              </button>
            </div>
          )}
          <div ref={lijstRef} aria-label={t("botsing_lijst")}>
            {groepen.map(({ groep: waarde, botsingen: rijen }) => {
              const sleutel = sleutelVan(waarde);
              const dicht = ingeklapt.has(sleutel);
              const limiet = limieten[sleutel] ?? PER_KEER;
              const open = teBeslissen(rijen).length;
              const actie = groepsActie?.sleutel === sleutel ? groepsActie : null;
              return (
                <section key={sleutel} className="inspector__section botsing__groep">
                  <h3 className="inspector__section-title botsing__groepkop" data-groep={sleutel}>
                    <button
                      type="button"
                      className="botsing__groepknop"
                      aria-expanded={!dicht}
                      onClick={() =>
                        setIngeklapt((s) => {
                          const nieuw = new Set(s);
                          if (!nieuw.delete(sleutel)) nieuw.add(sleutel);
                          return nieuw;
                        })
                      }
                    >
                      <Icon svg={dicht ? uiChevronRight : uiChevronDown} size={12} /> {groepNaam(waarde)} ({rijen.length})
                    </button>
                  </h3>
                  {mag && open > 0 && !actie && (
                    <div className="botsing__acties">
                      <button
                        type="button"
                        className="oa-btn oa-btn--secondary oa-btn--sm"
                        data-actie="groep-afwijzen"
                        disabled={bezig || open > GROEPSACTIE_MAX}
                        onClick={() => zetGroepsActie({ sleutel, status: "genegeerd" })}
                      >
                        {t("groep_alles_afwijzen")}
                      </button>
                      <button
                        type="button"
                        className="oa-btn oa-btn--secondary oa-btn--sm"
                        data-actie="groep-accepteren"
                        disabled={bezig || open > GROEPSACTIE_MAX}
                        onClick={() => zetGroepsActie({ sleutel, status: "geaccepteerd" })}
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
                        <RedenVeld disabled={bezig} onBevestig={(reden) => void beslisGroep(rijen, actie.status, reden)} onAnnuleer={() => zetGroepsActie(null)} />
                      ) : (
                        <div className="botsing__acties">
                          <button type="button" className="oa-btn oa-btn--primary oa-btn--sm" data-actie="groep-bevestig" disabled={bezig} onClick={() => void beslisGroep(rijen, actie.status, "")}>
                            {t("actie.accepteren")}
                          </button>
                          <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" data-actie="groep-annuleer" disabled={bezig} onClick={() => zetGroepsActie(null)}>
                            {t("annuleren")}
                          </button>
                        </div>
                      )}
                      {groepFout && <p className="viewer__error">{groepFout}</p>}
                    </div>
                  )}
                  {!dicht && (
                    <ul className="issue__lijst">
                      {rijen.slice(0, limiet).map((b) => (
                        <ClashRow
                          key={b.naam}
                          b={b}
                          open={gekozen === b.naam}
                          mag={mag}
                          bezig={bezig}
                          afwijzen={afwijzen === b.naam}
                          fout={rijFout?.naam === b.naam ? rijFout.melding : null}
                          onKies={() => (gekozen === b.naam ? toonAlles() : kies(b))}
                          onBeslis={(status, reden) => void beslis(b, status, reden)}
                          onAfwijzen={(aan) => setAfwijzen(aan ? b.naam : null)}
                          onNaar={naarElement}
                          onAllesTonen={toonAlles}
                        />
                      ))}
                    </ul>
                  )}
                  {!dicht && rijen.length > limiet && (
                    <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" data-actie="meer" onClick={() => setLimieten({ ...limieten, [sleutel]: limiet + PER_KEER })}>
                      {t("meer_tonen", { aantal: rijen.length - limiet })}
                    </button>
                  )}
                </section>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
