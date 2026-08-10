# Inputs Needed From You

Every input the build needs from a human, when it is needed, and step-by-step
instructions for getting each one. Nothing here is blocking today — Sprints 0
and 1 are complete and Sprints 2 through 5 run against recorded fixtures.

**Security rule that applies to every item below:** never paste a real secret
into this file, into a chat message, into a commit, or into `.env.example`. Put
real values in `.env` only (git-ignored). When something below asks for a
secret, the answer I need is usually the *decision* or the *reference*, not the
secret itself. Where I genuinely need a value in `.env`, the instruction says
"put it in `.env` yourself" — you do that step, not me.

Legend for **Needed by**: the sprint that stops without it.

| # | Input | Needed by | Type |
|---|---|---|---|
| 1 | Amazon listing source & auth mechanism | Sprint 2 (soft), Sprint 4 (hard) | Decision + credential |
| 2 | Flipkart / Myntra / Nykaa listing sources | Sprint 4 | Decision + credential |
| 3 | Telegram bot token | Sprint 6 | Secret |
| 4 | Your Telegram chat ID | Sprint 6 | Value |
| 5 | Secrets-manager product | Sprint 8 | Decision |
| 6 | Marketplace shopping accounts | Sprint 8 | Secret + policy |
| 7 | Per-account daily spend cap | Sprint 8 | Value |
| 8 | Purchase automation approach | Sprint 10 | Decision |
| 9 | Deal scoring weights | Sprint 3 | Value (defaults exist) |
| 10 | Admin Dashboard frontend framework | Sprint 14 | Decision |
| 11 | Deployment target & CI secrets | Sprint 16 | Decision |
| 12 | Monitoring / logging stack | Sprint 16 | Decision |

---

## 1. Amazon listing source & auth mechanism

**Why:** `SERVICE_INTERFACES.md` §1 defines what a connector returns, but no
frozen contract says *how* a connector reads a marketplace. Sprint 2 builds
against recorded fixtures, so it does not block — but the fixtures have to
resemble something real, and Sprint 4 needs the live path.

**What I need:** one of these three answers.

- **(a) Official API.** Amazon Product Advertising API (PA-API 5.0), or Amazon
  SP-API if you sell on Amazon.
- **(b) Third-party data provider.** e.g. Rainforest API, Oxylabs, ScraperAPI,
  Bright Data — you pick, I integrate.
- **(c) Direct HTML fetch.** Fastest to start, but brittle and subject to
  Amazon's Conditions of Use. If you choose this, say so explicitly and confirm
  you accept that; I will build it but I want the decision on the record.

**How to get (a):**
1. Go to <https://affiliate-program.amazon.in/> and sign up for Amazon
   Associates (PA-API requires an Associates account).
2. Get approved. Amazon requires **3 qualifying sales within 180 days** before
   PA-API access is granted — this is the slow step, start it early if you want
   this route.
3. Once approved, go to <https://affiliate-program.amazon.in/assoc_credentials/home>
   and create credentials. You get an **Access Key**, a **Secret Key**, and your
   **Partner Tag** (looks like `yourname-21`).
4. Put them in `.env` yourself:
   ```
   AMAZON_ACCESS_KEY=...
   AMAZON_SECRET_KEY=...
   AMAZON_PARTNER_TAG=yourname-21
   ```
5. Tell me only: "PA-API, keys are in .env". I will read the names, never the
   values.

**How to get (b):**
1. Pick a provider and sign up.
2. Copy the API key from their dashboard into `.env` as `AMAZON_API_KEY`.
3. Send me the provider name and a link to their response-format docs. I need
   the response shape to write `normalize()`; I do not need the key.

**How to help with (c):** save 5 or more real Amazon product pages as HTML
(browser: File → Save Page As → "Webpage, HTML Only") into
`services/marketplace-connector/tests/fixtures/amazon/`. Pick a mix: one in
stock, one out of stock, one with no MRP shown, one with no ratings, one with
size/colour variants. These become the Sprint 2 fixtures either way — they are
useful under all three options.

---

## 2. Flipkart / Myntra / Nykaa listing sources

**Why:** Sprint 4 builds the other three connectors. `ENUMS.md` fixes the four
marketplaces; nothing fixes how to read them.

**What I need:** the same (a)/(b)/(c) choice as item 1, per marketplace. They do
not have to match — Flipkart via a provider and Nykaa via HTML is fine.

**Notes on each:**
- **Flipkart** has an affiliate API but it has been closed to new signups for
  years. Assume (b) or (c) unless you already hold credentials.
- **Myntra** and **Nykaa** have no public product API at all. (b) or (c).

