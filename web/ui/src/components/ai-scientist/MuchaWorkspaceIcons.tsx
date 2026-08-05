import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function IconFrame(props: IconProps) {
  return (
    <svg
      aria-hidden="true"
      fill="currentColor"
      height="1em"
      viewBox="0 0 24 24"
      width="1em"
      {...props}
    />
  );
}

export function ComposeIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path d="M15.67 3.91a3.12 3.12 0 0 1 4.42 4.42l-5.94 5.93a5 5 0 0 1-2.83 1.42l-2.18.31a1 1 0 0 1-1.13-1.13l.31-2.18a5 5 0 0 1 1.42-2.83l5.93-5.94Zm3 1.42a1.12 1.12 0 0 0-1.58 0l-5.94 5.93a3 3 0 0 0-.85 1.7l-.12.86.86-.12a3 3 0 0 0 1.7-.85l5.93-5.94a1.12 1.12 0 0 0 0-1.58ZM11 4a1 1 0 0 1-1 1c-1 0-1.7.01-2.25.06-.54.05-.86.14-1.11.27a3 3 0 0 0-1.31 1.31c-.13.26-.23.61-.28 1.21C5 8.47 5 9.26 5 10.4v3.2c0 1.14 0 1.93.05 2.55.05.6.15.95.28 1.21a3 3 0 0 0 1.31 1.31c.26.13.61.23 1.21.28.62.05 1.41.05 2.55.05h3.2c1.14 0 1.93 0 2.55-.05.6-.05.95-.15 1.21-.28a3 3 0 0 0 1.31-1.31c.13-.25.22-.57.27-1.11.05-.55.06-1.26.06-2.25a1 1 0 1 1 2 0c0 .98-.01 1.78-.07 2.44-.06.67-.19 1.27-.47 1.83a5 5 0 0 1-2.19 2.19c-.59.3-1.23.43-1.96.49-.71.06-1.58.06-2.67.06h-3.28c-1.09 0-1.96 0-2.67-.06-.73-.06-1.37-.19-1.96-.49a5 5 0 0 1-2.19-2.19c-.3-.59-.43-1.23-.49-1.96C3 15.6 3 14.73 3 13.64v-3.28C3 9.27 3 8.4 3.06 7.69c.06-.73.19-1.37.49-1.96a5 5 0 0 1 2.19-2.19c.56-.28 1.16-.41 1.83-.47C8.22 3.01 9.02 3 10 3a1 1 0 0 1 1 1Z" />
    </IconFrame>
  );
}

export function SidebarIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path fillRule="evenodd" d="M6 5a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h2V5H6Zm4 0v14h8a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1h-8ZM3 6a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3v12a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V6Z" clipRule="evenodd" />
    </IconFrame>
  );
}

export function PanelIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path fillRule="evenodd" d="M18 5a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1h-2V5h2Zm-4 0v14H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h8Zm7 1a3 3 0 0 0-3-3H6a3 3 0 0 0-3 3v12a3 3 0 0 0 3 3h12a3 3 0 0 0 3-3V6Z" clipRule="evenodd" />
    </IconFrame>
  );
}

export function SourcesIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path d="M6.75 13a4.25 4.25 0 0 1 4.13 3.25c.8 0 1.4-.01 1.87-.04.29-.02.49-.04.63-.07.14-.03.18-.06.16-.05l.14-.11a1 1 0 0 0 .3-.91l-.04-.17c0 .02-.01-.02-.1-.13a5.5 5.5 0 0 0-1.28-1.09L11.4 12.8c-.88-.66-1.58-1.18-2.08-1.61a4.9 4.9 0 0 1-1.05-1.2l-.08-.2a3 3 0 0 1 1.19-3.56l.19-.11c.46-.23 1.02-.3 1.55-.33.53-.03 1.19-.04 2-.04a4.25 4.25 0 1 1 0 2c-.8 0-1.41.01-1.87.04-.29.02-.49.04-.63.07-.14.03-.18.06-.16.05l-.08.04a1 1 0 0 0-.32 1.15c0-.02.01.02.1.13.1.11.24.25.46.44.44.38 1.08.86 1.98 1.53l1.18.89c.35.27.65.51.9.72.47.4.93.85 1.13 1.4l.08.25a3 3 0 0 1-1.05 3.16l-.21.15c-.49.32-1.14.4-1.75.44-.53.03-1.19.04-2 .04A4.25 4.25 0 1 1 6.75 13Zm0 2a2.25 2.25 0 1 0 0 4.5 2.25 2.25 0 0 0 0-4.5Zm10.5-10.5a2.25 2.25 0 1 0 0 4.5 2.25 2.25 0 0 0 0-4.5Z" />
    </IconFrame>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path d="M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16ZM2 12C2 6.48 6.48 2 12 2s10 4.48 10 10-4.48 10-10 10S2 17.52 2 12Zm14.08-4.07a1 1 0 0 1 .24 1.4l-4.75 6.75a1 1 0 0 1-1.56.1l-2.5-2.75a1 1 0 1 1 1.48-1.35l1.66 1.82 4.03-5.73a1 1 0 0 1 1.4-.24Z" />
    </IconFrame>
  );
}

export function SettingsIcon(props: IconProps) {
  return (
    <IconFrame fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="2" {...props}>
      <path d="M4 7h10M18 7h2M4 17h2M10 17h10" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="8" cy="17" r="2" />
    </IconFrame>
  );
}

export function ArrowUpIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path fillRule="evenodd" d="M11.29 5.29a1 1 0 0 1 1.42 0l5 5a1 1 0 0 1-1.42 1.42L13 8.41V18a1 1 0 1 1-2 0V8.41l-3.29 3.3a1 1 0 0 1-1.42-1.42l5-5Z" clipRule="evenodd" />
    </IconFrame>
  );
}

export function StopIcon(props: IconProps) {
  return (
    <IconFrame {...props}>
      <path fillRule="evenodd" d="M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16ZM2 12C2 6.48 6.48 2 12 2s10 4.48 10 10-4.48 10-10 10S2 17.52 2 12Z" clipRule="evenodd" />
      <path d="M9 10a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1v-4Z" />
    </IconFrame>
  );
}

export function CloseIcon(props: IconProps) {
  return (
    <IconFrame fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="2" {...props}>
      <path d="m7 7 10 10M17 7 7 17" />
    </IconFrame>
  );
}
