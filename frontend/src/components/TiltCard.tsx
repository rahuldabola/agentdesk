import { useRef, type CSSProperties, type ReactNode } from "react";

/**
 * A card that tilts toward the pointer in 3D with a moving glare highlight.
 * Pure CSS transforms, so it's cheap and degrades to a flat card on touch.
 */
export default function TiltCard({
  children,
  className = "",
  style,
  max = 8,
  onClick,
  onMouseEnter,
  onMouseLeave,
  as = "div",
  ariaLabel,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  max?: number;
  onClick?: () => void;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
  as?: "div" | "button";
  ariaLabel?: string;
}) {
  const ref = useRef<HTMLElement>(null);

  function handleMove(e: React.PointerEvent) {
    const el = ref.current;
    if (!el || e.pointerType !== "mouse") return;
    const rect = el.getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width;
    const py = (e.clientY - rect.top) / rect.height;
    el.style.transform = `perspective(900px) rotateX(${((0.5 - py) * max).toFixed(2)}deg) rotateY(${((px - 0.5) * max).toFixed(2)}deg) translateZ(0)`;
    el.style.setProperty("--gx", `${(px * 100).toFixed(1)}%`);
    el.style.setProperty("--gy", `${(py * 100).toFixed(1)}%`);
    el.style.setProperty("--glare", "1");
  }

  function reset() {
    const el = ref.current;
    if (!el) return;
    el.style.transform = "perspective(900px) rotateX(0deg) rotateY(0deg)";
    el.style.setProperty("--glare", "0");
    onMouseLeave?.();
  }

  const Tag = as;
  return (
    <Tag
      ref={ref as never}
      type={as === "button" ? "button" : undefined}
      aria-label={ariaLabel}
      onPointerMove={handleMove}
      onPointerLeave={reset}
      onMouseEnter={onMouseEnter}
      onClick={onClick}
      className={`relative overflow-hidden transition-transform duration-200 ease-out will-change-transform [transform-style:preserve-3d] ${className}`}
      style={style}
    >
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 transition-opacity duration-300"
        style={{
          opacity: "var(--glare, 0)",
          background: "radial-gradient(circle at var(--gx, 50%) var(--gy, 50%), rgba(255,255,255,0.10), transparent 55%)",
        }}
      />
      {children}
    </Tag>
  );
}
