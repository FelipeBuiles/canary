import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { preload } from "react-dom";
import { Link, useNavigate } from "react-router-dom";
import { afterPageLoad } from "../lib/afterPageLoad";
import { responsiveMarketingImage } from "../lib/marketingImages";
import { homePaths } from "../lib/publicPages";
import { SHOWCASE_SHELF } from "../lib/showcaseShelf";
import { BrandMark } from "../components/BrandMark";
import { LANGUAGES, preloadLanguage, useI18n, type LanguageCode } from "../i18n";
import { landingCopy, type LandingCopy, type LandingStep } from "./landingCopy";
import "./HomePage.css";

const MEDIA = {
  heroLoop: "/marketing/masque-flipbook.mp4",
  heroPoster: "/marketing/masque-flipbook-poster.webp",
  editions: [
    "/marketing/janitor-riso-page-01.webp",
    "/marketing/janitor-gouache-page-01.webp",
    "/marketing/janitor-oil-page-01.webp",
  ],
  film: { youtubeId: "W-1bPTQXQaQ", poster: "/marketing/scenewright-film-poster.webp" },
  lookProofs: ["/marketing/home/look-proof-a.webp", "/marketing/home/look-proof-b.webp"],
  castSheet: "/marketing/home/cast-sheet.webp",
  reviewPage: "/marketing/home/review-page.webp",
  bookCover: "/marketing/home/cover-monkeys-paw.webp",
} as const;

/** The source text behind the hero loop; decorative, so it stays in the original English. */
const MANUSCRIPT = {
  title: "The Masque of the Red Death",
  excerpt: "The “Red Death” had long devastated the country. No pestilence had ever been so fatal, or so hideous. Blood was its Avatar and its seal, the redness and the horror of blood…",
};

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

function subscribeReducedMotion(onChange: () => void) {
  const query = window.matchMedia?.(REDUCED_MOTION);
  query?.addEventListener("change", onChange);
  return () => query?.removeEventListener("change", onChange);
}

function usePrefersReducedMotion() {
  return useSyncExternalStore(
    subscribeReducedMotion,
    () => window.matchMedia?.(REDUCED_MOTION).matches ?? false,
    () => true,
  );
}

function Arrow({ down = false }: { down?: boolean }) {
  return (
    <svg className="home-arrow" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d={down ? "M12 5v14M6 13l6 6 6-6" : "M5 12h14M13 6l6 6-6 6"} />
    </svg>
  );
}

