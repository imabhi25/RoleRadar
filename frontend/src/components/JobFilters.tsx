import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { createPortal } from "react-dom";
import type { JobFilterOptions } from "../api/client";

export interface SelectedFilters {
  sort?: "recommended" | "newest" | "oldest" | "company" | "title";
  search: string;
  country: string[];
  location?: string[];
  company: string;
  skill: string;
  workplace_type: string[];
  role_type: string[];
  experience_level?: string[];
  min_compensation?: number | null;
  compensation_currency?: string | null;
  sponsorship?: "all" | "available" | "not_required" | string;
  term: string[];
  /** "recent" = the default public window (last 30 days); the others narrow it. */
  freshness: "recent" | "today" | "week" | "14d";
}

interface JobFiltersProps {
  filterOptions: JobFilterOptions;
  selectedFilters: SelectedFilters;
  onFilterChange: (filters: SelectedFilters, isDiscrete?: boolean) => void;
  onReset: () => void;
  disabled?: boolean;
  onSearchInputChange?: (value: string) => void;
  /** When set, the search box is rendered into this element (the navbar) instead of inside the panel. */
  searchSlot?: HTMLElement | null;
}
const ROLE_OPTIONS = [
  { label: "Full-time", value: "full_time" },
  { label: "Internship", value: "internship" },
  { label: "Co-op", value: "co_op" },
];
const TERM_OPTIONS = [{ label: "Winter", value: "winter" }, { label: "Summer", value: "summer" }, { label: "Fall", value: "fall" }];
const WORKPLACE_OPTIONS = [{ label: "Remote", value: "remote" }, { label: "Hybrid", value: "hybrid" }, { label: "On-site", value: "on_site" }];
const DATE_OPTIONS: { label: string; value: SelectedFilters["freshness"] }[] = [
  { label: "Last 30 days", value: "recent" }, { label: "Today (UTC)", value: "today" },
  { label: "Last 7 days", value: "week" }, { label: "Last 14 days", value: "14d" },
];
const EXPERIENCE_OPTIONS = [{ label: "Entry Level / New Grad", value: "entry" }, { label: "Mid Level", value: "mid" }, { label: "Senior / Staff / Lead", value: "senior" }];

/** Real selects let each browser/OS provide its own menu, keyboard behavior, and system colors. */
export function NativeSelect({ label, value, children, onChange, disabled = false }: {
  label: string; value: string; children: React.ReactNode; onChange: (value: string) => void; disabled?: boolean;
}) {
  const active = Boolean(value && value !== "recent" && value !== "recommended");
  return <span className={`native-select-control${active ? " is-active" : ""}`}>
    <select aria-label={label} className="native-select" value={value} disabled={disabled}
      onChange={(event) => onChange(event.target.value)}>{children}</select>
    <svg className="native-select-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m7 10 5 5 5-5" /></svg>
  </span>;
}

