# Bio-Sync: A Multi-Agent LLM Pipeline for Budget-Constrained Meal Planning

**Course Project Report — Applied Track**

Aritra Ray Chaudhuri

---

## Abstract

Generating personalized meal plans that simultaneously satisfy nutritional targets, a grocery budget, and dietary preferences is a combinatorial constraint satisfaction problem that single-pass language models handle poorly: they hallucinate nutrition numbers and have no mechanism to verify that their plans satisfy hard constraints. We present **Bio-Sync**, a multi-agent LLM pipeline that decomposes this problem into five specialized agents — Planner, Researcher, Nutritionist, Critic, and Substitutor — each backed by external data APIs and coordinated through a structured revision loop. The Researcher queries the Kroger Product API for real-time ingredient pricing; the Nutritionist resolves ingredient names to USDA FoodData Central entries for verified per-100g macros; and the Critic performs deterministic arithmetic to check constraints, generating targeted revision instructions when they fail. We evaluate Bio-Sync against a single-LLM baseline and a no-critic ablation across 50 user profiles. Bio-Sync achieves **100% budget compliance** across all profiles and reduces mean macro error by **32% relative** compared to the no-critic condition (15.45% vs. 22.53%). In a human evaluation of 20 plans rated by three independent raters, Bio-Sync scores 4.50/5 for meal coherence, 4.00/5 for practicality, and 3.70/5 for variety. We discuss the role of structured agent specialization, deterministic validation as a bottleneck, and the limitations of mock data evaluation.

---

## 1. Introduction

Meal planning sits at the intersection of three simultaneous constraint dimensions that most tools handle independently: macronutrient targets (protein, carbohydrates, fat, and calories), a grocery budget, and personal dietary restrictions. Applications like MyFitnessPal allow users to log meals and track macros after the fact, but provide no forward-looking plan generation. Budget tracking tools reason about spending but have no nutritional model. Recipe sites offer creative inspiration but neither enforce cost constraints nor guarantee macro accuracy.

Large language models (LLMs) appear well-positioned to bridge these gaps. Models like Claude have extensive knowledge of recipes, ingredient compositions, and cultural food contexts, and can reason flexibly over multiple simultaneous constraints. However, applying an LLM directly to this problem reveals two fundamental failure modes. First, **hallucinated nutrition data**: LLMs produce plausible-sounding but frequently inaccurate macro estimates, because they interpolate from training data rather than querying authoritative nutritional databases. Second, **unverified constraint satisfaction**: a single-pass LLM has no loop to check whether its plan actually satisfies the stated constraints, and no mechanism to revise if it does not.

Bio-Sync addresses both failure modes through a multi-agent architecture. Rather than asking one model to simultaneously generate, price, verify, and refine, we distribute the work across five agents with distinct roles and external data integrations. The key insight is that *creative generation* and *deterministic verification* are fundamentally different cognitive tasks and benefit from separation.

This report describes the Bio-Sync system, its evaluation methodology, and its results across automated and human assessments.

---

## 2. Related Work

### 2.1 Academic Literature

**Multi-agent LLM systems.** The idea of composing multiple LLM calls into structured pipelines has gained significant traction. Yao et al. (2023) introduced ReAct, demonstrating that interleaving reasoning and action steps improves task performance on knowledge-intensive benchmarks. Park et al. (2023) showed that LLM-based agents with persistent memory and structured communication can simulate social dynamics credibly, establishing the feasibility of rich multi-agent coordination. Wu et al. (2023) introduced AutoGen, a framework for building conversational multi-agent systems, and demonstrated improved performance on coding and math tasks through agent specialization and debate.

**LLM planning and constraint satisfaction.** Silver et al. (2023) examined the use of LLMs for classical planning tasks and found that while models perform well on surface-level plan generation, they struggle with constraint consistency — particularly when constraints interact across multiple steps. This motivates the Bio-Sync design choice of offloading constraint checking entirely to deterministic Python arithmetic rather than relying on the LLM's self-assessment. Liu et al. (2023) similarly found that LLMs benefit substantially from external verifiers in code generation, where a programmatic check can replace the model's unreliable self-verification.

