import {
  HostError,
  type BimHost,
  type ElementProperties,
  type KernFout,
  type ModelSource,
  type Project,
} from "./BimHost";

/** Host for the local development server (`openbim-kern lokaal <map>`). */
export class LocalHost implements BimHost {
  /** Issues and clashes live in the SuperCloud; locally there is none. */
  readonly coordinatie = undefined;

  constructor(private readonly baseUrl = "http://127.0.0.1:8740") {}

  async project(): Promise<Project> {
    return (await this.request("/lokaal/project")).json();
  }

  async laad(bron: ModelSource, deel: string): Promise<ArrayBuffer> {
    const query = new URLSearchParams({ sleutel: bron.sleutel, versie: bron.versie, deel });
    return (await this.request(`/lokaal/laad?${query}`)).arrayBuffer();
  }

  async eigenschappen(bron: ModelSource, globalids: string[]): Promise<Record<string, ElementProperties>> {
    const response = await this.request("/lokaal/eigenschappen", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bron, globalids }),
    });
    return (await response.json()).elementen;
  }

  private async request(path: string, init?: RequestInit): Promise<Response> {
    const response = await fetch(`${this.baseUrl}${path}`, init);
    if (!response.ok) throw new HostError(response.status, await readError(response));
    return response;
  }
}

async function readError(response: Response): Promise<KernFout | null> {
  try {
    const body = await response.json();
    return typeof body?.error_code === "string" ? (body as KernFout) : null;
  } catch {
    return null;
  }
}
