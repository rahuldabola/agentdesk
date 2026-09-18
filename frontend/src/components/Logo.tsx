export default function Logo({ size = 32 }: { size?: number }) {
  return (
    <div
      className="relative flex shrink-0 items-center justify-center rounded-[30%] shadow-[0_6px_24px_-6px_#7c6dfa]"
      style={{ width: size, height: size, background: "linear-gradient(135deg,#9b8cff 0%,#6a5af0 55%,#38bdf8 130%)" }}
    >
      <svg width={size * 0.55} height={size * 0.55} viewBox="0 0 24 24" fill="none" aria-hidden>
        <path d="M6 18 L12 6 L18 18 M8.5 13.5 H15.5" stroke="white" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}
