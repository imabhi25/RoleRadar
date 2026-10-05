import React from "react";

interface ErrorBoundaryProps {
  /** Shown instead of the crashed subtree; receives a reset callback. */
  fallback: (reset: () => void) => React.ReactNode;
  children: React.ReactNode;
  /** Changing this value clears a previous crash (e.g. when the view is opened again). */
  resetKey?: unknown;
}

interface ErrorBoundaryState {
  crashed: boolean;
}

/**
 * Contains a render crash inside optional UI (analytics widgets, the dev-only logo sheet) so it can never blank
 * the core job browser.
 */
export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { crashed: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { crashed: true };
  }

  componentDidCatch(error: unknown): void {
    console.error("Optional section failed to render:", error);
  }

  componentDidUpdate(previous: ErrorBoundaryProps): void {
    if (this.state.crashed && previous.resetKey !== this.props.resetKey) this.setState({ crashed: false });
  }

  reset = (): void => this.setState({ crashed: false });

  render(): React.ReactNode {
    return this.state.crashed ? this.props.fallback(this.reset) : this.props.children;
  }
}
