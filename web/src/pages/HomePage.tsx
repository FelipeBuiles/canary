import { PublicationShowcase } from "../components/book/PublicationShowcase";
import { Link } from "react-router-dom";
import { BrandIdentity } from "../components/BrandIdentity";
import { BrandMark } from "../components/BrandMark";
import { LANGUAGES, useI18n, type LanguageCode } from "../i18n";
import { LANDING_COPY, type LandingCopy, type LandingFaq, type LandingStep } from "./landingCopy";
import "./HomePage.css";

const MARKETING_IMAGES = {
  pages: [
    "/marketing/dungeon-crawler-carl-page-25.webp",
    "/api/public/books/d1cb0ec790244ce6849974daa586146b/ccf1a606bd1747c4864d8a4770000891/pages/21",
  ],
  anya: "/marketing/anya-reference.webp",
  rurik: "/marketing/rurik-reference.webp",
  tavern: "/marketing/tavern-reference.webp",
} as const;

function LanguageSwitcher({
  activeLanguage,
  label,
  onChange,
}: {
  activeLanguage: LanguageCode;
  label: string;
  onChange: (language: LanguageCode) => void;
}) {
  return (
    <div className="landing-language" aria-label={label} role="group">
      {LANGUAGES.map(({ code, label: languageLabel }) => (
        <button
          key={code}
          type="button"
          className={activeLanguage === code ? "is-active" : undefined}
          aria-pressed={activeLanguage === code}
          title={languageLabel}
          onClick={() => onChange(code)}
        >
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

function HeroFolio({ copy }: { copy: LandingCopy["hero"] }) {
  return (
    <figure className="landing-folio" aria-label={copy.visualAlt}>
      <div className="landing-manuscript" aria-hidden="true">
        <div className="landing-manuscript__label">{copy.manuscriptLabel}</div>
        <div className="landing-manuscript__title">{copy.chapterLabel}</div>
        <div className="landing-manuscript__lines">
          <span />
          <span />
          <span />
          <span />
          <span />
          <span />
          <span />
          <span />
        </div>
      </div>

      <div className="landing-comic-sheet">
        <div className="landing-comic-sheet__topline">
          <span>{copy.sampleLabel}</span>
          <span>{copy.sceneLabel}</span>
        </div>
        <div className="landing-comic-grid">
          <div className="landing-comic-panel landing-comic-panel--place">
            <img
              src={MARKETING_IMAGES.tavern}
              alt=""
              width="1200"
              height="1200"
              loading="eager"
              decoding="async"
            />
            <span>{copy.visualLabels[1]}</span>
          </div>
          <div className="landing-comic-panel landing-comic-panel--anya">
            <img
              src={MARKETING_IMAGES.anya}
              alt=""
              width="1200"
              height="1200"
              loading="eager"
              decoding="async"
              fetchPriority="high"
            />
            <span>{copy.visualLabels[0]}</span>
          </div>
          <div className="landing-comic-panel landing-comic-panel--rurik">
            <img
              src={MARKETING_IMAGES.rurik}
              alt=""
              width="1200"
              height="1200"
              loading="eager"
              decoding="async"
            />
            <span>{copy.visualLabels[2]}</span>
          </div>
        </div>
        <figcaption>{copy.sampleCaption}</figcaption>
      </div>
    </figure>
  );
}

function ProcessStep({ step }: { step: LandingStep }) {
  return (
    <li className="landing-process-step">
      <div className="landing-process-step__index" aria-hidden="true">
        <span>{step.number}</span>
        <span>{step.label}</span>
      </div>
      <div>
        <h3>{step.title}</h3>
        <p>{step.body}</p>
      </div>
    </li>
  );
}

function FaqItem({ item }: { item: LandingFaq }) {
  return (
    <details className="landing-faq-item">
      <summary>
        <span>{item.question}</span>
        <span className="landing-faq-item__mark" aria-hidden="true" />
      </summary>
      <p>{item.answer}</p>
    </details>
  );
}

export function HomePage() {
  const { language, setLanguage } = useI18n();
  const copy = LANDING_COPY[language];

  return (
    <div className="landing-page">
      <a className="landing-skip-link" href="#landing-main">
        {copy.nav.skip}
      </a>

      <header className="landing-header">
        <Link className="inline-flex w-fit items-center" to="/" aria-label={copy.nav.home}>
          <BrandIdentity />
        </Link>

        <nav className="landing-header__nav" aria-label={copy.nav.navigation}>
          <a href="#process">{copy.nav.process}</a>
          <a href="#continuity">{copy.nav.continuity}</a>
          <a href="#rights">{copy.nav.rights}</a>
          <a href="#questions">{copy.nav.faq}</a>
        </nav>

        <div className="landing-header__actions">
          <LanguageSwitcher
            activeLanguage={language}
            label={copy.nav.language}
            onChange={setLanguage}
          />
          <Link className="landing-sign-in" to="/login">
            {copy.nav.signIn}
          </Link>
          <Link className="landing-cta landing-cta--small" to="/signup">
            {copy.nav.cta}
          </Link>
        </div>
      </header>

      <main id="landing-main">
        <section className="landing-hero" aria-labelledby="landing-hero-title">
          <div className="landing-hero__copy">
            <div className="landing-hero__label">{copy.hero.label}</div>
            <h1 id="landing-hero-title">{copy.hero.title}</h1>
            <p className="landing-hero__body">{copy.hero.body}</p>
            <div className="landing-hero__actions">
              <Link className="landing-cta landing-cta--hero" to="/signup">
                <span>{copy.hero.primaryCta}</span>
                <span aria-hidden="true">↗</span>
              </Link>
              <a className="landing-text-link landing-text-link--light" href="#continuity">
                {copy.hero.secondaryCta}
                <span aria-hidden="true">↓</span>
              </a>
            </div>
            <p className="landing-hero__formats">{copy.hero.formats}</p>
          </div>
          <div className="landing-hero__visual">
            <HeroFolio copy={copy.hero} />
          </div>
        </section>

        <section className="landing-premise" aria-label={copy.premise.title}>
          <h2>{copy.premise.title}</h2>
          <p>{copy.premise.body}</p>
        </section>

        <section className="landing-continuity" id="continuity" aria-labelledby="landing-continuity-title">
          <div className="landing-continuity__intro">
            <p className="landing-continuity__promise">{copy.continuity.promise}</p>
            <h2 id="landing-continuity-title">{copy.continuity.title}</h2>
            <p>{copy.continuity.body}</p>
          </div>

          <div className="landing-page-samples">
            {MARKETING_IMAGES.pages.map((src, index) => (
              <figure key={src}>
                <a href={src} target="_blank" rel="noopener noreferrer" aria-label={copy.continuity.inspectLinks[index]}>
                  <img src={src} alt={copy.continuity.alts[index]} width="1024" height="1536" loading="lazy" decoding="async" />
                </a>
                <figcaption>
                  <span>{copy.continuity.captions[index]}</span>
                  <a href={src} target="_blank" rel="noopener noreferrer">{copy.continuity.inspectLinks[index]}</a>
                </figcaption>
              </figure>
            ))}
          </div>
          <p className="landing-page-samples__note">{copy.continuity.sample}</p>
          <div className="landing-reference-inspection">
            <div>
              <h3>{copy.continuity.inspectTitle}</h3>
              <p>{copy.continuity.inspectBody}</p>
            </div>
            <Link className="landing-cta" to="/signup">{copy.hero.primaryCta}</Link>
          </div>
        </section>

        <PublicationShowcase />

        <section className="landing-process" id="process" aria-labelledby="landing-process-title">
          <div className="landing-section-heading">
            <h2 id="landing-process-title">{copy.process.title}</h2>
            <p>{copy.process.body}</p>
          </div>
          <ol className="landing-process-list">
            {copy.process.steps.map((step) => (
              <ProcessStep key={step.number} step={step} />
            ))}
          </ol>
        </section>

        <section className="landing-direction" id="rights" aria-labelledby="landing-direction-title">
          <div className="landing-direction__heading">
            <h2 id="landing-direction-title">{copy.direction.title}</h2>
            <p>{copy.direction.body}</p>
          </div>

          <div className="landing-direction__columns">
            <div>
              <h3>{copy.direction.youLabel}</h3>
              <ul>
                {copy.direction.youItems.map((item) => (
                  <li key={item}>
                    <span aria-hidden="true">◆</span>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3>{copy.direction.toolLabel}</h3>
              <ul>
                {copy.direction.toolItems.map((item) => (
                  <li key={item}>
                    <span aria-hidden="true">→</span>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="landing-disclosure">
            <p>{copy.direction.disclosure}</p>
            <Link to="/legal/terms">
              {copy.direction.termsLink}
              <span aria-hidden="true">↗</span>
            </Link>
          </div>
        </section>

        <section className="landing-trust" aria-labelledby="landing-trust-title">
          <div className="landing-trust__copy">
            <h2 id="landing-trust-title">{copy.trust.title}</h2>
            <p>{copy.trust.body}</p>
          </div>
          <ul className="landing-trust__facts">
            {copy.trust.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <div className="landing-trust__action">
            <Link className="landing-cta landing-cta--gold" to="/signup">
              {copy.trust.cta}
              <span aria-hidden="true">↗</span>
            </Link>
            <p>{copy.trust.note}</p>
          </div>
        </section>

        <section className="landing-faq" id="questions" aria-labelledby="landing-faq-title">
          <div className="landing-faq__heading">
            <h2 id="landing-faq-title">{copy.faq.title}</h2>
            <p>{copy.faq.body}</p>
          </div>
          <div className="landing-faq__items">
            {copy.faq.items.map((item) => (
              <FaqItem key={item.question} item={item} />
            ))}
          </div>
        </section>

        <section className="landing-final" aria-labelledby="landing-final-title">
          <BrandMark className="landing-final__mark" variant="primary" />
          <h2 id="landing-final-title">{copy.final.title}</h2>
          <p>{copy.final.body}</p>
          <div>
            <Link className="landing-cta landing-cta--final" to="/signup">
              {copy.final.cta}
              <span aria-hidden="true">↗</span>
            </Link>
            <Link className="landing-text-link" to="/login">
              {copy.final.signIn}
            </Link>
          </div>
        </section>
      </main>

      <footer className="landing-footer">
        <div>
          <BrandMark className="landing-footer__mark" variant="reversed" />
          <span>
            <strong>Scenewright</strong>
            <small>{copy.footer.line}</small>
          </span>
        </div>
        <nav aria-label="Legal">
          <Link to="/legal/terms">{copy.footer.terms}</Link>
          <Link to="/legal/privacy">{copy.footer.privacy}</Link>
          <Link to="/legal/acceptable-use">{copy.footer.acceptableUse}</Link>
        </nav>
        <p>© 2026 Scenewright</p>
      </footer>
    </div>
  );
}
