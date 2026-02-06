# Beginner Guide

This guide walks you through running Summa Technologica for the first time.

## What this tool does

You type a question. It returns a structured argument in this format:

1. Objection 1
2. Objection 2
3. Objection 3
4. On the contrary...
5. I answer that...
6. Reply to Objection 1, 2, and 3

Four AI agents work in sequence to produce this. The format forces rigorous, adversarial reasoning rather than a single flat answer.

## First-time setup

Run these commands from the project root:

```bash
pip install --upgrade pip
pip install crewai
pip install -e .
```

## Add your API key

Create a `.env` file from the provided template:

```bash
cp .env.example .env
```

Open `.env` in any text editor and set your values.

If you use OpenAI:

```
OPENAI_API_KEY=your-key-here
MODEL=gpt-4o-mini
```

If you use DeepSeek:

```
DEEPSEEK_API_KEY=your-key-here
MODEL=deepseek/deepseek-chat
```

You only need to do this once. The tool loads `.env` automatically on every run.

## Run the tool

Basic usage:

```bash
summa-technologica 'Can quantum error correction inspire new classical coding methods?'
```

With a domain:

```bash
summa-technologica 'Could dark matter be modeled as emergent from spacetime topology?' --domain physics
```

Save output to a file:

```bash
summa-technologica 'Your question' --save output.md
```

## Common errors

**"crewai is not installed in this environment"**

CrewAI is missing. Run:

```bash
pip install crewai
pip install -e .
```

**API or authentication errors**

Your API key is missing or invalid. Check the values in `.env`.

**"command not found: summa-technologica"**

The package is not installed. Run:

```bash
pip install -e .
```

## Customization

To change agent behavior, edit the YAML files in `summa_technologica/config/`. No code changes required.

- `agents.yaml` controls agent roles, goals, and backstories
- `tasks.yaml` controls task prompts and sequencing
