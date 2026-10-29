import { KOPPEL_DREMPEL, type BcfCamera, type Topic, type TopicElement, type TopicInput, type Viewpoint } from "./bcf";

export type TopicFilter = { status?: string; soort?: string; toegewezen?: string; tekst?: string };

/** What the user fills in for a new issue. */
export type IssueForm = {
  title: string;
  topic_type?: string | null;
  priority?: string | null;
  assigned_to?: string | null;
  description?: string | null;
};

/** The topics that match the filter, the most recently changed first. */
export function filterTopics(topics: Topic[], filter: TopicFilter): Topic[] {
  const tekst = filter.tekst?.trim().toLowerCase();
  return topics
    .filter((t) => !filter.status || t.topic_status === filter.status)
    .filter((t) => !filter.soort || t.topic_type === filter.soort)
    .filter((t) => !filter.toegewezen || t.assigned_to === filter.toegewezen)
    .filter(
      (t) =>
        !tekst ||
        [t.title, t.description ?? "", ...t.labels].some((veld) => veld.toLowerCase().includes(tekst)),
    )
    .sort((a, b) => b.modified_date.localeCompare(a.modified_date));
}

/** A new topic and its first viewpoint: the camera of the view, the selected elements and the (marked up) snapshot. */
export function nieuwTopic(
  form: IssueForm,
  camera: BcfCamera,
  selectie: string[],
  snapshotPng?: string,
): { topic: TopicInput; standpunt: Viewpoint } {
  const topic: TopicInput = { title: form.title.trim() };
  for (const veld of ["topic_type", "priority", "assigned_to", "description"] as const) {
    const waarde = form[veld]?.trim();
    if (waarde) topic[veld] = waarde;
  }
  const standpunt: Viewpoint = { perspective_camera: camera.perspective_camera };
  if (selectie.length) standpunt.components = { selection: selectie.map((ifc_guid) => ({ ifc_guid })) };
  if (snapshotPng) standpunt.snapshot = { snapshot_type: "png", snapshot_data: snapshotPng };
  return { topic, standpunt };
}

/** A version link below the threshold: elements of issues and clashes may have been linked wrongly or not at all. */
export function koppelWaarschuwing(matchrate: number | null | undefined): boolean {
  return matchrate != null && matchrate < KOPPEL_DREMPEL;
}

/** Elements of the topic that were not found again in the version the project shows. */
export function verlorenElementen(topic: Topic): TopicElement[] {
  return (topic.elementen ?? []).filter((e) => !e.teruggevonden);
}