**How to help regardless of choice:** same fixture-saving exercise as item 1(c),
into `tests/fixtures/flipkart/`, `.../myntra/`, `.../nykaa/`. 5+ pages each.

---

## 3. Telegram bot token

**Why:** Sprint 6 is the Telegram Bot. Nothing in it can run without a token.

**Steps:**
1. Open Telegram, search for **@BotFather**, start a chat.
2. Send `/newbot`.
3. Give it a display name (anything, e.g. "Deal Watch").
4. Give it a username — must be unique and end in `bot`, e.g.
   `chirag_dealwatch_bot`.
5. BotFather replies with a token shaped like
   `1234567890:AAF...` (about 46 characters).
6. Put it in `.env` yourself:
   ```
   TELEGRAM_BOT_TOKEN=<paste here>
   ```
7. Tell me only: "bot token is in .env, bot username is @...". **Do not paste
   the token to me.** Anyone holding it controls the bot.

If a token ever leaks: BotFather → `/revoke` → pick the bot. Old token dies
immediately.

---

## 4. Your Telegram chat ID

**Why:** `telegram_users.telegram_chat_id` (`DATABASE_SCHEMA.md` §7). Deal
notifications go to a chat ID, and you need at least one seeded so Sprint 6 has
somewhere to send.

**Steps:**
1. In Telegram, search for **@userinfobot** and press Start.
2. It replies with your numeric ID, e.g. `123456789`.
3. Send me that number. It is not a secret — it is just an address.

---

## 5. Secrets-manager product

**Why:** `accounts.credentials_ref` (`DATABASE_SCHEMA.md` §9) stores a
*reference* to marketplace login credentials, never the credentials. Something
has to resolve that reference. `ZIP_10_INFRASTRUCTURE/SECRETS.md` is an empty
stub and the roadmap logs this as a known gap (§7 item 2).

**What I need:** pick one.

- **`env`** — credentials live in environment variables, `credentials_ref` is
  the variable name. Zero setup, fine for local and single-host. This is the
  current `.env.example` default.
- **AWS Secrets Manager / GCP Secret Manager / Azure Key Vault** — pick if you
  are already on that cloud.
- **HashiCorp Vault** — most capable, most setup.
- **1Password / Doppler / Infisical** — good middle ground, hosted, cheap.

**How to decide:** if you do not have a strong reason, say `env` now and revisit
at Sprint 16. The code reads `SECRETS_MANAGER_PROVIDER` and the resolver is
swappable by design, so this is not a one-way door.

**What to send me:** just the word. e.g. "use env for now".

---

## 6. Marketplace shopping accounts

**Why:** Sprint 8 is the Account Service. `accounts` rows are the pool the Order
Planner allocates purchases across.

**What I need:**
1. **How many accounts per marketplace** you intend to use. One is enough to
   build against; the allocation logic only gets interesting at two or more.
2. For each: a **label** (`accounts.label`) — an internal alias like
   `amazon-primary`. This is what appears in logs. The login email must never
   appear in logs, which is exactly why this column exists.
3. The **credentials reference**, whose shape depends on item 5. With `env`, it
   is a variable name like `AMAZON_ACCT_01`.

**Steps:**
1. Decide the labels and send me the list, e.g.:
   ```
   AMAZON: amazon-primary, amazon-secondary
   FLIPKART: flipkart-primary
   ```
2. Put the actual logins in `.env` yourself, one pair per account:
   ```
   AMAZON_ACCT_01_EMAIL=...
   AMAZON_ACCT_01_PASSWORD=...
   ```
3. Tell me the variable names, never the values.

**Please also confirm:** these accounts are yours, and you accept that automated
purchasing may violate the marketplace's terms of service and can get an account
restricted. The schema already models `SUSPENDED`/`BANNED` states, so the design
anticipates it — but the decision to run it is yours, and I want it stated once,
explicitly, before Sprint 8.

---

## 7. Per-account daily spend cap

**Why:** `accounts.daily_spend_cap` is `NOT NULL` — every account row needs one,
and there is no default in the schema.

**What I need:** a rupee amount per account. I store paise, so ₹10,000 becomes
`1000000`; you can just tell me "₹10,000" and I will convert.

**How to decide:** the cap is a blast-radius limit, not a budget. Set it to the
most you would tolerate losing to a bug in a single day. A number you find
slightly too low is the right number.

Also tell me if the daily reset boundary should stay `Asia/Kolkata`
(`DAILY_SPEND_RESET_TZ` in `.env.example`).

---

## 8. Purchase automation approach

