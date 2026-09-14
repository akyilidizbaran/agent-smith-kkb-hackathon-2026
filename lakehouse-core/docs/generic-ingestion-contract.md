# Generic Ingestion Contract

`GenericTabularConnector` and `GenericTabularParser` handle the data nobody wrote a connector
for: a file a user uploads, a URL a jury member reads out during the demo. Everything the
source-specific connectors know about their endpoint, this pair deliberately does not know
about anything.

The whole design follows one rule: **when a file can be read more than one way, refuse and
ask.** A failed parse costs a round trip. A silently wrong table costs the answer.

---

## 1. Boundaries

| Layer | Does | Never does |
|---|---|---|
| `GenericTabularConnector` | Proves the target is allowed, fetches exact bytes, stores them as an immutable RAW artifact, resolves the format | Parses, interprets a column, follows a link inside the content |
| `GenericTabularParser` | Reads the stored artifact, produces a Bronze frame of **strings** | Opens a socket, infers a type, parses a date or a number, guesses what a column means |
| `AdhocObservationMapping` | States which column is the date and which is the value, and how each is written | Carries a measure type, frequency, unit or aggregation rule |

`source_id` is fixed to **`adhoc`**. A single reserved namespace makes provenance structural:
a `series_id` starting `adhoc:` came from a file somebody handed us in a session, and
`adhoc.fact_observation` is the only fact table it can reach. Letting a caller choose the
source id here would let user-supplied data borrow a reviewed source's identity.

---

## 2. Supported formats

| Format | Read with | Ambiguity that must be resolved by the caller |
|---|---|---|
| CSV | stdlib `csv` | `delimiter` when more than one quote-aware parse is valid |
| TSV | stdlib `csv` | same, defaulting to tab |
| JSON | stdlib `json` | `records_field` when the object holds several candidate arrays |
| XLSX | `openpyxl` (`read_only`, `data_only=False`) | `sheet_name` when more than one sheet is visible |
| HTML | stdlib `html.parser` | `table_index` when the document holds more than one table |

**Refused, with a reason rather than a failure:** `.xls` (legacy OLE2), `.xlsm` and `.xlsb`
(macro-enabled), PDF and images. PDF and image extraction belong to the agent layer, which
hands this layer a CSV.

**Not supported and not attempted:** JavaScript-rendered pages. The connector stores the
bytes the server returned; if a page builds its table in the browser, those bytes contain no
table and the parse fails honestly.

### Format resolution

Four signals, in this precedence:

1. **File signature.** The only signal derived from the bytes, so it wins. A workbook served
   as `text/csv` and named `.csv` is still a workbook.
2. **Explicit `format` parameter**, checked against the signature first. Asking for CSV when
   the bytes are XLSX is a mistake worth surfacing.
3. **`Content-Type` and extension.** Consulted last, and only to name a text format.

When the extension and `Content-Type` disagree and no signature settles it, the blob is
**refused**. One of the two is wrong and this layer cannot tell which.

---

## 3. Local file boundary

There is no default root and no implicit "current directory". A connector built without
`allowed_local_roots` cannot read a local file at all.

| Check | What it stops |
|---|---|
| `resolve(strict=True)` before comparing | `..` traversal and symlinks, both gone by comparison time |
| Root match on resolved parents, not `startswith` | `/data-evil` counting as inside `/data` |
| Regular files only | Directories, devices, FIFOs, sockets. `/dev/zero` would fill the limit |
| Size check before the read | The obvious case, cheaply |
| **Size check again on the bytes read** | A file that grows between `stat` and `read` |

The second size check is the guarantee; the first is a courtesy. One extra byte is requested
deliberately, so growth is detected rather than silently truncated.

**On `.env`, SSH keys and Git credentials.** There is no filename blacklist, on purpose: a
blacklist is a list of the secrets somebody already thought of. The boundary is the root
allow-list. If `~/.ssh` is not an allowed root, `id_rsa` is unreachable whatever it is called;
if somebody makes `$HOME` an allowed root, no blacklist would save them. The operator's job is
to point the roots at an upload directory.

---

## 4. URL boundary

| Rule | Reason |
|---|---|
| `http` and `https` only | `file://` would bypass the local allow-list entirely |
| No `user:password@host` | Credentials would land in the stored locator and in logs |
| Blocked: loopback, private, link-local, multicast, reserved, unspecified, site-local, IPv4-mapped equivalents | The connector must not become a way to read its own host |
| Blocked by name: `localhost`, `*.localhost`, `*.local`, `*.internal`, known cloud metadata hosts | Split-horizon resolvers can make a metadata endpoint look ordinary |
| **Every** resolved address is checked | A name with one public and one loopback record would otherwise pass on the public one |
| Redirects followed manually, **each hop re-validated**, capped | "Public URL redirects to 169.254.169.254" is the attack this exists for |
| Body read in chunks, abandoned the moment it exceeds the limit | An unbounded body never reaches memory |
| Retries only on timeout, connection error, 408, 429 and 5xx | A 403 will still be a 403 |
| Error messages quote the status, never the body | An error page can echo the request, including its secrets |
| Query string dropped from the stored locator | An API key or signed-URL token lives there |

### Known limitation, stated plainly

**DNS rebinding is not prevented.** The address check happens in this code; the HTTP client
then does its own resolution. A resolver that answers with a public address for the check and
a private one for the connection would defeat it. Closing that requires pinning the connection
to the validated address, which this version does not do. Redirect hops *are* re-validated, so
the common redirect-to-metadata case is covered; the residual risk is a hostile or compromised
resolver.

Do not describe this boundary as SSRF-proof. It raises the cost of the common attacks and says
so; it is not a substitute for network egress rules.

---

## 5. Parser policy

### Everything is a string

