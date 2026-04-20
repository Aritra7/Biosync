# Bio-Sync

A budget-constrained AI meal planner powered by a multi-agent pipeline. Set your macro targets, daily budget, and dietary preferences — Bio-Sync generates a complete meal plan with verified nutrition data and real grocery prices.

## How it works

Five specialized LLM agents collaborate in a loop:

1. **Planner** — generates a structured meal plan (JSON) based on your constraints
2. **Researcher** — looks up real grocery prices via the Kroger Product API
3. **Nutritionist** — verifies macros against the USDA FoodData Central database
4. **Critic** — checks all constraints; sends the plan back for revision if anything fails
5. **Substitutor** — if the plan still fails after 3 iterations, suggests targeted ingredient swaps

## Setup

**Requirements:** Python 3.11+

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=your_key_here

# Optional — leave unset to use mock grocery/nutrition data
KROGER_CLIENT_ID=your_kroger_client_id
KROGER_CLIENT_SECRET=your_kroger_client_secret
USDA_API_KEY=your_usda_api_key
```

By default the app runs with mock APIs so no external keys are required.
Set `BIOSYNC_REAL_APIS=true` in your `.env` to use live data.

## Run

```bash
streamlit run app.py
```

## Run tests

```bash
python -m pytest tests/ -v -s
```

## Project structure

```
app.py               # Streamlit UI
src/
  pipeline.py        # Orchestrates the agent loop
  schemas.py         # Pydantic data models
  agents/
    planner.py
    researcher.py
    nutritionist.py
    critic.py
    substitutor.py
    base.py          # Shared LLM call utility
  tools/
    usda.py          # USDA API + mock
    kroger.py        # Kroger API + mock
tests/
  test_pipeline.py
  test_api_wrappers.py
```
