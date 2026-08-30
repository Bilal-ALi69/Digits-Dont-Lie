"use client"

import { useEffect, useRef, useState } from "react"
import { FileTextIcon } from "lucide-react"

import { CornerBrackets } from "@/components/verifier/corner-brackets"

interface ScanStageProps {
  /** The document being analysed, when one was uploaded. */
  file?: File
  /** The typed value, when the user entered one instead of a file. */
  value?: string
}

/** Long digit runs are masked here for the same reason they are masked on the
 *  results and confirm screens: this frame is the most prominent thing on
 *  display during the wait, and quite possibly on a projector in front of a
 *  room. A PAN should not be the largest text in the building. */
function maskIfCardLike(value: string): string {
  const digits = value.replace(/\D/g, "")
  if (digits.length < 12) return value
  return "*".repeat(digits.length - 4) + digits.slice(-4)
}

/** The height the sweep has to travel, published to CSS. The keyframe animates
 *  a transform, so it needs the pixel distance — it cannot express "to the
 *  bottom of my parent" on its own. */
const DEFAULT_STAGE_H = 240

/**
 * The document under the lens.
 *
 * The processing screen used to show a pulsing bar for five seconds, which is a
 * long time to look at nothing in particular — and during a live demo it is
 * five seconds of an audience waiting. This puts the thing the user just handed
 * over on screen instead, with a line sweeping down it and brackets locking
 * onto its corners.
 *
 * Nothing here claims a finding. There are no detection boxes over the page:
 * drawing rectangles on a real document as though OCR had located something
 * there would be inventing analysis output, and the actual results screen is
 * where findings belong. The frame says "this is being read", which is true,
 * and stops there.
 */
export function ScanStage({ file, value }: ScanStageProps) {
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [stageH, setStageH] = useState(DEFAULT_STAGE_H)
  const stageRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!file || !file.type.startsWith("image/")) return
    const url = URL.createObjectURL(file)
    setImageUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  // The sweep travels a pixel distance, so it has to be measured rather than
  // assumed — an image's aspect ratio decides the frame's height and is not
  // known until it has loaded.
  useEffect(() => {
    const el = stageRef.current
    if (!el || typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver(([entry]) => {
      const h = entry.contentRect.height
      if (h > 0) setStageH(h)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const digits = value ? maskIfCardLike(value.trim()) : null

  return (
    <div
      ref={stageRef}
      className="scan-stage bg-surface-inset border-hairline/70 relative mx-auto w-full rounded-2xl border"
      style={{ ["--scan-h" as string]: `${stageH}px` }}
      aria-hidden="true"
    >
      {/* The document itself */}
      {imageUrl ? (
        <img
          src={imageUrl}
          alt=""
          className="max-h-[240px] w-full rounded-2xl object-contain max-sm:max-h-[180px]"
        />
      ) : digits ? (
        <div className="flex min-h-[150px] flex-wrap items-center justify-center gap-x-1 gap-y-2 px-6 py-10 max-sm:min-h-[120px] max-sm:px-3 max-sm:py-7">
          {digits.split("").map((ch, i) => (
            <span
              key={i}
              // Each glyph lights as the sweep reaches it. The delay is the
              // glyph's share of the 2.6s cycle, so the highlight tracks the
              // line down the frame instead of running on a timer of its own.
              className="scan-digit text-muted-foreground font-mono text-2xl font-semibold tabular-nums max-sm:text-lg"
              style={{ ["--digit-delay" as string]: `${(i / Math.max(1, digits.length)) * 900}ms` }}
            >
              {ch === " " ? " " : ch}
            </span>
          ))}
        </div>
      ) : (
        // A PDF has no thumbnail the client can render without pulling in a
        // renderer, so it gets its glyph and the same treatment around it.
        <div className="flex min-h-[150px] flex-col items-center justify-center gap-3 px-6 py-10 max-sm:min-h-[120px] max-sm:py-7">
          <FileTextIcon className="text-muted-foreground/40 size-10" />
          <span className="text-caption text-muted-foreground max-w-[22ch] truncate text-center">
            {file?.name ?? "Document"}
          </span>
        </div>
      )}

      <div className="scan-grid rounded-2xl" />
      <div className="scan-line" />
      {/* Finally wired up — this component has been sitting unused in the repo
          since the scanner idea was first sketched. */}
      <CornerBrackets className="text-orange scan-bracket [&>span]:size-4" />
    </div>
  )
}
