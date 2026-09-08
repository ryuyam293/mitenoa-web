# MITENOA Development Instructions

## Project

MITENOA Web Service

Main application:
- Flask
- main.py
- Google Sheets
- Google Cloud Storage
- Google Cloud Run

## Critical deployment rule

Cloud Run services:

- sorachi-tosou-line
- sorachi-kurashi-line

Solar / MITENOA / shared changes in this work must only be deployed to:

sorachi-tosou-line

NEVER deploy these changes to:

sorachi-kurashi-line

Do not deploy anything without explicit human approval.

## Existing routes

Important routes include:

- /
- /tosou
- /kurashi
- /solar
- /solar/diagnosis
- /solar/result/{token}
- /admin/

Do not break existing tosou or kurashi functionality.

## MITENOA brand

Brand:
MITENOA

Concept:
「決めるのは、見てから。」

Subcopy:
「契約する前に、もう一つの判断材料を。」

Colors:
- Deep navy #0B1D3A
- Sage green #4C7F6B
- Soft gray #C7C9CC
- Warm orange #FF7A00

Font:
Noto Sans JP

MITENOA is a neutral second-opinion / decision-support service.

Do not introduce:
- aggressive sales language
- unsupported claims
- fearmongering
- fee-driven recommendation logic
- unauthorized personal-data sharing

The customer makes the final decision.

## Solar LP

Main route:
/solar

The LP has already undergone substantial visual iteration.

Do not redesign accepted sections from scratch unless there is a clear reason.

Accepted/frozen areas include:

- header
- logo
- hero
- hero background
- hero CTA
- trust strip
- concern cards
- 8 checkpoints
- flow cards
- reasons
- FAQ
- final CTA background
- footer

Recent conversion-story work includes:

- contract-before-check rationale
- customer benefits
- MITENOA purpose
- final CTA loss-aversion messaging

Inspect the current code to determine exactly which changes are actually implemented.
Do not infer version state from comments alone.

## Important assets

Hero:
https://storage.googleapis.com/mitenoa-public-assets-project-adeebf5f-75d4-46a5-bb5/solar/lp/mitenoa-solar-hero-v7.png

Logo:
https://storage.googleapis.com/mitenoa-public-assets-project-adeebf5f-75d4-46a5-bb5/brand/mitenoa-logo-with-tagline-ja2.png

LINE:
https://lin.ee/pEQ2wuC

## Privacy / consent

Do not automatically share customer information with vendors.

Comparison / vendor sharing requires separate customer consent.

Do not expose:
- result tokens
- vendor tokens
- customer PII
- credentials
- secrets

## Working rules

Before editing:

1. inspect relevant code
2. explain current state
3. identify affected routes/functions/templates/CSS
4. identify regression risks
5. make the smallest coherent change

After editing:

1. run python syntax checks
2. run available tests
3. verify /solar
4. verify /solar/diagnosis
5. verify token handling where relevant
6. verify existing tosou routes
7. verify existing kurashi routes when possible
8. review diff

Do not deploy without approval.

## Current objective

Continue development of the MITENOA solar LP.

Priority:

1. customer comprehension
2. conversion to free diagnosis / LINE consultation
3. visual polish
4. responsive behavior
5. maintainability
6. regression safety

The customer should clearly understand:

- what this service is
- why checking before contract matters
- what they gain from using MITENOA
- what MITENOA is
- why the diagnosis is free
- why they should act before signing
- how to ask for help

Avoid unsupported expressions such as:

- 絶対に損する
- 数十万円損する
- 騙される
- guaranteed savings
