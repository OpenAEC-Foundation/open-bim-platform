import { Icon, uiRefresh, viewFitAll, viewLoadModel } from "@openaec/icons";
import { StatusBar, StatusItem, TitleBar } from "@openaec/shell";
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { useTranslation } from "react-i18next";
import { FragmentsEngine } from "../engine/FragmentsEngine";
import { sourceKey, type BimHost, type ModelInfo, type ModelSource, type Project } from "../host/BimHost";
import { DEFAULT_BUDGET, planLoad, switchOnNewlyReady } from "../model/budget";
import type { Vec3, Viewpoint } from "../model/bcf";
import type { Selection } from "../model/selection";
import { ClashPanel } from "./ClashPanel";
import { describe, isNoFolder } from "./format";
import { IssuesPanel } from "./IssuesPanel";
import { ModelList } from "./ModelList";
import { PropertiesPanel } from "./PropertiesPanel";
import type { ElementRef, Weergave } from "./weergave";

export const VERSION = "0.1.0";
const POLL_MS = 5000;
const CLICK_TOLERANCE_PX = 4;

/** Engine key of one part of a model version. */
export function partKey(bron: ModelSource, deel: string): string {
  return `${sourceKey(bron)}/${deel}`;
}

function withKey(set: Set<string>, key: string): Set<string> {
  return new Set(set).add(key);
}

type Tab = "eigenschappen" | "issues" | "botsingen";

function withoutKey(set: Set<string>, key: string): Set<string> {
  const next = new Set(set);
  next.delete(key);
  return next;
}

