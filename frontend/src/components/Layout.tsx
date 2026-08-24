import type { ReactNode } from "react";

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      {actions ? <div className="page-header-actions">{actions}</div> : null}
    </header>
  );
}

export function SectionCard({
  title,
  subtitle,
  headerAction,
  children,
  className = "",
}: {
  title?: string;
  subtitle?: string;
  headerAction?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`section-card ${className}`.trim()}>
      {title ? (
        <div className="section-card-header">
          <div>
            <h2>{title}</h2>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
          {headerAction}
        </div>
      ) : null}
      <div className="section-card-body">{children}</div>
    </section>
  );
}