function LanguageSwitcher({ activeLanguage, label, onChange }: {
  activeLanguage: LanguageCode;
  label: string;
  onChange: (language: LanguageCode) => void;
}) {
  return (
    <div className="home-language" aria-label={label} role="group">
      {LANGUAGES.map(({ code, label: languageLabel }) => (
        <button key={code} type="button" className={activeLanguage === code ? "is-active" : undefined}
          aria-pressed={activeLanguage === code} title={languageLabel} onClick={() => onChange(code)}>
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

function HeroFolio({ copy }: { copy: LandingCopy["hero"] }) {
  const reducedMotion = usePrefersReducedMotion();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [paused, setPaused] = useState(true);
  const [videoReady, setVideoReady] = useState(false);
  preload(MEDIA.heroPoster, { as: "image", fetchPriority: "high" });
  useEffect(() => {
    if (!reducedMotion) return afterPageLoad(() => setVideoReady(true));
  }, [reducedMotion]);

  const toggle = () => {
    const video = videoRef.current;
    if (!video) return;
    if (!videoReady) {
      // Explicit Play starts immediately, even before the optional idle load.
      video.src = MEDIA.heroLoop;
      setVideoReady(true);
    }
    if (video.paused) {
      void video.play()?.catch(() => setPaused(true));
    } else {
      video.pause();
    }
  };

  return (
    <figure className="home-folio" aria-label={copy.loopAlt}>
      <div className="home-manuscript" aria-hidden="true">
        <span className="home-over">{copy.manuscriptLabel}</span>
        <span className="home-manuscript__title">{MANUSCRIPT.title}</span>
        <span className="home-manuscript__rule" />
        <span className="home-manuscript__text">{MANUSCRIPT.excerpt}</span>
      </div>
      <div className="home-sheet">
        <div className="home-sheet__top">
          <span className="home-cap home-cap--small">{copy.loopTag}</span>
          {!reducedMotion && (
            <button type="button" className="home-sheet__toggle" aria-pressed={paused} onClick={toggle}>
              {paused ? copy.playLoop : copy.pauseLoop}
            </button>
          )}
        </div>
        <div className="home-sheet__art">
          {reducedMotion ? (
            <img src={MEDIA.heroPoster} alt="" width="600" height="750" decoding="async" fetchPriority="high" />
          ) : (
            <video ref={videoRef} src={videoReady ? MEDIA.heroLoop : undefined} poster={MEDIA.heroPoster}
              width="600" height="750" autoPlay muted loop playsInline preload="none"
              onPlaying={() => setPaused(false)} onPause={() => setPaused(true)} onError={() => setPaused(true)}
              aria-hidden="true" />
          )}
        </div>
        <figcaption>{copy.loopCaption}</figcaption>
      </div>
    </figure>
  );
}

function BookShelf({ copy }: { copy: LandingCopy["books"] }) {
  const { t } = useI18n();
  return (
    <section className="home-section" id="books" aria-labelledby="home-books-title">
      <div className="home-wrap">
        <div className="home-heading">
          <div>
            <h2 id="home-books-title" className="home-h2">{copy.title}</h2>
            <p>{copy.body}</p>
          </div>
          <Link className="home-link" to="/samples">{copy.samples} <Arrow /></Link>
        </div>
        <ul className="home-shelf">
          {SHOWCASE_SHELF.map(book => (
            <li key={book.id}>
              <Link className="home-cover" to={`/read/${book.id}`}>
                <span className="home-cover__art">
                  <img src={book.cover} alt="" width="476" height="636" loading="lazy" decoding="async" />
                  <span className="home-cover__title">{book.title}</span>
                  <span className="home-cap home-cover__read" aria-hidden="true">{copy.read}</span>
                </span>
                <span className="home-cover__author">{book.author}</span>
                <span className="home-cover__pages">{t("landing.books.pages", { count: book.pages })}</span>
              </Link>
            </li>
          ))}
        </ul>
        <p className="home-note">{copy.note}</p>
      </div>
    </section>
  );
}

function StylesSection({ copy, language }: { copy: LandingCopy["styles"]; language: LanguageCode }) {
  const [playing, setPlaying] = useState(false);
  const { youtubeId, poster } = MEDIA.film;
  // Privacy-enhanced embed, loaded only after an explicit play.
  const player = `https://www.youtube-nocookie.com/embed/${youtubeId}?autoplay=1&rel=0&playsinline=1&hl=${language}`;
  return (
    <section className="home-section home-ink" id="styles" aria-labelledby="home-styles-title">
      <div className="home-wrap home-styles">
        <div className="home-styles__copy">
          <span className="home-cap">{copy.label}</span>
          <h2 id="home-styles-title" className="home-h2">{copy.title}</h2>
          <p>{copy.body}</p>
          <div className="home-film">
            {playing ? (
              <iframe src={player} title={copy.playerTitle}
                allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowFullScreen
                referrerPolicy="strict-origin-when-cross-origin" />
            ) : (
              <button type="button" className="home-film__poster" onClick={() => setPlaying(true)} aria-label={copy.play}>
                <img src={poster} {...responsiveMarketingImage(poster, "(max-width: 900px) 90vw, 400px")} alt={copy.posterAlt} loading="lazy" decoding="async" />
                <span className="home-film__play" aria-hidden="true">
                  <svg viewBox="0 0 24 24" focusable="false"><path d="M7 4.5v15l12.5-7.5z" /></svg>
                  {copy.playLabel}
                </span>
              </button>
            )}
          </div>
          <p className="home-note home-note--ink">
            {copy.filmNote}{" "}
            <a href={`https://www.youtube.com/watch?v=${youtubeId}`} target="_blank" rel="noopener noreferrer">{copy.youtube} ↗</a>
          </p>
        </div>
        <div className="home-styles__editions">
          <ul className="home-editions">
            {MEDIA.editions.map((src, index) => {
              const edition = copy.editions[index];
              return (
                <li key={src}>
                  <a className="home-edition" href={src} target="_blank" rel="noopener noreferrer" aria-label={edition.link}>
                    <img src={src} {...responsiveMarketingImage(src, "(max-width: 760px) 30vw, 22vw")} alt={edition.alt} loading="lazy" decoding="async" />
                    <span className="home-edition__label">{edition.label}</span>
                    <span className="home-edition__note">{edition.note}</span>
                  </a>
                </li>
              );
            })}
          </ul>
          <p className="home-note home-note--ink">{copy.license}</p>
        </div>
      </div>
    </section>
  );
}

function StepVignette({ index, copy }: { index: number; copy: LandingCopy["process"] }) {
  switch (index) {
    case 0:
      return (
        <div className="home-vig home-vig--paper">
          <div className="home-vig__brief">
            <span className="home-over home-over--red">{copy.brief.heading}</span>
            <ol>
              {copy.brief.items.map((item, position) => <li key={item}><b>{position + 1}</b>{item}</li>)}
            </ol>
            <span className="home-vig__more">{copy.brief.more}</span>
          </div>
        </div>
      );
    case 1:
      return (
        <div className="home-vig">
          <img className="home-vig__proof" src={MEDIA.lookProofs[0]} alt="" width="420" height="525" loading="lazy" decoding="async" />
          <img className="home-vig__proof home-vig__proof--front" src={MEDIA.lookProofs[1]} alt="" width="420" height="525" loading="lazy" decoding="async" />
        </div>
      );
    case 2:
      return (
        <div className="home-vig">
          <img className="home-vig__fill" src={MEDIA.castSheet} alt="" width="720" height="479" loading="lazy" decoding="async" />
        </div>
      );
    case 3:
      return (
        <div className="home-vig home-vig--center">
          <span className="home-vig__page">
            <img src={MEDIA.reviewPage} alt="" width="360" height="537" loading="lazy" decoding="async" />
            <span className="home-vig__marker">1</span>
          </span>
          <span className="home-vig__note">
            {copy.review.note}
            <b>{copy.review.action}</b>
          </span>
        </div>
      );
    default:
      return (
        <div className="home-vig home-vig--paper home-vig--center">
          <img className="home-vig__cover" src={MEDIA.bookCover} alt="" width="476" height="636" loading="lazy" decoding="async" />
          <span className="home-vig__formats">
            <span className="home-cap home-cap--paper">PDF</span>
            <span className="home-cap home-cap--paper">CBZ</span>
            <span className="home-cap home-cap--paper">{copy.shareLink}</span>
          </span>
        </div>
      );
  }
}

function ProcessStep({ step, index, copy }: { step: LandingStep; index: number; copy: LandingCopy["process"] }) {
  return (
    <li className="home-step">
      <div aria-hidden="true"><StepVignette index={index} copy={copy} /></div>
      <div className="home-step__meta">
        <span className="home-step__number">{step.number}</span>
        <span className="home-over">{step.label}</span>
        {step.approve && <span className="home-cap home-cap--tiny">{copy.approve}</span>}
      </div>
      <h3>{step.title}</h3>
      <p>{step.body}</p>
    </li>
  );
}

export function HomePage() {
  const { language, setLanguage, t } = useI18n();
  const navigate = useNavigate();
  const copy = landingCopy(t);

  return (
    <div className="home-page">
      <a className="home-skip" href="#home-main">{copy.nav.skip}</a>

      <header className="home-header">
        <div className="home-wrap home-header__row">
          <Link className="home-brand" to="/" aria-label={copy.nav.home}>
            <BrandMark className="home-brand__mark" variant="reversed" />
            <span className="home-brand__name">Scenewright</span>
            <span className="home-brand__beta">Beta</span>
          </Link>
          <nav className="home-header__nav" aria-label={copy.nav.navigation}>
            <a href="#books">{copy.nav.books}</a>
            <a href="#styles">{copy.nav.styles}</a>
            <a href="#how">{copy.nav.process}</a>
            <a href="#pricing">{copy.nav.pricing}</a>
            <a href="#questions">{copy.nav.faq}</a>
          </nav>
          <div className="home-header__actions">
            <LanguageSwitcher activeLanguage={language} label={copy.nav.language} onChange={next => {
              setLanguage(next);
              // Arrive at the translated page with its copy ready, not a re-render.
              void preloadLanguage(next).then(() => navigate(homePaths[next]));
            }} />
            <Link className="home-header__sign-in" to="/login">{copy.nav.signIn}</Link>
            <Link className="home-btn home-btn--small" to="/signup">{copy.nav.cta}</Link>
          </div>
        </div>
      </header>

      <main id="home-main">
        <section className="home-hero home-ink" aria-labelledby="home-hero-title">
          <div className="home-wrap home-hero__grid">
            <div className="home-hero__copy">
              <span className="home-cap">{copy.hero.label}</span>
              <h1 id="home-hero-title">{copy.hero.title}</h1>
              <p className="home-hero__body">{copy.hero.body}</p>
              <div className="home-hero__actions">
                <Link className="home-btn home-btn--on-ink" to="/signup">{copy.hero.primaryCta} <Arrow /></Link>
                <a className="home-link home-link--light" href="#books">{copy.hero.secondaryCta} <Arrow down /></a>
              </div>
              <p className="home-over home-hero__formats">{copy.hero.formats}</p>
            </div>
            <div className="home-hero__visual">
              <HeroFolio copy={copy.hero} />
            </div>
          </div>
        </section>

        <BookShelf copy={copy.books} />
        <StylesSection copy={copy.styles} language={language} />

        <section className="home-section" id="how" aria-labelledby="home-how-title">
          <div className="home-wrap">
            <div className="home-heading">
              <div>
                <h2 id="home-how-title" className="home-h2">{copy.process.title}</h2>
                <p>{copy.process.body}</p>
              </div>
            </div>
            <ol className="home-steps">
              {copy.process.steps.map((step, index) => <ProcessStep key={step.number} step={step} index={index} copy={copy.process} />)}
            </ol>
            <div className="home-samples">
              <span><b>{copy.process.samples.title}</b> {copy.process.samples.body}</span>
              <Link className="home-link home-link--small" to="/samples">{copy.process.samples.link} <Arrow /></Link>
            </div>
          </div>
        </section>

        <section className="home-section home-section--tight" aria-label={`${copy.rights.title} · ${copy.pricing.title}`}>
          <div className="home-wrap home-two">
            <div className="home-rights" id="rights">
              <h2 className="home-h3">{copy.rights.title}</h2>
              <div className="home-rights__columns">
                <div>
                  <span className="home-over home-over--red">{copy.rights.youLabel}</span>
                  <ul>{copy.rights.youItems.map(item => <li key={item}>{item}</li>)}</ul>
                </div>
                <div>
                  <span className="home-over">{copy.rights.toolLabel}</span>
                  <ul className="home-rights__muted">{copy.rights.toolItems.map(item => <li key={item}>{item}</li>)}</ul>
                </div>
              </div>
              <p className="home-rights__disclosure">
                {copy.rights.disclosure} <Link to="/legal/terms">{copy.rights.termsLink}</Link>
              </p>
            </div>
            <div className="home-pricing home-ink" id="pricing">
              <h2 className="home-h3">{copy.pricing.title}</h2>
              <p>{copy.pricing.body}</p>
              <ul>{copy.pricing.items.map(item => <li key={item}>{item}</li>)}</ul>
              <Link className="home-link home-link--gold home-link--small" to="/pricing">{copy.pricing.link} <Arrow /></Link>
            </div>
          </div>
        </section>

        <section className="home-section home-faq" id="questions" aria-labelledby="home-faq-title">
          <div className="home-wrap home-faq__grid">
            <div>
              <h2 id="home-faq-title" className="home-h2">{copy.faq.title}</h2>
              <p>{copy.faq.contact} <a href="mailto:hello@scenewright.ink">hello@scenewright.ink</a></p>
            </div>
            <div className="home-faq__items">
              {copy.faq.items.map((item, index) => (
                <details key={item.question} className="home-faq__item" open={index === 0 || undefined}>
                  <summary>
                    <span>{item.question}</span>
                    <span className="home-faq__mark" aria-hidden="true">
                      <svg viewBox="0 0 24 24" focusable="false"><path d="M12 5v14M5 12h14" /></svg>
                    </span>
                  </summary>
                  <p>{item.answer}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section className="home-final" aria-labelledby="home-final-title">
          <div className="home-wrap home-final__row">
            <div>
              <h2 id="home-final-title" className="home-h2">{copy.final.title}</h2>
              <p>{copy.final.body}</p>
            </div>
            <div className="home-final__actions">
              <Link className="home-btn" to="/signup">{copy.final.cta} <Arrow /></Link>
              <Link className="home-link home-link--small" to="/login">{copy.final.signIn}</Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="home-footer home-ink">
        <div className="home-wrap">
          <div className="home-footer__row">
            <div>
              <span className="home-brand">
                <BrandMark className="home-brand__mark" variant="reversed" />
                <span className="home-brand__name">Scenewright</span>
              </span>
              <p>{copy.footer.line}</p>
            </div>
            <div className="home-footer__links">
              <nav aria-label={copy.footer.product}>
                <span className="home-over">{copy.footer.product}</span>
                <Link to="/how-it-works">{copy.footer.workflow}</Link>
                <Link to="/pricing">{copy.footer.pricing}</Link>
                <Link to="/guides/turn-a-novel-into-a-comic">{copy.footer.guide}</Link>
                <Link to="/examples/kaitlin-out-of-space">{copy.footer.example}</Link>
                <Link to="/about">{copy.footer.about}</Link>
              </nav>
              <nav aria-label={copy.footer.legal}>
                <span className="home-over">{copy.footer.legal}</span>
                <Link to="/legal/terms">{copy.footer.terms}</Link>
                <Link to="/legal/privacy">{copy.footer.privacy}</Link>
                <Link to="/legal/acceptable-use">{copy.footer.acceptableUse}</Link>
              </nav>
              <nav aria-label={copy.nav.language}>
                <span className="home-over">{copy.nav.language}</span>
                {LANGUAGES.map(({ code, label }) => <Link key={code} to={homePaths[code]} lang={code} hrefLang={code}
                  onPointerEnter={() => void preloadLanguage(code)} onFocus={() => void preloadLanguage(code)}>{label}</Link>)}
              </nav>
            </div>
          </div>
          <p className="home-footer__legal">© 2026 Scenewright</p>
        </div>
      </footer>
    </div>
  );
}
