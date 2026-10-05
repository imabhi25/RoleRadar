import { describe, expect, it } from "vitest";
import { postingHighlights } from "../src/utils/postingHighlights";
import { renderDescription } from "../src/utils/descriptionPipeline";

const highlights = (title: string, html: string) => postingHighlights(title, renderDescription(html, "Acme", title).mainHtml);

describe("source-backed posting highlights", () => {
  it("preserves equivalent experience as an alternative to a required degree", () => {
    const requirement = "A bachelor's degree in computer science or equivalent work experience.";
    expect(highlights("Software Engineer", `<h2>Requirements</h2><ul><li>${requirement}</li></ul>`))
      .toEqual([{ key: "education", label: "Education", value: requirement }]);
  });

  it("never turns preferred education into a required degree", () => {
    expect(highlights("Software Engineer", '<h2>Preferred qualifications</h2><p>A master’s degree.</p>')).toEqual([]);
    expect(highlights("Software Engineer", '<h2>Requirements</h2><p>A bachelor’s degree is preferred but not required.</p>')).toEqual([]);
  });

  it("shows only explicit title levels and never infers Mid from Engineer II", () => {
    expect(postingHighlights("Senior Software Engineer", "")).toEqual([{ key: "experience", label: "Experience level", value: "Senior" }]);
    expect(postingHighlights("Software Development Engineer II", "")).toEqual([]);
  });

  it("keeps company background and unclassified education out of the requirements grid", () => {
    expect(highlights("Software Engineer", '<h2>Company</h2><p>Our founder has a master’s degree.</p>')).toEqual([]);
    expect(highlights("Software Engineer", '<p>We have partnerships with bachelor degree programs.</p>')).toEqual([]);
  });
});
