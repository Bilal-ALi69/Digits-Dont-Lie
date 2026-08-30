import { BrandPopover } from "@/components/verifier/brand-popover"
import { ThemeToggle } from "@/components/verifier/theme-toggle"

export function AppHeader() {
  return (
    <header className="chrome-bar fixed top-0 right-0 left-0 z-40">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6 max-sm:h-14 max-sm:px-4">
        {/* The wordmark is the disclosure. This replaced a "How it works"
            button parked under the input card, which spent a permanent slot in
            the primary flow on something nobody needs mid-task. */}
        <BrandPopover>
          {/* Brand icon — shield with "1" digit motif. The shield draws itself
              once on load: a 64-unit dash offset retracting to 0, which reads as
              the mark being verified rather than placed. It is the first thing
              on screen, so it is the right place to spend a gesture. */}
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden="true"
            className="shrink-0 overflow-visible"
          >
            <path
              d="M12 2.5L4 6v5.5c0 5.5 3.4 10.6 8 12 4.6-1.4 8-6.5 8-12V6L12 2.5z"
              stroke="var(--orange-ink)"
              strokeWidth="1.4"
              strokeLinejoin="round"
              fill="none"
              pathLength={64}
              className="[stroke-dasharray:64] [stroke-dashoffset:64] animate-[brand-draw_900ms_var(--ease-rise)_200ms_forwards] motion-reduce:animate-none motion-reduce:[stroke-dashoffset:0]"
            />
            {/* "1" digit — core identity. Drawn after the shield closes, so the
                two strokes read as one gesture rather than a race. */}
            <path
              d="M12.3 7.2v9.2M10.2 9.4l2.1-2.2 2.1 2.2"
              stroke="var(--orange-ink)"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              pathLength={64}
              className="[stroke-dasharray:64] [stroke-dashoffset:64] animate-[brand-draw_620ms_var(--ease-rise)_760ms_forwards] motion-reduce:animate-none motion-reduce:[stroke-dashoffset:0]"
            />
          </svg>
          <span className="font-display text-heading text-xl font-extrabold tracking-tight max-sm:text-[1.0625rem]">
            Digits Don&apos;t <span className="text-orange-ink">Lie</span>
          </span>
          {/* At 360px this row needed ~308px of its 312px and fit only by
              squashing. The pill is the one element here with no job, so it is
              what gives way. */}
          <span className="text-micro text-orange-ink bg-orange/15 ring-orange/20 ml-1 rounded-full px-2 py-0.5 font-medium tracking-wide ring-1 ring-inset max-sm:hidden">
            Researchathon
          </span>
        </BrandPopover>
        <ThemeToggle />
      </div>
    </header>
  )
}
