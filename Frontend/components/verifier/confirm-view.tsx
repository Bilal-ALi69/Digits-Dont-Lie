"use client"

import { useState } from "react"
import {
  BanknoteIcon,
  CreditCardIcon,
  FileDigitIcon,
  FileTextIcon,
  FingerprintIcon,
  type LucideIcon,
} from "lucide-react"

import { cn } from "@/lib/utils"
import type { Candidate, DocType } from "@/lib/verifier"
import { Button } from "@/components/ui/button"
import { pressProps } from "@/components/verifier/sheen"

const ICONS: Record<DocType, LucideIcon> = {
  card: CreditCardIcon,
  amount: BanknoteIcon,
  invoice: FileDigitIcon,
  id: FingerprintIcon,
  // A whole document is never offered as a choice here — the backend reports it
  // from the document's own structure, not from a guess the user must settle.
  document: FileTextIcon,
}

interface ConfirmViewProps {
  value: string
  candidates: Candidate[]
  onConfirm: (type: DocType) => void
}

// Card is one of the still-undetermined candidates here, so long digit runs
// (potential PANs) are masked the same way results-view masks confirmed
// cards — showing the full number in plaintext before the type is even
// confirmed would defeat that protection.
function maskIfCardLike(value: string): string {
  const digits = value.replace(/\D/g, "")
  if (digits.length < 12) return value
  return "*".repeat(digits.length - 4) + digits.slice(-4)
}

export function ConfirmView({ value, candidates, onConfirm }: ConfirmViewProps) {
  const [selected, setSelected] = useState<DocType | null>(candidates[0]?.type ?? null)
  const displayValue = maskIfCardLike(value)

  return (
    <div className="rise mx-auto w-full max-w-md">
      <div className="mb-8 text-center max-sm:mb-6">
        <h1 className="text-foreground text-title font-semibold text-balance max-sm:text-headline max-sm:tracking-[-0.02em]">
          We&apos;re not fully sure what this is
        </h1>
        {/* An uploaded file has no client-side value to name here, so the
            sentence drops the reference rather than trailing off into "on ." */}
        <p className="mt-3 text-body text-muted-foreground text-pretty max-sm:text-callout">
          {displayValue ? (
            <>
              Confirm the type so we can run the right checks on{" "}
              <span className="font-mono font-medium text-foreground">{displayValue}</span>.
            </>
          ) : (
            <>Confirm the type so we can run the right checks.</>
          )}
        </p>
      </div>

      <div className="flex flex-col gap-3">
        {candidates.map((candidate) => {
          const Icon = ICONS[candidate.type]
          const isSelected = selected === candidate.type
          const pct = Math.round(candidate.confidence * 100)
          return (
            <button
              key={candidate.type}
              type="button"
              onClick={() => setSelected(candidate.type)}
              aria-pressed={isSelected}
              {...pressProps}
              className={cn(
                "tactile-card flex items-center gap-3.5 rounded-2xl border bg-surface-inset p-4 text-left outline-none active:scale-[0.985] focus-visible:ring-3 focus-visible:ring-orange/30",
                // A full-width row does not scale on press — that reads as the
                // page flinching. .row-press washes it under the finger instead,
                // and the 64px floor makes it a target rather than a paragraph.
                "row-press max-sm:min-h-16 max-sm:gap-3.5 max-sm:rounded-[1.25rem] max-sm:p-4 max-sm:active:scale-100",
                isSelected
                  ? "border-orange/50 bg-orange/8"
                  : "border-border",
              )}
            >
              <span
                className={cn(
                  "flex size-10 shrink-0 items-center justify-center rounded-xl transition-colors",
                  isSelected
                    ? "bg-orange/15 text-orange-ink"
                    : "bg-surface-raised text-muted-foreground",
                )}
              >
                <Icon className="size-5" />
              </span>
              <span className="flex-1">
                <span className="block text-body font-medium text-foreground">{candidate.label}</span>
                <span className="block text-caption text-muted-foreground">
                  {pct}% match
                </span>
              </span>
              <span
                className={cn(
                  "flex size-5 shrink-0 items-center justify-center rounded-full border-2 transition-[background-color,border-color] duration-(--dur-press) ease-(--ease-standard)",
                  isSelected ? "border-orange bg-orange" : "border-border",
                )}
              >
                <span
                  className={cn(
                    "size-2 rounded-full bg-white transition-transform duration-(--dur-press) ease-(--spring-press) motion-reduce:transition-none",
                    isSelected ? "scale-100" : "scale-0",
                  )}
                />
              </span>
            </button>
          )
        })}
      </div>

      {/* Desktop. On a phone this lives in the pinned bar below, so the primary
          action is in the same place on every screen of the flow instead of
          being reachable on one and scrolled off on the next. */}
      <Button
        size="lg"
        disabled={!selected}
        onClick={() => selected && onConfirm(selected)}
        className="btn-gradient mt-6 h-12 w-full rounded-2xl text-body font-semibold text-white disabled:opacity-40 max-sm:hidden"
      >
        Continue
      </Button>

      <div className="action-bar hidden max-sm:block">
        <Button
          size="lg"
          disabled={!selected}
          onClick={() => selected && onConfirm(selected)}
          {...pressProps}
          className="btn-gradient m3-press btn-liquid m3x-morph h-14 w-full text-callout font-semibold text-white disabled:opacity-55"
        >
          Continue
        </Button>
      </div>
    </div>
  )
}
