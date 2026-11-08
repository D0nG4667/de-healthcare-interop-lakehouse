# Rule 04: Test-Driven Development (TDD), 100% Coverage & Strict Typing

## Scope
Applies to all Python files in `src/` and `tests/`.

## Engineering Discipline

1. **Red-Green-Refactor Cycle:**
   - Always write or update unit tests in `tests/unit/` before implementing or modifying production modules in `src/healthcare_lakehouse/`.
   - Run `uv run pytest` to observe the expected failure (`RED`), implement minimal clean code (`GREEN`), and refactor for clarity (`REFACTOR`).

2. **100% Line & Branch Coverage Requirement:**
   - The test suite is configured with `fail_under = 100` in `pyproject.toml`.
   - Test both happy paths and edge/error cases:
     - Malformed HL7 v2 segments, missing `MSH`/`PID` headers, repeating fields (`~`), component delimiters (`^`).
     - FHIR R4 JSON and XML parsing, invalid resource types, missing identifiers.
     - HIPAA Safe Harbor edge cases: patients aged `89` vs `90` vs `104`, restricted vs non-restricted 3-digit ZIP codes, leap-year date shifts, KMS key rotation from `v1` to `v2`, and intentional PII leak detection by `HIPAAComplianceAuditor`.
     - Clinical deterioration scoring across all **NEWS2** physiological bands (`0`, `1`, `2`, `3`, supplemental oxygen, hypercapnic/SpO2 scales, consciousness `A` vs `C/V/P/U`) and **qSOFA** thresholds.

3. **Strict Static Typing (`mypy --strict`):**
   - Every function and method signature must declare parameter types and return types.
   - Prefer `pydantic.BaseModel` with `ConfigDict(frozen=True, extra="forbid")` or `dataclass(frozen=True, slots=True)` for value objects.
   - Avoid `Any` unless interfacing with untyped external JSON dicts, in which case narrow types immediately with `isinstance` guards or Pydantic validators.
