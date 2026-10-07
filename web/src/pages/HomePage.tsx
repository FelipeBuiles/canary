import { PublicationShowcase } from "../components/book/PublicationShowcase";
import { useShortStories } from "../api/queries";
import { genreLabel } from "../lib/storyBrowser";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { preload } from "react-dom";
import { afterPageLoad } from "../lib/afterPageLoad";
import { responsiveMarketingImage } from "../lib/marketingImages";
import { Link } from "react-router-dom";
import { BrandIdentity } from "../components/BrandIdentity";
import { BrandMark } from "../components/BrandMark";
import { LANGUAGES, useI18n, type LanguageCode } from "../i18n";
import { landingCopy, type LandingCopy, type LandingFaq, type LandingStep } from "./landingCopy";
import "./HomePage.css";

const MARKETING_IMAGES = {
  pages: [
    "/marketing/cthulhu-page-40.webp",
    "/marketing/elm-and-keep-page-12.webp",
  ],
  heroLoop: "/marketing/masque-flipbook.mp4",
  heroPoster: "/marketing/masque-flipbook-poster.webp",
  editions: [
    "/marketing/janitor-riso-page-01.webp",
    "/marketing/janitor-gouache-page-01.webp",
    "/marketing/janitor-oil-page-01.webp",
  ],
  film: {
    youtubeId: "W-1bPTQXQaQ",
    poster: "/marketing/scenewright-film-poster.webp",
  },
  sampleBook: [
    "/marketing/kaitlin-page-01.webp",
    "/marketing/kaitlin-page-12.webp",
    "/marketing/kaitlin-page-34.webp",
  ],
} as const;

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
  const reducedMotion = usePrefersReducedMotion();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [paused, setPaused] = useState(true);
  const [videoReady, setVideoReady] = useState(false);
  preload(MARKETING_IMAGES.heroPoster, { as: "image", fetchPriority: "high" });
  useEffect(() => {
    if (!reducedMotion) return afterPageLoad(() => setVideoReady(true));
  }, [reducedMotion]);

  const toggle = () => {
    const video = videoRef.current;
    if (!video) return;
    if (!videoReady) {
      // Explicit Play starts immediately, even before the optional idle load.
      video.src = MARKETING_IMAGES.heroLoop;
      setVideoReady(true);
    }
    if (video.paused) {
      void video.play()?.catch(() => setPaused(true));
    } else {
      video.pause();
    }
  };

  return (
    <figure className="landing-folio" aria-label={copy.loopAlt}>
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
          <span>{copy.loopTag}</span>
          {!reducedMotion && (
            <button type="button" className="landing-loop-toggle" aria-pressed={paused} onClick={toggle}>
              {paused ? copy.playLoop : copy.pauseLoop}
            </button>
          )}
        </div>
        <div className="landing-loop">
          {reducedMotion ? (
            <img src={MARKETING_IMAGES.heroPoster} alt="" width="600" height="750" decoding="async" fetchPriority="high" />
          ) : (
            <video
              ref={videoRef}
              src={videoReady ? MARKETING_IMAGES.heroLoop : undefined}
              poster={MARKETING_IMAGES.heroPoster}
              width="600"
              height="750"
              autoPlay
              muted
              loop
              playsInline
              preload="none"
              onPlaying={() => setPaused(false)}
              onPause={() => setPaused(true)}
              onError={() => setPaused(true)}
              aria-hidden="true"
            />
          )}
        </div>
        <figcaption>{copy.loopCaption}</figcaption>
      </div>
    </figure>
  );
}

function PageStrip({
  pages,
  alts,
  captions,
  links,
}: {
  pages: readonly string[];
  alts: readonly string[];
  captions: readonly string[];
  links?: readonly string[];
}) {
  return (
    <div className="landing-page-samples landing-page-samples--three">
      {pages.map((src, index) => (
        <figure key={src}>
          <a href={src} target="_blank" rel="noopener noreferrer" aria-label={links?.[index] ?? captions[index]}>
            <img src={src} {...responsiveMarketingImage(src, "(max-width: 680px) 90vw, (max-width: 900px) 45vw, 30vw")} alt={alts[index]} loading="lazy" decoding="async" />
          </a>
          <figcaption>
            <span>{captions[index]}</span>
            {links && <a href={src} target="_blank" rel="noopener noreferrer">{links[index]}</a>}
          </figcaption>
        </figure>
      ))}
    </div>
  );
}

function EditionsStrip({ copy }: { copy: LandingCopy["editions"] }) {
  return (
    <section className="landing-editions" aria-labelledby="landing-editions-title">
      <p className="landing-continuity__promise">{copy.promise}</p>
      <h3 id="landing-editions-title">{copy.title}</h3>
      <p>{copy.body}</p>
      <PageStrip pages={MARKETING_IMAGES.editions} alts={copy.alts} captions={copy.captions} links={copy.links} />
      <p className="landing-page-samples__note">{copy.note}</p>
    </section>
  );
}

function SampleBook({ copy }: { copy: LandingCopy["sampleBook"] }) {
  return (
    <section className="landing-sample-book" aria-labelledby="landing-sample-book-title">
      <div className="landing-sample-book__heading">
        <p className="landing-story-shelf__eyebrow">{copy.kicker}</p>
        <h3 id="landing-sample-book-title">{copy.title}</h3>
        <p>{copy.body}</p>
        <Link to="/samples?story=kaitlin-out-of-space" className="landing-story-shelf__read">
          {copy.readStory} <span aria-hidden="true">→</span>
        </Link>
      </div>
      <PageStrip pages={MARKETING_IMAGES.sampleBook} alts={copy.alts} captions={copy.captions} />
      <p className="landing-page-samples__note">{copy.note}</p>
    </section>
  );
}

