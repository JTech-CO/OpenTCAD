# Development

[한국어](../ko/development.md)

## Prerequisites

- Node.js 22 LTS or 24 LTS
- npm 10 or newer
- Python 3.12 through 3.14 for the runtime contract tests
- Git

No container runtime, external database server, or solver is required for the
static app or contract suite. The local service and SQLite stores use the
Python standard library. Native Docker and Podman observations are separate,
non-promoting qualification tasks.

## Setup and commands

```bash
npm install
npm run dev
```

The development server uses Vite. Production checks are:

```bash
npm run check
npm run coverage
```

Use `npm run preview` to serve the production bundle on `127.0.0.1`. The build uses relative asset URLs so a single artifact works under the GitHub repository subpath and on an ordinary local static server.

## M3 local host

After `npm run build`, inspect the product gates and start the non-executing
same-origin host:

```bash
npm run local:doctor
npm run local:preview
```

The preview deliberately does not open a credential store, SQLite database, or
OCI runtime. `npm run local:serve` is the product command; it must exit blocked
with the committed manifest. See [M3 local product service](m3-local-service.md)
for configuration, paths, exit behavior, and the activation order.

## Frontend rules

- Every user-visible string belongs in `frontend/src/i18n.ts` and must exist in both English and Korean.
- User typing state stays a string until explicit validation; do not coerce intermediate numeric input.
- Stable internal IDs are never derived from editable labels.
- Loading, empty, running, complete, partial, skipped, and failed states must remain visually and textually distinct.
- Color is supplementary. Status also needs text, shape, or icon-independent wording.
- Static reference data must be visibly labelled and must not use words such as “validated,” “converged,” or “solver result.”
- Store only device-local preferences, such as locale, in browser storage.

## Changing local-engine work

Do not add a direct `docker`, `podman`, shell, or subprocess call from the
frontend or API. The sandbox broker and activated OCI adapter are the only
components allowed to contact a runtime. Operator configuration must never
select commands, images, entrypoints, mounts, host paths, or environment
values.

An activation or release-profile change requires paired tests for rejection
and success, reviewed evidence hashes, exact image and entrypoint grants,
three-platform native observations, and licensing and numerical review. Test
fixtures may construct release profiles explicitly; production profiles remain
code-owned.

## Documentation parity

English and Korean documents are paired by path:

```text
docs/en/<name>.md
docs/ko/<name>.md
```

A functional or operational documentation change is incomplete until both files describe the same contract. Maintained product documentation is bilingual.
