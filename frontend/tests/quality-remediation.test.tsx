import { describe, it, expect } from "vitest";
import React from "react";
import { render } from "@testing-library/react";
import { cleanLocationDisplay, splitOutsideParentheses } from "../src/utils/formatters";
import { summarizeLocations } from "../src/utils/locations";
import { getJobCardCompensation, getCompensationDetail, formatPay } from "../src/utils/compensation";
import { buildJobFacts } from "../src/utils/jobFacts";
import { postingHighlights } from "../src/utils/postingHighlights";
import { JobCard } from "../src/components/JobCard";
import type { JobSummary } from "../src/api/client";

describe("Quality remediation regressions (Muse review findings)", () => {
  describe("Parenthetical location parsing", () => {
    it("does not split at semicolons inside parentheses for Instacart-style locations", () => {
      const input = "Canada, Remote (ON, AB, BC; NS Only)";
      const segments = splitOutsideParentheses(input, /[;|]+|\r?\n/);
      expect(segments).toEqual(["Canada, Remote (ON, AB, BC; NS Only)"]);

      const cleaned = cleanLocationDisplay(input, "Canada");
      expect(cleaned.display).toBe("Canada, Remote (ON, AB, BC; NS Only)");

      const job: JobSummary = {
        job_id: "instacart:test-1",
        title: "Senior Software Engineer",
        company: "Instacart",
        location: input,
        country: "Canada",
        workplace_type: "remote",
        source_name: "greenhouse",
        skills: [],
      };
      const summary = summarizeLocations(job);
      expect(summary.all).toHaveLength(1);
      expect(summary.all).not.toContain("NS Only)");
    });

    it("correctly splits multiple top-level locations while preserving parenthetical lists", () => {
      const input = "Toronto, ON; Remote (ON, AB, BC; NS Only); Vancouver, BC";
      const segments = splitOutsideParentheses(input, /[;|]+|\r?\n/).map((s) => s.trim());
      expect(segments).toHaveLength(3);
      expect(segments[0]).toBe("Toronto, ON");
      expect(segments[1]).toBe("Remote (ON, AB, BC; NS Only)");
      expect(segments[2]).toBe("Vancouver, BC");
    });
  });

  describe("Salary display, unit normalization, and unknown field suppression", () => {
    it("never leaks 'period not stated' into the UI", () => {
      const compNoPeriod = {
        source: "posting_text",
        ranges: [{ min: 80000, max: 175000, symbol: "$" }],
        compensationTierSummary: "$80K – $175K",
      };
      const cardText = getJobCardCompensation(compNoPeriod, "Canada");
      expect(cardText).not.toContain("period not stated");

      const detailText = getCompensationDetail(compNoPeriod, "Canada");
      expect(detailText).not.toContain("period not stated");

      expect(formatPay(60, 60, "USD")).toBe("$60");
      expect(formatPay(60, 60, "USD")).not.toContain("period not stated");
    });

    it("normalizes Canadian salaries with bare $ to CA$", () => {
      const compCanadaBare = {
        source: "posting_text",
        ranges: [{ min: 133000, max: 183000, symbol: "$", interval: "year" }],
        compensationTierSummary: "$133K – $183K",
      };
      const cardCanada = getJobCardCompensation(compCanadaBare, "Canada");
      expect(cardCanada).toBe("CA$133K – CA$183K/yr");

      const detailCanada = getCompensationDetail(compCanadaBare, "Canada");
      expect(detailCanada).toBe("CA$133K – CA$183K/yr");

      const summaryCanada = getJobCardCompensation({ compensationTierSummary: "$80K – $175K" }, "Canada");
      expect(summaryCanada).toBe("CA$80K – CA$175K");

      // US jobs keep standard USD $
      const compUS = {
        source: "posting_text",
        ranges: [{ min: 150000, max: 200000, symbol: "$", interval: "year" }],
        compensationTierSummary: "$150K – $200K",
      };
      const cardUS = getJobCardCompensation(compUS, "United States");
      expect(cardUS).toBe("$150K – $200K/yr");
    });

    it("normalizes bare numeric working hours with hours/week unit", () => {
      const job: JobSummary = {
        job_id: "cibc:backend-dev",
        title: "Consultant, Backend Developer",
        company: "CIBC",
        location: "Toronto, ON",
        country: "Canada",
        workplace_type: "hybrid",
        source_name: "workday",
        skills: [],
      };
      const facts = buildJobFacts(job, { hours: "37.5" });
      const hoursFact = facts.find((f) => f.key === "hours");
      expect(hoursFact?.value).toBe("37.5 hours/week");

      // Already formatted hours remain unchanged
      const factsExplicit = buildJobFacts(job, { hours: "40 hrs/wk" });
      expect(factsExplicit.find((f) => f.key === "hours")?.value).toBe("40 hrs/wk");
    });
  });

  describe("Entry Level classification safeguards", () => {
    it("does not classify roles with 3+ years experience, consultant title, or mentoring juniors as Entry level", () => {
      const cibcDesc = `
        <p>You can demonstrate 3 plus years of experience in Java/J2EE.</p>
        <p>Proven and solid hands-on experience of a minimum of 3+ years in Microservices.</p>
        <p>Mentorship - Be able to coach junior developers in the team and provide technical guidance.</p>
      `;
      const facts = postingHighlights("Consultant, Backend Developer", cibcDesc, "entry");
      const expFact = facts.find((f) => f.key === "experience");
      expect(expFact?.value).not.toBe("Entry level");
      expect(expFact?.value).toBe("Mid level");
    });

    it("preserves Entry level for genuine junior postings without contradictory requirements", () => {
      const juniorDesc = "<p>Great opportunity for graduates. 0-2 years of experience in Python.</p>";
      const facts = postingHighlights("Junior Software Developer", juniorDesc, "entry");
      const expFact = facts.find((f) => f.key === "experience");
      expect(expFact?.value).toBe("Entry level");
    });
  });

  describe("Recommended sort and Canadian card location priority", () => {
    it("leads with the Canadian location for multi-location jobs when preferredCountries includes Canada", () => {
      const multiLocationJob: JobSummary = {
        job_id: "tr:architect-1",
        title: "Principal Software Engineer",
        company: "Thomson Reuters",
        location: "New York, NY, United States",
        country: "United States",
        workplace_type: "hybrid",
        source_name: "workday",
        skills: [],
        locations: [
          { country: "United States", location: "New York, NY, United States" },
          { country: "Canada", location: "Toronto, Ontario, Canada" },
        ],
      };

      const { container } = render(
        <JobCard job={multiLocationJob} onClick={() => {}} preferredCountries={["Canada"]} />
      );
      expect(container.textContent).toContain("Toronto, Ontario, Canada");
      expect(container.textContent).not.toMatch(/^New York/);
    });
  });
});