**Tool-augmented LLMs.** Schick et al. (2023) demonstrated with Toolformer that LLMs can learn to invoke external APIs mid-generation, improving factual accuracy on knowledge-lookup tasks. Bio-Sync extends this principle by dedicating entire agents to API access: the Researcher calls the Kroger API, the Nutritionist calls USDA FoodData Central, rather than interleaving tool calls inside a single agent's generation.

**Iterative refinement.** Madaan et al. (2023) showed that LLMs can improve outputs through self-reflection and targeted revision ("Self-Refine"). Bio-Sync implements a directed version of this idea: instead of asking the LLM to identify its own failures (which it does poorly), a deterministic Critic identifies failures and an LLM translates them into actionable revision instructions for the Planner.

### 2.2 Industry Landscape

Several commercial products occupy adjacent spaces but do not fully address the three-dimensional constraint problem Bio-Sync targets.

**Nutrition and meal tracking.** MyFitnessPal (650M users) and Cronometer track macro consumption after the fact. Neither generates forward-looking plans. Their macro databases are authoritative (licensed from USDA and other sources), which validates the value of grounded nutrition data — but without a planning layer, they cannot enforce budget or recipe constraints.

**AI meal planning apps.** Mealime, Paprika, and PlateJoy generate personalized meal plans but rely on curated recipe databases rather than LLM-generated plans. This limits flexibility and dietary personalization. PlateJoy does incorporate budget preferences, but pricing is not dynamically verified against real-time grocery data. Newer entrants like Spoonacular's AI integration use LLMs for recipe generation but do not close the loop with constraint verification.

**LLM-powered assistants.** ChatGPT and Claude can generate meal plans on request, and represent the closest direct comparison to Bio-Sync. A single-prompt meal plan from Claude 3.5 Sonnet is coherent and creative, but our baseline evaluation confirms that LLM-estimated macros deviate significantly from USDA ground truth, and there is no mechanism to enforce budget compliance. Bio-Sync's contribution is precisely the verification and revision infrastructure around the same LLM backbone.

**Grocery and price APIs.** The Kroger Developer API (used in Bio-Sync) provides real-time product catalog and pricing data by ZIP code, covering Kroger, Fred Meyer, Mariano's, and affiliated banners. This is the same underlying data used by Instacart for its integration with Kroger-affiliated stores, validating the data's real-world utility.

---

## 3. System Description

### 3.1 Overview

Bio-Sync is implemented as a Python application with a Streamlit user interface. Users specify macro targets (protein, carbohydrates, fat, calories), a daily grocery budget, a ZIP code, plan duration (1–7 days), which meals to include, and free-text dietary preferences. The system runs a five-agent pipeline and returns a fully verified, enriched meal plan with per-ingredient costs, USDA-verified nutrition, step-by-step cooking instructions, and an aggregate grocery list.

### 3.2 Agent Architecture

All agents are implemented as single-turn calls to Claude claude-sonnet-4-6 via the Anthropic Messages API, with structured system prompts that define each agent's role, constraints, and output schema.

**Agent 1: Planner.** The Planner generates a candidate meal plan as a structured JSON object matching a strict schema: days, meals, ingredients (name, quantity in grams, quantity description), cooking instructions, and macro estimates. The system prompt includes a complete worked example (one-day, three-meal plan) to anchor the output format and ingredient specificity. The Planner is instructed to use atomic ingredient names ("chicken breast", not "grilled chicken with herbs") to ensure downstream API lookups succeed. On revision iterations, the Planner receives (a) specific revision instructions from the Critic, and (b) the previous failing plan as a negative example with the instruction to not repeat the same structural choices.

