import { Icon, uiClose } from "@openaec/icons";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Coordinatie } from "../host/BimHost";
import type { Clash, ClashFilter, ClashGroupBy, ClashSettings } from "../model/bcf";
import {
  type FilterChip,
  type Facetten,
  GROEPERINGEN,
  actieveWeergave,
  facetten,
  filterChips,
  filterUitWeergave,
  groepUitWeergave,
  schoneWeergaven,
  zonderChip,
} from "../model/clashes";
import { describe } from "./format";

const VELDEN: (keyof Facetten)[] = ["ernst", "status", "categorie", "disciplines", "verdieping", "ontwikkeling"];
const VERTAALD: Partial<Record<keyof Facetten, string>> = { ernst: "ernst", status: "botsing_status", ontwikkeling: "ontwikkeling" };

/** Filters with counts, removable chips, saved views and the grouping of the clash list. */
export function ClashFilters({
  coordinatie,
  botsingen,
  filter,
  onFilter,
  groep,
  onGroep,
  instellingen,
  onInstellingen,
}: {
  coordinatie: Coordinatie;
  botsingen: Clash[];
  filter: ClashFilter;
  onFilter: (filter: ClashFilter) => void;
  groep: ClashGroupBy;
  onGroep: (groep: ClashGroupBy) => void;
  instellingen: ClashSettings;
  onInstellingen: (instellingen: ClashSettings) => void;
}) {
  const { t } = useTranslation();
  const aantallen = useMemo(() => facetten(botsingen, filter), [botsingen, filter]);
  const [naam, setNaam] = useState<string | null>(null);
  const [gekozen, setGekozen] = useState<string | null>(null);
  const [fout, setFout] = useState<string | null>(null);
  const loopt = useRef(false);

  const waardeNaam = (veld: keyof Facetten, waarde: string) => (VERTAALD[veld] ? t(`${VERTAALD[veld]}.${waarde}`) : waarde);
  const chipNaam = (chip: FilterChip) => (chip.veld === "tekst" ? `"${chip.waarde}"` : `${t(`filter_veld.${chip.veld}`)}: ${waardeNaam(chip.veld, chip.waarde)}`);

  const actief = actieveWeergave(instellingen.weergaven, gekozen, filter, groep);

  const bewaar = async () => {
    const schoon = (naam ?? "").trim();
    if (!schoon || loopt.current) return;
    loopt.current = true;
    setFout(null);
    try {
      const weergaven = [...schoneWeergaven(instellingen.weergaven).filter((v) => v.naam !== schoon), { naam: schoon, filter, groep }];
      onInstellingen(await coordinatie.botsingInstellingenBewaar({ weergaven }));
      setNaam(null);
      setGekozen(schoon);
    } catch (e) {
      setFout(describe(e));
    } finally {
      loopt.current = false;
    }
  };

  const verwijder = async () => {
    if (!actief || loopt.current) return;
    loopt.current = true;
    setFout(null);
    try {
      const weergaven = schoneWeergaven(instellingen.weergaven).filter((v) => v.naam !== actief.naam);
      onInstellingen(await coordinatie.botsingInstellingenBewaar({ weergaven }));
      setGekozen(null);
    } catch (e) {
      setFout(describe(e));
    } finally {
      loopt.current = false;
    }
  };

  const chips = filterChips(filter);
  return (
    <div className="botsing__filters">
      <div className="issues__filter">
        <input
          className="oa-input"
          type="search"
          data-filter="tekst"
          aria-label={t("filter_zoek")}
          placeholder={t("filter_zoek")}
          value={filter.tekst}
          onChange={(e) => onFilter({ ...filter, tekst: e.target.value })}
        />
      </div>
      <div className="issues__filter">
        {VELDEN.map((veld) => {
          const opties = Object.entries(aantallen[veld])
            .filter(([waarde]) => !(filter[veld] as string[]).includes(waarde))
            .sort(([a, x], [b, y]) => y - x || a.localeCompare(b));
          return (
            <select
              key={veld}
              className="oa-input"
              data-filter={veld}
              aria-label={t(`filter_veld.${veld}`)}
              value=""
              disabled={opties.length === 0}
              onChange={(e) => e.target.value && onFilter({ ...filter, [veld]: [...filter[veld], e.target.value] })}
            >
              <option value="">{t(`filter_veld.${veld}`)}</option>
              {opties.map(([waarde, aantal]) => (
                <option key={waarde} value={waarde}>
                  {t("filter_optie", { waarde: waardeNaam(veld, waarde), aantal })}
                </option>
              ))}
            </select>
          );
        })}
      </div>
      {chips.length > 0 && (
        <div className="issues__filter botsing__chips">
          {chips.map((chip) => (
            <button
              key={`${chip.veld}:${chip.waarde}`}
              type="button"
              className="oa-badge oa-badge--neutral botsing__chip"
              data-chip={chip.veld}
              aria-label={t("filter_chip_weg", { label: chipNaam(chip) })}
              onClick={() => onFilter(zonderChip(filter, chip))}
            >
              {chipNaam(chip)} <Icon svg={uiClose} size={12} />
            </button>
          ))}
        </div>
      )}
      <div className="issues__filter">
        <select className="oa-input" data-filter="groep" aria-label={t("groeperen_op")} value={groep} onChange={(e) => onGroep(e.target.value as ClashGroupBy)}>
          {GROEPERINGEN.map((g) => (
            <option key={g} value={g}>
              {t("groeperen_op")}: {t(`groep_door.${g}`)}
            </option>
          ))}
        </select>
        <select
          className="oa-input"
          data-filter="weergave"
          aria-label={t("weergave_kies")}
          value={actief?.naam ?? ""}
          disabled={instellingen.weergaven.length === 0}
          onChange={(e) => {
            const weergave = instellingen.weergaven.find((v) => v.naam === e.target.value);
            setGekozen(weergave?.naam ?? null);
            if (!weergave) return;
            onFilter(filterUitWeergave(weergave.filter));
            onGroep(groepUitWeergave(weergave.groep));
          }}
        >
          <option value="">{t("weergave_kies")}</option>
          {instellingen.weergaven.map((v) => (
            <option key={v.naam} value={v.naam}>
              {v.naam}
            </option>
          ))}
        </select>
        {instellingen.mag_wijzigen && naam === null && (
          <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" data-actie="weergave-bewaren" onClick={() => setNaam("")}>
            {t("weergave_bewaren")}
          </button>
        )}
        {instellingen.mag_wijzigen && actief && (
          <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" data-actie="weergave-verwijderen" onClick={() => void verwijder()}>
            {t("weergave_verwijderen")}
          </button>
        )}
      </div>
      {instellingen.mag_wijzigen && naam !== null && (
        <div className="issues__filter">
          <input
            className="oa-input"
            data-filter="weergave-naam"
            autoFocus
            aria-label={t("weergave_naam")}
            placeholder={t("weergave_naam")}
            value={naam}
            onChange={(e) => setNaam(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void bewaar();
              else if (e.key === "Escape") setNaam(null);
            }}
          />
          <button type="button" className="oa-btn oa-btn--primary oa-btn--sm" disabled={!naam.trim()} onClick={() => void bewaar()}>
            {t("opslaan")}
          </button>
          <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" onClick={() => setNaam(null)}>
            {t("annuleren")}
          </button>
        </div>
      )}
      {fout && <p className="viewer__error botsing__melding">{fout}</p>}
    </div>
  );
}
