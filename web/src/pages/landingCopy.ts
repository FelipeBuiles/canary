import type { Translator } from "../locales/messages";
export interface LandingStep {
    number: string;
    label: string;
    title: string;
    body: string;
}
export interface LandingFaq {
    question: string;
    answer: string;
}
export interface LandingCopy {
    nav: {
        skip: string;
        home: string;
        navigation: string;
        process: string;
        film: string;
        continuity: string;
        rights: string;
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
        chapterLabel: string;
        loopTag: string;
        loopCaption: string;
        loopAlt: string;
        pauseLoop: string;
        playLoop: string;
    };
    premise: {
        title: string;
        body: string;
    };
    film: {
        kicker: string;
        title: string;
        body: string;
        chapters: string[];
        play: string;
        playLabel: string;
        duration: string;
        playerTitle: string;
        caption: string;
        youtube: string;
        posterAlt: string;
    };
    process: {
        title: string;
        body: string;
        steps: LandingStep[];
    };
    continuity: {
        title: string;
        body: string;
        promise: string;
        sample: string;
        captions: [
            string,
            string,
            string
        ];
        details: Array<{
            title: string;
            body: string;
        }>;
        alts: [
            string,
            string,
            string
        ];
        inspectTitle: string;
        inspectBody: string;
        inspectLinks: [
            string,
            string,
            string
        ];
    };
    editions: {
        promise: string;
        title: string;
        body: string;
        captions: [
            string,
            string,
            string
        ];
        alts: [
            string,
            string,
            string
        ];
        links: [
            string,
            string,
            string
        ];
        note: string;
    };
    sampleBook: {
        kicker: string;
        title: string;
        body: string;
        readStory: string;
        captions: [
            string,
            string,
            string
        ];
        alts: [
            string,
            string,
            string
        ];
        note: string;
    };
    direction: {
        title: string;
        body: string;
        youLabel: string;
        youItems: string[];
        toolLabel: string;
        toolItems: string[];
        disclosure: string;
        termsLink: string;
    };
    trust: {
        title: string;
        body: string;
        items: string[];
        cta: string;
        note: string;
    };
    faq: {
        title: string;
        body: string;
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
        terms: string;
        privacy: string;
        acceptableUse: string;
    };
}
/** Page structure only; all translated text lives in ICU catalogs. */
export function landingCopy(t: Translator): LandingCopy {
    return { nav: { process: t("landing.nav.process"),
            film: t("landing.nav.film"),
            continuity: t("landing.nav.continuity"),
            rights: t("landing.nav.rights"),
            faq: t("landing.nav.faq"),
            signIn: t("landing.nav.signIn"),
            cta: t("landing.nav.cta"),
            language: t("landing.nav.language"),
            skip: t("landing.nav.skip"),
            home: t("landing.nav.home"),
            navigation: t("landing.nav.navigation") },
        hero: { label: t("landing.hero.label"),
            title: t("landing.hero.title"),
            body: t("landing.hero.body"),
            primaryCta: t("landing.hero.primaryCta"),
            secondaryCta: t("landing.hero.secondaryCta"),
            formats: t("landing.hero.formats"),
            manuscriptLabel: t("landing.hero.manuscriptLabel"),
            chapterLabel: t("landing.hero.chapterLabel"),
            loopTag: t("landing.hero.loopTag"),
            loopCaption: t("landing.hero.loopCaption"),
            loopAlt: t("landing.hero.loopAlt"),
            pauseLoop: t("landing.hero.pauseLoop"),
            playLoop: t("landing.hero.playLoop") },
        premise: { title: t("landing.premise.title"),
            body: t("landing.premise.body") },
        film: { kicker: t("landing.film.kicker"),
            title: t("landing.film.title"),
            body: t("landing.film.body"),
            chapters: [t("landing.film.chapters.0"),
                t("landing.film.chapters.1"),
                t("landing.film.chapters.2"),
                t("landing.film.chapters.3")],
            play: t("landing.film.play"),
            playLabel: t("landing.film.playLabel"),
            duration: t("landing.film.duration"),
            playerTitle: t("landing.film.playerTitle"),
            caption: t("landing.film.caption"),
            youtube: t("landing.film.youtube"),
            posterAlt: t("landing.film.posterAlt") },
        process: { title: t("landing.process.title"),
            body: t("landing.process.body"),
            steps: [{ number: t("landing.process.steps.0.number"),
                    label: t("landing.process.steps.0.label"),
                    title: t("landing.process.steps.0.title"),
                    body: t("landing.process.steps.0.body") },
                { number: t("landing.process.steps.1.number"),
                    label: t("landing.process.steps.1.label"),
                    title: t("landing.process.steps.1.title"),
                    body: t("landing.process.steps.1.body") },
                { number: t("landing.process.steps.2.number"),
                    label: t("landing.process.steps.2.label"),
                    title: t("landing.process.steps.2.title"),
                    body: t("landing.process.steps.2.body") },
                { number: t("landing.process.steps.3.number"),
                    label: t("landing.process.steps.3.label"),
                    title: t("landing.process.steps.3.title"),
                    body: t("landing.process.steps.3.body") }] },
        continuity: { title: t("landing.continuity.title"),
            body: t("landing.continuity.body"),
            promise: t("landing.continuity.promise"),
            sample: t("landing.continuity.sample"),
            captions: [t("landing.continuity.captions.0"),
                t("landing.continuity.captions.1"),
                t("landing.continuity.captions.2")],
            details: [{ title: t("landing.continuity.details.0.title"),
                    body: t("landing.continuity.details.0.body") },
                { title: t("landing.continuity.details.1.title"),
                    body: t("landing.continuity.details.1.body") },
                { title: t("landing.continuity.details.2.title"),
                    body: t("landing.continuity.details.2.body") }],
            alts: [t("landing.continuity.alts.0"),
                t("landing.continuity.alts.1"),
                t("landing.continuity.alts.2")],
            inspectTitle: t("landing.continuity.inspectTitle"),
            inspectBody: t("landing.continuity.inspectBody"),
            inspectLinks: [t("landing.continuity.inspectLinks.0"),
                t("landing.continuity.inspectLinks.1"),
                t("landing.continuity.inspectLinks.2")] },
        editions: { promise: t("landing.editions.promise"),
            title: t("landing.editions.title"),
            body: t("landing.editions.body"),
            captions: [t("landing.editions.captions.0"),
                t("landing.editions.captions.1"),
                t("landing.editions.captions.2")],
            alts: [t("landing.editions.alts.0"),
                t("landing.editions.alts.1"),
                t("landing.editions.alts.2")],
            links: [t("landing.editions.links.0"),
                t("landing.editions.links.1"),
                t("landing.editions.links.2")],
            note: t("landing.editions.note") },
        sampleBook: { kicker: t("landing.sampleBook.kicker"),
            title: t("landing.sampleBook.title"),
            body: t("landing.sampleBook.body"),
            readStory: t("landing.sampleBook.readStory"),
            captions: [t("landing.sampleBook.captions.0"),
                t("landing.sampleBook.captions.1"),
                t("landing.sampleBook.captions.2")],
            alts: [t("landing.sampleBook.alts.0"),
                t("landing.sampleBook.alts.1"),
                t("landing.sampleBook.alts.2")],
            note: t("landing.sampleBook.note") },
        direction: { title: t("landing.direction.title"),
            body: t("landing.direction.body"),
            youLabel: t("landing.direction.youLabel"),
            youItems: [t("landing.direction.youItems.0"),
                t("landing.direction.youItems.1"),
                t("landing.direction.youItems.2"),
                t("landing.direction.youItems.3")],
            toolLabel: t("landing.direction.toolLabel"),
            toolItems: [t("landing.direction.toolItems.0"),
                t("landing.direction.toolItems.1"),
                t("landing.direction.toolItems.2"),
                t("landing.direction.toolItems.3")],
            disclosure: t("landing.direction.disclosure"),
            termsLink: t("landing.direction.termsLink") },
        trust: { title: t("landing.trust.title"),
            body: t("landing.trust.body"),
            items: [t("landing.trust.items.0"),
                t("landing.trust.items.1"),
                t("landing.trust.items.2"),
                t("landing.trust.items.3")],
            cta: t("landing.trust.cta"),
            note: t("landing.trust.note") },
        faq: { title: t("landing.faq.title"),
            body: t("landing.faq.body"),
            items: [{ question: t("landing.faq.items.0.question"),
                    answer: t("landing.faq.items.0.answer") },
                { question: t("landing.faq.items.1.question"),
                    answer: t("landing.faq.items.1.answer") },
                { question: t("landing.faq.items.2.question"),
                    answer: t("landing.faq.items.2.answer") },
                { question: t("landing.faq.items.3.question"),
                    answer: t("landing.faq.items.3.answer") },
                { question: t("landing.faq.items.4.question"),
                    answer: t("landing.faq.items.4.answer") },
                { question: t("landing.faq.items.5.question"),
                    answer: t("landing.faq.items.5.answer") }] },
        final: { title: t("landing.final.title"),
            body: t("landing.final.body"),
            cta: t("landing.final.cta"),
            signIn: t("landing.final.signIn") },
        footer: { line: t("landing.footer.line"),
            terms: t("landing.footer.terms"),
            privacy: t("landing.footer.privacy"),
            acceptableUse: t("landing.footer.acceptableUse") } };
}
