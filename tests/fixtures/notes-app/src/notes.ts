/** Validation shared by the HTTP handler and the unit tests. */
export function validateTitle(input: unknown): string | null {
  if (typeof input !== "string") return null;
  const title = input.trim();
  return title.length >= 1 && title.length <= 200 ? title : null;
}
