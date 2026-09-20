export function FlowIcon({ children, className = '' }: { children: string; className?: string }) {
  return <span aria-hidden="true" className={`flow-icon ${className}`}>{children}</span>;
}