function FilmSection({ copy, language }: { copy: LandingCopy["film"]; language: LanguageCode }) {
  const [playing, setPlaying] = useState(false);
  const { youtubeId, poster } = MARKETING_IMAGES.film;
  // Privacy-enhanced embed, loaded only after an explicit play.
  const player = `https://www.youtube-nocookie.com/embed/${youtubeId}?autoplay=1&rel=0&playsinline=1&hl=${language}`;
  return (
    <section className="landing-film" id="film" aria-labelledby="landing-film-title">
      <div className="landing-film__copy">
        <p className="landing-film__kicker">{copy.kicker}</p>
        <h2 id="landing-film-title">{copy.title}</h2>
        <p className="landing-film__body">{copy.body}</p>
        <ol className="landing-film__chapters">
          {copy.chapters.map(chapter => <li key={chapter}>{chapter}</li>)}
        </ol>
      </div>
      <figure className="landing-film__stage">
        <div className="landing-film__frame">
          {playing ? (
            <iframe
              src={player}
              title={copy.playerTitle}
              allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
              allowFullScreen
              referrerPolicy="strict-origin-when-cross-origin"
            />
          ) : (
            <button type="button" className="landing-film__poster" onClick={() => setPlaying(true)} aria-label={copy.play}>
              <img src={poster} {...responsiveMarketingImage(poster, "(max-width: 900px) 90vw, 55vw")} alt={copy.posterAlt} loading="lazy" decoding="async" />
              <span className="landing-film__play" aria-hidden="true">
                <svg viewBox="0 0 24 24" focusable="false"><path d="M8 5.5v13l10.5-6.5z" /></svg>
                {copy.playLabel}
              </span>
              <span className="landing-film__duration" aria-hidden="true">{copy.duration}</span>
            </button>
          )}
        </div>
        <figcaption>
          <span>{copy.caption}</span>
          <a href={`https://www.youtube.com/watch?v=${youtubeId}`} target="_blank" rel="noopener noreferrer">
            {copy.youtube} <span aria-hidden="true">↗</span>
          </a>
        </figcaption>
      </figure>
    </section>
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

function StoryShelfPreview({ copy }: { copy: LandingCopy["sampleBook"] }) {
  const { t } = useI18n();
  const { data: stories } = useShortStories();
  const featured = ["kaitlin-out-of-space", "the-sea-in-me", "an-education"]
    .flatMap((code) => stories?.find((story) => story.code === code) ?? []);

  return (
    <section className="landing-story-shelf" aria-labelledby="landing-story-shelf-title">
      <div className="landing-story-shelf__heading">
        <div>
          <p className="landing-story-shelf__eyebrow">{t("THE SAMPLE SHELF")}</p>
          <h2 id="landing-story-shelf-title">{t("Your next comic could start here.")}</h2>
          <p>{t("Read a complete, adaptation-ready story before you begin. From a quiet alien encounter to family drama and fantasy, each sample tests a different kind of page.")}</p>
        </div>
        <Link to="/samples" className="landing-story-shelf__link">{t("Explore all stories")} <span aria-hidden="true">↗</span></Link>
      </div>
      {featured.length > 0 && <div className="landing-story-shelf__books">
        {featured.map((story, index) => <article key={story.code} className="landing-story-shelf__book">
          <div className="landing-story-shelf__stamp"><span>{String(index + 1).padStart(2, "0")}</span><span>{t(genreLabel(story.genres[0] ?? "Story"))}</span></div>
          <h3>{story.title}</h3>
          <p className="landing-story-shelf__author">{story.author} · {story.words.toLocaleString()} {t("words")}</p>
          {story.description && <p className="landing-story-shelf__description">{t(story.description)}</p>}
          <Link to={`/samples?story=${encodeURIComponent(story.code)}`} className="landing-story-shelf__read">{t("Read and choose")} <span aria-hidden="true">→</span></Link>
        </article>)}
      </div>}
      <SampleBook copy={copy} />
    </section>
  );
}

export function HomePage() {
  const { language, setLanguage, t } = useI18n();
  const copy = landingCopy(t);

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
          <a href="#film">{copy.nav.film}</a>
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

        <FilmSection copy={copy.film} language={language} />

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
                  <img src={src} {...responsiveMarketingImage(src, "(max-width: 680px) 90vw, 45vw")} alt={copy.continuity.alts[index]} loading="lazy" decoding="async" />
                </a>
                <figcaption>
                  <span>{copy.continuity.captions[index]}</span>
                  <a href={src} target="_blank" rel="noopener noreferrer">{copy.continuity.inspectLinks[index]}</a>
                </figcaption>
              </figure>
            ))}
          </div>
          <p className="landing-page-samples__note">{copy.continuity.sample}</p>
          <EditionsStrip copy={copy.editions} />
          <div className="landing-reference-inspection">
            <div>
              <h3>{copy.continuity.inspectTitle}</h3>
              <p>{copy.continuity.inspectBody}</p>
            </div>
            <Link className="landing-cta" to="/signup">{copy.hero.primaryCta}</Link>
          </div>
        </section>

        <PublicationShowcase />
        <StoryShelfPreview copy={copy.sampleBook} />

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
