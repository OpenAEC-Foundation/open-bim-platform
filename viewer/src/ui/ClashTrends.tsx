import { Icon, uiChevronDown, uiChevronRight } from "@openaec/icons";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Coordinatie } from "../host/BimHost";
import type { ClashTrend } from "../model/bcf";
import { describe } from "./format";

const BREEDTE = 24;
const HOOGTE = 64;

/** The development over the last rounds, collapsed; it is only fetched the first time it is opened. */
export function ClashTrends({ coordinatie, ronde }: { coordinatie: Coordinatie; ronde: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [ooit, setOoit] = useState(false);
  const [poging, setPoging] = useState(0);
  const [trends, setTrends] = useState<ClashTrend[] | null>(null);
  const [fout, setFout] = useState<string | null>(null);

  useEffect(() => {
    if (!ooit) return;
    let cancelled = false;
    setFout(null);
    coordinatie
      .botsingTrends(ronde)
      .then((lijst) => {
        if (!cancelled) setTrends(lijst);
      })
      .catch((e: unknown) => {
        if (!cancelled) setFout(t("trend_fout", { melding: describe(e) }));
      });
    return () => {
      cancelled = true;
    };
  }, [coordinatie, ronde, ooit, poging, t]);

  const hoogste = Math.max(1, ...(trends ?? []).map((x) => x.samenvatting?.totaal ?? 0));
  const hoogte = (aantal: number) => Math.round((aantal / hoogste) * HOOGTE);

  return (
    <section className="botsing__trend" data-sectie="verloop">
      <button
        type="button"
        className="oa-btn oa-btn--ghost oa-btn--sm"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
          setOoit(true);
        }}
      >
        <Icon svg={open ? uiChevronDown : uiChevronRight} size={14} /> {t("trend_titel")}
      </button>
      {open && fout && (
        <p className="viewer__error">
          {fout}{" "}
          <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" onClick={() => setPoging(poging + 1)}>
            {t("trend_opnieuw")}
          </button>
        </p>
      )}
      {open && !fout && !trends && <p className="viewer__hint">{t("trend_laden")}</p>}
      {open && trends && trends.length === 0 && <p className="viewer__hint">{t("trend_leeg")}</p>}
      {open && trends && trends.length > 0 && (
        <div className="botsing__trend-inhoud">
          <svg
            className="trend__grafiek"
            role="img"
            aria-label={t("trend_grafiek")}
            viewBox={`0 0 ${trends.length * BREEDTE} ${HOOGTE}`}
            preserveAspectRatio="none"
          >
            {trends.map((x, i) => {
              const totaal = hoogte(x.samenvatting?.totaal ?? 0);
              const open_ = hoogte(x.samenvatting?.open ?? 0);
              return (
                <g key={x.naam}>
                  <rect className="trend__totaal" x={i * BREEDTE + 4} y={HOOGTE - totaal} width={BREEDTE - 8} height={totaal} />
                  <rect className="trend__open" x={i * BREEDTE + 4} y={HOOGTE - open_} width={BREEDTE - 8} height={open_} />
                </g>
              );
            })}
          </svg>
          <table className="trend__tabel">
            <thead>
              <tr>
                <th scope="col">{t("trend_kolom.ronde")}</th>
                <th scope="col">{t("trend_kolom.totaal")}</th>
                <th scope="col">{t("trend_kolom.open")}</th>
                <th scope="col">{t("trend_kolom.nieuw")}</th>
                <th scope="col">{t("trend_kolom.weg")}</th>
              </tr>
            </thead>
            <tbody>
              {trends.map((x) => (
                <tr key={x.naam}>
                  <th scope="row">{x.titel}</th>
                  <td>{x.samenvatting?.totaal ?? "–"}</td>
                  <td>{x.samenvatting?.open ?? "–"}</td>
                  <td>{x.samenvatting?.nieuw ?? "–"}</td>
                  <td>{x.samenvatting?.weg ?? "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
