import { LegalLayout } from "../../layout/LegalLayout";

/**
 * Acceptable Use Policy + abuse/DMCA report instructions. This document is the
 * contractual basis for account termination and doubles as the public-facing
 * report channel — the mechanism by which the operator gains "actual
 * knowledge" of prohibited content (e.g. for mandatory NCMEC reporting).
 */
export function AcceptableUsePage() {
  return (
    <LegalLayout title="Acceptable Use &amp; Reporting" updated="July 2, 2026">
      <p>
        This Acceptable Use Policy describes what you may not do with
        Scenewright and how to report violations. It supplements (and is
        enforced under) our <a href="/legal/terms">Terms of Service</a>.
        Violations may result in content removal, credit forfeiture, or account
        termination.
      </p>

      <h2>Prohibited Content &amp; Conduct</h2>
      <p>You may not use the Service to upload, generate, or facilitate:</p>
      <ul>
        <li>
          Child sexual abuse material (CSAM), or any content that sexualizes
          minors — including realistic or AI-generated depictions. This is
          strictly illegal and will be reported to the appropriate authorities.
        </li>
        <li>
          Non-consensual intimate imagery of any real person, including
          deepfakes.
        </li>
        <li>
          Content that infringes another person's copyright, trademark, or other
          intellectual property.
        </li>
        <li>
          Content that promotes violence, terrorism, or harm to people or
          animals.
        </li>
        <li>
          Content that is unlawful, defamatory, or fraudulent in your
          jurisdiction or ours.
        </li>
        <li>
          Attempts to reverse-engineer, overload, or otherwise disrupt the
          Service.
        </li>
      </ul>
      <p>
        We rely primarily on the safety filters built into the AI model
        providers we use, combined with user reporting. We do not pre-screen all
        uploads.
      </p>

      <h2>Reporting Abuse</h2>
      <p>
        If you encounter prohibited content on the Service, report it to{" "}
        <a href="mailto:legal@scenewright.ink">legal@scenewright.ink</a> with the
        project or panel location and a short description. We review reports and
        act on violations, including by reporting illegal content (such as CSAM)
        to the appropriate authorities.
      </p>

      <h2>Copyright &amp; DMCA Takedowns</h2>
      <p>
        We respect intellectual property. If you believe Content on the Service
        infringes your copyright, send a takedown notice to{" "}
        <a href="mailto:legal@scenewright.ink">legal@scenewright.ink</a>{" "}
        including:
      </p>
      <ul>
        <li>Your name, address, phone number, and email.</li>
        <li>
          Identification of the copyrighted work you claim is infringed.
        </li>
        <li>
          The location of the material on the Service you want removed.
        </li>
        <li>
          A statement that you have a good-faith belief the use is not
          authorized, and that the information is accurate — and, under penalty
          of perjury, that you are the owner or authorized to act.
        </li>
        <li>Your physical or electronic signature.</li>
      </ul>
      <p>
        We will process valid notices and may terminate the accounts of
        repeat infringers.
      </p>

      <h2>Enforcement</h2>
      <p>
        We reserve the right to remove any Content, cancel credits, or terminate
        any account that violates this policy, at our sole discretion, without
        notice or liability.
      </p>

      <h2>Contact</h2>
      <p>
        Abuse, DMCA, and policy questions:{" "}
        <a href="mailto:legal@scenewright.ink">legal@scenewright.ink</a>.
      </p>
    </LegalLayout>
  );
}
