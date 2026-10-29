import { expect, test } from "@playwright/test";
import { LOKAAL } from "../playwright.config";

type TreeNode = { globalid: string; klasse: string; naam: string | null; kinderen: TreeNode[] };
type Model = {
  bron: { soort: "bestand"; sleutel: string; versie: string };
  status: string;
  index: { omzetter: string } | null;
};

function* walk(node: TreeNode): Generator<TreeNode> {
  yield node;
  for (const child of node.kinderen) yield* walk(child);
}

test("converts two models, loads them and shows the properties of a wall", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));

  expect((await request.post(`${LOKAAL}/lokaal/omzetten`)).ok()).toBe(true);
  const models = async (): Promise<Model[]> => (await (await request.get(`${LOKAAL}/lokaal/project`)).json()).modellen;
  await expect
    .poll(async () => (await models()).map((m) => m.status), { timeout: 180_000, intervals: [1_000] })
    .toEqual(["klaar", "klaar"]);

  await page.goto("/");
  await expect(page.locator('.model-list__item[data-geladen="true"]')).toHaveCount(2, { timeout: 60_000 });
  await expect(page.locator(".viewer__canvas canvas")).toHaveCount(1);

  const model = (await models()).find((m) => m.bron.sleutel === "Constructie/wand model.ifc");
  expect(model?.index).toBeTruthy();
  const { bron, index } = model as Model & { index: { omzetter: string } };
  const treePath = `.afgeleid/${bron.sleutel}/${bron.versie}/${index.omzetter}/ruimtelijk.json`;
  const tree: TreeNode = await (await request.get(`${LOKAAL}/lokaal/bestanden/${encodeURI(treePath)}`)).json();
  const wall = [...walk(tree)].find((n) => n.klasse === "IfcWall" && n.naam?.startsWith("Wand A 0"));
  expect(wall).toBeTruthy();

  // Test entry of the development build: select an element as a click in the view would.
  await page.evaluate((selection) => {
    (window as unknown as { __openbimSelect: (s: unknown) => void }).__openbimSelect(selection);
  }, { bron, globalid: wall?.globalid });
  await expect(page.locator(".inspector__row", { hasText: "FireRating" })).toContainText("60");

  expect(errors).toEqual([]);
});