export function App({ host, budget = DEFAULT_BUDGET }: { host: BimHost; budget?: number }) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<FragmentsEngine | null>(null);
  /** sourceKey → engine keys of its loaded parts. */
  const partsRef = useRef(new Map<string, string[]>());
  /** engine key of a part → its model version. */
  const sourcesRef = useRef(new Map<string, ModelSource>());
  /** Engine work runs one step at a time, in order. */
  const queueRef = useRef<Promise<void>>(Promise.resolve());
  const plannedRef = useRef(false);
  /** Models that were ready at a plan: from then on their switch is the user's. */
  const seenReadyRef = useRef<Set<string>>(new Set());
  const pointerRef = useRef<{ x: number; y: number } | null>(null);

  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [noFolder, setNoFolder] = useState(false);
  /** Models switched on, by sleutel: switching on a model means its current version. */
  const [enabled, setEnabled] = useState<Set<string>>(new Set());
  const [loaded, setLoaded] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState<Set<string>>(new Set());
  const [selection, setSelection] = useState<Selection | null>(null);
  const [tab, setTab] = useState<Tab>("eigenschappen");
  const selectionRef = useRef<Selection | null>(null);

  useEffect(() => {
    const engine = new FragmentsEngine(canvasRef.current as HTMLDivElement);
    engineRef.current = engine;
    return () => {
      engine.dispose();
      engineRef.current = null;
      partsRef.current.clear();
      sourcesRef.current.clear();
      setLoaded(new Set());
    };
  }, []);

  const refresh = useCallback(async () => {
    try {
      setProject(await host.project());
      setError(null);
      setNoFolder(false);
    } catch (e) {
      if (isNoFolder(e)) setNoFolder(true);
      else setError(t("project_fout", { melding: describe(e) }));
    }
  }, [host, t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // While models are being converted, ask again now and then.
  const converting = project?.modellen.some((m) => m.status === "wacht" || m.status === "bezig") ?? false;
  useEffect(() => {
    if (!converting) return;
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [converting, refresh]);

  // The first time models are ready, switch on what fits in the budget; after that the switches are the user's. A
  // model that becomes ready later (the project was opened while it was being converted) is switched on when it fits
  // next to what is on.
  useEffect(() => {
    if (!project) return;
    const ready = project.modellen.filter((m) => m.status === "klaar").map((m) => m.bron.sleutel);
    if (!ready.length) return;
    if (!plannedRef.current) {
      plannedRef.current = true;
      seenReadyRef.current = new Set(ready);
      setEnabled(new Set(planLoad(project.modellen, budget).load.map((m) => m.bron.sleutel)));
      return;
    }
    if (ready.every((key) => seenReadyRef.current.has(key))) return;
    const added = switchOnNewlyReady(project.modellen, enabled, seenReadyRef.current, budget);
    for (const key of ready) seenReadyRef.current.add(key);
    if (added.length) setEnabled(new Set([...enabled, ...added.map((m) => m.bron.sleutel)]));
  }, [project, budget, enabled]);

  // Bring the engine in line with the switches: unload what is off, load what is on.
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine || !project) return;
    const wanted = new Map<string, ModelInfo>();
    for (const model of project.modellen) {
      if (model.status === "klaar" && enabled.has(model.bron.sleutel)) wanted.set(sourceKey(model.bron), model);
    }
    queueRef.current = queueRef.current.then(async () => {
      if (engineRef.current !== engine) return;
      for (const [key, parts] of [...partsRef.current]) {
        if (wanted.has(key)) continue;
        for (const part of parts) {
          await engine.unload(part);
          sourcesRef.current.delete(part);
        }
        partsRef.current.delete(key);
        setLoaded((previous) => withoutKey(previous, key));
      }
      const wasEmpty = partsRef.current.size === 0;
      let added = false;
      for (const [key, model] of wanted) {
        if (partsRef.current.has(key)) continue;
        setLoading((previous) => withKey(previous, key));
        const parts: string[] = [];
        try {
          for (const deel of model.delen) {
            const part = partKey(model.bron, deel.naam);
            await engine.load(part, await host.laad(model.bron, deel.naam));
            sourcesRef.current.set(part, model.bron);
            parts.push(part);
          }
          partsRef.current.set(key, parts);
          setLoaded((previous) => withKey(previous, key));
          added = true;
        } catch (e) {
          for (const part of parts) await engine.unload(part);
          setError(describe(e));
        } finally {
          setLoading((previous) => withoutKey(previous, key));
        }
      }
      if (wasEmpty && added) await engine.fit();
    });
  }, [project, enabled, host]);

  // Mark the selected element once its model is in the view.
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine) return;
    const target = selection
      ? { keys: partsRef.current.get(sourceKey(selection.bron)) ?? [], globalid: selection.globalid }
      : null;
    queueRef.current = queueRef.current.then(() => engine.highlight(target)).catch((e) => setError(describe(e)));
  }, [selection, loaded]);

  useEffect(() => {
    selectionRef.current = selection;
  }, [selection]);

  /** What the issue and clash panels may do with the view: camera, selection, snapshot, marking. */
  const weergave = useMemo<Weergave>(() => {
    const targets = (elementen: ElementRef[]) =>
      elementen.map(({ bestand, globalid }) => ({
        globalid,
        keys: [...partsRef.current]
          .filter(([key]) => !bestand || key.startsWith(`bestand:${bestand}@`))
          .flatMap(([, parts]) => parts),
      }));
    const later = (stap: (engine: FragmentsEngine) => Promise<void>) => {
      const engine = engineRef.current;
      if (!engine) return Promise.resolve();
      const klaar = queueRef.current.then(() => stap(engine));
      queueRef.current = klaar.catch((e) => setError(describe(e)));
      return klaar;
    };
    return {
      camera: () => (engineRef.current && partsRef.current.size ? engineRef.current.camera() : null),
      selectie: () => (selectionRef.current ? [selectionRef.current.globalid] : []),
      snapshot: async () => (engineRef.current ? engineRef.current.snapshot() : null),
      toon: (standpunt: Viewpoint | null, elementen: ElementRef[]) =>
        later(async (engine) => {
          if (standpunt?.perspective_camera) await engine.setCamera({ perspective_camera: standpunt.perspective_camera });
          const selectie = (standpunt?.components?.selection ?? []).map((c) => ({ bestand: null, globalid: c.ifc_guid }));
          await engine.highlightMany(targets(elementen.length ? elementen : selectie));
        }),
      focus: (punt: Vec3, elementen: ElementRef[]) =>
        later(async (engine) => {
          await engine.focus(punt, 2);
          await engine.highlightMany(targets(elementen));
        }),
    };
  }, []);

  // Test entry for the browser test (e2e/smoke.spec.ts); it exists only in the development build.
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    const target = window as unknown as { __openbimSelect?: (selection: Selection | null) => void };
    target.__openbimSelect = setSelection;
    return () => {
      delete target.__openbimSelect;
    };
  }, []);

  const onPointerDown = (event: PointerEvent) => {
    pointerRef.current = { x: event.clientX, y: event.clientY };
  };
  const onPointerUp = async (event: PointerEvent) => {
    const start = pointerRef.current;
    pointerRef.current = null;
    // A drag turns the camera; only a click selects.
    if (!start || Math.hypot(event.clientX - start.x, event.clientY - start.y) > CLICK_TOLERANCE_PX) return;
    const hit = await engineRef.current?.pick(event.clientX, event.clientY);
    const bron = hit ? sourcesRef.current.get(hit.key) : undefined;
    setSelection(hit && bron ? { bron, globalid: hit.globalid } : null);
  };

  const toggle = (model: ModelInfo, on: boolean) =>
    setEnabled((previous) => (on ? withKey(previous, model.bron.sleutel) : withoutKey(previous, model.bron.sleutel)));

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
      <div className="viewer__body viewer__body--inspector">
        <aside className="oa-sidebar viewer__sidebar" aria-label={t("modellen")}>
          <div className="oa-sidebar__header">
            <span className="oa-sidebar__section-label">{t("modellen")}</span>
          </div>
          {error && <p className="viewer__error">{error}</p>}
          {noFolder && <p className="viewer__hint">{t("geen_map")}</p>}
          {!project && !error && !noFolder && <p className="viewer__hint">{t("project_laden")}</p>}
          {project && models.length === 0 && <p className="viewer__hint">{t("geen_modellen")}</p>}
          {models.length > 0 && (
            <ModelList
              models={models}
              budget={budget}
              enabled={enabled}
              loaded={loaded}
              loading={loading}
              onToggle={toggle}
            />
          )}
        </aside>
        <main
          className="viewer__canvas"
          ref={canvasRef}
          onPointerDown={onPointerDown}
          onPointerUp={(event) => void onPointerUp(event)}
        >
          {loaded.size === 0 && (
            <div className="viewer__empty">
              <Icon svg={viewLoadModel} size={48} />
              <strong>{t("leeg_titel")}</strong>
              <span>{t("leeg_hint")}</span>
            </div>
          )}
        </main>
        <div className="rechts">
          {host.coordinatie && (
            <div className="tabs" role="tablist" aria-label={t("panelen")}>
              {(["eigenschappen", "issues", "botsingen"] as Tab[]).map((naam) => (
                <button
                  key={naam}
                  type="button"
                  role="tab"
                  className="tabs__tab"
                  aria-selected={tab === naam}
                  onClick={() => setTab(naam)}
                >
                  {t(`tab_${naam}`)}
                </button>
              ))}
            </div>
          )}
          {(tab === "eigenschappen" || !host.coordinatie) && <PropertiesPanel host={host} selection={selection} />}
          {tab === "issues" && host.coordinatie && (
            <aside className="inspector" aria-label={t("tab_issues")}>
              <IssuesPanel coordinatie={host.coordinatie} weergave={weergave} modellen={models} />
            </aside>
          )}
          {tab === "botsingen" && host.coordinatie && (
            <aside className="inspector" aria-label={t("tab_botsingen")}>
              <ClashPanel coordinatie={host.coordinatie} weergave={weergave} modellen={models} />
            </aside>
          )}
        </div>
      </div>
      <StatusBar
        left={<StatusItem>{t("geladen", { aantal: loaded.size, totaal: models.length })}</StatusItem>}
        right={<StatusItem>{`v${VERSION}`}</StatusItem>}
      />
    </div>
  );
}
