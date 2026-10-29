import { useEffect, useRef, type PointerEvent } from "react";
import { useTranslation } from "react-i18next";

/** The snapshot is scaled down to this width: a BCF snapshot is at most 5 MB. */
const MAX_WIDTH = 1280;
const LINE_WIDTH = 4;

/**
 * The snapshot of a new issue, with free lines drawn over it in the accent colour. `onChange` gets the PNG (base64,
 * without the data-URL prefix) after the image is ready and after every line.
 */
export function Markup({ beeld, onChange }: { beeld: Blob; onChange: (png: string) => void }) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<ImageBitmap | null>(null);
  const drawingRef = useRef(false);
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  const emit = () => {
    const canvas = canvasRef.current;
    if (canvas) onChangeRef.current(canvas.toDataURL("image/png").split(",", 2)[1] ?? "");
  };

  const drawImage = () => {
    const canvas = canvasRef.current;
    const image = imageRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !image || !context) return;
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    emit();
  };

  useEffect(() => {
    let cancelled = false;
    void createImageBitmap(beeld).then((image) => {
      if (cancelled) return;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const scale = Math.min(1, MAX_WIDTH / image.width);
      canvas.width = Math.round(image.width * scale);
      canvas.height = Math.round(image.height * scale);
      imageRef.current = image;
      drawImage();
    });
    return () => {
      cancelled = true;
    };
    // drawImage only reads refs, so the image is the only dependency.
  }, [beeld]);

  const point = (event: PointerEvent<HTMLCanvasElement>) => {
    const canvas = event.currentTarget;
    const box = canvas.getBoundingClientRect();
    return [((event.clientX - box.left) / box.width) * canvas.width, ((event.clientY - box.top) / box.height) * canvas.height];
  };

  const onPointerDown = (event: PointerEvent<HTMLCanvasElement>) => {
    const context = event.currentTarget.getContext("2d");
    if (!context) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drawingRef.current = true;
    context.strokeStyle = getComputedStyle(event.currentTarget).getPropertyValue("--theme-accent").trim() || "#d97706";
    context.lineWidth = LINE_WIDTH;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.beginPath();
    context.moveTo(...(point(event) as [number, number]));
  };

  const onPointerMove = (event: PointerEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current) return;
    const context = event.currentTarget.getContext("2d");
    context?.lineTo(...(point(event) as [number, number]));
    context?.stroke();
  };

  const onPointerUp = () => {
    if (!drawingRef.current) return;
    drawingRef.current = false;
    emit();
  };

  return (
    <div className="markup">
      <canvas
        ref={canvasRef}
        className="markup__canvas"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        aria-label={t("markering")}
      />
      <div className="markup__bar">
        <span>{t("markering")}</span>
        <button type="button" className="oa-btn oa-btn--ghost oa-btn--sm" onClick={drawImage}>
          {t("markering_wissen")}
        </button>
      </div>
    </div>
  );
}
