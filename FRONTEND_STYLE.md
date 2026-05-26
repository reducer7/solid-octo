# Solidocto Frontend Style‑Guide (Agent Edition)
**Version 1.0 — For automated UI modifications**

This guide defines the required conventions for all frontend code, components, layout, naming, and UX behaviour in Solidocto.  
Agents must follow these rules exactly when creating, modifying, or deleting frontend elements.

---

## 1. Layout & Structure

### 1.1 Page Layout
- Single‑column, centered layout.
- Maximum width: **720px**.
- All content must align to this column.
- Vertical spacing between major sections: **24px**.

### 1.2 Component Structure
All UI must be composed of the following component categories:

- `HeaderSection`
- `ConnectionStatus`
- `InputPanel`
- `ActionButtons`
- `ProgressPanel`
- `IndicatorRing1`
- `IndicatorRing2`
- `ResultSummary`
- `TechnicalDetails`
- `Footer`

Agents must not introduce new categories without explicit instruction.

---

## 2. Typography

### 2.1 Font
- Use a single sans‑serif font family (Inter, Roboto, or system default).
- Font sizes:
  - Title: **24px**
  - Section headers: **18px**
  - Body text: **14–16px**
  - Labels / metadata: **12–13px**

### 2.2 Text Rules
- No ALL CAPS except for badges.
- No italics unless quoting user input.
- Prefer short, scannable lines over long paragraphs.

---

## 3. Colour System

### 3.1 Core Palette
Agents must use only these semantic tokens:

- `--color-bg`
- `--color-surface`
- `--color-border`
- `--color-text-primary`
- `--color-text-secondary`
- `--color-accent-ai`
- `--color-accent-human`
- `--color-accent-other`
- `--color-warning`
- `--color-error`
- `--color-success`

### 3.2 Classification Colours
- AI → **#FF4D4D**
- HUMAN → **#4CAF50**
- OTHER → **#FFC107**

Agents must not invent new colours.

---

## 4. Interaction Rules

### 4.1 Buttons
- Primary action: filled button, accent colour.
- Secondary action: outlined button.
- Disabled state: 40% opacity, no hover effect.

### 4.2 Input Box
- Auto‑expands vertically.
- Shows live character + word count.
- Colour rules:
  - Under 200 chars → orange
  - Under 100 chars → red

### 4.3 Progress Panel
Each step must have one of four states:

- `pending`
- `running`
- `done`
- `error`

No additional states allowed.

---

## 5. Component Behaviour

### 5.1 ConnectionStatus
- Shows coloured dot + label:
  - Green: Connected
  - Red: Disconnected
- Includes a “Reconnect” button.

### 5.2 IndicatorRing1
- Default: grey outer ring, label “NO RESULT”.
- On result:
  - Animate ring to classification colour.
  - AI, Human, Other proportionally. Add percentages
  - Inner number is the the higher, Other, AI,  Hum , for example with the number

### 5.2 IndicatorRing2
- Default: grey outer ring, label “NO RESULT”.
- On result:
  - Animate ring to classification colour.
  - The is AI, Human ONLY. Add percentages of AI vs Human
  - Inner number is the the higher, AI , Hum , for example with the number
  - 

### 5.3 ResultSummary
Must include:
- Classification  
- Confidence score  
- 2–4 key signals  
- One explanatory sentence  

### 5.4 TechnicalDetails
A collapsible `<details>` block containing:
- SimHash  
- Token count  
- Perplexity  
- POS distribution  
- Flags  

Agents must not expose raw backend logs.

---

## 6. Naming Conventions

### 6.1 CSS / Tailwind
- Use semantic class names.
  - GOOD: `indicator-ring`
  - BAD: `big-red-circle`

### 6.2 IDs
- IDs must be **kebab‑case**.
  - Example: `result-summary-card`

### 6.3 JS Variables
- camelCase for variables  
- PascalCase for components  
- CONSTANT_CASE for constants  

---

## 7. Accessibility Requirements
- Minimum contrast ratio: **4.5:1**
- All interactive elements must have `aria-label`
- Keyboard shortcuts:
  - `Ctrl+Enter` → Analyze
  - `Esc` → Clear

---

## 8. Error Handling

