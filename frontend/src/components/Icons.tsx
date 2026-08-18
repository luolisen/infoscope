import type { ReactNode, SVGProps } from "react";

type IconProps = Omit<SVGProps<SVGSVGElement>, "children">;

function Icon({ children, ...props }: IconProps & { children: ReactNode }) {
  return (
    <svg aria-hidden="true" fill="none" focusable="false" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" viewBox="0 0 24 24" {...props}>
      {children}
    </svg>
  );
}

export function SearchIcon(props: IconProps) {
  return <Icon {...props}><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.4 15.4 4.1 4.1" /></Icon>;
}

export function CloseIcon(props: IconProps) {
  return <Icon {...props}><path d="m6.5 6.5 11 11m0-11-11 11" /></Icon>;
}

export function BookmarkIcon({ filled = false, ...props }: IconProps & { filled?: boolean }) {
  return <Icon {...props}><path d="M7 4.5h10v15l-5-3.2-5 3.2z" fill={filled ? "currentColor" : "none"} /></Icon>;
}

export function SendIcon(props: IconProps) {
  return <Icon {...props}><path d="M12 19V5m-5 5 5-5 5 5" /></Icon>;
}

export function PinIcon({ filled = false, ...props }: IconProps & { filled?: boolean }) {
  return <Icon {...props}><path d="m8 4 8 0-1.5 5 2.5 2.5v1H7v-1L9.5 9zM12 12.5V20" fill={filled ? "currentColor" : "none"} /></Icon>;
}

export function ChevronIcon({ direction = "right", ...props }: IconProps & { direction?: "left" | "right" }) {
  const path = direction === "left" ? "m14.5 6-6 6 6 6" : "m9.5 6 6 6-6 6";
  return <Icon {...props}><path d={path} /></Icon>;
}
