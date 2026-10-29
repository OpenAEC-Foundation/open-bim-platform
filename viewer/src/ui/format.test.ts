import { expect, test } from "vitest";
import { HostError } from "../host/BimHost";
import { describe as describeError, formatBytes, formatValue, isNoFolder } from "./format";

test("formatBytes uses binary units in the reader's language", () => {
  expect(formatBytes(2 * 1024 ** 3, "nl")).toBe("2 GB");
  expect(formatBytes(1.5 * 1024 ** 2, "nl")).toBe("1,5 MB");
  expect(formatBytes(1.5 * 1024 ** 2, "en")).toBe("1.5 MB");
  expect(formatBytes(12, "nl")).toBe("12 B");
});

test("formatValue", () => {
  expect(formatValue(true, "nl", "Ja", "Nee")).toBe("Ja");
  expect(formatValue(2.5, "nl", "Ja", "Nee")).toBe("2,5");
  expect(formatValue(["a", 1], "nl", "Ja", "Nee")).toBe("a, 1");
  expect(formatValue(null, "nl", "Ja", "Nee")).toBe("");
});

test("describe shows the kern's message and remedy", () => {
  const error = new HostError(409, { error_code: "x", melding: "Nog niet klaar.", remedie: "Wacht even." });
  expect(describeError(error)).toBe("Nog niet klaar. Wacht even.");
});

test("isNoFolder recognises a host without a model folder", () => {
  expect(isNoFolder(new HostError(0, { error_code: "geen_map", melding: "Kies eerst een modelmap.", remedie: "" }))).toBe(true);
  expect(isNoFolder(new HostError(0, { error_code: "werkplek", melding: "Weg.", remedie: "" }))).toBe(false);
  expect(isNoFolder(new Error("geen_map"))).toBe(false);
});
