---
kind: post
channel: landing
title: Make the homepage process intro match how the product works
target: https://scenewright.ink/
facts:
  - step-story
  - step-look
  - step-cast
  - step-pages
sources:
  - https://scenewright.ink/
created: 2026-10-27
status: approved
approval:
  hash: 23d077b3437b6159d8bc240df69101481e74178a4253f26d1b38688f07ba56be
  at: 2026-10-28T03:43:33.980Z
---

Manual port only. No canary files changed.

Destination: `web/src/locales/en.json`, exact key `landing.process.body`. Consumer: `LandingCopy.process.body` in `web/src/pages/landingCopy.ts`.

Old: Five stations. Scenewright does the drafting between them, and nothing moves on until you approve it.

Proposed: Scenewright maps your story and draws lettered pages. You approve the brief, choose the look and the cast, and ask for changes in plain words.

Facts: `step-story`, `step-look`, `step-cast`, `step-pages` in `knowledge/facts.yaml`.

Reason: the live homepage (fetched 2026-10-27) promises five stations and that nothing moves without approval. The product has four stations, and the adaptation and page plan run on their own. A new author who sees work start without a click may feel the page misled them. The proposed line names only what the author really decides. This is a correction, not a measured lift.

Matching locale keys, proposed for native review before porting:

- `web/src/locales/es.json`, `landing.process.body`. Old: Cinco estaciones. Scenewright hace los borradores entre ellas, y nada avanza hasta que tú lo apruebas. Proposed: Scenewright identifica tu historia y dibuja páginas rotuladas. Tú apruebas el brief, eliges el estilo y el reparto, y pides cambios con tus propias palabras.
- `web/src/locales/fr.json`, `landing.process.body`. Old: Cinq étapes. Scenewright prépare les ébauches entre elles, et rien n’avance tant que vous ne l’avez pas approuvé. Proposed: Scenewright repère votre histoire et dessine des pages lettrées. Vous approuvez le brief, choisissez le style et les personnages, et demandez des changements avec vos mots.

Human follow-up: the step list still shows a "You approve" badge on the Pages step, but pages are accepted unless the author flags one. Decide in canary whether that badge should read differently. It is set by `approve: index < 4` in `web/src/pages/landingCopy.ts`, not by this key. After porting, run canary's i18n and web build checks.
