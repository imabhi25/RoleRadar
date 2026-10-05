import React, { useEffect, useRef } from "react";
import { JobDetailContent } from "./JobDetailContent";

interface JobDetailModalProps {
  jobId: string | null;
  onClose: () => void;
}

/**
 * Mobile / narrow-width job detail: a single-column overlay. The content itself is shared
 * with the desktop split-view pane (JobDetailContent).
 */
export const JobDetailModal: React.FC<JobDetailModalProps> = ({ jobId, onClose }) => {
  const modalRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  // Handle ESC key to close modal, lock background scrolling, and restore focus to opener
  useEffect(() => {
    if (!jobId) {
      return;
    }

    // Capture the element that had focus when the modal was opened, or fall back to the job card
    const active = document.activeElement as HTMLElement | null;
    const cardElement = jobId ? document.getElementById(`job-title-btn-${jobId}`) : null;
    const isLegitOpener =
      active &&
      active !== document.body &&
      active !== document.documentElement &&
      typeof active.focus === "function";
    const openerElement =
      isLegitOpener && (active === cardElement || cardElement?.contains(active))
        ? cardElement || active
        : cardElement;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }

      // Keyboard focus trap within modal dialog
      if (e.key === "Tab" && modalRef.current) {
        const focusableElements = modalRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusableElements.length === 0) return;

        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === firstElement) {
            e.preventDefault();
            lastElement.focus();
          }
        } else {
          if (document.activeElement === lastElement) {
            e.preventDefault();
            firstElement.focus();
          }
        }
      }
    };

    const originalBodyOverflow = document.body.style.overflow;
    const originalHtmlOverflow = document.documentElement.style.overflow;
    document.addEventListener("keydown", handleKeyDown);
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
    closeButtonRef.current?.focus();

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = originalBodyOverflow;
      document.documentElement.style.overflow = originalHtmlOverflow;

      // Restore focus to opener card
      const targetToFocus =
        openerElement && document.contains(openerElement)
          ? openerElement
          : cardElement && document.contains(cardElement)
          ? cardElement
          : jobId
          ? document.getElementById(`job-card-${jobId}`) ||
            document.getElementById(`job-title-btn-${jobId}`)
          : null;

      if (targetToFocus && typeof targetToFocus.focus === "function") {
        requestAnimationFrame(() => {
          targetToFocus.focus();
        });
      }
    };
  }, [jobId, onClose]);

  if (!jobId) {
    return null;
  }

  const handleBackdropClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  return (
    <div className="modal-backdrop" onClick={handleBackdropClick} role="presentation">
      <div
        className="modal-container"
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-job-title"
        onClick={(e) => e.stopPropagation()}
      >
        <JobDetailContent jobId={jobId} variant="modal" onClose={onClose} closeButtonRef={closeButtonRef} />
      </div>
    </div>
  );
};
