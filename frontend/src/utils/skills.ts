import { CANONICAL_SKILLS } from "./urlState";

export type SkillResolution =
  | { status: "unchecked"; skill: string }      // nothing to validate against (options not loaded / none published)
  | { status: "supported"; skill: string }      // exactly a supported skill
  | { status: "canonicalized"; skill: string }  // a supported skill spelled differently (case, or a known alias such as "golang")
  | { status: "unknown"; skill: string };       // not a skill the API offers

/**
 * Validates a skill from the URL against the skills the API currently offers (`/api/jobs/filters`). The list is data,
 * not code: a skill added later is supported the moment postings carry it, with no front-end change. A built-in alias
 * table only maps spelling variants onto an offered skill; it never makes an unoffered skill valid.
 */
export function resolveSkillFilter(value: string, supported: readonly string[] | null | undefined): SkillResolution {
  const skill = value.trim();
  if (!skill || !supported || supported.length === 0) return { status: "unchecked", skill };
  const byLower = new Map(supported.map((name) => [name.toLowerCase(), name] as const));
  const exact = byLower.get(skill.toLowerCase());
  if (exact) return { status: exact === skill ? "supported" : "canonicalized", skill: exact };
  const alias = CANONICAL_SKILLS[skill.toLowerCase()];
  const viaAlias = alias ? byLower.get(alias.toLowerCase()) : undefined;
  if (viaAlias) return { status: "canonicalized", skill: viaAlias };
  return { status: "unknown", skill };
}
