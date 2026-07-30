import type { LanguageCode } from "../i18n";

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
    process: string;
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
    sampleLabel: string;
    sampleCaption: string;
    manuscriptLabel: string;
    visualLabels: [string, string, string];
    visualAlt: string;
  };
  premise: {
    title: string;
    body: string;
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
    captions: [string, string, string];
    details: Array<{ title: string; body: string }>;
    alts: [string, string, string];
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

export const LANDING_COPY: Record<LanguageCode, LandingCopy> = {
  en: {
    nav: {
      process: "How it works",
      continuity: "Continuity",
      rights: "Your rights",
      faq: "Questions",
      signIn: "Sign in",
      cta: "Create your studio",
      language: "Language",
    },
    hero: {
      label: "A graphic-novel studio for novelists",
      title: "Turn your novel into a graphic novel you direct.",
      body: "Upload a finished manuscript. Shape the adaptation, cast, and visual style, review complete comic pages by exception, then export the verified book as PDF or CBZ.",
      primaryCta: "Start with a sample story",
      secondaryCta: "See the four decisions",
      formats: "AI-assisted visual adaptation · EPUB, PDF or TXT in · PDF or CBZ out",
      sampleLabel: "Development sample",
      sampleCaption: "Approved cast and world references",
      manuscriptLabel: "The manuscript",
      visualLabels: ["Approved cast", "Place reference", "Visual direction"],
      visualAlt: "Development sample showing two illustrated character references and a recurring tavern location.",
    },
    premise: {
      title: "A whole-book workflow, not a one-prompt trick.",
      body: "Your manuscript stays the source of truth from the first story beat to the last page.",
    },
    process: {
      title: "Four decisions between manuscript and finished book.",
      body: "Scenewright runs the production line. You keep the creative gates.",
      steps: [
        {
          number: "01",
          label: "Story",
          title: "Confirm the story",
          body: "Scenewright maps the characters, places and scene beats. You review the story bible before anything moves on.",
        },
        {
          number: "02",
          label: "Look",
          title: "Choose the look",
          body: "Pick a visual direction, then approve reference art for the cast and recurring locations.",
        },
        {
          number: "03",
          label: "Pages",
          title: "Fix by exception",
          body: "The adaptation and page plan run in the background. Review complete page revisions and correct only what misses.",
        },
        {
          number: "04",
          label: "Book",
          title: "Finish the edition",
          body: "Run final preflight, resolve any returned corrections, then export the verified edition as PDF or CBZ.",
        },
      ],
    },
    continuity: {
      title: "Keep the cast. Keep the world. Keep the thread.",
      body: "Approved character references, location plates, and book-level continuity guide every complete page. Every new page starts with more than a standalone prompt.",
      promise: "Built for long-form continuity",
      sample: "Development reference set · not customer work",
      captions: ["Character reference", "Recurring location", "Character reference"],
      details: [
        {
          title: "Character references",
          body: "Approved poses guide every complete page where that character appears.",
        },
        {
          title: "Location plates",
          body: "Recurring places keep the visual anchors you approved.",
        },
        {
          title: "Page continuity",
          body: "Book-level story state helps each complete page stay consistent with the pages around it.",
        },
      ],
      alts: [
        "Illustrated development portrait of Anya in a dark coat.",
        "Illustrated development plate of a lantern-lit timber tavern.",
        "Illustrated development portrait of Rurik in a fur cloak.",
      ],
    },
    direction: {
      title: "The tool takes the workload. You keep the creative decisions.",
      body: "Scenewright is built as an instrument for an author—not a slot machine that replaces one.",
      youLabel: "You direct",
      youItems: ["The story and source text", "The look and cast", "What gets corrected", "The final issue decisions"],
      toolLabel: "Scenewright drafts",
      toolItems: ["The story bible and brief", "The adaptation and page plan", "Complete comic pages", "Verified PDF and CBZ editions"],
      disclosure: "Scenewright uses third-party generative models to assist with adaptation and illustration. Your manuscript stays yours, and we claim no ownership over generated output. Purely generated imagery may have limited copyright protection.",
      termsLink: "Read the full rights and copyright terms",
    },
    trust: {
      title: "Pay for the production, not another subscription.",
      body: "Buy credits when you are ready. Every paid step shows an estimate before it runs.",
      items: ["No subscription", "Credits never expire", "Packs start at $12", "Estimate before paid steps"],
      cta: "Create your studio",
      note: "Actual credit use varies with manuscript length, visual quality and revisions.",
    },
    faq: {
      title: "Before you hand over the manuscript.",
      body: "The practical answers, without the fine-print fog.",
      items: [
        {
          question: "Can I upload a full novel?",
          answer: "Yes. Scenewright accepts EPUB, PDF and TXT manuscripts, adapts the story, and plans the complete book page by page.",
        },
        {
          question: "Can I change what it makes?",
          answer: "Yes. You approve the story, look and cast, then review complete page revisions and decide which page issues to correct or accept as-is.",
        },
        {
          question: "Will every character look perfectly identical?",
          answer: "No generative system can promise perfect continuity. Scenewright improves it with approved character references, location plates and book-level story state, then lets you correct complete pages that miss.",
        },
        {
          question: "Who owns the manuscript and output?",
          answer: "You retain ownership of your manuscript. Scenewright claims no ownership over generated output, though purely generated images may not qualify for copyright protection in every jurisdiction.",
        },
        {
          question: "Does Scenewright use AI?",
          answer: "Yes. Third-party generative models assist with adaptation and illustration. The workflow keeps the author in charge of the key choices, edits and final arrangement.",
        },
        {
          question: "How much will my book cost?",
          answer: "There is no subscription. Credit packs start at $12, credits never expire, and Scenewright estimates each paid step before it runs. Total use depends on length, quality and revisions.",
        },
      ],
    },
    final: {
      title: "Your story is already written. Direct the edition readers can see.",
      body: "Start with a sample story inside the studio, or bring your own manuscript when you are ready.",
      cta: "Create my studio",
      signIn: "I already have an account",
    },
    footer: {
      line: "Your novel, scene by scene.",
      terms: "Terms",
      privacy: "Privacy",
      acceptableUse: "Acceptable use",
    },
  },
  es: {
    nav: {
      process: "Cómo funciona",
      continuity: "Continuidad",
      rights: "Tus derechos",
      faq: "Preguntas",
      signIn: "Iniciar sesión",
      cta: "Crea tu estudio",
      language: "Idioma",
    },
    hero: {
      label: "Un estudio de novela gráfica para novelistas",
      title: "Convierte tu novela en una novela gráfica que tú diriges.",
      body: "Sube un manuscrito terminado. Define la adaptación, el reparto y el estilo visual, revisa páginas completas por excepción y exporta el libro verificado en PDF o CBZ.",
      primaryCta: "Empieza con un cuento de muestra",
      secondaryCta: "Conoce las cuatro decisiones",
      formats: "Adaptación visual asistida por IA · EPUB, PDF o TXT de entrada · PDF o CBZ de salida",
      sampleLabel: "Muestra de desarrollo",
      sampleCaption: "Reparto y mundo de referencia aprobados",
      manuscriptLabel: "El manuscrito",
      visualLabels: ["Reparto aprobado", "Lugar de referencia", "Dirección visual"],
      visualAlt: "Muestra de desarrollo con dos personajes ilustrados y una taberna recurrente como referencia.",
    },
    premise: {
      title: "Un flujo para todo el libro, no un truco de un solo prompt.",
      body: "Tu manuscrito sigue siendo la fuente de verdad desde el primer giro hasta la última página.",
    },
    process: {
      title: "Cuatro decisiones entre el manuscrito y el libro terminado.",
      body: "Scenewright mueve la producción. Tú conservas las decisiones creativas.",
      steps: [
        {
          number: "01",
          label: "Historia",
          title: "Confirma la historia",
          body: "Scenewright identifica personajes, lugares y escenas. Tú revisas la biblia de la historia antes de avanzar.",
        },
        {
          number: "02",
          label: "Estilo",
          title: "Elige el aspecto",
          body: "Escoge una dirección visual y aprueba el arte de referencia del reparto y de los lugares recurrentes.",
        },
        {
          number: "03",
          label: "Páginas",
          title: "Corrige por excepción",
          body: "La adaptación y el plan de páginas avanzan en segundo plano. Revisa páginas completas y corrige solo lo que falla.",
        },
        {
          number: "04",
          label: "Libro",
          title: "Termina la edición",
          body: "Ejecuta la verificación final, resuelve las correcciones devueltas y exporta la edición en PDF o CBZ.",
        },
      ],
    },
    continuity: {
      title: "Conserva el reparto. Conserva el mundo. Conserva el hilo.",
      body: "Las referencias de personajes y lugares aprobadas, junto con la continuidad del libro, guían cada página completa. Cada página parte de mucho más que un prompt aislado.",
      promise: "Pensado para la continuidad de largo formato",
      sample: "Referencias de desarrollo · no es trabajo de un cliente",
      captions: ["Referencia de personaje", "Lugar recurrente", "Referencia de personaje"],
      details: [
        {
          title: "Referencias de personajes",
          body: "Las poses aprobadas guían cada página completa donde aparece el personaje.",
        },
        {
          title: "Lugares de referencia",
          body: "Los lugares recurrentes conservan los rasgos visuales que aprobaste.",
        },
        {
          title: "Continuidad de página",
          body: "El estado narrativo del libro mantiene cada página coherente con las que la rodean.",
        },
      ],
      alts: [
        "Retrato ilustrado de desarrollo de Anya con abrigo oscuro.",
        "Referencia ilustrada de una taberna de madera iluminada con faroles.",
        "Retrato ilustrado de desarrollo de Rurik con capa de piel.",
      ],
    },
    direction: {
      title: "La herramienta asume la carga. Tú conservas las decisiones creativas.",
      body: "Scenewright está hecho como instrumento para el autor, no como una máquina que lo sustituye.",
      youLabel: "Tú diriges",
      youItems: ["La historia y el texto original", "El estilo y el reparto", "Qué se corrige", "Las decisiones finales sobre incidencias"],
      toolLabel: "Scenewright prepara",
      toolItems: ["La biblia y el enfoque", "La adaptación y el plan de páginas", "Páginas completas de cómic", "Ediciones PDF y CBZ verificadas"],
      disclosure: "Scenewright usa modelos generativos de terceros para ayudar con la adaptación y la ilustración. Tu manuscrito sigue siendo tuyo y no reclamamos propiedad sobre el resultado generado. Las imágenes puramente generadas pueden tener protección de autor limitada.",
      termsLink: "Lee todos los términos sobre derechos y autoría",
    },
    trust: {
      title: "Paga por la producción, no por otra suscripción.",
      body: "Compra créditos cuando estés listo. Cada paso de pago muestra una estimación antes de ejecutarse.",
      items: ["Sin suscripción", "Los créditos no vencen", "Paquetes desde 12 USD", "Estimación antes de pagar"],
      cta: "Crea tu estudio",
      note: "El uso real depende de la extensión, la calidad visual y las revisiones.",
    },
    faq: {
      title: "Antes de entregar el manuscrito.",
      body: "Respuestas prácticas, sin niebla de letra pequeña.",
      items: [
        {
          question: "¿Puedo subir una novela completa?",
          answer: "Sí. Scenewright acepta manuscritos EPUB, PDF y TXT, adapta la historia y planifica el libro página a página.",
        },
        {
          question: "¿Puedo cambiar lo que produce?",
          answer: "Sí. Apruebas la historia, el estilo y el reparto; después revisas páginas completas, solicitas correcciones y decides qué incidencias editoriales aceptar.",
        },
        {
          question: "¿Cada personaje será perfectamente idéntico?",
          answer: "Ningún sistema generativo puede prometer continuidad perfecta. Scenewright la refuerza con referencias aprobadas, lugares recurrentes y el estado narrativo del libro, y permite corregir páginas completas.",
        },
        {
          question: "¿Quién posee el manuscrito y el resultado?",
          answer: "Conservas la propiedad de tu manuscrito. Scenewright no reclama propiedad sobre el resultado generado, aunque las imágenes puramente generadas pueden no recibir protección de autor en todas las jurisdicciones.",
        },
        {
          question: "¿Scenewright usa IA?",
          answer: "Sí. Modelos generativos de terceros ayudan con la adaptación y la ilustración. El flujo mantiene al autor al mando de las decisiones, correcciones y composición final.",
        },
        {
          question: "¿Cuánto costará mi libro?",
          answer: "No hay suscripción. Los paquetes parten de 12 USD, los créditos no vencen y Scenewright estima cada paso de pago. El total depende de la extensión, la calidad y las revisiones.",
        },
      ],
    },
    final: {
      title: "Tu historia ya está escrita. Dirige la edición que los lectores podrán ver.",
      body: "Empieza con un cuento de muestra dentro del estudio o trae tu manuscrito cuando estés listo.",
      cta: "Crear mi estudio",
      signIn: "Ya tengo una cuenta",
    },
    footer: {
      line: "Tu novela, escena por escena.",
      terms: "Términos",
      privacy: "Privacidad",
      acceptableUse: "Uso aceptable",
    },
  },
  fr: {
    nav: {
      process: "Fonctionnement",
      continuity: "Continuité",
      rights: "Vos droits",
      faq: "Questions",
      signIn: "Se connecter",
      cta: "Créer votre studio",
      language: "Langue",
    },
    hero: {
      label: "Un studio de roman graphique pour les romanciers",
      title: "Transformez votre roman en roman graphique, sous votre direction.",
      body: "Importez un manuscrit achevé. Façonnez l’adaptation, les personnages et le style, révisez les pages complètes par exception, puis exportez le livre vérifié en PDF ou CBZ.",
      primaryCta: "Commencer avec un récit exemple",
      secondaryCta: "Voir les quatre décisions",
      formats: "Adaptation visuelle assistée par IA · EPUB, PDF ou TXT en entrée · PDF ou CBZ en sortie",
      sampleLabel: "Exemple de développement",
      sampleCaption: "Personnages et univers de référence approuvés",
      manuscriptLabel: "Le manuscrit",
      visualLabels: ["Personnages approuvés", "Lieu de référence", "Direction visuelle"],
      visualAlt: "Exemple de développement montrant deux personnages illustrés et une taverne récurrente comme référence.",
    },
    premise: {
      title: "Un flux pour le livre entier, pas un tour de passe-passe en un prompt.",
      body: "Votre manuscrit reste la source de vérité, du premier temps fort à la dernière page.",
    },
    process: {
      title: "Quatre décisions entre le manuscrit et le livre terminé.",
      body: "Scenewright fait avancer la production. Vous gardez les choix créatifs.",
      steps: [
        {
          number: "01",
          label: "Récit",
          title: "Confirmez le récit",
          body: "Scenewright repère personnages, lieux et scènes. Vous relisez la bible narrative avant de poursuivre.",
        },
        {
          number: "02",
          label: "Style",
          title: "Choisissez l’allure",
          body: "Choisissez une direction visuelle, puis approuvez les références des personnages et des lieux récurrents.",
        },
        {
          number: "03",
          label: "Pages",
          title: "Corrigez par exception",
          body: "L’adaptation et le plan des pages avancent en arrière-plan. Révisez les pages complètes et corrigez seulement ce qui manque.",
        },
        {
          number: "04",
          label: "Livre",
          title: "Finalisez l’édition",
          body: "Lancez le contrôle final, résolvez les corrections renvoyées, puis exportez l’édition en PDF ou CBZ.",
        },
      ],
    },
    continuity: {
      title: "Gardez les personnages. Gardez l’univers. Gardez le fil.",
      body: "Les références approuvées des personnages et des lieux, ainsi que la continuité du livre, guident chaque page complète. Chaque page part de bien plus qu’un prompt isolé.",
      promise: "Pensé pour la continuité au long cours",
      sample: "Références de développement · pas un projet client",
      captions: ["Référence de personnage", "Lieu récurrent", "Référence de personnage"],
      details: [
        {
          title: "Références des personnages",
          body: "Les poses approuvées guident chaque page complète où le personnage apparaît.",
        },
        {
          title: "Planches de lieux",
          body: "Les lieux récurrents conservent les repères visuels que vous avez approuvés.",
        },
        {
          title: "Continuité de page",
          body: "L’état narratif du livre maintient chaque page cohérente avec celles qui l’entourent.",
        },
      ],
      alts: [
        "Portrait illustré de développement d’Anya dans un manteau sombre.",
        "Planche illustrée d’une taverne en bois éclairée par des lanternes.",
        "Portrait illustré de développement de Rurik dans une cape de fourrure.",
      ],
    },
    direction: {
      title: "L’outil prend en charge le travail. Vous gardez les choix créatifs.",
      body: "Scenewright est conçu comme l’instrument d’un auteur, pas comme une machine qui le remplace.",
      youLabel: "Vous dirigez",
      youItems: ["Le récit et le texte source", "Le style et les personnages", "Ce qui doit être corrigé", "Les décisions finales sur les problèmes"],
      toolLabel: "Scenewright prépare",
      toolItems: ["La bible narrative et le brief", "L’adaptation et le plan des pages", "Les pages complètes de la BD", "Les éditions PDF et CBZ vérifiées"],
      disclosure: "Scenewright utilise des modèles génératifs tiers pour aider à l’adaptation et à l’illustration. Votre manuscrit reste à vous et nous ne revendiquons aucun droit de propriété sur les sorties générées. Une image purement générée peut bénéficier d’une protection limitée.",
      termsLink: "Lire les conditions complètes sur les droits et le copyright",
    },
    trust: {
      title: "Payez la production, pas un abonnement de plus.",
      body: "Achetez des crédits quand vous êtes prêt. Chaque étape payante affiche une estimation avant de démarrer.",
      items: ["Sans abonnement", "Les crédits n’expirent jamais", "Packs dès 12 $ US", "Estimation avant paiement"],
      cta: "Créer votre studio",
      note: "La consommation réelle varie selon la longueur, la qualité visuelle et les révisions.",
    },
    faq: {
      title: "Avant de confier le manuscrit.",
      body: "Les réponses pratiques, sans brouillard juridique.",
      items: [
        {
          question: "Puis-je importer un roman entier ?",
          answer: "Oui. Scenewright accepte les manuscrits EPUB, PDF et TXT, adapte le récit et planifie le livre page par page.",
        },
        {
          question: "Puis-je modifier le résultat ?",
          answer: "Oui. Vous approuvez le récit, le style et les personnages, puis révisez les pages complètes, demandez des corrections et décidez quels problèmes éditoriaux accepter.",
        },
        {
          question: "Chaque personnage sera-t-il parfaitement identique ?",
          answer: "Aucun système génératif ne peut promettre une continuité parfaite. Scenewright la renforce avec des références approuvées, des lieux récurrents et l’état narratif du livre, puis permet de corriger les pages complètes.",
        },
        {
          question: "À qui appartiennent le manuscrit et le résultat ?",
          answer: "Vous conservez la propriété de votre manuscrit. Scenewright ne revendique aucun droit de propriété sur les sorties générées, même si une image purement générée peut ne pas être protégeable partout.",
        },
        {
          question: "Scenewright utilise-t-il l’IA ?",
          answer: "Oui. Des modèles génératifs tiers aident à l’adaptation et à l’illustration. Le flux laisse à l’auteur les choix clés, les corrections et la composition finale.",
        },
        {
          question: "Combien coûtera mon livre ?",
          answer: "Il n’y a pas d’abonnement. Les packs commencent à 12 $ US, les crédits n’expirent pas et Scenewright estime chaque étape payante. Le total dépend de la longueur, de la qualité et des révisions.",
        },
      ],
    },
    final: {
      title: "Votre histoire est déjà écrite. Dirigez l’édition que les lecteurs pourront voir.",
      body: "Commencez avec un récit exemple dans le studio, ou apportez votre manuscrit quand vous êtes prêt.",
      cta: "Créer mon studio",
      signIn: "J’ai déjà un compte",
    },
    footer: {
      line: "Votre roman, scène par scène.",
      terms: "Conditions",
      privacy: "Confidentialité",
      acceptableUse: "Utilisation acceptable",
    },
  },
};
