import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { JobFilters, type SelectedFilters } from "../src/components/JobFilters";
import { parseUrlSearch, serializeUrlSearch } from "../src/utils/urlState";

const defaultFilters: SelectedFilters = {
  sort: "recommended",
  search: "",
  country: [],
  location: [],
  company: "",
  skill: "",
  workplace_type: [],
  role_type: [],
  experience_level: [],
  min_compensation: null,
  compensation_currency: null,
  sponsorship: "all",
  term: [],
  freshness: "recent",
};

const filterOptions = {
  countries: ["Canada", "United States"],
  companies: ["Amazon", "Shopify"],
  skills: ["Python", "React"],
  workplace_types: ["remote", "hybrid", "on_site"],
  locations: ["Toronto (GTA)", "Vancouver", "Montreal", "Ottawa"],
  experience_levels: ["internship", "entry", "mid", "senior"],
};

describe("Location Multi-Select", () => {
  it("preserves multiple locations from shared URLs and replaces them with a native choice", async () => {
    const onFilterChange = vi.fn();
    render(<JobFilters filterOptions={filterOptions} selectedFilters={{ ...defaultFilters, location: ['Toronto (GTA)', 'Vancouver'] }} onFilterChange={onFilterChange} onReset={() => {}} />);
    expect(screen.getByRole('combobox', { name: 'Location' })).toHaveValue('__multiple');
    expect(screen.getByRole('region', { name: 'Active filters' })).toHaveTextContent('Toronto (GTA)');
    await userEvent.click(screen.getByRole('button', { name: 'Remove location Toronto (GTA) filter' }));
    expect(onFilterChange).toHaveBeenLastCalledWith(expect.objectContaining({ location: ['Vancouver'] }), true);
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Location' }), 'location:Ottawa');
    expect(onFilterChange).toHaveBeenLastCalledWith(expect.objectContaining({ location: ['Ottawa'], country: [] }), true);
  });

  it("serializes and parses multiple locations into and from repeated URL search parameters", () => {
    const filters: SelectedFilters = {
      ...defaultFilters,
      location: ["Toronto (GTA)", "Vancouver"],
    };

    const searchString = serializeUrlSearch(filters, 1);
    expect(searchString).toContain("location=Toronto+%28GTA%29&location=Vancouver");

    const parsed = parseUrlSearch(searchString);
    expect(parsed.filters.location).toEqual(["Toronto (GTA)", "Vancouver"]);
  });

  it("preserves commas inside location values: San Francisco, CA and New York, NY individually, together, and after reload", () => {
    // 1. San Francisco, CA individually
    const sfFilters: SelectedFilters = { ...defaultFilters, location: ["San Francisco, CA"] };
    const sfUrl = serializeUrlSearch(sfFilters, 1);
    expect(sfUrl).toBe("?location=San+Francisco%2C+CA");
    const sfParsed = parseUrlSearch(sfUrl);
    expect(sfParsed.filters.location).toEqual(["San Francisco, CA"]);

    // 2. New York, NY individually
    const nyFilters: SelectedFilters = { ...defaultFilters, location: ["New York, NY"] };
    const nyUrl = serializeUrlSearch(nyFilters, 1);
    expect(nyUrl).toBe("?location=New+York%2C+NY");
    const nyParsed = parseUrlSearch(nyUrl);
    expect(nyParsed.filters.location).toEqual(["New York, NY"]);

    // 3. Together
    const bothFilters: SelectedFilters = {
      ...defaultFilters,
      location: ["San Francisco, CA", "New York, NY"],
    };
    const bothUrl = serializeUrlSearch(bothFilters, 1);
    expect(bothUrl).toBe("?location=San+Francisco%2C+CA&location=New+York%2C+NY");

    // 4. After reload (re-parsing the serialized URL)
    const reloaded = parseUrlSearch(bothUrl);
    expect(reloaded.filters.location).toEqual(["San Francisco, CA", "New York, NY"]);
    expect(reloaded.filters.location[0]).toBe("San Francisco, CA");
    expect(reloaded.filters.location[1]).toBe("New York, NY");
  });
});
