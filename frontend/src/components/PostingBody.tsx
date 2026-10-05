import { useLayoutEffect, useRef } from "react";

interface PostingBodyProps {
  html: string;
  summary: boolean;
  language?: string | null;
  hasOriginal: boolean;
}

/** Crossfade the two posting views while resizing their shared container. Only the incoming view is interactive. */
export function PostingBody({ html, summary, language, hasOriginal }: PostingBodyProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const previous = useRef<{ node: HTMLDivElement; height: number } | null>(null);

  useLayoutEffect(() => {
    const container = containerRef.current;
    const content = contentRef.current;
    if (!container || !content) return;
    const old = previous.current;
    const next = { node: content.cloneNode(true) as HTMLDivElement, height: content.getBoundingClientRect().height };
    previous.current = next;
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => {
      next.height = content.getBoundingClientRect().height;
    }) : null;
    observer?.observe(content);
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!old || reduced?.matches || typeof container.animate !== "function") return () => observer?.disconnect();

    const outgoing = old.node;
    outgoing.classList.add("posting-body-outgoing");
    outgoing.setAttribute("aria-hidden", "true");
    outgoing.inert = true;
    outgoing.querySelectorAll("[id]").forEach((element) => element.removeAttribute("id"));
    container.appendChild(outgoing);
    container.classList.add("is-transitioning");
    const options = { duration: 260, easing: "cubic-bezier(0.22, 1, 0.36, 1)" };
    const animations = [
      container.animate([{ height: `${old.height}px` }, { height: `${next.height}px` }], { ...options, fill: "both" }),
      content.animate([{ opacity: 0, transform: "translateY(4px)" }, { opacity: 1, transform: "translateY(0)" }], options),
      outgoing.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 140, fill: "forwards" }),
    ];
    const finish = () => {
      animations.forEach((animation) => animation.cancel());
      outgoing.remove();
      container.classList.remove("is-transitioning");
    };
    animations[0].onfinish = finish;
    const preferenceChanged = () => { if (reduced?.matches) finish(); };
    reduced?.addEventListener("change", preferenceChanged);
    return () => {
      // Preserve the current visible height when a reader changes the toggle again before the animation ends.
      if (container.classList.contains("is-transitioning")) next.height = container.getBoundingClientRect().height;
      observer?.disconnect();
      reduced?.removeEventListener("change", preferenceChanged);
      finish();
    };
  }, [html, summary, language, hasOriginal]);

  return (
    <div ref={containerRef} className="posting-body-transition">
      <div ref={contentRef} className="posting-body-content">
        {summary && <p className="job-summary-note">Selected excerpts from the employer’s posting. Full Posting includes all details.</p>}
        {html ? (
          <div lang={language ?? undefined} className="modal-description job-description-prose" dangerouslySetInnerHTML={{ __html: html }} />
        ) : (
          <p className="no-description-text">{hasOriginal ? "Select Full Posting to read the employer’s description." : "No additional description provided in source posting."}</p>
        )}
      </div>
    </div>
  );
}
