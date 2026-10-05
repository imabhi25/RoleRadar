// Renders every crawled job through the same front-end code users run, and records what they would see.
// Run from frontend/:  AUDIT_DIR=/path/to/crawl npx vitest run --config ../scripts/public_data_audit/vitest.audit.config.ts
import { test } from "vitest";
import fs from "node:fs";
import { renderDescription } from "../../frontend/src/utils/descriptionPipeline";
import { summarizePosting } from "../../frontend/src/utils/postingSummary";
import { parseAndSanitizeJobDescription } from "../../frontend/src/utils/sanitizeDescription";
import { analyzeLanguage } from "../../frontend/src/utils/descriptionLanguage";
import { presentHeadings, structureDescription } from "../../frontend/src/utils/descriptionSections";
import { getJobCardCompensation } from "../../frontend/src/utils/compensation";
import { buildJobFacts } from "../../frontend/src/utils/jobFacts";
import { summarizeLocations } from "../../frontend/src/utils/locations";

const DIR = process.env.AUDIT_DIR as string;
const text = (html: string) => {
  const d = document.createElement("div");
  d.innerHTML = html.replace(/<\/?(p|div|li|ul|ol|br|h[1-6]|section|tr|td|table|strong|b|em|i|span|a|u)\b[^>]*>/gi, " ");
  return (d.textContent || "").replace(/ /g, " ").replace(/\s+/g, " ").trim();
};

test("render every job as the UI does", () => {
  const jobs = JSON.parse(fs.readFileSync(`${DIR}/detail.json`, "utf8"));
  const out: unknown[] = [];
  for (const j of jobs) {
    try {
      const description = renderDescription(j.description, j.company, j.title, undefined);
      const originalHtml = j.description ? parseAndSanitizeJobDescription(j.description, j.company).html : "";
      const summaryHtml = summarizePosting(description.teamHtml + description.mainHtml, description.language);
      const fullHtml = presentHeadings(structureDescription(analyzeLanguage(originalHtml).html[description.view] || originalHtml, j.company));
      const facts = buildJobFacts(j, { primaryLocation: j.location, ...description.meta } as never);
      const fact = (key: string) => facts.find((f) => f.key === key)?.value ?? null;
      out.push({
        id: j.job_id, company: j.company, src: j.source_name, title: j.title,
        card: getJobCardCompensation(j.compensation), pane: fact("compensation"), sourcePay: fact("sourceCompensation"),
        summary: text(summaryHtml), full: text(fullHtml), policies: text(description.policiesHtml),
        forcedFull: !summaryHtml && !!originalHtml, lang: description.language,
        locations: summarizeLocations(j).all, facts: facts.map((f) => [f.label, f.value]),
      });
    } catch (e) {
      out.push({ id: j.job_id, error: String(e).slice(0, 160) });
    }
  }
  fs.writeFileSync(`${DIR}/ui.json`, JSON.stringify(out));
});
