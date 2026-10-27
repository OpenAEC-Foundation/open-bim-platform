import { useTranslation } from "react-i18next";
import { sourceKey, type ModelInfo, type ModelStatus } from "../host/BimHost";
import { estimateBytes } from "../model/budget";
import { formatBytes } from "./format";

const BADGE: Record<ModelStatus, string> = {
  wacht: "oa-badge--neutral",
  bezig: "oa-badge--info",
  klaar: "oa-badge--success",
  fout: "oa-badge--danger",
};

type Props = {
  models: ModelInfo[];
  budget: number;
  /** Switched-on models, by sleutel. */
  enabled: Set<string>;
  /** Loaded model versions, by sourceKey. */
  loaded: Set<string>;
  loading: Set<string>;
  onToggle: (model: ModelInfo, on: boolean) => void;
};

/** The models of the project with status and version, a switch to load each, and the memory against the budget. */
export function ModelList({ models, budget, enabled, loaded, loading, onToggle }: Props) {
  const { t, i18n } = useTranslation();
  const used = models
    .filter((m) => m.status === "klaar" && enabled.has(m.bron.sleutel))
    .reduce((sum, m) => sum + estimateBytes(m), 0);
  const over = used > budget;
  return (
    <>
      <div className="memory" data-over={over}>
        <div className="memory__label">
          <span>{t("geheugen")}</span>
          <span>
            {t("geheugen_van", {
              gebruikt: formatBytes(used, i18n.language),
              budget: formatBytes(budget, i18n.language),
            })}
          </span>
        </div>
        <div
          className="memory__bar"
          role="meter"
          aria-label={t("geheugen")}
          aria-valuemin={0}
          aria-valuemax={budget}
          aria-valuenow={used}
        >
          <div className="memory__fill" style={{ width: `${Math.min(100, (used / budget) * 100)}%` }} />
        </div>
        {over && <span className="memory__warning">{t("geheugen_over")}</span>}
      </div>
      <ul className="model-list">
        {models.map((model) => {
          const key = sourceKey(model.bron);
          return (
            <ModelRow
              key={key}
              model={model}
              on={enabled.has(model.bron.sleutel)}
              isLoaded={loaded.has(key)}
              isLoading={loading.has(key)}
              onToggle={onToggle}
            />
          );
        })}
      </ul>
    </>
  );
}

type RowProps = {
  model: ModelInfo;
  on: boolean;
  isLoaded: boolean;
  isLoading: boolean;
  onToggle: (model: ModelInfo, on: boolean) => void;
};

function ModelRow({ model, on, isLoaded, isLoading, onToggle }: RowProps) {
  const { t, i18n } = useTranslation();
  const ready = model.status === "klaar";
  const state = !ready
    ? null
    : isLoading || (on && !isLoaded)
      ? t("laden")
      : isLoaded
        ? t("geladen_ja")
        : t("klaar_uit");
  return (
    <li className="model-list__item" data-status={model.status} data-geladen={isLoaded}>
      <label className="model-list__toggle">
        <input
          type="checkbox"
          checked={on}
          disabled={!ready}
          onChange={(event) => onToggle(model, event.target.checked)}
          aria-label={t("aan_uit", { naam: model.naam })}
        />
        <span className="model-list__name" title={model.bron.sleutel}>
          {model.naam}
        </span>
      </label>
      <span className="model-list__meta">
        <span className={`oa-badge ${BADGE[model.status]}`}>{t(`status.${model.status}`)}</span>
        <span>{model.discipline || t("discipline_geen")}</span>
        {state && <span>{state}</span>}
      </span>
      <span className="model-list__meta model-list__version">
        {t("versie", { versie: model.bron.versie })}
        {ready && ` · ${formatBytes(estimateBytes(model), i18n.language)}`}
      </span>
      {model.status === "fout" && model.fout && <span className="model-list__error">{model.fout.melding}</span>}
    </li>
  );
}
