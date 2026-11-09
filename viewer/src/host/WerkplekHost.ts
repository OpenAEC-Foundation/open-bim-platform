import {
  HostError,
  type BimHost,
  type ElementProperties,
  type ModelSource,
  type Project,
} from "./BimHost";

/**
 * The channel to the guest page of the SuperCloud workspace, set up by the workspace bridge in the iframe
 * (`window.werkplekBim`): the bridge checks origins, does the hello handshake and numbers the requests.
 */
export interface WerkplekKanaal {
  vraag(soort: string, extra?: Record<string, unknown>, overdracht?: Transferable[]): Promise<unknown>;
}

declare global {
  interface Window {
    werkplekBim?: WerkplekKanaal;
  }
}

/** Host in the workspace: everything goes through the guest page, which acts with the user's own session. */
export class WerkplekHost implements BimHost {
  constructor(private readonly kanaal: WerkplekKanaal) {}

  /** The workspace channel when the viewer runs in the workspace, otherwise null. */
  static fromWindow(venster: Window = window): WerkplekHost | null {
    return venster.werkplekBim ? new WerkplekHost(venster.werkplekBim) : null;
  }

  async project(): Promise<Project> {
    return (await this.vraag("bim.project")) as Project;
  }

  async laad(bron: ModelSource, deel: string): Promise<ArrayBuffer> {
    const antwoord = (await this.vraag("bim.laad", { bron, deel })) as { bytes?: unknown };
    if (!(antwoord?.bytes instanceof ArrayBuffer)) {
      throw new HostError(0, { error_code: "geen_bytes", melding: "De werkplek gaf geen bytes terug.", remedie: "" });
    }
    return antwoord.bytes;
  }

  async eigenschappen(bron: ModelSource, globalids: string[]): Promise<Record<string, ElementProperties>> {
    return (await this.vraag("bim.eigenschappen", { bron, globalids })) as Record<string, ElementProperties>;
  }

  private async vraag(soort: string, extra?: Record<string, unknown>): Promise<unknown> {
    try {
      return await this.kanaal.vraag(soort, extra);
    } catch (fout) {
      const code = (fout as { code?: unknown } | null)?.code;
      const melding = fout instanceof Error ? fout.message : String(fout);
      throw new HostError(0, { error_code: typeof code === "string" ? code : "werkplek", melding, remedie: "" });
    }
  }
}
