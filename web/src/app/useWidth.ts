import { useEffect, useState } from "react";

/** Chart width before the container is measured. */
export const W0 = 200;

/** Content width of the element, following the panel as it is resized. */
export function useWidth() {
  // callback ref: the panel div mounts only after the loading state, so observe it when it appears
  const [el, ref] = useState<HTMLDivElement | null>(null);
  const [w, setW] = useState(W0);
  useEffect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const read = () => setW(Math.max(W0, Math.round(el.clientWidth)) || W0);
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [ref, w] as const;
}
