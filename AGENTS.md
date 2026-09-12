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

## Autonomous Development Workflow

- 原則として、1フェーズ単位で自律的に
  調査 → 実装 → テスト → 原因分析 → 修正 → 再テスト
  まで進める。
- 通常のローカル開発作業では、途中確認を求めない。
- 複数の妥当な実装方法がある場合は、以下の優先順位で自分で判断する。
  1. 最小変更
  2. 既存挙動維持
  3. 低リスク
  4. 保守性
- 承認済みのフェーズ内では、可逆なローカル操作を自律実行してよい。

### Local operations that do not require confirmation

- repository内のファイル読取・編集
- /tmp 配下の一時ファイル作成・編集
- Python実行
- unittest / pytest
- py_compile
- Playwright / headless browserによるローカル検証
- screenshot比較
- git status
- git diff
- git diff --check
- git add
- 明示的にcommitまで許可されたフェーズでのgit commit
- ローカルサーバー起動
- 静的解析
- ローカルの依存関係確認

これらについては「実行してよいですか？」と途中確認しない。

### Human approval required

以下は必ず人間の明示承認を得てから実行する。

- git push
- deploy
- production環境への変更
- productionデータ変更
- 外部公開
- 本番設定変更
- アカウント作成
- 権限変更
- 費用発生
- 外部サービスへの書込み
- 法的・安全上重要な判断
- 大規模な仕様変更
- destructive operation

### Execution behavior

- 途中経過を逐次質問しない。
- 問題が起きた場合は、まず自分で原因を分析して解決を試みる。
- 安全な範囲で複数回の修正・再検証を自律的に行う。
- 完了時に、
  - 変更内容
  - テスト結果
  - 残存リスク
  - git status
  をまとめて報告する。
- commit / push / deploy の境界は必ず守る。

## Model Usage Policy

- 通常の開発作業は GPT-5.6 Luna を優先する。
- GPT-6 Astra は以下の場合だけ使用を推奨する。
  - 複雑なアーキテクチャ変更
  - 原因不明の重大バグ
  - 広範囲なリファクタ
  - 高度なセキュリティ判断
  - 難しい複数設計案の比較
- Astraが不要な作業ではLunaを使い、利用枠を節約する。