**Why:** Sprint 10 is the Purchase Agent — the component that actually buys.
`SERVICE_INTERFACES.md` §7 fixes `execute(purchase_task) -> PurchaseOutcome` but
says nothing about the mechanism.

**What I need:** one of:

- **Browser automation** (Playwright or Selenium) driving a logged-in session.
  This is what the ZIP_08 documents assume. Needs real logins (item 6) and real
  session persistence.
- **Manual approval loop** — the agent prepares the cart and the bot pings you
  to press "buy" yourself. Slower, but no credential automation and no ToS
  exposure.
- **Dry-run only** — the agent logs what it would have bought and emits
  `PURCHASE_COMPLETED` with a synthetic reference. Useful to prove the whole
  pipeline end to end before any money moves.

**My recommendation:** build dry-run first regardless of the eventual answer. It
exercises every downstream consumer — Order Planner, Inventory Service, Account
Service — with zero risk, and it is the same interface. Tell me which of the
other two it should graduate into.

---

## 9. Deal scoring weights

**Why:** `ScoreBreakdown.weights_version` (`CANONICAL_MODELS.md`) exists because
the weights are configuration, and the score is stored verbatim with the version
that produced it. Sprint 3 needs a starting set.

**What I need:** how much each factor is worth, out of 100:

| Factor | Meaning | Suggested |
|---|---|---|
| `discount_score` | how far below reference price | 40 |
| `brand_score` | `brands.tier` — PREMIUM / STANDARD / UNBRANDED | 25 |
| `rating_score` | listing rating and review count | 20 |
| `velocity_score` | how fast the price dropped, from `price_history` | 15 |

Also: **the minimum score that triggers a notification.** Suggested: 70.

You can just say "use the suggested values" — they are checked into config as
`v1` and changing them later is a new `weights_version`, not a migration.

---

## 10. Admin Dashboard frontend framework

**Why:** `API_CONTRACTS.md` defines the full REST surface the Dashboard
consumes, but no document names a frontend framework. Logged in the roadmap as
known gap §7 item 1, to be decided at Sprint 14 Task 14.1.

**What I need:** React, Vue, Svelte, or plain server-rendered HTML.

**How to decide:** whichever you can read. This is an internal single-operator
dashboard, so ecosystem size does not matter much. If you have no preference,
say so and I will use React with Vite — the least surprising choice for anyone
who later looks at the repo.

---

## 11. Deployment target & CI secrets

**Why:** Sprint 16 hardens and releases. `ZIP_10_INFRASTRUCTURE` is entirely
empty stubs, so cloud, hosting, and backup strategy are all undecided (roadmap
§7 item 2).

**What I need:**
1. **Where it runs:** your own VPS (Hetzner/DigitalOcean/Linode), a managed
   container platform (Fly.io, Railway, Render), or a full cloud (AWS/GCP).
2. **Whether CI should deploy** or just build and test. Today it lints and
   tests only.
3. If CI deploys: add the deploy credential as a **GitHub Actions secret**, not
   as a file:
   - GitHub → your repo → Settings → Secrets and variables → Actions
   - "New repository secret", name it, paste the value there
   - Tell me only the secret's *name*; the workflow references it as
     `${{ secrets.NAME }}`.

**How to decide (1):** a single VPS running `docker compose` is the honest match
for this system's size, and it is what the compose file already describes.
Anything more is worth doing only if you already know why you want it.

---

## 12. Monitoring / logging stack

**Why:** Sprint 16 Tasks 16.4-16.6. `MONITORING.md` and `LOGGING.md` are empty
stubs.

**What I need:** either "stdout logs only, no monitoring" — which is a
legitimate answer for a single-operator system — or a product name (Grafana
Cloud, Better Stack, Axiom, Sentry for errors).

**How to decide:** if you will not look at a dashboard, do not run one. Sentry
alone, for errors, is the highest value-per-effort option and has a usable free
tier: sign up at <https://sentry.io>, create a Python project, copy the **DSN**
it shows you into `.env` as `SENTRY_DSN`. A DSN is low-sensitivity but still
belongs in `.env`, not here.

---

## What I need first, in order

Nothing is blocking right now. When you have a spare hour, the highest-value
items are the ones with lead time or that unblock whole sprints:

1. **Item 1 or the fixtures in 1(c)** — Sprint 2 starts next and real fixtures
   make it real work rather than guesswork. If you want the PA-API route, start
   the Associates signup now; it is the only item here with a multi-week wait.
2. **Item 3 + 4** (Telegram token and chat ID) — five minutes total, and it
   unblocks all of Sprint 6.
3. **Item 9** — one line ("use the suggested values") unblocks Sprint 3.

Everything else can wait until its sprint.
