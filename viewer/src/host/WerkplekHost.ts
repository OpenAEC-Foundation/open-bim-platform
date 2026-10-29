import type { Clash, ClashRound, ClashStatus, Comment, Extensions, Topic, Viewpoint } from "../model/bcf";
import {
  HostError,
  type BimHost,
  type Coordinatie,
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
  /** Issues and clashes, as bim.* messages that the guest page executes for the model folder of the page. */
  readonly coordinatie: Coordinatie;

  constructor(private readonly kanaal: WerkplekKanaal) {
    const vraag = <T>(soort: string, extra?: Record<string, unknown>) => this.vraag(soort, extra) as Promise<T>;
    this.coordinatie = {
      instellingen: () => vraag<Extensions>("bim.instellingen"),
      issues: () => vraag<Topic[]>("bim.issues"),
      issueBewaar: (topic) => vraag<Topic>("bim.issue_bewaar", { topic }),
      issueVerwijder: async (guid) => void (await vraag("bim.issue_verwijder", { guid })),
      reacties: (guid) => vraag<Comment[]>("bim.reacties", { guid }),
      reactieBewaar: (guid, reactie) => vraag<Comment>("bim.reactie_bewaar", { guid, reactie }),
      standpuntBewaar: (guid, standpunt) => vraag<Viewpoint>("bim.standpunt_bewaar", { guid, standpunt }),
      snapshot: (guid, standpunt) => vraag("bim.snapshot", { guid, standpunt }),
      bcfExport: (versie) => vraag("bim.bcf_export", { versie }),
      bcfImport: () => vraag("bim.bcf_import"),
      botsingsrondeStart: (set_a, set_b, soort, tolerantie, titel) =>
        vraag("bim.botsingsronde_start", { set_a, set_b, soort, tolerantie, ...(titel ? { titel } : {}) }),
      botsingsrondes: () => vraag<ClashRound[]>("bim.botsingsrondes"),
      botsingen: (ronde) => vraag<Clash[]>("bim.botsingen", { ronde }),
      botsingStatus: (botsing, status: ClashStatus) => vraag<Clash>("bim.botsing_status", { botsing, status }),
      botsingNaarIssue: (botsing) => vraag<Topic>("bim.botsing_naar_issue", { botsing }),
    };
  }

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
