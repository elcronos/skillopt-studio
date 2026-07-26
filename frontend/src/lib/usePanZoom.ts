import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Self-contained pan/zoom viewport state for an SVG (or any content) rendered
 * inside a fixed-size canvas. No external dependency — a CSS transform
 * (`translate(x,y) scale(k)`) is applied to a wrapper element.
 *
 * Features:
 *  - mouse-wheel zoom toward the cursor
 *  - click-drag to pan (with a movement threshold so plain clicks still fire on
 *    child nodes — see `wasDragging`)
 *  - programmatic zoom in/out (about the canvas center) and reset
 *  - fit-to-view: scale + center the content so it fills the canvas
 *
 * The hook is presentation-agnostic: bind `viewportRef` to the clipping canvas
 * and apply `transform` to the inner content wrapper.
 */

export interface PanZoomTransform {
  x: number;
  y: number;
  k: number;
}

const MIN_SCALE = 0.1;
const MAX_SCALE = 8;
const ZOOM_STEP = 1.25; // button zoom multiplier
const DRAG_THRESHOLD = 4; // px of movement before a press counts as a drag

function clampScale(k: number) {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, k));
}

export interface UsePanZoom {
  viewportRef: React.RefObject<HTMLDivElement>;
  transform: PanZoomTransform;
  /** CSS transform string for the content wrapper. */
  transformStyle: string;
  isPanning: boolean;
  /** True immediately after a drag — consult this in click handlers to ignore
   *  the click that terminates a pan gesture. */
  wasDragging: () => boolean;
  zoomIn: () => void;
  zoomOut: () => void;
  /** Translate the content plane by a screen-space delta (used to bring an
   *  externally-selected node into view without changing zoom). */
  panBy: (dx: number, dy: number) => void;
  reset: () => void;
  /** Measure content + canvas and fit the content to the viewport. */
  fit: () => void;
  /** Call after the content (SVG) has (re)rendered so fit-on-render can run. */
  measureKey: number;
}

/**
 * @param getContentSize returns the natural [width, height] of the content to
 *        fit, or null if not measurable yet (fit becomes a no-op).
 * @param fitDeps when any of these change, a fit() is scheduled on next frame.
 */
