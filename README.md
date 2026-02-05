# Survey Logic Detection Engine

Analyzes survey questionnaires (PDF) and SPSS datasets using Manus AI to produce structured JSON with complete logic mapping.

## Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Add your MANUS_API_KEY
```

## Usage

```bash
# Full automatic analysis with progress
python app.py --pdf survey.pdf --spss data.sav --auto --thinking

# Use manus-1.6-max for complex surveys
python app.py --pdf survey.pdf --spss data.sav --auto --profile manus-1.6-max

# Custom prompt
python app.py --pdf survey.pdf --spss data.sav --auto --prompt my_prompt.txt

# Extract SPSS metadata only
python app.py --pdf survey.pdf --spss data.sav -m
```

## Options

| Option | Description |
|--------|-------------|
| `--pdf, -p` | PDF questionnaire (required) |
| `--spss, -s` | SPSS .sav file |
| `--auto, -a` | Wait + download results |
| `--thinking, -t` | Show AI progress |
| `--profile` | `manus-1.6`, `manus-1.6-lite`, `manus-1.6-max` |
| `--prompt` | Custom prompt file (default: `prompt.txt`) |
| `--output-dir, -o` | Output directory (default: `output`) |

## Logic Types

The prompt extracts 8 logic types:

| Type | Description |
|------|-------------|
| `skip` | Routing (terminate → END, skip to section/question) |
| `exclusive` | Mutually exclusive answers (code 99) |
| `count` | Min/max selections |
| `sum` | Must sum to target value |
| `piping` | Values from other questions |
| `recode` | Derived variables (age groups, tiers) |
| `validation` | Cross-question rules (B12 >= B03) |
| `custom` | Other inter-question logic |

## Output

JSON with structure:
```json
{
  "survey": {"id": "...", "name": "..."},
  "derived_variables": [...],
  "questions": [
    {
      "id": "Q1",
      "section": "A", 
      "text": "...",
      "type": "single_select",
      "vars": ["Q1"],
      "answers": [{"code": 1, "text": "..."}],
      "logic": [{"type": "skip", "condition": "Q1=2", "target": "END"}]
    }
  ]
}
```

## Files

- `app.py` - Main CLI application
- `manus_client.py` - Manus API client
- `spss_metadata.py` - SPSS metadata extractor
- `prompt.txt` - Editable analysis prompt