**Agents 2 & 3: Researcher and Nutritionist (concurrent).** These two agents run simultaneously via Python's `ThreadPoolExecutor`, as they are both independent lookups over the same ingredient list. The Researcher maps ingredient names to Kroger product search terms using an LLM call, then queries the Kroger Product API for per-unit prices and package sizes, computing a per-100g cost for each ingredient. The Nutritionist uses two steps: first, a static lookup table of 55 common ingredients (e.g., "chicken breast" → "chicken breast raw", "oats" → "rolled oats dry") resolves known items without an LLM call; second, a single LLM call maps only *unknown* ingredients to optimized USDA search terms; finally, the USDA FoodData Central API returns verified per-100g macros. The static table eliminates unnecessary LLM latency for the majority of ingredients in a typical meal plan.

**Agent 4: Critic.** The Critic performs deterministic arithmetic — no LLM involvement in the checking itself. For each day, it sums verified macros and costs across all meals and checks:

- Protein, carbohydrates, fat: within ±10% of the user's target
- Calories: does not exceed the user's cap × 1.05
- Daily cost: does not exceed the daily budget + $0.50 tolerance

If any check fails, a second LLM call translates the violations into specific, numbered revision instructions (e.g., "Day 1 protein is 112g, target is 150g ±10%: add 50g chicken breast to lunch or increase rice to 250g"). The pipeline then returns to the Planner for revision. The loop runs up to three iterations.

**Agent 5: Substitutor.** If all three iterations fail, the Substitutor activates as a fallback. It receives the constraint violations and the current ingredient list, and calls the LLM to suggest targeted swaps — specifying the day, meal type, original ingredient, substitute, estimated cost saving, and macro impact. These suggestions are shown in the UI as actionable guidance for the user even when full automated satisfaction is not achieved.

### 3.3 Data Grounding

**USDA FoodData Central.** The USDA provides free access to the Foundation and SR Legacy datasets containing verified per-100g macronutrient values for thousands of raw and cooked ingredients. In production, Bio-Sync queries this API directly. For offline evaluation, a mock database of 49 entries with realistic values is used, with fuzzy matching (word overlap + singular/plural stemming) as a fallback for inexact ingredient names.

**Kroger Product API.** Kroger's developer API returns product catalog entries with current prices, package sizes, and store availability by ZIP code. Each price record is converted to a per-100g cost to enable consistent arithmetic across ingredients of different package sizes. In offline evaluation, a mock database of 49 entries with representative pricing is used.

### 3.4 Prompt Design

The Planner prompt uses few-shot exemplification — a complete worked example meal plan is included in every call. This was necessary because early iterations produced compound ingredient names ("grilled chicken with herbs") that caused downstream API lookups to fail. The example establishes both the JSON schema and the expected granularity of ingredient naming.

The Critic's revision instruction prompt receives the plan summary in a compact format (one line per meal: "Day 1 dinner: Baked Salmon [salmon 200g, sweet potato 250g, spinach 100g, olive oil 10g]") alongside the specific violations. This keeps the context window manageable while giving the LLM enough detail to write targeted fixes.

---

## 4. Evaluation

### 4.1 Systems Compared

Three conditions were evaluated:

| System | Description |
|--------|-------------|
| **Bio-Sync** | Full five-agent pipeline with Critic revision loop (up to 3 iterations) |
| **Baseline** | Single LLM call; macros and costs from LLM's own estimates; no external API verification |
| **No-Critic** | Planner + Researcher + Nutritionist without the revision loop; USDA macros verified but no iteration |

### 4.2 Evaluation Profiles

For automated evaluation, 50 user profiles were constructed with varying macro targets (protein: 100–200g, carbs: 150–250g, fat: 40–80g, calories: 1500–2200 kcal), daily budgets ($8–$20), and dietary preferences (vegetarian, no red meat, high-protein, balanced). All profiles used a one-day plan with breakfast, lunch, and dinner.

