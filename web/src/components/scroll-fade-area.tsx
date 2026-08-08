"use client";

import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type Ref,
} from "react";

import { cn } from "@/lib/utils";

type ScrollFadeAreaProps = {
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  viewportClassName?: string;
  /** Tailwind `from-*` class for the fade gradient. */
  fadeFromClassName?: string;
  watch?: unknown;
  viewportRef?: Ref<HTMLDivElement>;
};

function assignRef<T>(ref: Ref<T> | undefined, value: T | null) {
  if (!ref) return;
  if (typeof ref === "function") {
    ref(value);
    return;
  }
  ref.current = value;
}

export function ScrollFadeArea({
  children,
  className,
  contentClassName,
  viewportClassName,
  fadeFromClassName = "from-background",
  watch,
  viewportRef,
}: ScrollFadeAreaProps) {
  const localRef = useRef<HTMLDivElement | null>(null);
  const [scrollFade, setScrollFade] = useState({ top: false, bottom: false });

  useEffect(() => {
    const viewport = localRef.current;
    if (!viewport) return;

    const updateFade = () => {
      const { scrollTop, scrollHeight, clientHeight } = viewport;
      const maxScroll = scrollHeight - clientHeight;
      setScrollFade({
        top: scrollTop > 4,
        bottom: maxScroll > 4 && scrollTop < maxScroll - 4,
      });
    };

    updateFade();
    viewport.addEventListener("scroll", updateFade, { passive: true });
    const resizeObserver = new ResizeObserver(updateFade);
    resizeObserver.observe(viewport);
    const content = viewport.firstElementChild;
    if (content) resizeObserver.observe(content);

    return () => {
      viewport.removeEventListener("scroll", updateFade);
      resizeObserver.disconnect();
    };
  }, [watch]);

  return (
    <div className={cn("relative min-h-0", className)}>
      <div
        ref={(node) => {
          localRef.current = node;
          assignRef(viewportRef, node);
        }}
        className={cn("h-full min-h-0 overflow-y-auto", viewportClassName)}
      >
        <div className={contentClassName}>{children}</div>
      </div>

      <div
        aria-hidden="true"
        className={cn(
          "pointer-events-none absolute inset-x-0 top-0 z-10 h-10 bg-linear-to-b to-transparent transition-opacity duration-200 ease-out motion-reduce:transition-none",
          fadeFromClassName,
          scrollFade.top ? "opacity-100" : "opacity-0",
        )}
      />
      <div
        aria-hidden="true"
        className={cn(
          "pointer-events-none absolute inset-x-0 bottom-0 z-10 h-14 bg-linear-to-t to-transparent transition-opacity duration-200 ease-out motion-reduce:transition-none",
          fadeFromClassName,
          scrollFade.bottom ? "opacity-100" : "opacity-0",
        )}
      />
    </div>
  );
}
