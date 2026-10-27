import { Icon, uiRefresh, viewFitAll, viewLoadModel } from "@openaec/icons";
import { StatusBar, StatusItem, TitleBar } from "@openaec/shell";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FragmentsEngine } from "../engine/FragmentsEngine";
import { HostError, sourceKey, type BimHost, type ModelInfo, type ModelSource, type Project } from "../host/BimHost";

export const VERSION = "0.1.0";

/** Engine key of one part of a model version. */
export function partKey(bron: ModelSource, deel: string): string {
  return `${sourceKey(bron)}/${deel}`;
}

export function App({ host }: { host: BimHost }) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<FragmentsEngine | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<Set<string>>(new Set());

  useEffect(() => {
    const engine = new FragmentsEngine(canvasRef.current as HTMLDivElement);
    engineRef.current = engine;
    return () => {
      engine.dispose();
      engineRef.current = null;
    };
  }, []);

  const refresh = useCallback(async () => {
    try {
      setProject(await host.project());
      setError(null);
    } catch (e) {
      setError(t("project_fout", { melding: describe(e) }));
    }
  }, [host, t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!project) return;
    let cancelled = false;
    const ready = project.modellen.filter((m) => m.status === "klaar");
    (async () => {
      for (const model of ready) {
        for (const deel of model.delen) {
          const bytes = await host.laad(model.bron, deel.naam);
          if (cancelled || !engineRef.current) return;
          await engineRef.current.load(partKey(model.bron, deel.naam), bytes);
        }
        if (cancelled) return;
        setLoaded((previous) => new Set(previous).add(sourceKey(model.bron)));
      }
      await engineRef.current?.fit();
    })().catch((e: unknown) => setError(describe(e)));
    return () => {
      cancelled = true;
    };
  }, [project, host]);

  const models = project?.modellen ?? [];
  return (
    <div className="viewer">
      <TitleBar
        appName={project ? `${t("titel")} · ${project.project}` : t("titel")}
        appVersion={VERSION}
        enableWindowControls={false}
        actions={[
          { id: "passend", label: t("passend"), icon: viewFitAll, onClick: () => void engineRef.current?.fit() },
          { id: "vernieuwen", label: t("vernieuwen"), icon: uiRefresh, onClick: () => void refresh() },
        ]}
      />
      <div className="viewer__body">
        <aside className="oa-sidebar viewer__sidebar" aria-label={t("modellen")}>
          <div className="oa-sidebar__header">
            <span className="oa-sidebar__section-label">{t("modellen")}</span>
          </div>
          {error && <p className="viewer__error">{error}</p>}
          {!project && !error && <p className="viewer__hint">{t("project_laden")}</p>}
          {project && models.length === 0 && <p className="viewer__hint">{t("geen_modellen")}</p>}
          <ul className="model-list">
            {models.map((model) => (
              <ModelRow key={sourceKey(model.bron)} model={model} loaded={loaded.has(sourceKey(model.bron))} />
            ))}
          </ul>
        </aside>
        <main className="viewer__canvas" ref={canvasRef}>
          {loaded.size === 0 && (
            <div className="viewer__empty">
              <Icon svg={viewLoadModel} size={48} />
              <strong>{t("leeg_titel")}</strong>
              <span>{t("leeg_hint")}</span>
            </div>
          )}
        </main>
      </div>
      <StatusBar
        left={<StatusItem>{t("geladen", { aantal: loaded.size, totaal: models.length })}</StatusItem>}
        right={<StatusItem>{`v${VERSION}`}</StatusItem>}
      />
    </div>
  );
}

function ModelRow({ model, loaded }: { model: ModelInfo; loaded: boolean }) {
  const { t } = useTranslation();
  return (
    <li className="model-list__item" data-geladen={loaded}>
      <span className="model-list__name">{model.naam}</span>
      <span className="model-list__meta">
        {model.discipline || t("discipline_geen")} · {t(`status.${model.status}`)}
      </span>
    </li>
  );
}

function describe(error: unknown): string {
  if (error instanceof HostError) return error.fout ? `${error.fout.melding} ${error.fout.remedie}` : error.message;
  return error instanceof Error ? error.message : String(error);
}