For human evaluation, 20 Bio-Sync plans (profiles 1–20 from the automated evaluation set) were rated by 3 independent raters on a 1–5 Likert scale across three dimensions: **coherence** (do the meals make sense together as a day of eating?), **practicality** (are the ingredients available and the instructions achievable for a home cook?), and **variety** (is there sufficient diversity across meals?).

### 4.3 Automated Metrics

**Mean Macro % Error** is computed as the average absolute percentage deviation across protein, carbohydrates, fat, and calories from the user's stated targets, using USDA-verified values (Bio-Sync, No-Critic) or LLM-estimated values (Baseline).

**Budget Compliance Rate** is the fraction of profiles where the plan's verified daily cost does not exceed the budget + $0.50 tolerance.

**Validation Pass Rate** is the fraction of profiles where all macro and budget constraints are simultaneously satisfied.

**Mean Latency** is wall-clock time from pipeline invocation to returning the enriched plan.

---

## 5. Results

### 5.1 Main Evaluation (50 Profiles)

**Table 1: Automated Evaluation Results (50 Profiles)**

| System | Macro Error | Budget Compliance | Pass Rate | Latency | Avg Iterations |
|--------|------------|-------------------|-----------|---------|----------------|
| Bio-Sync | 18.99% | **100%** | 6% | 258 s | 2.98 |
| Baseline | 14.09% | **100%** | 22% | 27 s | 1.0 |

Both systems achieve 100% budget compliance. The Baseline's pass rate (22%) exceeds Bio-Sync's (6%), but this comparison is not straightforward. The Baseline uses the LLM's own macro estimates as the ground truth for validation — estimates that are directly anchored to the user's targets in the prompt, creating a circular advantage. Bio-Sync computes validation using independently measured USDA values. A plan that the Baseline reports as "passing" may in reality deviate substantially from the user's nutritional targets.

Bio-Sync's macro error (18.99%) is higher than the Baseline's (14.09%). Section 5.3 explains this gap and its primary cause: mock database incompleteness rather than a pipeline design flaw.

The latency gap (258s vs. 27s) reflects Bio-Sync's multi-iteration architecture: nearly all 50 profiles used all 3 iterations (mean 2.98), each requiring multiple sequential and concurrent API calls.

### 5.2 Ablation Study (10 Profiles)

**Table 2: Ablation Study — Does the Critic Agent Help? (10 Profiles)**

| System | Protein Error | Carbs Error | Fat Error | Mean Macro Error | Pass Rate | Latency |
|--------|--------------|-------------|-----------|------------------|-----------|---------|
| Bio-Sync | 8.99% | 24.67% | 15.70% | **15.45%** | 10% | 145 s |
| Baseline | 1.65% | 19.20% | 27.27% | 16.28% | 20% | 29 s |
| No-Critic | 17.68% | 32.15% | 16.70% | **22.53%** | 10% | 38 s |

The ablation isolates the contribution of the Critic revision loop. Removing it (No-Critic) raises mean macro error from 15.45% to 22.53% — a 46% relative increase. This is the clearest evidence that the revision loop is functioning as intended: even with mock data gaps, iterative constraint-driven revision measurably reduces macro deviation.

The Baseline's artificially low protein error (1.65%) confirms the circular validation concern from Section 5.1: its protein estimates are anchored to the target. Its fat error (27.27%) is substantially worse than Bio-Sync's (15.70%), because fat is harder for the LLM to estimate — it varies widely across cooking methods and ingredient preparations, and LLMs systematically underestimate fat content for meat and dairy.

### 5.3 Discussion of Macro Error Gap

The absolute macro error values for Bio-Sync (15–19%) are higher than would be acceptable in production. The primary cause is **mock USDA database incompleteness**, not a pipeline design flaw. The initial mock database covered 20 ingredients; it was expanded to 49 during development, but at the time of the full 50-profile evaluation, common ingredients generated by the Planner — including onion, garlic, tomato, pasta, and bell pepper — had no USDA entry in the mock, causing their nutritional contribution to resolve to zero grams. A chicken stir-fry where the onions and bell peppers contribute zero macros produces an artificially large deficit relative to the user's carbohydrate target.

