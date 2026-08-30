/**
 * Pointer handlers for `.sheen-surface`.
 *
 * The specular highlight was hover-only, which means it did not exist on a
 * phone — `:hover` on a touchscreen is emulated, latching on after a tap and
 * staying stuck until something else is tapped. The CSS now gates hover behind
 * `(hover: hover)` and exposes a press state instead; these handlers drive it.
 *
 * Everything is written straight onto the node rather than through React state:
 * a pointermove that re-rendered the card on every frame would be far more
 * expensive than the single gradient the compositor is already handling.
 */

function setPoint(el: HTMLElement, clientX: number, clientY: number) {
  const r = el.getBoundingClientRect()
  el.style.setProperty("--mx", `${((clientX - r.left) / r.width) * 100}%`)
  el.style.setProperty("--my", `${((clientY - r.top) / r.height) * 100}%`)
}

export const sheenProps = {
  onPointerMove: (e: React.PointerEvent<HTMLElement>) => {
    setPoint(e.currentTarget, e.clientX, e.clientY)
  },
  onPointerDown: (e: React.PointerEvent<HTMLElement>) => {
    setPoint(e.currentTarget, e.clientX, e.clientY)
    // Only touch and pen get the press bloom. A mouse already has hover, and
    // showing both would double the highlight on every click.
    if (e.pointerType !== "mouse") e.currentTarget.dataset.pressed = "true"
  },
  onPointerUp: (e: React.PointerEvent<HTMLElement>) => {
    delete e.currentTarget.dataset.pressed
  },
  // Fires when the browser takes the gesture over — most importantly when a
  // touch turns into a scroll. Without this the highlight would be left lit
  // while the page moved away underneath it.
  onPointerCancel: (e: React.PointerEvent<HTMLElement>) => {
    delete e.currentTarget.dataset.pressed
  },
  onPointerLeave: (e: React.PointerEvent<HTMLElement>) => {
    delete e.currentTarget.dataset.pressed
  },
}

/**
 * Press handlers for `.m3-press`.
 *
 * Separate from `sheenProps` because a button wants the state layer on every
 * pointer type — a mouse included — whereas the card's specular bloom is only
 * for touch, since a mouse already has hover.
 */
export const pressProps = {
  onPointerDown: (e: React.PointerEvent<HTMLElement>) => {
    setPoint(e.currentTarget, e.clientX, e.clientY)
    e.currentTarget.dataset.pressed = "true"
  },
  onPointerUp: (e: React.PointerEvent<HTMLElement>) => {
    delete e.currentTarget.dataset.pressed
  },
  onPointerCancel: (e: React.PointerEvent<HTMLElement>) => {
    delete e.currentTarget.dataset.pressed
  },
  onPointerLeave: (e: React.PointerEvent<HTMLElement>) => {
    delete e.currentTarget.dataset.pressed
  },
}
