import type { Translator } from "../locales/messages";
export interface LandingStep {
    number: string;
    label: string;
    title: string;
    body: string;
    approve: boolean;
}
export interface LandingFaq {
    question: string;
    answer: string;
}
export interface LandingEdition {
    label: string;
    note: string;
    alt: string;
    link: string;
}
export interface LandingCopy {
    nav: {
        skip: string;
        home: string;
        navigation: string;
        books: string;
        styles: string;
        process: string;
        pricing: string;
        faq: string;
        signIn: string;
        cta: string;
        language: string;
    };
    hero: {
        label: string;
        title: string;
        body: string;
        primaryCta: string;
        secondaryCta: string;
        formats: string;
        manuscriptLabel: string;
        loopTag: string;
        loopCaption: string;
        loopAlt: string;
        pauseLoop: string;
        playLoop: string;
    };
    books: {
        title: string;
        body: string;
        samples: string;
        read: string;
        note: string;
    };
    styles: {
        label: string;
        title: string;
        body: string;
        play: string;
        playLabel: string;
        playerTitle: string;
        posterAlt: string;
        filmNote: string;
        youtube: string;
        editions: [LandingEdition, LandingEdition, LandingEdition];
        license: string;
    };
    process: {
        title: string;
        body: string;
        approve: string;
        steps: LandingStep[];
        brief: { heading: string; items: [string, string, string]; more: string };
        review: { note: string; action: string };
        shareLink: string;
        samples: { title: string; body: string; link: string };
    };
    rights: {
        title: string;
        youLabel: string;
        youItems: string[];
        toolLabel: string;
        toolItems: string[];
        disclosure: string;
        termsLink: string;
    };
    pricing: {
        title: string;
        body: string;
        items: string[];
        link: string;
    };
    faq: {
        title: string;
        contact: string;
        items: LandingFaq[];
    };
    final: {
        title: string;
        body: string;
        cta: string;
        signIn: string;
    };
    footer: {
        line: string;
        product: string;
        legal: string;
        terms: string;
        privacy: string;
        acceptableUse: string;
        workflow: string;
        pricing: string;
        guide: string;
        example: string;
        about: string;
    };
}
const steps = (t: Translator): LandingStep[] => [0, 1, 2, 3, 4].map(index => ({
    number: String(index + 1).padStart(2, "0"),
    label: t(`landing.process.steps.${index}.label`),
    title: t(`landing.process.steps.${index}.title`),
    body: t(`landing.process.steps.${index}.body`),
    approve: index < 4,
}));
const edition = (t: Translator, index: number): LandingEdition => ({
    label: t(`landing.styles.editions.${index}.label`),
    note: t(`landing.styles.editions.${index}.note`),
    alt: t(`landing.styles.editions.${index}.alt`),
    link: t(`landing.styles.editions.${index}.link`),
});
/** Page structure only; all translated text lives in ICU catalogs. */
export function landingCopy(t: Translator): LandingCopy {
    return { nav: { skip: t("landing.nav.skip"),
            home: t("landing.nav.home"),
            navigation: t("landing.nav.navigation"),
            books: t("landing.nav.books"),
            styles: t("landing.nav.styles"),
            process: t("landing.nav.process"),
            pricing: t("landing.nav.pricing"),
            faq: t("landing.nav.faq"),
            signIn: t("landing.nav.signIn"),
            cta: t("landing.nav.cta"),
            language: t("landing.nav.language") },
        hero: { label: t("landing.hero.label"),
            title: t("landing.hero.title"),
            body: t("landing.hero.body"),
            primaryCta: t("landing.hero.primaryCta"),
            secondaryCta: t("landing.hero.secondaryCta"),
            formats: t("landing.hero.formats"),
            manuscriptLabel: t("landing.hero.manuscriptLabel"),
            loopTag: t("landing.hero.loopTag"),
            loopCaption: t("landing.hero.loopCaption"),
            loopAlt: t("landing.hero.loopAlt"),
            pauseLoop: t("landing.hero.pauseLoop"),
            playLoop: t("landing.hero.playLoop") },
        books: { title: t("landing.books.title"),
            body: t("landing.books.body"),
            samples: t("landing.books.samples"),
            read: t("landing.books.read"),
            note: t("landing.books.note") },
        styles: { label: t("landing.styles.label"),
            title: t("landing.styles.title"),
            body: t("landing.styles.body"),
            play: t("landing.styles.play"),
            playLabel: t("landing.styles.playLabel"),
            playerTitle: t("landing.styles.playerTitle"),
            posterAlt: t("landing.styles.posterAlt"),
            filmNote: t("landing.styles.filmNote"),
            youtube: t("landing.styles.youtube"),
            editions: [edition(t, 0), edition(t, 1), edition(t, 2)],
            license: t("landing.styles.license") },
        process: { title: t("landing.process.title"),
            body: t("landing.process.body"),
            approve: t("landing.process.approve"),
            steps: steps(t),
            brief: { heading: t("landing.process.brief.heading"),
                items: [t("landing.process.brief.items.0"),
                    t("landing.process.brief.items.1"),
                    t("landing.process.brief.items.2")],
                more: t("landing.process.brief.more") },
            review: { note: t("landing.process.review.note"),
                action: t("landing.process.review.action") },
            shareLink: t("landing.process.shareLink"),
            samples: { title: t("landing.process.samples.title"),
                body: t("landing.process.samples.body"),
                link: t("landing.process.samples.link") } },
        rights: { title: t("landing.rights.title"),
            youLabel: t("landing.rights.youLabel"),
            youItems: [0, 1, 2, 3].map(index => t(`landing.rights.youItems.${index}`)),
            toolLabel: t("landing.rights.toolLabel"),
            toolItems: [0, 1, 2, 3].map(index => t(`landing.rights.toolItems.${index}`)),
            disclosure: t("landing.rights.disclosure"),
            termsLink: t("landing.rights.termsLink") },
        pricing: { title: t("landing.pricing.title"),
            body: t("landing.pricing.body"),
            items: [0, 1, 2, 3].map(index => t(`landing.pricing.items.${index}`)),
            link: t("landing.pricing.link") },
        faq: { title: t("landing.faq.title"),
            contact: t("landing.faq.contact"),
            items: [0, 1, 2, 3, 4, 5].map(index => ({ question: t(`landing.faq.items.${index}.question`),
                answer: t(`landing.faq.items.${index}.answer`) })) },
        final: { title: t("landing.final.title"),
            body: t("landing.final.body"),
            cta: t("landing.final.cta"),
            signIn: t("landing.final.signIn") },
        footer: { line: t("landing.footer.line"),
            product: t("landing.footer.product"),
            legal: t("landing.footer.legal"),
            terms: t("landing.footer.terms"),
            privacy: t("landing.footer.privacy"),
            acceptableUse: t("landing.footer.acceptableUse"),
            workflow: t("landing.footer.workflow"),
            pricing: t("landing.footer.pricing"),
            guide: t("landing.footer.guide"),
            example: t("landing.footer.example"),
            about: t("landing.footer.about") } };
}
