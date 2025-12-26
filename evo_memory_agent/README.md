# Evo Memory Agent

## Setup

1. Install dependencies from both subprojects:

```bash
pip install -r A_mem/requirements.txt
pip install -r GAM_root/requirements.txt
```

2. Create a `.env` file with your OpenRouter API key:

```bash
OPENROUTER_API_KEY=your_key_here
```

## Usage

- `a_mem_memory_creation.py` creates memories.
- `amem_gam_retriever.py` retrieves memories for a query.
