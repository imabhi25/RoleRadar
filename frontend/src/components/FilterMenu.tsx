import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

export interface MenuOption {
  value: string;
  label: string;
}

/** One list of choices inside a menu. Single-choice groups replace the value; multiple groups toggle it. */
export interface MenuGroup {
  id: string;
  title?: string;
  options: MenuOption[];
  selected: string[];
  multiple?: boolean;
  onSelect: (value: string) => void;
}

interface FilterMenuProps {
  /** Accessible name of the control ("Role", "Sort jobs", ...). */
  label: string;
  /** Text shown on the trigger button. */
  buttonText: string;
  groups: MenuGroup[];
  active?: boolean;
  disabled?: boolean;
  className?: string;
  align?: "left" | "right";
  /** Adds a filter box above long lists (company, skill). */
  search?: { placeholder: string; value: string; onChange: (value: string) => void; empty: boolean; emptyText: string };
  /** Menus close after a pick unless a group is multi-select. */
  closeOnSelect?: boolean;
}

const OPTION_SELECTOR = '[role="option"]';

/**
 * One menu design for every filter and the sort control: a quiet trigger and a list of plain rows with a
 * leading check on the selected row(s). Selection is also exposed through aria-selected (the check is not the
 * only signal), the list is keyboard operable (arrows, Home/End, Enter/Space, Esc) and Esc returns focus
 * to the trigger.
 */
export const FilterMenu: React.FC<FilterMenuProps> = ({
  label,
  buttonText,
  groups,
  active = false,
  disabled = false,
  className = "",
  align = "left",
  search,
  closeOnSelect,
}) => {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const baseId = useId();
  const hasMultiple = useMemo(() => groups.some((g) => g.multiple), [groups]);
  const shouldClose = closeOnSelect ?? !hasMultiple;

  const options = useCallback(
    () => Array.from(popoverRef.current?.querySelectorAll<HTMLElement>(OPTION_SELECTOR) ?? []),
    []
  );

  const close = useCallback((restoreFocus: boolean) => {
    setOpen(false);
    if (restoreFocus) requestAnimationFrame(() => triggerRef.current?.focus());
  }, []);

  // Outside click closes (opening another menu is an outside click for this one); Esc closes from anywhere
  // and hands focus back to the trigger. The explorer's own Esc handler ignores keys while a menu is open.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onEscape = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      close(true);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onEscape);
    };
  }, [open, close]);

  // Move focus into the menu on open: the filter box if there is one, else the selected (or first) row.
  useEffect(() => {
    if (!open) return;
    const frame = requestAnimationFrame(() => {
      if (search) {
        popoverRef.current?.querySelector<HTMLInputElement>("input")?.focus();
        return;
      }
      const rows = options();
      (rows.find((row) => row.getAttribute("aria-selected") === "true") ?? rows[0])?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [open, search, options]);

  const focusRow = (delta: number | "first" | "last") => {
    const rows = options();
    if (rows.length === 0) return;
    const index = rows.indexOf(document.activeElement as HTMLElement);
    const next =
      delta === "first" ? 0 : delta === "last" ? rows.length - 1 : Math.min(rows.length - 1, Math.max(0, index + delta));
    rows[next].focus();
  };

  const onPopoverKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const inSearch = (e.target as HTMLElement).tagName === "INPUT";
    if (e.key === "ArrowDown") {
      e.preventDefault();
      focusRow(inSearch ? "first" : 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (inSearch) return;
      const rows = options();
      if (rows.indexOf(document.activeElement as HTMLElement) === 0 && search) {
        popoverRef.current?.querySelector<HTMLInputElement>("input")?.focus();
      } else {
        focusRow(-1);
      }
    } else if (!inSearch && e.key === "Home") {
      e.preventDefault();
      focusRow("first");
    } else if (!inSearch && e.key === "End") {
      e.preventDefault();
      focusRow("last");
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  };

  const onTriggerKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "ArrowDown" && !open && !disabled) {
      e.preventDefault();
      setOpen(true);
    }
  };

  const select = (group: MenuGroup, value: string) => {
    group.onSelect(value);
    if (shouldClose) close(true);
  };

  return (
    <div className={`filter-menu ${className}`.trim()} ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={`filter-dropdown-btn${active ? " active" : ""}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? `${baseId}-menu` : undefined}
        aria-label={buttonText.toLowerCase().startsWith(label.toLowerCase()) ? buttonText : `${label}: ${buttonText}`}
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={onTriggerKeyDown}
      >
        <span className="dropdown-btn-truncate">{buttonText}</span>
        <svg
          className={`dropdown-chevron${open ? " open" : ""}`}
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {open && (
        <div
          id={`${baseId}-menu`}
          ref={popoverRef}
          className={`filter-popover filter-popover-${align}`}
          onKeyDown={onPopoverKeyDown}
        >
          {search && (
            <div className="filter-popover-search-wrap">
              <input
                type="text"
                placeholder={search.placeholder}
                aria-label={search.placeholder}
                value={search.value}
                onChange={(e) => search.onChange(e.target.value)}
                className="popover-search-input"
                autoComplete="off"
              />
            </div>
          )}
          <div className="filter-popover-scrollable">
            {groups.map((group) => (
              <div key={group.id} className="menu-group">
                {group.title && (
                  <div className="menu-group-title" id={`${baseId}-${group.id}`}>
                    {group.title}
                  </div>
                )}
                <div
                  role="listbox"
                  aria-multiselectable={group.multiple ? true : undefined}
                  aria-labelledby={group.title ? `${baseId}-${group.id}` : undefined}
                  aria-label={group.title ? undefined : label}
                >
                  {group.options.map((option) => {
                    const selected = group.selected.includes(option.value);
                    return (
                      <button
                        key={option.value || "__all"}
                        type="button"
                        role="option"
                        aria-selected={selected}
                        tabIndex={-1}
                        className={`menu-option${selected ? " selected" : ""}`}
                        onClick={() => select(group, option.value)}
                      >
                        <span className="menu-check" aria-hidden="true">
                          {selected ? "✓" : ""}
                        </span>
                        <span className="menu-option-label">{option.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
            {search?.empty && (
              <div className="popover-empty">{search.emptyText}</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
