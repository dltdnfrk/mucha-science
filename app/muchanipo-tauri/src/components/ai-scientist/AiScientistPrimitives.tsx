import type {
  ButtonHTMLAttributes,
  ReactNode,
  TextareaHTMLAttributes,
} from "react";
import { cn } from "../../lib/utils";

const SCIENTIFIC_STAGES = [
  { number: "01", label: "질문" },
  { number: "02", label: "가설" },
  { number: "03", label: "실험" },
  { number: "04", label: "외부 결과" },
  { number: "05", label: "증거" },
  { number: "06", label: "판정" },
] as const;

type ButtonVariant = "primary" | "neutral" | "text" | "destructive";
type FolioVariant = "working" | "evidence" | "verdict" | "diagnostics";

interface ResearchMastheadProps {
  readonly cycleLabel?: string;
  readonly protocolLabel?: string;
  readonly utility?: ReactNode;
}

export function ResearchMasthead({
  cycleLabel = "사이클 대기 중",
  protocolLabel = "프로토콜 ai-scientist.v1",
  utility,
}: ResearchMastheadProps) {
  return (
    <header className="ms-masthead">
      <div className="ms-masthead__identity">
        <a className="ms-wordmark" href="#/scientific" aria-label="Mucha Science AI 과학자 홈">
          Mucha Science
        </a>
        <span className="ms-masthead__focus">AI 과학자</span>
      </div>
      <div className="ms-masthead__metadata">
        <span>{cycleLabel}</span>
        <span>{protocolLabel}</span>
      </div>
      {utility ? <div className="ms-masthead__utility">{utility}</div> : null}
    </header>
  );
}

interface ProtocolRulerProps {
  readonly current: string;
}

export function ProtocolRuler({ current }: ProtocolRulerProps) {
  return (
    <nav
      aria-label="과학적 검증 사이클 단계"
      className="ms-protocol-ruler"
      tabIndex={0}
    >
      <span className="ms-protocol-ruler__hint" aria-hidden="true">
        단계 더 보기 →
      </span>
      <ol>
        {SCIENTIFIC_STAGES.map((stage) => {
          const isCurrent = stage.label === current;
          return (
            <li
              aria-current={isCurrent ? "step" : undefined}
              className={isCurrent ? "is-current" : undefined}
              key={stage.number}
            >
              <span className="ms-protocol-ruler__number">{stage.number}</span>
              <span>{stage.label}</span>
              <small>{isCurrent ? "현재" : "대기"}</small>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

interface FolioSectionProps {
  readonly children: ReactNode;
  readonly description?: string;
  readonly kicker?: string;
  readonly title: string;
  readonly variant?: FolioVariant;
}

export function FolioSection({
  children,
  description,
  kicker,
  title,
  variant = "working",
}: FolioSectionProps) {
  const headingId = `ms-section-${(kicker ?? title).toLowerCase().replaceAll(" ", "-")}`;
  return (
    <section
      aria-labelledby={headingId}
      className={`ms-folio-section ms-folio-section--${variant}`}
    >
      <header className="ms-folio-section__header">
        {kicker ? <p>{kicker}</p> : null}
        <h2 id={headingId}>{title}</h2>
        {description ? <span>{description}</span> : null}
      </header>
      <div className="ms-folio-section__body">{children}</div>
    </section>
  );
}

interface RuledFieldProps extends Omit<
  TextareaHTMLAttributes<HTMLTextAreaElement>,
  "aria-describedby" | "id"
> {
  readonly error?: string;
  readonly helper: string;
  readonly id: string;
  readonly label: string;
  readonly variant?: "question" | "protocol";
}

export function RuledField({
  className,
  error,
  helper,
  id,
  label,
  variant = "question",
  ...props
}: RuledFieldProps) {
  const messageId = `${id}-${error ? "error" : "helper"}`;

  return (
    <div
      className={cn(
        "ms-field-stack",
        "ms-ruled-field",
        `ms-ruled-field--${variant}`,
        error && "is-error",
        className,
      )}
    >
      <label htmlFor={id}>{label}</label>
      <textarea
        {...props}
        id={id}
        aria-describedby={messageId}
        aria-invalid={error ? "true" : undefined}
      />
      <p id={messageId} role={error ? "alert" : undefined}>
        {error ?? helper}
      </p>
    </div>
  );
}

interface RuleButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  readonly loading?: boolean;
  readonly variant?: ButtonVariant;
}

export function RuleButton({
  children,
  className,
  disabled,
  loading = false,
  variant = "neutral",
  ...props
}: RuleButtonProps) {
  return (
    <button
      type="button"
      className={cn("ms-rule-button", `ms-rule-button--${variant}`, className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? "처리 중…" : children}
    </button>
  );
}
