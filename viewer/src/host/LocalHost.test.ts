import { afterEach, describe, expect, test, vi } from "vitest";
import { HostError, sourceKey, type ModelSource } from "./BimHost";
import { LocalHost } from "./LocalHost";

const bron: ModelSource = { soort: "bestand", sleutel: "Installaties/kanaal één.ifc", versie: "0123456789ab" };

function respond(body: BodyInit | null, init: ResponseInit = {}) {
  const fetchMock = vi.fn(async (_url: string | URL | Request, _init?: RequestInit) => new Response(body, init));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("LocalHost", () => {
  test("project calls /lokaal/project", async () => {
    const project = { project: "P", werkwijze: "bestanden", modellen: [{ bron, naam: "kanaal één" }] };
    const fetchMock = respond(JSON.stringify(project), { headers: { "Content-Type": "application/json" } });
    expect((await new LocalHost("http://x").project()).modellen).toHaveLength(1);
    expect(String(fetchMock.mock.calls[0][0])).toBe("http://x/lokaal/project");
  });

  test("laad returns the bytes of the part", async () => {
    const fetchMock = respond(new Uint8Array([1, 2, 3]));
    const buf = await new LocalHost("http://x").laad(bron, "deel-2.frag");
    expect(new Uint8Array(buf)[0]).toBe(1);
    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.pathname).toBe("/lokaal/laad");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      sleutel: bron.sleutel,
      versie: bron.versie,
      deel: "deel-2.frag",
    });
  });

  test("eigenschappen posts the source and the GlobalIds", async () => {
    const elementen = { abc: { klasse: "IfcWall" } };
    const fetchMock = respond(JSON.stringify({ elementen }), { headers: { "Content-Type": "application/json" } });
    expect(await new LocalHost("http://x").eigenschappen(bron, ["abc"])).toEqual(elementen);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://x/lokaal/eigenschappen");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ bron, globalids: ["abc"] });
  });

  test("an error answer becomes a HostError with the kern's message", async () => {
    const fout = { error_code: "nog_niet_klaar", melding: "Nog niet omgezet.", remedie: "Wacht." };
    respond(JSON.stringify(fout), { status: 409, headers: { "Content-Type": "application/json" } });
    const error = await new LocalHost("http://x").laad(bron, "model.frag").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(HostError);
    expect((error as HostError).status).toBe(409);
    expect((error as HostError).fout?.error_code).toBe("nog_niet_klaar");
  });

  test("defaults to the local server on 127.0.0.1:8740", async () => {
    const fetchMock = respond(JSON.stringify({ modellen: [] }), { headers: { "Content-Type": "application/json" } });
    await new LocalHost().project();
    expect(String(fetchMock.mock.calls[0][0])).toBe("http://127.0.0.1:8740/lokaal/project");
  });
});

test("sourceKey includes version", () => {
  expect(sourceKey({ soort: "bestand", sleutel: "a.ifc", versie: "abc" })).toBe("bestand:a.ifc@abc");
});