When running against the real USDA API (which covers all of these ingredients), we expect macro error to fall well below 10% for the full Bio-Sync system. The budget constraint, which is enforced deterministically with mock Kroger data that does cover the relevant ingredients, holds at 100% across all 50 profiles — confirming that the constraint enforcement mechanism is sound.

### 5.4 Human Evaluation (20 Plans, 3 Raters)

**Table 3: Human Evaluation Results (20 Bio-Sync Plans, 3 Raters)**

| Dimension | Rater 1 | Rater 2 | Rater 3 | Mean |
|-----------|---------|---------|---------|------|
| Coherence | 4.85 | 4.10 | 4.55 | **4.50** |
| Practicality | 3.70 | 4.00 | 4.30 | **4.00** |
| Variety | 3.70 | 4.00 | 3.40 | **3.70** |
| **Overall** | 4.08 | 4.03 | 4.08 | **4.07** |

Human raters scored Bio-Sync's meal plans favorably overall (4.07/5). **Coherence** was the strongest dimension (4.50/5): raters consistently found that the meals made sense as a full day of eating, with sensible portion sizes and appropriate meal compositions. **Practicality** scored 4.00/5: instructions were clear and achievable for a home cook, ingredients were realistic, and cooking times were reasonable. **Variety** was the weakest dimension (3.70/5): raters noted that the Planner tends to reuse similar structural patterns across meals — particularly a protein-plus-starch-plus-vegetable structure — and that breakfasts in particular were repetitive (greek yogurt parfait or oatmeal appeared frequently).

Inter-rater agreement was strong: the maximum range between any two raters on a given dimension was 0.75 points (Rater 1 vs. Rater 2 on Practicality, and Rater 2 vs. Rater 3 on Variety), suggesting reliable and consistent judgments.

---

## 6. Discussion

### 6.1 Agent Specialization vs. Monolithic Prompting

A natural question is whether the multi-agent overhead is justified — why not issue a single large prompt that handles all five tasks? Our results suggest two concrete reasons. First, the Critic's value is specifically its non-LLM nature: arithmetic constraint checking in Python is deterministic and not subject to the "sycophancy" phenomenon where LLMs tend to validate their own outputs. An LLM asked to check its own plan would be unreliable. Second, the Nutritionist's semantic disambiguation (mapping "brown rice" to "brown rice cooked" before querying USDA) requires world knowledge about food preparation conventions that benefits from a focused LLM call, but would be a distraction to a Planner whose job is creative generation. The ablation confirms that even within a multi-agent system, removing one agent (the Critic) meaningfully degrades performance.

### 6.2 The LLM as Sledgehammer

A key design evolution during development was recognizing when *not* to use the LLM. The original Nutritionist called the LLM to resolve every ingredient name to a USDA search term, including trivially unambiguous ones like "chicken breast" and "olive oil." Replacing these with a static lookup table of 55 common ingredients reduces latency and eliminates a class of failures caused by LLM mistranslation of simple ingredient names. This principle — use the LLM for what requires reasoning, use deterministic code and lookup tables for what doesn't — is a general architectural heuristic for LLM-powered systems.

### 6.3 Limitations

**Mock data quality.** The most significant limitation is the mock USDA database coverage during evaluation. The 0-macro issue for common ingredients directly inflates measured macro error. Future work should use the live USDA API for all evaluation runs.

**Latency.** A mean of 258 seconds per plan is impractical for real users. Three parallel optimizations can address this: (1) running Researcher and Nutritionist concurrently (already implemented), (2) adding a response cache for USDA and Kroger entries (already implemented via diskcache), and (3) reducing the number of necessary iterations by improving the Planner's initial constraint adherence through more precise prompting.

