"use client"

import { useEffect, useRef, useState } from "react"

import { cn } from "@/lib/utils"

/* ─── Reading primitives ──────────────────────────────────────────────────────
   The old page put every one of its fourteen sections behind an accordion, so
   reading it end to end meant fourteen clicks and the page never showed its own
   length. A methodology document's job is to be read, not to be compact — so
   the content is open, and the work of keeping it from feeling endless is done
   by rhythm instead: a fixed measure, one heading scale, and a lot of air.
   -------------------------------------------------------------------------- */

/** The prose measure. Body copy on this page is set at 15px rather than the
 *  app's 14px — this is the one screen someone reads for minutes rather than
 *  glances at — so 64ch lands around 560px, comfortably inside the 45–75
 *  character band. Figures and headings deliberately run wider than this, to
 *  the full column, so the page has two widths instead of one and the visual
 *  material gets room to be visual. */
export const MEASURE = "max-w-[64ch]"

/** Reveals its children once, when they first reach the viewport.
 *
 *  Deliberately one-shot and deliberately small (12px, no scale): a long
 *  document that re-animates on every scroll direction change is exhausting to
 *  read, which is the opposite of what this page is for. */
export function Reveal({
  children,
  className,
  delay = 0,
}: {
  children: React.ReactNode
  className?: string
  delay?: number
}) {
  const [shown, setShown] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (typeof IntersectionObserver === "undefined") {
      setShown(true)
      return
    }
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setShown(true)
          io.disconnect()
        }
      },
      { rootMargin: "0px 0px -12% 0px", threshold: 0.05 },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [])

  return (
    <div
      ref={ref}
      className={cn(
        "transition-[opacity,transform] duration-[560ms] ease-(--ease-rise) motion-reduce:transition-none",
        shown ? "translate-y-0 opacity-100" : "translate-y-3 opacity-0",
        // Reduced motion keeps the content, drops the travel.
        "motion-reduce:translate-y-0 motion-reduce:opacity-100",
        className,
      )}
      style={{ transitionDelay: shown ? `${delay}ms` : "0ms" }}
    >
      {children}
    </div>
  )
}

/** An act heading. Four of these carry the whole document, so a reader always
 *  knows which quarter of the pipeline they are standing in. */
export function Act({
  numeral,
  title,
  blurb,
  icon: Icon,
}: {
  numeral: string
  title: string
  blurb: string
  icon: React.ElementType
}) {
  return (
    <Reveal className="mt-28 mb-10 first:mt-0 max-sm:mt-16 max-sm:mb-7">
      <div className="flex items-center gap-3">
        <span className="bg-orange/10 ring-orange/20 flex size-7 items-center justify-center rounded-lg ring-1 ring-inset">
          <Icon className="text-orange-ink size-3.5" />
        </span>
        <span className="text-orange-ink/70 font-mono text-mini font-bold tracking-[0.2em]">
          {numeral}
        </span>
        <span className="bg-hairline-strong/50 h-px flex-1" />
      </div>
      <h2 className="font-display text-heading text-display-sm mt-5 font-extrabold">{title}</h2>
      <p className={cn("text-muted-foreground text-lead mt-3 leading-[1.55]", MEASURE)}>{blurb}</p>
    </Reveal>
  )
}

/** A numbered section. The number is a quiet marker in the margin rather than
 *  part of the heading, so the headings themselves stay scannable. */
export function Section({
  id,
  n,
  title,
  children,
}: {
  id: string
  n: string
  title: string
  children: React.ReactNode
}) {
  return (
    <Reveal>
      {/* scroll-mt clears the sticky header, so an anchor jump does not land
          the heading underneath the bar. */}
      <section id={id} className="scroll-mt-28 py-9 max-sm:scroll-mt-20 max-sm:py-6">
        <div className="flex items-baseline gap-3">
          <span className="text-orange-ink/45 font-mono text-mini font-bold tabular-nums">{n}</span>
          <h3 className="font-display text-title text-foreground font-bold">{title}</h3>
        </div>
        {/* Not constrained here: each child sets its own width, so prose sits at
            the 64ch measure while figures run to the full column. */}
        <div className="mt-5 flex flex-col gap-5">{children}</div>
      </section>
    </Reveal>
  )
}

export function P({ children }: { children: React.ReactNode }) {
  return (
    <p className={cn("text-muted-foreground text-callout leading-[1.75]", MEASURE)}>
      {children}
    </p>
  )
}

export function Strong({ children }: { children: React.ReactNode }) {
  return <strong className="text-foreground font-semibold">{children}</strong>
}

/** Key–value content, which is most of what the old page expressed as bullet
 *  lists of "**Term** — description". A definition list says the same thing
 *  with the term actually distinguished, and scans in a fraction of the time. */
export function Terms({
  items,
}: {
  // ReactNode rather than string: the API-endpoint rows set their term as
  // `POST /api/analyze` with the path in <Code>, and a string type forced that
  // through a cast at the call site.
  items: { key?: string; term: React.ReactNode; desc: React.ReactNode }[]
}) {
  return (
    <dl className={cn("border-hairline/60 flex flex-col gap-0 border-t", MEASURE)}>
      {items.map((it, i) => (
        <div
          key={it.key ?? (typeof it.term === "string" ? it.term : i)}
          className="border-hairline/60 grid gap-x-6 gap-y-1 border-b py-3.5 sm:grid-cols-[10.5rem_1fr]"
        >
          <dt className="text-footnote text-foreground font-semibold">{it.term}</dt>
          <dd className="text-footnote text-muted-foreground leading-[1.7]">{it.desc}</dd>
        </div>
      ))}
    </dl>
  )
}

/** An ordered procedure. Used where the sequence is the content — the Luhn
 *  steps, chiefly — and numbered in the margin so the steps align. */
export function Steps({ items }: { items: React.ReactNode[] }) {
  return (
    <ol className={cn("flex flex-col gap-3", MEASURE)}>
      {items.map((it, i) => (
        <li key={i} className="flex gap-3">
          <span className="bg-orange/12 text-orange-ink text-mini mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full font-mono font-bold tabular-nums">
            {i + 1}
          </span>
          <span className="text-footnote text-muted-foreground flex-1 leading-[1.7]">{it}</span>
        </li>
      ))}
    </ol>
  )
}

/** A quiet aside. Reserved for genuine caveats, so it keeps its weight — the
 *  moment everything is a callout, nothing is. */
export function Note({ children }: { children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "bg-surface-inset/70 border-l-orange/50 rounded-r-xl border-l-2 py-3.5 pr-4 pl-4",
        MEASURE,
      )}
    >
      <p className="text-footnote text-muted-foreground leading-[1.7]">{children}</p>
    </div>
  )
}

/** A display figure: something set apart from the prose because it is the
 *  thing being explained rather than a sentence about it. */
export function Figure({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <figure className="panel-raised bg-surface-card border-hairline/70 my-3 overflow-hidden rounded-2xl border">
      <figcaption className="border-hairline/60 text-micro text-muted-foreground/70 border-b px-5 py-2.5 font-mono font-semibold tracking-[0.16em] uppercase max-sm:px-4">
        {label}
      </figcaption>
      <div className="px-5 py-5 max-sm:px-4 max-sm:py-4">{children}</div>
    </figure>
  )
}

export function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="bg-secondary text-orange-ink text-caption rounded px-1.5 py-0.5 font-mono">
      {children}
    </code>
  )
}
