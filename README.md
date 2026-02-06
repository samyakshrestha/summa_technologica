# Summa Technologica

A command-line brainstorming tool that applies the medieval Scholastic method to modern questions.

You give it a question. It returns a structured argument: three objections, a counter-thesis, a central answer, and point-by-point replies. The format comes from Thomas Aquinas's *Summa Theologica*, where every question was stress-tested through formal disputation before a conclusion was reached.

Under the hood, four AI agents work in sequence. One frames the problem. One generates the strongest possible objections. One synthesizes a thesis and replies. One reviews the whole thing for logical consistency and rejects anything generic. The result is more rigorous than what a single prompt can produce, because the structure forces adversarial reasoning.

It works for any domain: physics, philosophy, economics, policy, mathematics, or anything else you want to think carefully about.

## Example

```
$ summa-technologica 'Is free will compatible with determinism?' --domain philosophy
```

Output:

```
Question: Is free will compatible with determinism?

Objections:
1. ...
2. ...
3. ...

On the contrary...
...

I answer that...
...

Replies to objections:
Reply to Objection 1. ...
Reply to Objection 2. ...
Reply to Objection 3. ...
```

## Setup

Requires Python 3.10+ and an API key from OpenAI (or another supported provider).

```bash
pip install crewai
pip install -e .
cp .env.example .env
```

Open `.env` and add your API key:

```
OPENAI_API_KEY=your-key-here
MODEL=gpt-4o-mini
```

## Usage

```bash
summa-technologica 'Your question here'
summa-technologica 'Your question here' --domain 'physics'
summa-technologica 'Your question here' --format json
summa-technologica 'Your question here' --save output.md
```

## Configuration

All configuration lives in `.env`. Key options:

| Variable | Default | Purpose |
|---|---|---|
| `MODEL` | `gpt-4o-mini` | Which model to use |
| `SUMMA_VERBOSE` | `false` | Show agent reasoning in real time |
| `SUMMA_DEFAULT_DOMAIN` | `general science` | Default domain if `--domain` is not passed |

You can use any provider supported by LiteLLM. Examples:

```
MODEL=gpt-4o-mini              # OpenAI
MODEL=deepseek/deepseek-chat   # DeepSeek (needs DEEPSEEK_API_KEY)
MODEL=gemini/gemini-2.0-flash  # Google (needs GEMINI_API_KEY)
MODEL=ollama/llama3            # Local via Ollama (free)
```

## Project structure

```
summa_technologica/
    config/
        agents.yaml        # Agent roles, goals, and backstories
        tasks.yaml         # Task prompts and sequencing
    crew.py                # CrewAI workflow definition
    models.py              # Data structures and JSON validation
    cli.py                 # Command-line interface
    formatter.py           # Markdown output formatting
    config.py              # Environment/settings loader
tests/
    test_models.py         # Unit tests for the JSON parser
```

## Customization

To change how the agents think, edit `summa_technologica/config/agents.yaml` and `summa_technologica/config/tasks.yaml`. No code changes needed.

## Author

Samyak Shrestha
