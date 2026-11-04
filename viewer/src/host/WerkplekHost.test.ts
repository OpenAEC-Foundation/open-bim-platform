import { describe, expect, test, vi } from "vitest";
import { HostError, type ModelSource } from "./BimHost";
import { WerkplekHost, type WerkplekKanaal } from "./WerkplekHost";

const bron: ModelSource = { soort: "bestand", sleutel: "bestand-123", versie: "3" };

function kanaal(antwoord: (soort: string, extra?: Record<string, unknown>) => unknown) {
  const vraag = vi.fn(async (soort: string, extra?: Record<string, unknown>) => antwoord(soort, extra));
  return { kanaal: { vraag } satisfies WerkplekKanaal, vraag };
}

describe("WerkplekHost", () => {
  test("project asks bim.project", async () => {
    const { kanaal: k, vraag } = kanaal(() => ({ project: "P", werkwijze: "bestanden", modellen: [] }));
    expect((await new WerkplekHost(k).project()).project).toBe("P");
    expect(vraag).toHaveBeenCalledWith("bim.project", undefined);
  });

  test("laad asks bim.laad with the source and part, and returns the bytes", async () => {
    const { kanaal: k, vraag } = kanaal(() => ({ bytes: new Uint8Array([7, 8]).buffer }));
    const bytes = await new WerkplekHost(k).laad(bron, "deel-2.frag");
    expect(new Uint8Array(bytes)).toEqual(new Uint8Array([7, 8]));
    expect(vraag).toHaveBeenCalledWith("bim.laad", { bron, deel: "deel-2.frag" });
  });

  test("laad without bytes is an error", async () => {
    const { kanaal: k } = kanaal(() => ({}));
    await expect(new WerkplekHost(k).laad(bron, "model.frag")).rejects.toBeInstanceOf(HostError);
  });

  test("eigenschappen asks bim.eigenschappen", async () => {
    const { kanaal: k, vraag } = kanaal(() => ({ abc: { klasse: "IfcWall" } }));
    expect(await new WerkplekHost(k).eigenschappen(bron, ["abc"])).toEqual({ abc: { klasse: "IfcWall" } });
    expect(vraag).toHaveBeenCalledWith("bim.eigenschappen", { bron, globalids: ["abc"] });
  });

  test("an error of the guest page keeps its code", async () => {
    const { kanaal: k } = kanaal(() => {
      throw Object.assign(new Error("Nog niet omgezet."), { code: "nog_niet_klaar" });
    });
    const fout = await new WerkplekHost(k).laad(bron, "model.frag").catch((e: unknown) => e);
    expect(fout).toBeInstanceOf(HostError);
    expect((fout as HostError).fout).toEqual({ error_code: "nog_niet_klaar", melding: "Nog niet omgezet.", remedie: "" });
  });

  test("fromWindow uses the channel of the workspace bridge, if there is one", () => {
    const { kanaal: k } = kanaal(() => null);
    expect(WerkplekHost.fromWindow({ werkplekBim: k } as unknown as Window)).toBeInstanceOf(WerkplekHost);
    expect(WerkplekHost.fromWindow({} as Window)).toBeNull();
  });

  test("coordinatie sends bim.issue_bewaar and returns the topic", async () => {
    const topic = { guid: "a0c1f6a2-5a40-4b8e-9d60-1c0f4b1c0001", title: "Wand" };
    const { kanaal: k, vraag } = kanaal(() => topic);
    expect(await new WerkplekHost(k).coordinatie.issueBewaar({ title: "Wand" })).toEqual(topic);
    expect(vraag).toHaveBeenCalledWith("bim.issue_bewaar", { topic: { title: "Wand" } });
  });

  test("coordinatie passes guids, rounds and clashes to the guest page", async () => {
    const { kanaal: k, vraag } = kanaal(() => []);
    const c = new WerkplekHost(k).coordinatie;
    await c.reacties("g1");
    await c.standpunten("g1");
    await c.standpuntBewaar("g1", { perspective_camera: undefined });
    await c.botsingStatus("x1", "genegeerd");
    expect(vraag).toHaveBeenCalledWith("bim.reacties", { guid: "g1" });
    expect(vraag).toHaveBeenCalledWith("bim.standpunten", { guid: "g1" });
    expect(vraag).toHaveBeenCalledWith("bim.standpunt_bewaar", { guid: "g1", standpunt: { perspective_camera: undefined } });
    expect(vraag).toHaveBeenCalledWith("bim.botsing_status", { botsing: "x1", status: "genegeerd" });
  });

  test("botsingsrondeControles sends the checks and the preset, and the title only when given", async () => {
    const { kanaal: k, vraag } = kanaal(() => ({ ronde: "r1" }));
    const c = new WerkplekHost(k).coordinatie;
    const controles = [{ set_a: [{ bestand: "b1" }], set_b: [{ bestand: "b2", klassen: ["IfcDuctSegment"] }], soort: "hard" as const, tolerantie: 0.01 }];
    expect(await c.botsingsrondeControles(controles, "harde")).toEqual({ ronde: "r1" });
    expect(vraag).toHaveBeenLastCalledWith("bim.botsingsronde_start", { controles, voorinstelling: "harde" });
    await c.botsingsrondeControles(controles, null, "Mijn ronde");
    expect(vraag).toHaveBeenLastCalledWith("bim.botsingsronde_start", { controles, voorinstelling: null, titel: "Mijn ronde" });
  });

  test("botsingStatus sends the reason only when there is one", async () => {
    const { kanaal: k, vraag } = kanaal(() => ({}));
    const c = new WerkplekHost(k).coordinatie;
    await c.botsingStatus("x1", "genegeerd", "dubbel geteld");
    expect(vraag).toHaveBeenLastCalledWith("bim.botsing_status", { botsing: "x1", status: "genegeerd", reden: "dubbel geteld" });
    await c.botsingStatus("x1", "bevestigd");
    expect(vraag).toHaveBeenLastCalledWith("bim.botsing_status", { botsing: "x1", status: "bevestigd" });
  });

  test("botsingStatusVeel, settings and trends send their messages", async () => {
    const { kanaal: k, vraag } = kanaal(() => []);
    const c = new WerkplekHost(k).coordinatie;
    await c.botsingStatusVeel(["x1", "x2"], "genegeerd", "ruis");
    expect(vraag).toHaveBeenLastCalledWith("bim.botsing_status_veel", { botsingen: ["x1", "x2"], status: "genegeerd", reden: "ruis" });
    await c.botsingStatusVeel(["x1"], "geaccepteerd");
    expect(vraag).toHaveBeenLastCalledWith("bim.botsing_status_veel", { botsingen: ["x1"], status: "geaccepteerd" });
    await c.botsingInstellingen();
    expect(vraag).toHaveBeenLastCalledWith("bim.botsing_instellingen", undefined);
    await c.botsingInstellingenBewaar({ regels: [{ a: "a", b: "b", soort: "hard", mm: 0, ernst: null }] });
    expect(vraag).toHaveBeenLastCalledWith("bim.botsing_instellingen_bewaar", { regels: [{ a: "a", b: "b", soort: "hard", mm: 0, ernst: null }] });
    await c.botsingInstellingenBewaar({ weergaven: [] });
    expect(vraag).toHaveBeenLastCalledWith("bim.botsing_instellingen_bewaar", { weergaven: [] });
    await c.botsingTrends("r1");
    expect(vraag).toHaveBeenLastCalledWith("bim.botsing_trends", { ronde: "r1" });
  });

  test("a cancelled import is null", async () => {
    const { kanaal: k } = kanaal(() => null);
    expect(await new WerkplekHost(k).coordinatie.bcfImport()).toBeNull();
  });

  test("a field of the bridge envelope (soort, id, werkplek) never travels in a request", async () => {
    const { kanaal: k, vraag } = kanaal(() => null);
    const host = new WerkplekHost(k);
    await expect(
      (host as unknown as { vraag(s: string, e: Record<string, unknown>): Promise<unknown> }).vraag("bim.x", { soort: "hard" }),
    ).rejects.toBeInstanceOf(HostError);
    expect(vraag).not.toHaveBeenCalled();
  });
});
