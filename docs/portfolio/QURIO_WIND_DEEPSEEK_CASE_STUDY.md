# Qurio supplemental case — professional data integration

## The question

Can Qurio retain an authorized professional-market-data export with the correct
exchange-session semantics, run bounded research, and carry the same immutable dataset
through a Continue version without presenting the result as a live feed or an alpha claim?

This supplemental engineering proof uses an authorized Wind CSI300 export and DeepSeek.
It demonstrates a validated integration path. It does not demonstrate a direct Wind API
connection, real-time quotes, trading capability, or future returns.

## The retained boundary

| Item | Value |
|---|---|
| Dataset | Wind CSI300 `000300.SH · 1D` |
| Bars | 619 |
| Coverage | 2024-01-02 → 2026-07-24 |
| Calendar | `XSHG` regular sessions · `Asia/Shanghai` · 252 periods/year |
| Provider | DeepSeek |
| Model | `deepseek-v4-flash` |
| Research lineage | Root → Continue, retained as two History records |
| Experiments | 3 in Root; 2 in Continue |

The raw Wind CSV is not included in the repository. Qurio retains its SHA-256, the
normalized dataset digest, and the database record digest so the integration boundary
can be checked without redistributing the source data.

## What the integration proved

### 1. Exchange dates were not treated as a 24/7 clock

The import explicitly declared `XSHG`. Qurio parsed ISO `date` values as exchange
session labels, stored them as UTC-midnight canonical timestamps, and annualized the
daily series at 252 periods per year.

The dataset passed cadence validation with zero violations. The validator checks
weekday-consistent ordering but deliberately does not infer whether every exchange
holiday is complete.

### 2. One retained dataset powered both research versions

The Root and Continue runs retain the same:

- dataset ID;
- normalized dataset digest;
- `XSHG` calendar contract;
- DeepSeek provider/model identity;
- approved strategy-family scope.

Continue points to the Root run and a retained seed candidate. This is structured
Research Memory, not copied chat history.

### 3. Research Memory rejected exact duplicates

The Root run completed three experiments with no failed tool or provider-decision
events. During Continue, five exact duplicate proposals were rejected as
`RESEARCH_MEMORY_EXACT_DUPLICATE`; the run still completed with two retained experiments
and no provider-decision failure.

That result is included for transparency. It demonstrates that a new research version
cannot silently relabel an already-tested candidate as fresh evidence.

## Evidence integrity

The sanitized evidence is generated from the retained SQLite state in read-only mode and
cross-checks the raw export digest before writing:

- [Sanitized integration evidence](./evidence/qurio-wind-csi300-deepseek.json)
- Evidence file SHA-256:
  `32711e26c715f6cc4c76f4c1d4101179573ec1c6a87031e3ebcee190af6d679d`
- Raw export SHA-256:
  `99c6efb063e8668a0e043a3fd277725c7a58aa2042a4bd127a6ddd9ef8de1c1e`
- Dataset digest:
  `sha256:43c879662659d8e773b9a326b19df4fcf9f668c340ed5b992ec4e23c672e412e`
- Record digest:
  `sha256:f83fa58b534772271229254fdea4390bb6e8a483501713c7557fb76ba9722ada`

The evidence contains no credential, local path, workspace/user identifier, prompt,
raw bar array, or database content.

## What this case does not prove

- It is not a live or real-time Wind feed.
- It does not establish a direct Wind API or general multi-source product capability.
- It does not establish exchange-holiday completeness.
- It does not establish alpha, profitability, statistical significance, or an
  investment recommendation.
- It does not publish or redistribute the original Wind export.

The Kraken/DeepSeek case remains Qurio's canonical Agent reliability proof. This case is
the complementary proof that professional exported data can enter the same verifiable
research and lineage path with explicit market-calendar semantics.