export const JobFilters: React.FC<JobFiltersProps> = ({ filterOptions, selectedFilters, onFilterChange, onReset, disabled = false, onSearchInputChange, searchSlot = null }) => {
  const [searchInput, setSearchInput] = useState(selectedFilters.search);
  const searchInputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { setSearchInput(selectedFilters.search); onSearchInputChange?.(selectedFilters.search); }, [selectedFilters.search, onSearchInputChange]);
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchInput !== selectedFilters.search) onFilterChange({ ...selectedFilters, search: searchInput }, false);
    }, 400);
    return () => clearTimeout(timer);
  }, [searchInput, selectedFilters, onFilterChange]);
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault(); searchInputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, []);
  const handleRoleToggle = useCallback((value: string) => onFilterChange({ ...selectedFilters,
    role_type: selectedFilters.role_type.filter((role) => role !== value) }, true), [selectedFilters, onFilterChange]);
  const handleTermToggle = useCallback((value: string) => onFilterChange({ ...selectedFilters,
    term: selectedFilters.term.filter((term) => term !== value) }, true), [selectedFilters, onFilterChange]);
  const handleExperienceToggle = useCallback((value: string) => onFilterChange({ ...selectedFilters,
    experience_level: (selectedFilters.experience_level || []).filter((level) => level !== value) }, true), [selectedFilters, onFilterChange]);
  const handleClearSearch = () => {
    setSearchInput("");
    onSearchInputChange?.("");
    if (selectedFilters.search) onFilterChange({ ...selectedFilters, search: "" }, true);
    searchInputRef.current?.focus();
  };
  // Construct active filter chips
  const activeChips = useMemo(() => {
    const chips: {
      id: string;
      label: string;
      onRemove: () => void;
      ariaLabel: string;
    }[] = [];

    selectedFilters.role_type.forEach((role) => {
      const opt = ROLE_OPTIONS.find((o) => o.value === role);
      const label = opt ? opt.label : role;
      chips.push({
        id: `role-${role}`,
        label: `Job type: ${label}`,
        onRemove: () => handleRoleToggle(role),
        ariaLabel: `Remove ${label} filter`,
      });
    });

    selectedFilters.term.forEach((term) => {
      const opt = TERM_OPTIONS.find((o) => o.value === term);
      const label = `Term: ${opt ? opt.label : term}`;
      chips.push({
        id: `term-${term}`,
        label,
        onRemove: () => handleTermToggle(term),
        ariaLabel: `Remove ${label} filter`,
      });
    });

    if (selectedFilters.freshness !== "recent") {
      const opt = DATE_OPTIONS.find((o) => o.value === selectedFilters.freshness);
      const label = opt ? opt.label : selectedFilters.freshness;
      chips.push({
        id: "freshness",
        label: `Date: ${label}`,
        onRemove: () => onFilterChange({ ...selectedFilters, freshness: "recent" }),
        ariaLabel: "Remove date posted filter",
      });
    }

    // All countries is the default, so it is not an "active" filter; an explicit country is.
    if (selectedFilters.country.length > 0) {
      const countries = selectedFilters.country.join(", ");
      chips.push({
        id: "country",
        label: `Country: ${countries}`,
        onRemove: () => onFilterChange({ ...selectedFilters, country: [] }, true),
        ariaLabel: `Remove country ${countries} filter (back to all countries)`,
      });
    }

    selectedFilters.workplace_type.forEach((wp) => {
      const opt = WORKPLACE_OPTIONS.find((o) => o.value === wp);
      const label = opt ? opt.label : wp;
      chips.push({
        id: `workplace-${wp}`,
        label: `Workplace: ${label}`,
        onRemove: () => onFilterChange({ ...selectedFilters, workplace_type: selectedFilters.workplace_type.filter((w) => w !== wp) }, true),
        ariaLabel: `Remove ${label} workplace filter`,
      });
    });

    if (selectedFilters.company) {
      const canonicalCompany =
        filterOptions.companies.find(
          (c) => c.toLowerCase() === selectedFilters.company.toLowerCase()
        ) || selectedFilters.company;
      chips.push({
        id: "company",
        label: `Company: ${canonicalCompany}`,
        onRemove: () => onFilterChange({ ...selectedFilters, company: "" }, true),
        ariaLabel: `Remove company ${canonicalCompany} filter`,
      });
    }

    if (selectedFilters.skill) {
      const canonicalSkill =
        filterOptions.skills.find(
          (s) => s.toLowerCase() === selectedFilters.skill.toLowerCase()
        ) || selectedFilters.skill;
      chips.push({
        id: "skill",
        label: `Skill: ${canonicalSkill}`,
        onRemove: () => onFilterChange({ ...selectedFilters, skill: "" }, true),
        ariaLabel: `Remove skill ${canonicalSkill} filter`,
      });
    }

    if (selectedFilters.location && selectedFilters.location.length > 0) {
      selectedFilters.location.forEach((loc) => {
        chips.push({
          id: `loc-${loc}`,
          label: `Location: ${loc}`,
          onRemove: () =>
            onFilterChange(
              {
                ...selectedFilters,
                location: selectedFilters.location?.filter((l) => l !== loc) || [],
              },
              true
            ),
          ariaLabel: `Remove location ${loc} filter`,
        });
      });
    }

    if (selectedFilters.experience_level && selectedFilters.experience_level.length > 0) {
      selectedFilters.experience_level.forEach((exp) => {
        const opt = EXPERIENCE_OPTIONS.find((o) => o.value === exp);
        chips.push({
          id: `exp-${exp}`,
          label: `Experience: ${opt?.label ?? exp}`,
          onRemove: () => handleExperienceToggle(exp),
          ariaLabel: `Remove experience ${opt?.label ?? exp} filter`,
        });
      });
    }

    if (selectedFilters.min_compensation) {
      const curr =
        selectedFilters.compensation_currency ||
        (selectedFilters.country[0] === "Canada"
          ? "CAD"
          : selectedFilters.country[0] === "United States"
          ? "USD"
          : "CAD");
      chips.push({
        id: "min-comp",
        label: `Min pay: ${curr} $${Math.round(selectedFilters.min_compensation / 1000)}k+`,
        onRemove: () => onFilterChange({ ...selectedFilters, min_compensation: null }, true),
        ariaLabel: "Remove minimum compensation filter",
      });
    }

    if (selectedFilters.sponsorship && selectedFilters.sponsorship !== "all") {
      chips.push({
        id: "sponsorship",
        label: selectedFilters.sponsorship === "available" ? "Sponsorship: Available" : "Sponsorship: Not Required",
        onRemove: () => onFilterChange({ ...selectedFilters, sponsorship: "all" }, true),
        ariaLabel: "Remove sponsorship filter",
      });
    }

    return chips;
  }, [
    selectedFilters,
    filterOptions.companies,
    filterOptions.skills,
    onFilterChange,
    handleRoleToggle,
    handleTermToggle,
    handleExperienceToggle,
  ]);

  const locations = Array.from(new Set([...(filterOptions.locations || []), ...(selectedFilters.location || [])]));
  // Match the countries supported by the shared URL schema, so selections survive reloads.
  const countries = ["Canada", "United States"];
  const geography = (selectedFilters.location?.length || 0) + selectedFilters.country.length;
  const locationValue = geography > 1 ? "__multiple" : selectedFilters.location?.[0] ? `location:${selectedFilters.location[0]}` : selectedFilters.country[0] ? `country:${selectedFilters.country[0]}` : "";
  const arrayValue = (values: string[] | undefined) => values && values.length > 1 ? "__multiple" : values?.[0] || "";
  const choiceOptions = (values: string[] | undefined, options: { value: string; label: string }[], label: string) => <>
    <option value="">{label}</option>
    {(values?.length || 0) > 1 && <option value="__multiple" disabled>{label} ({values!.length})</option>}
    {values?.filter((value) => !options.some((option) => option.value === value)).map((value) => <option key={value} value={value}>{value.replace(/_/g, " ")}</option>)}
    {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
  </>;
  const searchRow = <div className="search-bar-row">
    <div className="search-input-wrapper">
      <svg className="search-icon-svg" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" /></svg>
      <input ref={searchInputRef} id="job-search-input" type="search" value={searchInput}
        onChange={(event) => { setSearchInput(event.target.value); onSearchInputChange?.(event.target.value); }} placeholder="Search jobs, companies, or skills..."
        disabled={disabled} className="search-input" autoComplete="off" aria-label="Search jobs, companies, or skills" />
      {searchInput && <button type="button" onClick={handleClearSearch} className="search-clear-btn" aria-label="Clear search text">✕</button>}
      <div className="search-shortcut-badge" aria-hidden="true">⌘ K</div>
    </div>
  </div>;
  return <div className="filter-panel" aria-label="Job filters">
    <div className="job-search-toolbar">
      {/* On wide screens the search box lives in the navbar (a slot the app provides); elsewhere it stays here. */}
      {searchSlot ? createPortal(searchRow, searchSlot) : searchRow}
      <div className="essential-filters" role="group" aria-label="Essential job filters">
        <NativeSelect label="Location" value={locationValue} disabled={disabled} onChange={(value) => {
          onFilterChange({ ...selectedFilters, location: value.startsWith("location:") ? [value.slice(9)] : [],
            country: value.startsWith("country:") ? [value.slice(8)] : [] }, true);
        }}>
          <option value="">Location</option>
          {geography > 1 && <option value="__multiple" disabled>Location ({geography})</option>}
          <optgroup label="Countries">{countries.map((country) => <option key={country} value={`country:${country}`}>{country}</option>)}</optgroup>
          <optgroup label="Cities and regions">{locations.map((location) => <option key={location} value={`location:${location}`}>{location}</option>)}</optgroup>
        </NativeSelect>
        <NativeSelect label="Job type" value={arrayValue(selectedFilters.role_type)} disabled={disabled}
          onChange={(value) => onFilterChange({ ...selectedFilters, role_type: value ? [value] : [], term: [] }, true)}>
          {choiceOptions(selectedFilters.role_type, ROLE_OPTIONS, "Job type")}
        </NativeSelect>
        <NativeSelect label="Experience" value={arrayValue(selectedFilters.experience_level)} disabled={disabled}
          onChange={(value) => onFilterChange({ ...selectedFilters, experience_level: value ? [value] : [] }, true)}>
          {choiceOptions(selectedFilters.experience_level, EXPERIENCE_OPTIONS, "Experience")}
        </NativeSelect>
        <NativeSelect label="Workplace" value={arrayValue(selectedFilters.workplace_type)} disabled={disabled}
          onChange={(value) => onFilterChange({ ...selectedFilters, workplace_type: value ? [value] : [] }, true)}>
          {choiceOptions(selectedFilters.workplace_type, WORKPLACE_OPTIONS, "Workplace")}
        </NativeSelect>
        <NativeSelect label="Date posted" value={selectedFilters.freshness} disabled={disabled}
          onChange={(value) => onFilterChange({ ...selectedFilters, freshness: value as SelectedFilters["freshness"] }, true)}>
          {DATE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.value === "recent" ? "Date posted" : option.label}</option>)}
        </NativeSelect>
      </div>
    </div>
    {activeChips.length > 0 && <div className="active-filters-row" role="region" aria-label="Active filters">
      <div className="active-chips-wrap">{activeChips.map((chip) => <span key={chip.id} className="active-filter-chip">
        <span className="chip-label">{chip.label}</span><button type="button" onClick={chip.onRemove} aria-label={chip.ariaLabel} className="chip-remove-btn"><span aria-hidden="true">✕</span></button>
      </span>)}</div>
      <button type="button" onClick={onReset} className="reset-filters-btn" aria-label="Reset all filters">Reset filters</button>
    </div>}
  </div>;
};
