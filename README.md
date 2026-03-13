# SpinePA Agent — Zero-Retention PA Packet Generator

This build is designed for clinic-side prior authorization preparation without a backend PHI case repository.

## What it does
- Upload clinical notes, imaging reports, and supporting documents
- Generate a patient- and payer-specific PA summary letter
- Generate payer submission instructions and portal copy blocks
- Show approval likelihood, support score, criteria met, and missing items
- Export a ZIP packet locally for clinic submission

## Privacy mode
- No backend case queue is maintained
- `/cases` endpoints are disabled for persistent storage
- Uploaded files are processed transiently to generate the output packet

## Main routes
- `/status`
- `/settings`
- `/knowledge-base`
- `/analyze`
- `/generate-letter`
- `/build-package`
- `/export-package`

## Deploy on Vercel
This project is configured for Vercel Python + static hosting using `vercel.json`.

Optional environment variables:
- `PRACTICE_NAME`
- `PROVIDER_NAME`
- `PROVIDER_NPI`
- `PROVIDER_NPI_<NAME>`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`
