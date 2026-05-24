# Solidocto: Examines a peice of text for indicators of human or AI creation

## Basic Overview
On a webpage, a user can paste in a section of text. Unicode is accepted, but formatting is not.

The section of text will be fixed to prevent overflows (1023 characters).

The user will then press submit.

Captcha can be toggled with configuration for testing versus production:

- app.require_captcha: false (default for local testing)
- app.require_captcha: true (require non-empty captcha_token)

The system will demonstate an set of activities, such as:

- Checking structure
- Identifying key components
- Looking for AI markers
- Looking for Human markers
- Finalizing report

the report will then respond to the user:

AI marker report: 0 - 999
999 = almost cert. AI

Human markers found:
999 = almost cert human

Unknown markers found (this is a nice name for garbage)
999 = garbage

The report will never say what the markers were, to protect the IP from training other AI models to avoid detection.

The report will also fuzz slightly the results to ensure the markers cannot be fingerprinted.

## Backend activity
### Pass 1: similarity

- backend calculates the simhash for the input test.
- looks in the redis database for similar texts
    - if the hamming distance is less than 5 (use config yamls for this) then simply report the last result retrived from the database
        - mark this in the return JSON
        - skip further tests and report to user
    - if not similar, proceed to garbage tests

### Pass 2: garbage

- backend looks for garbage or non-english input
- tests to run: (set values in yaml)
    1. Entrpoy test
        - if entropy > 5 set unknown = 999, and skip all further tests.
        - < 3 add 10 human indicator
        - 3 - 5 add 1 human and 1 AI indicator
    2. Repeated char test
        - max_run_length / total_length
            - gt 0.15 - add 20 garbage
            - gt 0.25 - 999 garbage, skip all further tests.
    3. Non printable char density
        - control_chars / total_chars
            - gt 0.02 - add 20 garbage
            - gt 0.05 - 999 garbage, skipp all further tests.
    4. unicode outliers
        - categorize by letter, number, punctuation, symbol, other
            - other gt 20%, garbage = 999, skill all further tests
            - punct gt 20%, garbage = 999, skill all further tests
            - symbols gt 20%, garbage = 999, skill all further tests
            - numbers gt 50%, garbage = 999, skill all further tests
    5. Word-salad detector
        - get a list of 5k common english words
            - look at fraction of those works from the submission words
                - if % of works not from common list is < 30% add 100 garbage
                - if % of words not from common list is < 15%, garbage = 999, skip all further tests
        - add option to ignore capitalised words and initialisations in ratio calculator
    6. Line-Length variance
        - calc the SD of sentence lengths
        - minimum 3 lines. 
        - SD lt 2: +1 AI, +1 garbage
        - SD gt 3 lt 9: +1 AI, +1 human
        - SD gt 9: +1 garbage
    7. Character-bigram frequency
        - using the bigrams.json file, look at the frequency of bigrams in submitted text
        - if the distribution in the sample does not have a similar distro - it's uniform, or spikes
            - calculated a KL-divergance 
                - if lt 0.1 - +1 AI +1 Hum
                - if gt 0.2 lt 0.3 - +1 garbage, +2 AI
                - if gt 0.3 lt 0.6 - +2 garbage, +3 AI
                - if gt 0.6 lt 1 - +10 garbage
                - if gt 1 - 999 garbage

### Pass 3: Construction Tests
    The construction tests load the sample text into small local NLP model. It looks to semantic and linguistic features.
    The model should be only around 100-300 dimensions.
    Embedding + POS + LM

    1. semantics coherence test
        - this is sentence to sentence symantic drift.
        - compute embeddings for each sentence
        - cosine simularity
        - if simularity is lt 0.2 for 50% of the sentence pairs - garbage +10
    2. topic persistence
        - if the number of clusters is gt than half the number of sentences - garbage +10
        - if the number of clusters is gt 75% the number of sentences - garbage + 20
    3. embedding variance
        - very low lt 0.05 - AI +10
        - mod low gte 0.05 lt 0.1 - AI +5
        - human gte 0.1, lt 0.25 - Human +5
        - mod high gte 0.25, lt 0.35, human +1, garbage +5
        - very high gte 0.35 - garbage +10
    4. marker presence vs clause structure
        - requires a small dependancy parser, like spaCy-mini
        - markers are because, however, therefore, although
        - if no subortinate cause, or clause is empty, or main caluse is missing - AI +5
        - tag as marker misuse
    5. symantic relationship check
        - for "because" marker (see 4 above), check the embedding (clause) is related to the embedding (effect)
            - if the cosine simularity is lt 0.2, then AI +5, garbage +10
            - if gte 0.2 lt 0.3, then AI +5, garbage +5
            - gte 0.3, human +5, AI +5
        - for "however" marker (see 4 above), embedding(A) and embedding(B) should be related but contrasting
            - if the simularity is lt 0.1, then AI +1, garbage +10
            - if gte 0.1 lt 0.2, then AI +1, garbage +5
            - if gte 0.2 lt 0.6, then AI +2, human +3
            - gte 0.8, garbage +5, AI +5
        - for "therefore" marker (see 4 above), premise → conclusion should be strongly related
            - if the simularity is gt 0.4 then AI +2, human +5
            - if lte 0.4 then garbage +5, AI+2
        - for "although" marker (see 4 above), concession and main clause should be related but not identical
            - if the simularity is lt 0.2, AI +5, garbage +5
            - if the simularity is gte 0.2 lt 0.6, human +5, AI +2
            - if gte 0.6 then garbage +5, AI +5
    6. marker spirals because, however, therefore, although
        - if the frequency of markers is gt 1 per sentence, then AI +2
        - if two diff markers apear in the same sentence, then AI +2
        - if three different markers appear in the sample text then AI +4




     

