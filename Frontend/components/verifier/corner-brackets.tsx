import { cn } from "@/lib/utils"

interface CornerBracketsProps {
  className?: string
}

export function CornerBrackets({ className }: CornerBracketsProps) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "pointer-events-none absolute inset-0 text-brand/20",
        className,
      )}
    >
      <span className="absolute top-2.5 left-2.5 size-2.5 border-t-[1.5px] border-l-[1.5px] border-current" />
      <span className="absolute top-2.5 right-2.5 size-2.5 border-t-[1.5px] border-r-[1.5px] border-current" />
      <span className="absolute bottom-2.5 left-2.5 size-2.5 border-b-[1.5px] border-l-[1.5px] border-current" />
      <span className="absolute right-2.5 bottom-2.5 size-2.5 border-b-[1.5px] border-r-[1.5px] border-current" />
    </div>
  )
}