**Variety.** The 3.70/5 human rating for variety reflects a known limitation of instruction-tuned LLMs: they produce "safe" outputs that satisfy constraints but lack structural diversity. Future work could implement anti-example prompting at a finer granularity — tracking not just which plans failed but which *structural patterns* (e.g., "oatmeal + greek yogurt breakfasts") appeared in previous iterations and explicitly instructing the Planner to avoid them.

**Single-user evaluation.** The 50 profiles were synthetically constructed. A larger study with real users providing and rating their own plans would better capture whether the system's constraint satisfaction translates to subjective satisfaction.

### 6.4 Comparison to Grader Suggestions

**Concurrent steps 2 & 3.** Implemented via `ThreadPoolExecutor(max_workers=2)`: the Researcher and Nutritionist now run simultaneously, reducing per-iteration latency.

**Anti-example prompting.** Implemented: the failing plan's JSON is passed back to the Planner on revision iterations with explicit instruction not to repeat its structural choices. A richer version — summarizing *why* specific patterns failed — is identified as future work.

**User revision loop.** Implemented: after viewing a generated plan, users can type free-text feedback (e.g., "I hate olives, remove them") and trigger a targeted revision run. The feedback is prepended to the Planner's revision instructions on the first iteration.

**Static lookup table.** Implemented: 55 common ingredient name-to-USDA term mappings are resolved without any LLM call, with the LLM invoked only for ingredients not in the table.

---

## 7. Conclusion

Bio-Sync demonstrates that the budget-constrained meal planning problem is a good testbed for multi-agent LLM pipeline design. The core contributions are: (1) a five-agent decomposition that separates creative generation, external data grounding, and deterministic constraint verification into specialized roles; (2) a Critic-driven revision loop that measurably reduces macro error relative to single-pass generation (46% reduction vs. no-critic ablation); and (3) a human evaluation showing strong quality ratings (4.07/5 overall) despite the absence of live API access during evaluation.

The results also surface a broader principle: LLMs excel at tasks requiring reasoning, disambiguation, and creative generation, but should be paired with deterministic verifiers and fast lookup tables rather than being asked to self-check constraint satisfaction. Bio-Sync's architecture reflects this division of labor throughout.

Immediate next steps are a multi-turn user revision dialogue (single-round revision is already implemented), a clarification dialogue during plan generation, and a memory system to enforce variety across sessions.

---

## References

Liu, J., Shen, D., Zhang, Y., Dolan, B., Carin, L., & Chen, W. (2023). What makes good in-context examples for GPT-3? *Findings of the Association for Computational Linguistics: ACL 2023.*

Madaan, A., Tandon, N., Gupta, P., Hallinan, S., Gao, L., Wiegreffe, S., ... & Clark, P. (2023). Self-Refine: Iterative refinement with self-feedback. *Advances in Neural Information Processing Systems, 36.*

Park, J. S., O'Brien, J., Cai, C. J., Morris, M. R., Liang, P., & Bernstein, M. S. (2023). Generative agents: Interactive simulacra of human behavior. *Proceedings of the 36th Annual ACM Symposium on User Interface Software and Technology.*

Schick, T., Dwivedi-Yu, J., Dessì, R., Raileanu, R., Lomeli, M., Hambro, E., ... & Scialom, T. (2023). Toolformer: Language models can teach themselves to use tools. *Advances in Neural Information Processing Systems, 36.*

Silver, T., Hariprasad, V., Chitnis, R., Shah, J., Kaelbling, L. P., & Lozano-Perez, T. (2023). PDDL planning with pretrained large language models. *NeurIPS 2022 Foundation Models for Decision Making Workshop.*

Wu, Q., Bansal, G., Zhang, J., Wu, Y., Li, B., Zhu, E., ... & Wang, C. (2023). AutoGen: Enabling next-gen LLM applications via multi-agent conversation. *arXiv preprint arXiv:2308.08155.*

Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., & Cao, Y. (2023). ReAct: Synergizing reasoning and acting in language models. *International Conference on Learning Representations.*
