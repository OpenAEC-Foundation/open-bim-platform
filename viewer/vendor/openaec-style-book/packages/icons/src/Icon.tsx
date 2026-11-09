import type { CSSProperties } from "react";

export interface IconProps {
  /** SVG-string, bijv. `editUndo` uit `@openaec/icons`. */
  svg: string;
  /** Breedte en hoogte in px (standaard 20). */
  size?: number;
  /** Toegankelijke naam; zonder title is het icoon decoratief. */
  title?: string;
  className?: string;
  style?: CSSProperties;
}

export function Icon({ svg, size = 20, title, className, style }: IconProps) {
  return (
    <span
      className={className}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      style={{ display: "inline-flex", width: size, height: size, ...style }}
      dangerouslySetInnerHTML={{ __html: svg.replace("<svg ", `<svg width="${size}" height="${size}" `) }}
    />
  );
}
