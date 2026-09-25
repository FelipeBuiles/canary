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
    skip: string;
    home: string;
    navigation: string;
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
    inspectTitle: string;
    inspectBody: string;
    inspectLinks: [string, string, string];
  };
  editions: {
    promise: string;
    title: string;
    body: string;
    captions: [string, string, string];
    alts: [string, string, string];
    links: [string, string, string];
    note: string;
  };
  sampleBook: {
    kicker: string;
    title: string;
    body: string;
    readStory: string;
    captions: [string, string, string];
    alts: [string, string, string];
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

export const LANDING_COPY: Record<LanguageCode, LandingCopy> = {
  en: {
    nav: {
      process: "How it works",
      continuity: "Read a scene",
      rights: "Your rights",
      faq: "Questions",
      signIn: "Sign in",
      cta: "Start small",
      language: "Language",
      skip: "Skip to content",
      home: "Scenewright home",
      navigation: "Primary navigation",
    },
    hero: {
      label: "An AI-assisted comic studio for indie authors",
      title: "Your story. Its first comic scene.",
      body: "Give readers a new way into your world. Start with a short excerpt, direct the look and cast, then review and export your comic as PDF or CBZ. Expand when the result feels like your story.",
      primaryCta: "Create my first scene",
      secondaryCta: "Read a development sample",
      formats: "AI-assisted visual adaptation · EPUB, PDF or TXT in · PDF or CBZ out",
      manuscriptLabel: "The manuscript",
      chapterLabel: "YOUR EXCERPT",
      loopTag: "One scene · many looks",
      loopCaption: "Real style proofs of one Dungeon Crawler Carl scene · showcase project",
      loopAlt: "Looping video: one Dungeon Crawler Carl comic page redrawn in a series of art styles, from oil painting to claymation, blueprint, stained glass and cross-stitch.",
      pauseLoop: "Pause",
      playLoop: "Play",
    },
    premise: {
      title: "Start with a scene worth seeing.",
      body: "Choose a short excerpt with a clear setting, a small cast and a turning point. Upload it as its own EPUB, PDF or TXT file—or try a sample story in the studio.",
    },
    process: {
      title: "You direct. The studio handles production.",
      body: "Approve the story brief, style and cast. The adaptation and page plan run between your creative checkpoints.",
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
          title: "Describe it, show it, or ask for six",
          body: "Type the look you picture, upload an image you love, or let Scenewright pitch six directions made for your story. Try as many as you want, then approve reference art for the cast and recurring places.",
        },
        {
          number: "03",
          label: "Pages",
          title: "Review the pages",
          body: "The adaptation and page plan run in the background. Review complete page revisions and correct only what misses.",
        },
        {
          number: "04",
          label: "Book",
          title: "Finish the edition",
          body: "Review the art and lettering, resolve any required corrections, then export your edition as PDF or CBZ. Automated checks do not guarantee visual quality.",
        },
      ],
    },
    continuity: {
      title: "Different stories. Distinct worlds.",
      body: "Explore pixel-art fantasy in Dungeon Crawler Carl and painted cosmic horror in The Call of Cthulhu. Open either page to read the lettering at full size.",
      promise: "From two showcase projects",
      sample: "Showcase projects · Dungeon Crawler Carl, page 25 · The Call of Cthulhu, page 21 · English text. Not customer work; results vary.",
      captions: ["Dungeon Crawler Carl · Page 25", "The Call of Cthulhu · Page 21", ""],
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
      alts: ["Dungeon Crawler Carl comic page 25: Carl and a cat outside the Tutorial Guild, with game achievement notifications in a torchlit pixel-art dungeon. English lettering.", "The Call of Cthulhu comic page 21: Castro describes the Great Old Ones, with scenes of ancient ruins, R’lyeh and cosmic space. English narration.", ""],
      inspectTitle: "A story you can actually read.",
      inspectBody: "Panels, narration and dialogue arrive together. These pages show the current development workflow, including its imperfections. You review the story, art and lettering before deciding what to keep or correct.",
      inspectLinks: ["Read page 25 at full size", "Read page 21 at full size", ""],
    },
    editions: {
      promise: "One story, three editions",
      title: "One story, three books.",
      body: "Three editions of Site-30’s Janitor were adapted from the same text, and each opens on the same line. Each one found its own look, its own pacing and its own lettering.",
      captions: ["Risograph zine · Page 1", "Gouache noir · Page 1 · editable lettering", "Oil-painted noir · Page 1"],
      alts: [
        "Site-30’s Janitor, risograph edition, page 1: a single full-page panel of a sleepy cartoon janitor slumped among mops and orange buckets under a bare bulb. English captions.",
        "Site-30’s Janitor, gouache edition, page 1: four panels of a weary janitor in a dark supply closet answering a crackling wall intercom. English captions and balloons.",
        "Site-30’s Janitor, oil-painted edition, page 1: four panels of a tired janitor in a green-lit closet pressing the intercom button. English captions and balloons.",
      ],
      links: ["Read the risograph page at full size", "Read the gouache page at full size", "Read the oil-painted page at full size"],
      note: "Showcase projects · Site-30’s Janitor by JanitorCakeworth, SCP Wiki, CC BY-SA 3.0; these adaptations are shared under the same license · English text. Not customer work; results vary.",
    },
    sampleBook: {
      kicker: "From the sample shelf",
      title: "Read the story. Then read the book it became.",
      body: "Kaitlin Out of Space by Krishan Coupland is one of the sample stories on this shelf. Its showcase edition runs 59 pages in a 1960s space-age look, with lettering that stays editable.",
      readStory: "Read the original story",
      captions: ["Page 1", "Page 11", "Page 41"],
      alts: [
        "Kaitlin Out of Space, page 1: an older woman finds a small figure in a scorched spacesuit lying in a circle of burned grass in her garden. English narration.",
        "Kaitlin Out of Space, page 11: in the garden, the woman mimes taking off gloves; the young visitor copies her, and their hands meet on the table. English dialogue and narration.",
        "Kaitlin Out of Space, page 41: the woman kneels on the lawn and reaches toward the kneeling astronaut, then sees her blue eyes up close. English narration.",
      ],
      note: "Showcase project · Kaitlin Out of Space by Krishan Coupland (CC0) · English text. Not customer work; results vary.",
    },
    direction: {
      title: "The tool takes the workload. You keep the creative decisions.",
      body: "Scenewright is built as an instrument for an author—not a slot machine that replaces one.",
      youLabel: "You direct",
      youItems: ["The story and source text", "The look and cast", "What gets corrected", "The final issue decisions"],
      toolLabel: "Scenewright drafts",
      toolItems: ["The story bible and brief", "The adaptation and page plan", "Complete comic pages", "PDF and CBZ exports"],
      disclosure: "Scenewright uses third-party generative models to assist with adaptation and illustration. Your manuscript stays yours, and we claim no ownership over generated output. Purely generated imagery may have limited copyright protection.",
      termsLink: "Read the full rights and copyright terms",
    },
    trust: {
      title: "Pay for the production, not another subscription.",
      body: "Buy credits when you are ready. Every paid step shows an estimate before it runs.",
      items: ["No subscription", "Credits never expire", "Packs start at US$12", "Estimate before paid steps"],
      cta: "Create your studio",
      note: "Credits cover production, not a fixed number of pages. Length, quality and revisions affect the total.",
    },
    faq: {
      title: "Before your first scene.",
      body: "The practical answers, without the fine-print fog.",
      items: [
        {
          question: "What should I start with?",
          answer: "Start with a short excerpt saved as its own EPUB, PDF or TXT file, or use a sample story in the studio. Full manuscripts are supported, but a smaller first project helps you assess the result and credit use before expanding.",
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
          answer: "There is no subscription. Credit packs start at US$12, credits never expire, and Scenewright estimates each paid step before it runs. Total use depends on length, quality and revisions.",
        },
      ],
    },
    final: {
      title: "Give your readers a scene to step into.",
      body: "Bring one short excerpt, or explore a sample story. Find your visual direction before committing to a longer adaptation.",
      cta: "Create my first scene",
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
      continuity: "Lee una escena",
      rights: "Tus derechos",
      faq: "Preguntas",
      signIn: "Iniciar sesión",
      cta: "Empieza poco a poco",
      language: "Idioma",
      skip: "Saltar al contenido",
      home: "Inicio de Scenewright",
      navigation: "Navegación principal",
    },
    hero: {
      label: "Un estudio de cómic con IA para autores independientes",
      title: "Tu historia. Su primera escena de cómic.",
      body: "Dale a tus lectores otra forma de entrar en tu mundo. Empieza con un fragmento breve, dirige el estilo y el reparto, y revisa y exporta tu cómic en PDF o CBZ. Amplía cuando el resultado refleje tu historia.",
      primaryCta: "Crear mi primera escena",
      secondaryCta: "Lee una muestra de desarrollo",
      formats: "Adaptación visual asistida por IA · EPUB, PDF o TXT de entrada · PDF o CBZ de salida",
      manuscriptLabel: "El manuscrito",
      chapterLabel: "TU FRAGMENTO",
      loopTag: "Una escena · muchos estilos",
      loopCaption: "Pruebas de estilo reales de una escena de Dungeon Crawler Carl · proyecto de muestra",
      loopAlt: "Vídeo en bucle: una página de cómic de Dungeon Crawler Carl redibujada en una serie de estilos, de la pintura al óleo a la plastilina, el plano técnico, la vidriera y el punto de cruz.",
      pauseLoop: "Pausar",
      playLoop: "Reproducir",
    },
    premise: {
      title: "Empieza con una escena que merezca verse.",
      body: "Elige un fragmento breve con un lugar claro, pocos personajes y un giro narrativo. Súbelo como archivo EPUB, PDF o TXT independiente, o prueba un cuento de muestra en el estudio.",
    },
    process: {
      title: "Tú diriges. El estudio se encarga de producir.",
      body: "Aprueba el enfoque narrativo, el estilo y el reparto. La adaptación y el plan de páginas avanzan entre tus revisiones creativas.",
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
          title: "Descríbelo, muéstralo o pide seis",
          body: "Escribe el estilo que imaginas, sube una imagen que te encante o deja que Scenewright te proponga seis direcciones pensadas para tu historia. Prueba todas las que quieras y aprueba el arte de referencia del reparto y de los lugares recurrentes.",
        },
        {
          number: "03",
          label: "Páginas",
          title: "Revisa las páginas",
          body: "La adaptación y el plan de páginas avanzan en segundo plano. Revisa páginas completas y corrige solo lo que falla.",
        },
        {
          number: "04",
          label: "Libro",
          title: "Termina la edición",
          body: "Revisa el arte y los textos, resuelve las correcciones necesarias y exporta en PDF o CBZ. Los controles automáticos no garantizan la calidad visual.",
        },
      ],
    },
    continuity: {
      title: "Historias diferentes. Mundos distintos.",
      body: "Explora la fantasía en pixel art de Dungeon Crawler Carl y el horror cósmico pictórico de La llamada de Cthulhu. Abre cualquiera de las páginas para leer los textos a tamaño completo.",
      promise: "De dos proyectos de muestra",
      sample: "Proyectos de muestra · Dungeon Crawler Carl, página 25 · La llamada de Cthulhu, página 21 · Texto en inglés. No es trabajo de un cliente; los resultados varían.",
      captions: ["Dungeon Crawler Carl · Página 25", "La llamada de Cthulhu · Página 21", ""],
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
      alts: ["Página 25 del cómic Dungeon Crawler Carl: Carl y un gato ante el gremio tutorial, con avisos de logros en una mazmorra de pixel art iluminada por antorchas. Textos en inglés.", "Página 21 del cómic La llamada de Cthulhu: Castro describe a los Grandes Antiguos, con escenas de ruinas antiguas, R’lyeh y el espacio cósmico. Narración en inglés.", ""],
      inspectTitle: "Una historia que puedes leer.",
      inspectBody: "Las viñetas, la narración y los diálogos llegan juntos. Estas páginas muestran el flujo de desarrollo actual, incluidas sus imperfecciones. Tú revisas la historia, el arte y los textos antes de decidir qué conservar o corregir.",
      inspectLinks: ["Leer la página 25 a tamaño completo", "Leer la página 21 a tamaño completo", ""],
    },
    editions: {
      promise: "Una historia, tres ediciones",
      title: "Una historia, tres libros.",
      body: "Tres ediciones de Site-30’s Janitor se adaptaron del mismo texto y todas abren con la misma frase. Cada una encontró su propio estilo, su propio ritmo y sus propios textos.",
      captions: ["Fanzine risográfico · Página 1", "Noir en gouache · Página 1 · textos editables", "Noir al óleo · Página 1"],
      alts: [
        "Site-30’s Janitor, edición risográfica, página 1: una sola viñeta a página completa con un conserje de caricatura adormilado entre fregonas y cubos naranjas bajo una bombilla desnuda. Textos en inglés.",
        "Site-30’s Janitor, edición en gouache, página 1: cuatro viñetas de un conserje cansado en un cuarto de limpieza oscuro que responde a un interfono que chisporrotea. Textos y bocadillos en inglés.",
        "Site-30’s Janitor, edición al óleo, página 1: cuatro viñetas de un conserje agotado en un cuarto con luz verdosa que pulsa el botón del interfono. Textos y bocadillos en inglés.",
      ],
      links: ["Leer la página risográfica a tamaño completo", "Leer la página en gouache a tamaño completo", "Leer la página al óleo a tamaño completo"],
      note: "Proyectos de muestra · Site-30’s Janitor, de JanitorCakeworth, SCP Wiki, CC BY-SA 3.0; estas adaptaciones se comparten con la misma licencia · Texto en inglés. No es trabajo de un cliente; los resultados varían.",
    },
    sampleBook: {
      kicker: "De la estantería de muestras",
      title: "Lee el cuento. Después, lee el libro en que se convirtió.",
      body: "Kaitlin Out of Space, de Krishan Coupland, es uno de los cuentos de muestra de esta estantería. Su edición de muestra ocupa 59 páginas con una estética espacial de los años sesenta y textos que siguen siendo editables.",
      readStory: "Leer el cuento original",
      captions: ["Página 1", "Página 11", "Página 41"],
      alts: [
        "Kaitlin Out of Space, página 1: una mujer mayor encuentra una pequeña figura con un traje espacial chamuscado tendida en un círculo de hierba quemada de su jardín. Narración en inglés.",
        "Kaitlin Out of Space, página 11: en el jardín, la mujer finge quitarse unos guantes; la joven visitante la imita y sus manos se encuentran sobre la mesa. Diálogo y narración en inglés.",
        "Kaitlin Out of Space, página 41: la mujer, arrodillada en el césped, tiende la mano hacia la astronauta y ve de cerca sus ojos azules. Narración en inglés.",
      ],
      note: "Proyecto de muestra · Kaitlin Out of Space, de Krishan Coupland (CC0) · Texto en inglés. No es trabajo de un cliente; los resultados varían.",
    },
    direction: {
      title: "La herramienta asume la carga. Tú conservas las decisiones creativas.",
      body: "Scenewright está hecho como instrumento para el autor, no como una máquina que lo sustituye.",
      youLabel: "Tú diriges",
      youItems: ["La historia y el texto original", "El estilo y el reparto", "Qué se corrige", "Las decisiones finales sobre incidencias"],
      toolLabel: "Scenewright prepara",
      toolItems: ["La biblia y el enfoque", "La adaptación y el plan de páginas", "Páginas completas de cómic", "Exportaciones PDF y CBZ"],
      disclosure: "Scenewright usa modelos generativos de terceros para ayudar con la adaptación y la ilustración. Tu manuscrito sigue siendo tuyo y no reclamamos propiedad sobre el resultado generado. Las imágenes puramente generadas pueden tener protección de autor limitada.",
      termsLink: "Lee todos los términos sobre derechos y autoría",
    },
    trust: {
      title: "Paga por la producción, no por otra suscripción.",
      body: "Compra créditos cuando estés listo. Cada paso de pago muestra una estimación antes de ejecutarse.",
      items: ["Sin suscripción", "Los créditos no vencen", "Paquetes desde 12 USD", "Estimación antes de pagar"],
      cta: "Crea tu estudio",
      note: "Los créditos cubren la producción, no un número fijo de páginas. La extensión, la calidad y las revisiones afectan al total.",
    },
    faq: {
      title: "Antes de tu primera escena.",
      body: "Respuestas prácticas, sin niebla de letra pequeña.",
      items: [
        {
          question: "¿Con qué debería empezar?",
          answer: "Empieza con un fragmento breve guardado como archivo EPUB, PDF o TXT independiente, o usa un cuento de muestra del estudio. También se admiten manuscritos completos, pero un primer proyecto pequeño te ayuda a evaluar el resultado y el consumo de créditos antes de ampliar.",
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
      title: "Invita a tus lectores a entrar en una escena.",
      body: "Trae un fragmento breve o explora un cuento de muestra. Encuentra tu dirección visual antes de comprometerte con una adaptación más larga.",
      cta: "Crear mi primera escena",
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
      continuity: "Lire une scène",
      rights: "Vos droits",
      faq: "Questions",
      signIn: "Se connecter",
      cta: "Commencer petit",
      language: "Langue",
      skip: "Aller au contenu",
      home: "Accueil Scenewright",
      navigation: "Navigation principale",
    },
    hero: {
      label: "Un studio de BD avec IA pour les auteurs indépendants",
      title: "Votre récit. Sa première scène de BD.",
      body: "Offrez à vos lecteurs une nouvelle entrée dans votre univers. Partez d’un court extrait, dirigez le style et les personnages, puis révisez et exportez votre BD en PDF ou CBZ. Développez-la quand le résultat reflète votre récit.",
      primaryCta: "Créer ma première scène",
      secondaryCta: "Lire un exemple de développement",
      formats: "Adaptation visuelle assistée par IA · EPUB, PDF ou TXT en entrée · PDF ou CBZ en sortie",
      manuscriptLabel: "Le manuscrit",
      chapterLabel: "VOTRE EXTRAIT",
      loopTag: "Une scène · de multiples styles",
      loopCaption: "Vraies épreuves de style d’une scène de Dungeon Crawler Carl · projet de démonstration",
      loopAlt: "Vidéo en boucle : une page de BD de Dungeon Crawler Carl redessinée dans une série de styles, de la peinture à l’huile à la pâte à modeler, au plan d’architecte, au vitrail et au point de croix.",
      pauseLoop: "Pause",
      playLoop: "Lecture",
    },
    premise: {
      title: "Commencez par une scène qui mérite d’être vue.",
      body: "Choisissez un court extrait avec un lieu précis, peu de personnages et un tournant narratif. Importez-le dans un fichier EPUB, PDF ou TXT distinct, ou essayez un récit exemple dans le studio.",
    },
    process: {
      title: "Vous dirigez. Le studio assure la production.",
      body: "Approuvez le brief narratif, le style et les personnages. L’adaptation et le plan des pages avancent entre vos validations créatives.",
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
          title: "Décrivez-le, montrez-le ou demandez-en six",
          body: "Décrivez le style que vous imaginez, importez une image que vous aimez ou laissez Scenewright vous proposer six directions pensées pour votre récit. Essayez-en autant que vous voulez, puis approuvez les références des personnages et des lieux récurrents.",
        },
        {
          number: "03",
          label: "Pages",
          title: "Révisez les pages",
          body: "L’adaptation et le plan des pages avancent en arrière-plan. Révisez les pages complètes et corrigez seulement ce qui manque.",
        },
        {
          number: "04",
          label: "Livre",
          title: "Finalisez l’édition",
          body: "Vérifiez les images et les textes, résolvez les corrections nécessaires, puis exportez en PDF ou CBZ. Les contrôles automatiques ne garantissent pas la qualité visuelle.",
        },
      ],
    },
    continuity: {
      title: "Des histoires différentes. Des mondes distincts.",
      body: "Explorez la fantasy en pixel art de Dungeon Crawler Carl et l’horreur cosmique picturale de L’Appel de Cthulhu. Ouvrez chaque page pour lire les textes en taille réelle.",
      promise: "Issu de deux projets de démonstration",
      sample: "Projets de démonstration · Dungeon Crawler Carl, page 25 · L’Appel de Cthulhu, page 21 · Textes en anglais. Pas un projet client ; les résultats varient.",
      captions: ["Dungeon Crawler Carl · Page 25", "L’Appel de Cthulhu · Page 21", ""],
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
      alts: ["Page 25 de la BD Dungeon Crawler Carl : Carl et un chat devant la guilde du tutoriel, avec des notifications de succès dans un donjon en pixel art éclairé aux torches. Textes en anglais.", "Page 21 de la BD L’Appel de Cthulhu : Castro décrit les Grands Anciens, avec des scènes de ruines anciennes, de R’lyeh et de l’espace cosmique. Narration en anglais.", ""],
      inspectTitle: "Un récit que vous pouvez lire.",
      inspectBody: "Les cases, la narration et les dialogues arrivent ensemble. Ces pages montrent le flux de développement actuel, avec ses imperfections. Vous vérifiez le récit, les images et les textes avant de décider quoi conserver ou corriger.",
      inspectLinks: ["Lire la page 25 en taille réelle", "Lire la page 21 en taille réelle", ""],
    },
    editions: {
      promise: "Un récit, trois éditions",
      title: "Un récit, trois livres.",
      body: "Trois éditions de Site-30’s Janitor ont été adaptées du même texte, et chacune s’ouvre sur la même phrase. Chacune a trouvé son propre style, son propre rythme et son propre lettrage.",
      captions: ["Fanzine en risographie · Page 1", "Noir à la gouache · Page 1 · lettrage modifiable", "Noir à l’huile · Page 1"],
      alts: [
        "Site-30’s Janitor, édition risographie, page 1 : une seule case pleine page où un concierge de dessin animé somnole parmi des balais et des seaux orange, sous une ampoule nue. Textes en anglais.",
        "Site-30’s Janitor, édition gouache, page 1 : quatre cases où un concierge épuisé, dans un placard sombre, répond à un interphone qui grésille. Récitatifs et bulles en anglais.",
        "Site-30’s Janitor, édition à l’huile, page 1 : quatre cases où un concierge fatigué, dans un placard baigné de lumière verte, appuie sur le bouton de l’interphone. Récitatifs et bulles en anglais.",
      ],
      links: ["Lire la page en risographie en taille réelle", "Lire la page à la gouache en taille réelle", "Lire la page à l’huile en taille réelle"],
      note: "Projets de démonstration · Site-30’s Janitor, de JanitorCakeworth, SCP Wiki, CC BY-SA 3.0 ; ces adaptations sont partagées sous la même licence · Textes en anglais. Pas un projet client ; les résultats varient.",
    },
    sampleBook: {
      kicker: "Depuis l’étagère d’exemples",
      title: "Lisez la nouvelle. Puis lisez le livre qu’elle est devenue.",
      body: "Kaitlin Out of Space, de Krishan Coupland, fait partie des nouvelles de cette étagère. Son édition de démonstration compte 59 pages dans un style spatial des années 1960, avec un lettrage qui reste modifiable.",
      readStory: "Lire la nouvelle originale",
      captions: ["Page 1", "Page 11", "Page 41"],
      alts: [
        "Kaitlin Out of Space, page 1 : une femme âgée découvre une petite silhouette en combinaison spatiale calcinée, étendue dans un cercle d’herbe brûlée de son jardin. Narration en anglais.",
        "Kaitlin Out of Space, page 11 : dans le jardin, la femme mime le geste d’ôter des gants ; la jeune visiteuse l’imite et leurs mains se rejoignent sur la table. Dialogue et narration en anglais.",
        "Kaitlin Out of Space, page 41 : agenouillée sur la pelouse, la femme tend la main vers l’astronaute et découvre de près ses yeux bleus. Narration en anglais.",
      ],
      note: "Projet de démonstration · Kaitlin Out of Space, de Krishan Coupland (CC0) · Textes en anglais. Pas un projet client ; les résultats varient.",
    },
    direction: {
      title: "L’outil prend en charge le travail. Vous gardez les choix créatifs.",
      body: "Scenewright est conçu comme l’instrument d’un auteur, pas comme une machine qui le remplace.",
      youLabel: "Vous dirigez",
      youItems: ["Le récit et le texte source", "Le style et les personnages", "Ce qui doit être corrigé", "Les décisions finales sur les problèmes"],
      toolLabel: "Scenewright prépare",
      toolItems: ["La bible narrative et le brief", "L’adaptation et le plan des pages", "Les pages complètes de la BD", "Les exports PDF et CBZ"],
      disclosure: "Scenewright utilise des modèles génératifs tiers pour aider à l’adaptation et à l’illustration. Votre manuscrit reste à vous et nous ne revendiquons aucun droit de propriété sur les sorties générées. Une image purement générée peut bénéficier d’une protection limitée.",
      termsLink: "Lire les conditions complètes sur les droits et le copyright",
    },
    trust: {
      title: "Payez la production, pas un abonnement de plus.",
      body: "Achetez des crédits quand vous êtes prêt. Chaque étape payante affiche une estimation avant de démarrer.",
      items: ["Sans abonnement", "Les crédits n’expirent jamais", "Packs dès 12 $ US", "Estimation avant paiement"],
      cta: "Créer votre studio",
      note: "Les crédits couvrent la production, pas un nombre fixe de pages. La longueur, la qualité et les révisions influencent le total.",
    },
    faq: {
      title: "Avant votre première scène.",
      body: "Les réponses pratiques, sans brouillard juridique.",
      items: [
        {
          question: "Par quoi commencer ?",
          answer: "Commencez par un court extrait enregistré dans un fichier EPUB, PDF ou TXT distinct, ou utilisez un récit exemple du studio. Les manuscrits complets sont aussi acceptés, mais un premier projet court permet d’évaluer le résultat et la consommation de crédits avant de poursuivre.",
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
      title: "Invitez vos lecteurs à entrer dans une scène.",
      body: "Apportez un court extrait ou explorez un récit exemple. Trouvez votre direction visuelle avant de vous engager dans une adaptation plus longue.",
      cta: "Créer ma première scène",
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