The Bronze frame is `dtype=object` throughout. `0012` keeps its leading zeros, `1,5` stays
`1,5`, and a date stays whatever the source wrote. Type inference here would be a guess made
in the wrong place; the mapping is where a human states the reading.

### Headers

A blank or duplicate column name is **refused**, not repaired. `pandas` would silently rename
them to `Unnamed: 3` and `deger.1`, and a mapping written against the original names would
then refer to columns that no longer exist.

### Limits

| Limit | Value |
|---|---|
| Rows | 1,000,000 |
| Columns | 4,096 |
| Cell length | 32,768 characters |
| XLSX uncompressed total | 512 MiB, read from the zip directory before any entry is opened |
| HTML tables per document | 200 |

### Per-format ambiguity

**CSV/TSV.** Candidate delimiters `, ; \t |` are checked with strict `csv.reader`
parses, so quoted commas and multiline fields do not skew detection. More than one valid
candidate always requires an explicit `delimiter`; a TSV with no candidate defaults to tab.
Ragged rows retain the existing source warning. With `encoding="auto"`, decoders are tried
in order: `utf-8-sig`, `utf-8`, `cp1254`, `latin-1`. A non-UTF-8 fallback raises a warning.
Explicit encoding is restricted to those four names, recorded in provenance and applied
strictly without fallback. A CSV cell beginning `=` remains inert text.

**JSON.** A top-level array of objects, or exactly one array-of-objects field, is read.
Several candidates require `records_field`. Heterogeneous records and nested values are
refused: flattening would invent column names the source never published.

**XLSX.** Identification inspects ZIP directory entry names, without extracting or
expanding entries; both `xl/workbook.xml` and `[Content_Types].xml` must exist. Duplicate
entry names and VBA payloads are refused. The parser checks the uncompressed byte ceiling,
then opens `read_only=True`, `data_only=False`, `keep_links=False`. A formula anywhere in
the workbook (including headers and hidden/unselected sheets, with or without cached
values) rejects the entire workbook with guidance to calculate externally and export
values-only XLSX or CSV. No formula is evaluated. One visible sheet is selected automatically;
more than one requires `sheet_name`. Hidden sheets can be selected explicitly with a warning.

**HTML.** Parsed with the standard library's `html.parser` rather than lxml or
BeautifulSoup — one fewer dependency, and more importantly a small enough implementation to
state what it does not do. `<script>` and `<style>` content is discarded, so a table inside a
script string is never seen. There is no URL handling in the module at all, so `<img>`,
`<link>` and `<iframe>` are inert by construction rather than by policy. `rowspan` and
`colspan` are expanded into a rectangular grid. Cells over 32,768 characters are refused;
no cell is silently clipped.

### Warnings

Parser warnings flow into the existing observability path unchanged: `meta.ingest_warning`
stores them verbatim and the run closes as `warning`. They also raise the published
`quality_flag` to `source_warning`.

---

## 6. API

```python
GenericTabularConnector(
    storage,
    *,
    allowed_local_roots=None,   # required for any local read
    session=None,
    max_bytes=67_108_864,
    max_redirects=3,
    max_attempts=3,
    backoff_seconds=0.5,
    sleep=time.sleep,
    clock=<utc now>,            # validated at construction; read again after download
)

GenericTabularParser(*, schema_version="adhoc_tabular.v1")
```

All choices must be provided in `FetchSpec.parameters` before fetching. The parser has no
constructor selection override. `generic/config.py` owns the single canonical allow-list:

| Format | Parameters in addition to optional `format` |
|---|---|
| CSV/TSV | `delimiter` (comma, semicolon, tab, pipe), `encoding` |
| JSON | `records_field`, `encoding` |
| XLSX | `sheet_name` |
| HTML | `table_index` (non-negative integer), `encoding` |

Unknown or format-inapplicable parameters are rejected without echoing values, including
credential-shaped parameters. Defaults are explicit in the canonical configuration:
`encoding="auto"` and selection fields `None`. The resolved format is included. Canonical
sorted JSON and its SHA-256 are stored as `parser_config` and `parser_config_sha256` in
artifact metadata and `meta.artifact_request` provenance. Different configurations for one
RAW digest create separate request records and separate Bronze representations.

`ParsedBatch` and `ParquetIdentity` carry an additive `parser_config_sha256`. Generic Bronze
paths include `parser_config_sha256=<digest>` and Parquet embeds the same identity component.
Existing source-specific/Silver paths and metadata remain unchanged when the field is absent.
Publication requires the asset configuration, batch hash and durable identity to agree.
Old Generic Bronze files without configuration provenance must be ingested again.

Every run also records which artifacts it fetched. Right after `ArtifactRepository.register`
and before parsing, `IngestionPipeline` writes a `meta.run_artifact` row
(`run_id`, `artifact_sha256`, `source_id`, `dataset_id`, `fetched_at`, `parser_config_sha256`)
through `RunRepository.link_artifact`. The row survives a later parse or Bronze failure while
the run closes as `failed`; re-linking the same pair with identical facts is a no-op and with
different facts is refused. Curated sources without a parser configuration link with a NULL
digest and their results are otherwise unchanged. Ad-hoc publication requires this link and
takes `fetched_at` from it; see `docs/adhoc-publication-contract.md`.

Constructor checks require `max_bytes > 0`, finite `backoff_seconds >= 0`, a timezone-aware
clock (including a non-None UTC offset), and existing directories as allowed local roots.
Every received HTTP response is closed in `finally`, including redirects and stream failures.

Errors use the shared `LakehouseError` vocabulary. `ACCESS_DENIED` was added for policy
refusals — the target was reachable and well-formed but reading it is not allowed — because an
agent must be able to tell "I am not allowed" from `SOURCE_UNAVAILABLE`'s "it is down".