### Pass 4: AI detector

### Pass 5: Human detector






## redis database
The simhashes, the date seen, and the ai, human, garbage results are stored in a redis database so we can quickly find hamming distances.

1. Primary Storage: One Hash per Submission
Each analysed text becomes a single Redis Hash.

Key
Code
solidocto:entry:<simhash>
Where <simhash> is a 64‑bit or 128‑bit integer, stored as hex or decimal.

Value (Hash fields)
Code
ai_score          (int 0-999)
human_score       (int 0-999)
garbage_score     (int 0–999)
dominant          (string: "ai" | "human" | "garbage")
created_at        (unix timestamp)
ip_hash           (optional, SHA256 of IP)
simhash           (string or integer)
version           (int, schema version)
istest            (boolean)
Example
Code
HSET solidocto:entry:0x8f3a9c1d \
    ai_score 72 \
    human_score 18 \
    garbage_score 10 \
    dominant "ai" \
    created_at 1716090000 \
    ip_hash "a94a8fe5ccb19ba61c4c0873d391e987" \
    simhash "0x8f3a9c1d" \
    version 1 \
    istest true

2. Similarity Index: RedisBloom LSH
This is the only index you need.

Create the index (once)
Code
BF.LSH.CREATE solidocto:lsh 8 64
8 = number of bands

64 = number of bits in your SimHash

If you use 128‑bit SimHash, change the second number.

Insert a new simhash
Code
BF.LSH.ADD solidocto:lsh <simhash>
Query for near‑duplicates
Code
BF.LSH.QUERY solidocto:lsh <simhash>
This returns a list of candidate simhashes within Hamming distance.



## Technical
Techology stack
- websocket backend - to protect the IP
- HTML front end
- separate back-end components to protect the IP
- fast-fail if the content is garbage 
- keeps logs of activity - rotate logs

### Layout
-- Root
   |
   | - config.yaml
   | - frontend
   |     | - index.hmtl
   |
   | - backend
   |     |- tests
   |        | - similarity
   |              | - similar.yaml
   |              | - similar.py
   |        | - garbage
   |        |     | - garbage.yaml
   |        |     | - garbage_tests.py
   |        | - AI
   |             | - ai.yaml
   |             | - ai_tests.py
   |        | - Human
   |        |    | - human.yaml
   |             | - human_tests.py
   |        | - construction
   |             | - construction.yaml
   |             | - construction_tests.py
   |     | - reporter
   |        | - report.yaml
   |        | - report_gen.py
   |     | - logging
            | - logs.yaml
            | - logs.db  
            | - log_reader.py
            | - logging_stats.py
         | - database
            | - redis
    | - testing
        | - testing.yaml
        | - run_tests.py



## UX

One‑Page UX Layout (Modern 2026 Style)
Design style: glassmorphism + soft gradients + anti‑grid layout (the modern stack we discussed).

Sections: Header

Logo: Solidocto

Tagline: “Know your text.”

Text Input Panel

Large paste box (auto‑expanding) - max 1023 char. No formatting, but unicode.

Character counter

“Analyse Text” button (submit)

Simple capture (checkbox or 3‑digit math challenge)

Results Panel

Three horizontal cards:

AI Indicators: 
Human Indicators: 
Unidentified Indicators:
* Note, results are fuzzed.
* Note, large number of garbage tests will cause the engine to skip human and AI tests

Novelely: Very similar text seen before (recycled some results), or Novel text (new results)

Radar chart.

Key indicators list

“Download JSON” button (optional)

Footer

Privacy note

Version number

## Frontend <> backend

The front-end calculates a simhash just to verify the return JSON is the same result.

### Request
{
  "text": "string",
    "captcha_token": "string (optional unless app.require_captcha=true)",
    "datetimeUTC" : "string",
    "simhash" : "string",
    "hp_website": "string (hidden honeypot; must stay empty)",
    "hp_company": "string (hidden honeypot; must stay empty)"
}

If honeypot fields are non-empty, the backend rejects the request as bot-like traffic.

### Response
{
  "ai_count": 0-999,
  "human_score": 0-999,
  "garbage_score": 0-999,
  "novel_text" : boolean,
  "simhash" : "string"
}

### 
