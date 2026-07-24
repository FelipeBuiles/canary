import { getCachedBranding } from "../lib/legal";
import { supportMailto, type SupportDiagnostics } from "../lib/support";

export function SupportLink({
  diagnostics,
  children = "NEED HELP?",
  className = "",
}: {
  diagnostics?: SupportDiagnostics;
  children?: React.ReactNode;
  className?: string;
}) {
  const branding = getCachedBranding();
  return (
    <a
      href={supportMailto(branding.support_email, diagnostics)}
      className={className}
    >
      {children}
    </a>
  );
}