export function usePanZoom(
  getContentSize: () => { width: number; height: number } | null,
  fitDeps: unknown[],
): UsePanZoom {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [transform, setTransform] = useState<PanZoomTransform>({
    x: 0,
    y: 0,
    k: 1,
  });
  const [isPanning, setIsPanning] = useState(false);

  // Mutable drag bookkeeping (refs so handlers stay stable).
  const drag = useRef<{
    active: boolean;
    moved: boolean;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    pointerId: number;
  } | null>(null);
  const draggedRecently = useRef(false);

  const wasDragging = useCallback(() => draggedRecently.current, []);

  const fit = useCallback(() => {
    const vp = viewportRef.current;
    const size = getContentSize();
    if (!vp || !size || size.width <= 0 || size.height <= 0) return;
    const padding = 28;
    const availW = vp.clientWidth - padding * 2;
    const availH = vp.clientHeight - padding * 2;
    if (availW <= 0 || availH <= 0) return;
    // Fit to WIDTH (never upscale past 100%) so tall top-down graphs stay
    // readable and scroll vertically, instead of being shrunk to fit the full
    // height (which made big skills render at ~14%). If the graph already fits
    // both dimensions, center it; otherwise anchor near the top.
    const fitsHeight = size.height * Math.min(availW / size.width, 1) <= availH;
    const k = clampScale(Math.min(availW / size.width, 1));
    const x = (vp.clientWidth - size.width * k) / 2; // center horizontally
    const y = fitsHeight
      ? (vp.clientHeight - size.height * k) / 2 // center if it fits
      : padding; // else anchor to the top and let the user scroll/pan down
    setTransform({ x, y, k });
  }, [getContentSize]);

  const reset = useCallback(() => fit(), [fit]);

  const zoomAboutCenter = useCallback((factor: number) => {
    const vp = viewportRef.current;
    if (!vp) return;
    const cx = vp.clientWidth / 2;
    const cy = vp.clientHeight / 2;
    setTransform((t) => {
      const k = clampScale(t.k * factor);
      const ratio = k / t.k;
      return {
        k,
        x: cx - (cx - t.x) * ratio,
        y: cy - (cy - t.y) * ratio,
      };
    });
  }, []);

  const panBy = useCallback((dx: number, dy: number) => {
    setTransform((t) => ({ ...t, x: t.x + dx, y: t.y + dy }));
  }, []);

  const zoomIn = useCallback(() => zoomAboutCenter(ZOOM_STEP), [zoomAboutCenter]);
  const zoomOut = useCallback(
    () => zoomAboutCenter(1 / ZOOM_STEP),
    [zoomAboutCenter],
  );

  // Wheel zoom toward the cursor. Bound natively (non-passive) so we can
  // preventDefault and stop the page from scrolling.
  useEffect(() => {
    const vp = viewportRef.current;
    if (!vp) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = vp.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const factor = Math.exp(-e.deltaY * 0.0015);
      setTransform((t) => {
        const k = clampScale(t.k * factor);
        const ratio = k / t.k;
        return {
          k,
          x: px - (px - t.x) * ratio,
          y: py - (py - t.y) * ratio,
        };
      });
    };
    vp.addEventListener("wheel", onWheel, { passive: false });
    return () => vp.removeEventListener("wheel", onWheel);
  }, []);

  // Pointer-based pan with a movement threshold.
  useEffect(() => {
    const vp = viewportRef.current;
    if (!vp) return;

    const onPointerDown = (e: PointerEvent) => {
      if (e.button !== 0) return; // primary button only
      drag.current = {
        active: true,
        moved: false,
        startX: e.clientX,
        startY: e.clientY,
        originX: 0,
        originY: 0,
        pointerId: e.pointerId,
      };
      setTransform((t) => {
        if (drag.current) {
          drag.current.originX = t.x;
          drag.current.originY = t.y;
        }
        return t;
      });
      draggedRecently.current = false;
    };

    const onPointerMove = (e: PointerEvent) => {
      const d = drag.current;
      if (!d?.active) return;
      const dx = e.clientX - d.startX;
      const dy = e.clientY - d.startY;
      if (!d.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
      if (!d.moved) {
        d.moved = true;
        setIsPanning(true);
        vp.setPointerCapture(e.pointerId);
      }
      setTransform((t) => ({ ...t, x: d.originX + dx, y: d.originY + dy }));
    };

    const endDrag = (e: PointerEvent) => {
      const d = drag.current;
      if (!d?.active) return;
      if (d.moved) {
        // A real pan ended: swallow the synthetic click that follows.
        draggedRecently.current = true;
        setTimeout(() => {
          draggedRecently.current = false;
        }, 0);
        try {
          vp.releasePointerCapture(e.pointerId);
        } catch {
          /* capture may not be held */
        }
      }
      drag.current = null;
      setIsPanning(false);
    };

    vp.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", endDrag);
    window.addEventListener("pointercancel", endDrag);
    return () => {
      vp.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", endDrag);
      window.removeEventListener("pointercancel", endDrag);
    };
  }, []);

  // Fit-on-render: re-fit whenever the content changes. The bump value is also
  // exposed so consumers can key effects to "content settled" moments.
  const [measureKey, setMeasureKey] = useState(0);
  useEffect(() => {
    const id = requestAnimationFrame(() => {
      fit();
      setMeasureKey((k) => k + 1);
    });
    return () => cancelAnimationFrame(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, fitDeps);

  // Re-fit on viewport resize so the graph stays framed.
  useEffect(() => {
    const vp = viewportRef.current;
    if (!vp || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => fit());
    ro.observe(vp);
    return () => ro.disconnect();
  }, [fit]);

  const transformStyle = `translate(${transform.x}px, ${transform.y}px) scale(${transform.k})`;

  return {
    viewportRef,
    transform,
    transformStyle,
    isPanning,
    wasDragging,
    zoomIn,
    zoomOut,
    panBy,
    reset,
    fit,
    measureKey,
  };
}