### 8.1 Error Banner
- Red background  
- White text  
- Includes a retry button  

### 8.2 Input Validation
- Reject empty input  
- Reject input > 1023 chars  
- Show inline error message  

---

## 9. Forbidden Elements
Agents must NOT introduce:
- New colours  
- New fonts  
- New component categories  
- Animations longer than 300ms  
- Pop‑ups or modals  
- Tooltips that hide essential information  
- Backend‑specific logic in the frontend  

---

## 10. Change Protocol for Agents
When modifying the frontend, agents must:

1. Identify the component category affected.  
2. Apply changes only within that component.  
3. Preserve naming conventions.  
4. Preserve spacing, typography, and colour tokens.  
5. Validate accessibility rules.  
6. Output a diff‑style patch or full replacement block.  

---
IMPROVEMENTS 1:
# Solidocto Frontend Improvements (Agent‑Executable)

This document lists deterministic, atomic improvements agents can apply to the Solidocto frontend.  
Each item is written as a direct, unambiguous modification instruction.

---

## 1. Replace WebSocket URL Field with Connection Status

### Tasks
- Remove the `WEBSOCKET URL` input field.
- Add a `ConnectionStatus` component in the top‑right corner.
- Component must display:
  - Green dot + “Connected”
  - Red dot + “Disconnected”
- Add a small “Reconnect” button next to the status label.

---

## 2. Add Step‑by‑Step Progress Panel

### Tasks
- Insert a vertical progress list below the input panel.
- Include the following steps in this exact order:
- These correspond to the same tests (pass 1, pass 2, pass 3, pass 4... etc) being run in the background
  1. Similarity Checking
  2. Coherence Text
  3. Construction Verification  
  4. AI specific Tests  
  5. Human specific Tests 
- Each step must support the states:
  - `pending`
  - `running`
  - `done`
  - `error`
- Each step has a progress indicator


---

## 3. Upgrade Indicator Ring to Dynamic Version

### Tasks
- Replace static “NO RESULT” ring with a radial progress indicator.
- Animate the ring to the classification colour on result:
  - AI → blue  
  - HUMAN → orange  
  - OTHER → dark grey  
- Display larger % inside the ring

---

## 4. Improve Input Box UX

### Tasks
- Enable auto‑expanding textarea behaviour.
- Add a “Paste from clipboard” button.
- Add a “Sample text” dropdown with 3–4 predefined examples.
- Enhance character counter:
  - Normal: default colour  
  - Under 200 chars: orange  
  - Under 100 chars: red  

---

## 5. Add Result Summary Card

### Tasks
- Create a `ResultSummary` card displayed after analysis.
- Card must include:
  - Largest overall classification  
- Place this card directly below the indicator ring.

---

## 6. Add Collapsible Technical Details Section

### Tasks
- Add a `<details>` block titled “Technical Details”.
- Include:
  - SimHash  
  - Token count  
  - Raw Other score # this is the number, not the percentage 
  - Raw AI score  # this is the number, not the percentage 
  - Raw Human score  # this is the number, not the percentage
  - Admin Report # the json response object with the token break downs


---

## 7. Add Error‑State UX

### Tasks
- Add a red error banner for:
  - WebSocket disconnected  
  - Backend timeout  
  - Invalid input  
- Banner must include a retry button.
- Banner includes a ignore button
    - this clears the error unless the user attempts to reconnect and it fails again
- Add inline validation for:
  - Empty input  
  - Input > 1023 characters  (as specified by config at run time)

---

## 8. Optional Polish

### Tasks
- Add light/dark mode toggle using CSS variables.
- Add subtle animations:
  - Fade‑in for results  
  - Pulse animation during running tests  
  - Smooth ring transition  
- Add keyboard shortcuts:
  - `Ctrl+Enter` → Analyze  
  - `Esc` → Clear  

---

## 9. Component Mapping

### Tasks
Ensure all improvements map to existing component categories:

- `HeaderSection`
- `ConnectionStatus`
- `InputPanel`
- `ActionButtons`
- `ProgressPanel`
- `IndicatorRing1`
- `IndicatorRing2`
- `ResultSummary`
- `TechnicalDetails`
- `Footer`

No new categories may be introduced.

---

