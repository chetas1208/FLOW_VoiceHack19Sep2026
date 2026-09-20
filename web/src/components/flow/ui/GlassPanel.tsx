import type { ComponentPropsWithoutRef, ElementType, ReactNode } from 'react';

type GlassPanelProps<T extends ElementType> = {
  as?: T;
  level?: 1 | 2;
  primary?: boolean;
  className?: string;
  children: ReactNode;
} & Omit<ComponentPropsWithoutRef<T>, 'as' | 'className' | 'children'>;

export function GlassPanel<T extends ElementType = 'div'>({
  as,
  level = 2,
  primary,
  className = '',
  children,
  ...rest
}: GlassPanelProps<T>) {
  const Tag = as ?? 'div';
  const classes = [
    'glass-panel',
    level === 2 ? 'level-2' : '',
    primary ? 'is-primary-card' : '',
    className,
  ].filter(Boolean).join(' ');

  return (
    <Tag className={classes} {...rest}>
      {children}
    </Tag>
  );
}
