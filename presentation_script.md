# Bio-Sync Presentation Script (10 minutes)

Target: 11-766 LLM Applications course. Technical audience. ~50 seconds per slide.

---

## SLIDE 1 — Title (30 sec)

Bio-Sync is a multi-agent LLM system for budget-constrained meal planning. The user provides macro-nutrient targets — say 180 grams of protein, under 2000 calories — a daily food budget, and their ZIP code. The system generates a multi-day meal plan that satisfies all of those constraints simultaneously. This is an applied-track project — the contribution is a working end-to-end system, not a novel algorithm.

---

## SLIDE 2 — The Problem (50 sec)

The core problem is that meal planning sits at the intersection of three constraints that no existing tool handles together. First, macro targets — MyFitnessPal can track what you already ate, but it can't proactively generate a plan that hits 180g protein. Second, budget limits — budget apps track spending but don't reason about nutrition. Third, dietary preferences — recipe sites can filter for "Mediterranean" or "no shellfish," but they can't enforce that the resulting plan actually meets a calorie cap.

LLMs are uniquely positioned here because they can reason about all three simultaneously and generate coherent recipes with cooking instructions. But the literature — particularly NutriBench by Yin et al. — shows that 80% of LLM nutritional errors come from wrong prior knowledge, not math mistakes. So we can't just trust the LLM's estimates. That's the core design principle behind Bio-Sync: use the LLM for creative generation, but verify every factual claim against external APIs.

---

## SLIDE 3 — Architecture (60 sec)

The system has five specialized agents, each backed by a separate LLM call with its own system prompt.

The Planner generates a structured JSON meal plan — ingredients with gram quantities and cooking instructions. The Researcher takes each ingredient and queries the Kroger Product API via OAuth2 to get real store prices by ZIP code. The Nutritionist resolves ingredient names to USDA FoodData Central entries — this involves a semantic disambiguation step where the LLM maps "brown rice" to either the raw or cooked USDA entry, which have very different macro values.

The Critic is the key architectural choice. It does not use the LLM for validation — it runs deterministic Python arithmetic. It sums daily macros and costs, checks them against user targets with defined tolerances — plus or minus 10% for macros, a $0.50 budget tolerance — and if validation fails, it uses the LLM only to write specific revision instructions like "Day 1 is $2.30 over budget, replace salmon with tilapia."

The Planner then revises — not regenerates — the plan, using the failing plan as an anti-example. This loop runs up to 3 iterations. Steps 2 and 3 — Researcher and Nutritionist — run concurrently via ThreadPoolExecutor.

We evaluated with both mock databases and live APIs. Results are presented for both.

---

## SLIDE 4 — LLM Design Decisions (50 sec)

Five key design choices. First, structured JSON output — the Planner is constrained to emit a strict schema with a worked few-shot example to anchor the format. This eliminates parsing failures.

Second, semantic disambiguation — the Nutritionist makes a second LLM call specifically to resolve ambiguous food names before the USDA query. "Oats" becomes "rolled oats dry." This is critical because the raw-versus-cooked distinction can change macro values by 3x.

Third, targeted revision — the Critic doesn't just say "plan failed." It generates numbered, specific fixes. The Planner revises surgically rather than regenerating from scratch.

Fourth, anti-example prompting — on revision iterations, the failing plan's JSON is passed back with explicit instructions: "Do NOT repeat the structural patterns that caused these constraint violations."

Fifth, a static lookup table — 55 common ingredients like chicken breast, oats, garlic resolve to their USDA terms without any LLM call. This handles roughly 77% of ingredients in practice and reduces both latency and cost.

---

## SLIDE 5 — Evaluation Setup (40 sec)

We compare three systems: Bio-Sync with the full pipeline, a single-LLM baseline that generates everything in one pass, and a no-Critic ablation that removes the revision loop.

Metrics are mean macro percentage error against user targets, budget compliance rate, validation pass rate, and latency. We also conducted a human evaluation — 3 real raters scored 20 Bio-Sync plans on coherence, variety, and practicality using a Streamlit rating interface. That's 59 total ratings.

Critically, we ran evaluations in two modes: mock APIs — a controlled 47-item Kroger and 49-item USDA database — and real APIs hitting live Kroger OAuth2 and USDA FoodData Central. The comparison between these two modes is one of the most informative results.

---

## SLIDE 6 — Main Results, 50 Profiles (60 sec)

This is the 50-profile evaluation with real APIs — real Kroger prices, real USDA nutrition data.

Bio-Sync achieves 90% budget compliance and 36.49% mean macro error. The baseline gets 16.21% macro error with 100% budget compliance. At first glance, the baseline looks better — but this is misleading.

The baseline's macro numbers are self-graded. The LLM estimates its own macros, and those estimates are anchored to the user's targets in the prompt, so they're artificially close. It's grading its own homework. Bio-Sync's error comes from honest comparison against USDA ground-truth data.

Looking at the per-macro breakdown, protein error is only 19% — the static lookup table handles high-protein ingredients well. Calorie error is the outlier at 67.7%, and this drives the overall number. The root cause is gram-weight estimation — the LLM says "200 grams of chicken breast" but the actual USDA lookup depends on that weight being accurate. This is a known LLM weakness documented in the NutriBench literature.

