import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CompanyPageView } from "../src/components/CompanyPageView";
import { apiClient, type CompanyInfo, type JobSummary } from "../src/api/client";

const mockCompanies: CompanyInfo[] = [
  {
    name: "Amazon",
    logo_url: "/logos/amazon.svg",
    logo_source_url: null,
    logo_status: "verified",
    website_url: "https://amazon.com",
    active_jobs_count: 5,
  },
  {
    name: "Shopify",
    logo_url: "/logos/shopify.svg",
    logo_source_url: null,
    logo_status: "verified",
    website_url: "https://shopify.com",
    active_jobs_count: 3,
  },
];

const mockJobs: JobSummary[] = [
  {
    job_id: "amazon:101",
    title: "Software Development Engineer II",
    company: "Amazon",
    location: "Vancouver, BC",
    country: "Canada",
    workplace_type: "hybrid",
    role_type: "full_time",
    source_name: "amazon",
    skills: ["Java", "AWS"],
    posted_at: "2026-09-28T00:00:00Z",
    created_at: "2026-09-28T01:00:00Z",
    freshness_status: "recent",
    company_apply_url: "https://amazon.jobs/en/jobs/101",
    compensation: {
      compensationTierSummary: "CAD 140,000–185,000 /yr • Equity",
    },
  },
];

afterEach(() => {
  vi.restoreAllMocks();
});

describe("CompanyPageView", () => {
  it("renders verified sourced profile details and open roles for a company", async () => {
    vi.spyOn(apiClient, "getCompanies").mockResolvedValue(mockCompanies);
    vi.spyOn(apiClient, "getJobs").mockResolvedValue({ total: 1, limit: 50, offset: 0, jobs: mockJobs });

    const onBackToJobs = vi.fn();
    const onSelectJob = vi.fn();

    render(
      <CompanyPageView
        initialCompany="Amazon"
        onBackToJobs={onBackToJobs}
        onSelectJob={onSelectJob}
      />
    );

    // Header & Company name
    expect(await screen.findByRole("heading", { name: "Amazon", level: 1 })).toBeInTheDocument();

    // Sourced profile details
    expect(screen.getAllByText(/cloud infrastructure/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Headquarters")).toBeInTheDocument();
    expect(screen.getByText("Seattle, Washington, United States")).toBeInTheDocument();
    expect(screen.getByText("Industry")).toBeInTheDocument();
    expect(screen.getByText("Cloud Infrastructure & Software")).toBeInTheDocument();
    expect(screen.getByText("Benefits & Perks")).toBeInTheDocument();

    // Active Jobs Section
    expect(screen.getByRole("heading", { name: /Active Roles at Amazon/i })).toBeInTheDocument();
    expect(await screen.findByText("Software Development Engineer II")).toBeInTheDocument();
    expect(screen.getByText("Vancouver, BC")).toBeInTheDocument();
    expect(screen.getByText("CAD 140,000–185,000 /yr")).toBeInTheDocument();

    // Direct apply link
    const applyLink = screen.getByRole("link", { name: /Apply/i });
    expect(applyLink).toHaveAttribute("href", "https://amazon.jobs/en/jobs/101");
    expect(applyLink).toHaveAttribute("target", "_blank");

    // Action clicks
    const viewBtn = screen.getByRole("button", { name: "View Details" });
    await userEvent.click(viewBtn);
    expect(onSelectJob).toHaveBeenCalledWith("amazon:101");

    const backBtn = screen.getByRole("button", { name: "← Back to jobs" });
    await userEvent.click(backBtn);
    expect(onBackToJobs).toHaveBeenCalled();
  });

  it("renders company directory when no company is selected", async () => {
    vi.spyOn(apiClient, "getCompanies").mockResolvedValue(mockCompanies);

    render(
      <CompanyPageView
        onBackToJobs={vi.fn()}
        onSelectJob={vi.fn()}
      />
    );

    expect(await screen.findByRole("heading", { name: "Companies Hiring on RoleRadar", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("Amazon")).toBeInTheDocument();
    expect(screen.getByText("Shopify")).toBeInTheDocument();
    expect(screen.getByText("5 active jobs")).toBeInTheDocument();

    // Filter search input
    const searchInput = screen.getByPlaceholderText(/Search companies by name/i);
    await userEvent.type(searchInput, "Shop");

    expect(screen.getByText("Shopify")).toBeInTheDocument();
    expect(screen.queryByText("Amazon")).not.toBeInTheDocument();
  });

  it("renders official source link and verification date for company facts", async () => {
    vi.spyOn(apiClient, "getCompanies").mockResolvedValue(mockCompanies);
    vi.spyOn(apiClient, "getJobs").mockResolvedValue({ total: 0, limit: 50, offset: 0, jobs: [] });

    render(
      <CompanyPageView
        initialCompany="Amazon"
        onBackToJobs={vi.fn()}
        onSelectJob={vi.fn()}
      />
    );

    const sourceLink = await screen.findByRole("link", { name: /Official profile/i });
    expect(sourceLink).toHaveAttribute("href", "https://www.aboutamazon.com/workplace/employee-benefits");
    expect(sourceLink).toHaveAttribute("target", "_blank");
    expect(screen.getByText(/verified 2026-10-02/i)).toBeInTheDocument();
  });

  it("actually refetches jobs when the Retry button is clicked on error", async () => {
    vi.spyOn(apiClient, "getCompanies").mockResolvedValue(mockCompanies);
    const getJobsMock = vi
      .spyOn(apiClient, "getJobs")
      .mockRejectedValueOnce(new Error("Network failure"))
      .mockResolvedValueOnce({ total: 1, limit: 50, offset: 0, jobs: mockJobs });

    render(
      <CompanyPageView
        initialCompany="Amazon"
        onBackToJobs={vi.fn()}
        onSelectJob={vi.fn()}
      />
    );

    // Initial load fails and renders error
    const retryBtn = await screen.findByRole("button", { name: "Retry" });
    expect(retryBtn).toBeInTheDocument();
    expect(getJobsMock).toHaveBeenCalledTimes(1);

    // Clicking Retry increments retryNonce and invokes getJobs again
    await userEvent.click(retryBtn);
    expect(getJobsMock).toHaveBeenCalledTimes(2);

    // Successfully renders the job after retry
    expect(await screen.findByText("Software Development Engineer II")).toBeInTheDocument();
  });
});
