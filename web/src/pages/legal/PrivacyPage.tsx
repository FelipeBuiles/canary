import { LegalLayout } from "../../layout/LegalLayout";

/**
 * Privacy Policy — written to be *truthful* about what the Service actually
 * collects and does (the key risk for a small project is an inaccurate privacy
 * statement, not a missing clause). Describes: account email, uploaded
 * manuscripts, generated images, usage/cost events; storage on local disk +
 * Supabase; retention "until you delete your project"; the providers that
 * process data.
 */
export function PrivacyPage() {
  return (
    <LegalLayout title="Privacy Policy" updated="September 28, 2026">
      <p>
        This Privacy Policy explains what Scenewright collects, how we use it,
        and the choices you have. We aim to collect only what we need to run the
        Service.
      </p>

      <h2>Information We Collect</h2>
      <ul>
        <li>
          <strong>Account data:</strong> your email address and the studio name
          you provide at signup.
        </li>
        <li>
          <strong>Your Content:</strong> the manuscripts and text you upload,
          and the images the Service generates from them.
        </li>
        <li>
          <strong>Usage data:</strong> records of the AI operations you trigger
          (stage, model, tokens, image count, cost) tied to your account, which
          back the credits system and your billing history.
        </li>
        <li>
          <strong>Technical data:</strong> basic request information (IP,
          browser) as needed to serve the app and detect abuse.
        </li>
      </ul>

      <h2>How We Use Your Information</h2>
      <ul>
        <li>To operate the pipeline and generate your comic pages.</li>
        <li>To maintain your credit balance and process payments.</li>
        <li>To detect, prevent, and address abuse and fraud.</li>
        <li>To provide support and respond to reports.</li>
      </ul>

      <h2>Where Your Data Is Stored</h2>
      <p>
        Your uploaded manuscripts and generated images are stored on our
        server's disk, organized under your account. Account, project, and
        usage records are stored in our database (Supabase). Payments are
        processed by Stripe; we do not store your full card number.
      </p>

      <h2>Who Processes Your Data</h2>
      <p>To run the Service, your text and prompts are sent to third parties:</p>
      <ul>
        <li>
          <strong>AI model providers</strong> (such as Google, OpenAI, and
          others) that generate the text and images the Service produces.
        </li>
        <li>
          <strong>Supabase</strong> for authentication and the database.
        </li>
        <li>
          <strong>Stripe</strong> for payment processing.
        </li>
        <li>
          <strong>PostHog</strong> for page views, selected usage milestones,
          error reports, and operational diagnostics, linked to an account
          identifier once you sign in. Page views record a route template (never
          a project or book ID), campaign tags, and the referring site's domain;
          how you found us is saved with your account at signup. We do not send
          manuscripts, prompts, generated artwork, email addresses, or feedback
          messages to PostHog, and analytics uses no cookies or browser storage.
          Session replays and click analytics record interface layout and
          interactions with all typed input, story and page text masked, and
          images, artwork, and uploads blocked.
        </li>
      </ul>

      <h2>Feedback</h2>
      <p>Feedback you submit is stored privately in our database with your account and, when relevant, project reference. We review it to understand problems and decide what to improve.</p>

      <h2>Data Retention</h2>
      <p>
        We keep your Content and generated images for as long as your project
        exists. When you delete a project, the associated files and records are
        removed. Account data is retained until you delete your account. We may
        retain limited usage/billing records after deletion as needed for
        record-keeping and legal obligations.
      </p>

      <h2>Your Choices</h2>
      <ul>
        <li>You can delete any project at any time from the app.</li>
        <li>You can request deletion of your account by contacting us.</li>
        <li>
          You can request a copy of the data we hold about you by contacting us.
        </li>
      </ul>

      <h2>Cookies</h2>
      <p>
        The Service uses a session cookie so you stay logged in across page
        loads and so browser-native consumers (such as image requests) are
        authenticated. We do not use advertising or cross-site tracking cookies.
      </p>

      <h2>Children</h2>
      <p>
        The Service is not intended for children under 13 (or the minimum age
        in your country). We do not knowingly collect data from children.
      </p>

      <h2>Changes to This Policy</h2>
      <p>
        We may update this policy and will reflect the change in the "Last
        updated" date above.
      </p>

      <h2>Contact</h2>
      <p>
        Privacy questions:{" "}
        <a href="mailto:legal@scenewright.ink">legal@scenewright.ink</a>.
      </p>
    </LegalLayout>
  );
}