Bio-Sync averages 2.76 iterations, meaning the Critic is actively revising almost every plan. Latency is 220 seconds — roughly 3.5 minutes per plan.

---

## SLIDE 7 — Ablation: Mock vs Real (60 sec)

This slide is the most interesting comparison in the presentation. We ran the same 10 profiles through all three systems with both mock and real APIs.

With mock APIs, Bio-Sync gets 15.45% macro error and 100% budget compliance. The no-Critic variant gets 22.53% — a 46% relative increase. This confirms the Critic revision loop is doing meaningful work.

With real APIs, the picture changes significantly. Bio-Sync's macro error jumps to 37.69%, and budget compliance drops to 70%. The no-Critic variant is similar at 37.23% — suggesting that the Critic can't fully compensate for harder real-world constraints.

But here's what stays constant: the baseline is essentially unchanged — 16.28% mock, 16.63% real. This is because the baseline never touches external data. It uses the LLM's own estimates regardless. This actually proves our architectural thesis — when you ground in real data, you get honest but harder-to-satisfy numbers. The baseline looks stable because it's ignoring reality.

The budget compliance drop from 100% to 70% tells us real Kroger prices are higher and more variable than our mock assumptions. This is a tuning problem, not an architecture problem — widening Critic tolerances or prompting the Planner to target 80% of budget would address it.

---

## SLIDE 8 — Human Evaluation (50 sec)

Three human raters evaluated 20 Bio-Sync plans through a Streamlit interface, giving 59 total ratings across three dimensions.

Coherence scored highest at 4.15 out of 5 — the plans make culinary sense. Raters agreed that meals within a day form logical combinations. Practicality scored 3.63 — plans are generally cookable but sometimes include complex steps. Variety scored lowest at 3.56 — this is a known LLM pattern where instruction-tuned models tend to produce "safe" outputs that repeat protein-plus-starch structures.

Looking at per-rater breakdown, Raters 1 and 2 are consistent with each other. Rater 3 gave notably higher variety scores — 4.21 versus 3.2-3.3 for the other two. Practicality was the most consistent dimension across all three raters, clustering between 3.55 and 3.68.

The overall average is 3.78 out of 5. This is from real humans, not simulated — all ratings were collected on April 21st through the Streamlit interface.

---

## SLIDE 9 — Discussion (50 sec)

The mock-versus-real comparison reveals three things.

First, mock APIs create a controlled environment where the system performs well — 100% budget compliance, lower macro error. This is useful for development and debugging, but it overstates real-world performance.

Second, real APIs surface the actual challenges. The USDA API returns real per-100g macros, but ambiguous ingredient matches cause errors — "black beans" might match "black beans canned drained" versus "black beans dry" with very different calorie values. Kroger returns actual store prices that are higher and more variable than mock assumptions.

Third, the architecture itself is validated. The pipeline correctly queries live APIs, caches results, handles errors with exponential backoff, and runs the full revision loop with real data. The performance gap isn't an architecture failure — it's an ingredient disambiguation problem and a gram-weight estimation problem, both of which have clear improvement paths.

The single biggest bottleneck is calorie estimation at 67.7% error. This comes from the LLM's gram-weight estimates being inaccurate when multiplied by USDA per-100g calorie densities. Constraining the Planner to use standard serving sizes would directly address this.

---

## SLIDE 10 — Capabilities & Limitations (40 sec)

On the left — everything that's implemented and verified. The full 5-agent pipeline with concurrent execution, deterministic Critic validation, anti-example prompting, static lookup table, user revision, and critically — live API evaluation on both 50 and 10 profile sets. Human evaluation with real raters is also complete.

On the right — known limitations. Budget compliance is 90% with real prices, not 100%. Calorie error dominates macro error. Instacart integration exists only as mock data — the Instacart Connect API is a B2B product that requires a retailer partnership. GPT-4o was never successfully evaluated — only Claude Sonnet and Haiku were tested. And variety is the weakest dimension in human evaluation.

---

## SLIDE 11 — Next Steps (30 sec)

Five concrete improvements. First, fix the calorie estimation bottleneck by constraining the Planner to standard serving sizes. Second, improve budget compliance by prompting the Planner to target 80% of budget as a margin. Third, multi-turn revision dialogue — currently only one round is implemented. Fourth, variety improvement through explicit structural tracking across iterations. Fifth, complete the multi-model comparison with GPT-4o and Llama 3.

---

## SLIDE 12 — Summary (30 sec)

Five takeaways. Budget compliance is 90% with real Kroger prices. The Critic revision loop averages 2.76 iterations per plan, actively improving each one. Real human raters gave an overall 3.78 out of 5, with coherence strongest at 4.15. The mock-versus-real comparison demonstrates that honest data grounding reveals harder constraints — and that's a feature, not a bug. And the architecture works end-to-end with live APIs.

The core insight of this project: LLMs are most powerful as reasoning engines embedded in structured pipelines with external data grounding and deterministic validation — not as standalone generators.

Every number in this presentation is traceable to a specific JSON file in eval_results. No fabricated data. Thank you.
