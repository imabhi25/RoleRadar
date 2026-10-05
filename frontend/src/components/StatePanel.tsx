import React from "react";

export interface StatePanelAction {
  label: string;
  onClick: () => void;
  /** "primary" is the filled recovery action (Retry, Reset); "secondary" is the outlined escape (Close, Back). */
  kind?: "primary" | "secondary";
}

export interface StatePanelProps {
  variant: "error" | "unavailable" | "empty";
  title?: string;
  /** Short explanation. */
  children?: React.ReactNode;
  actions?: StatePanelAction[];
  className?: string;
  testId?: string;
}

/**
 * One shape for every error / unavailable / empty state: same spacing, same button heights, announced to assistive
 * technology the same way. Errors and unavailable states are role="alert"; an empty result is a polite status.
 */
export const StatePanel: React.FC<StatePanelProps> = ({ variant, title, children, actions = [], className = "", testId }) => (
  <div
    className={`state-panel state-panel-${variant} ${className}`.trim()}
    role={variant === "empty" ? "status" : "alert"}
    data-testid={testId}
  >
    {title && <h3 className="state-panel-title">{title}</h3>}
    {children && <p className="state-panel-text">{children}</p>}
    {actions.length > 0 && (
      <div className="state-actions">
        {actions.map((action) => (
          <button
            key={action.label}
            type="button"
            onClick={action.onClick}
            className={action.kind === "secondary" ? "secondary-button" : "retry-button"}
          >
            {action.label}
          </button>
        ))}
      </div>
    )}
  </div>
);
