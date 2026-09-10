"""GenericTabularConnector: what it will read, and what it refuses to.

No test here opens a socket. URL cases drive a FakeSession and a fake DNS resolver, so the
security boundary is exercised without depending on the internet or on anyone's DNS.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

import pytest
import requests

from src.lakehouse.errors import LakehouseError
from src.lakehouse.generic._access import (
    AccessDeniedError,
    LocalFilePolicy,
    assert_url_is_allowed,
    read_local_file,
)
from src.lakehouse.generic.connector import GenericTabularConnector, _safe_locator
from src.lakehouse.storage.raw import RawStorage

from ._support import (
    FETCHED_AT,
    SYNTHETIC_CSV,
    FakeResponse,
    FakeSession,
    ingest,
    public_resolver,
    spec,
    write_bytes,
    write_csv,
    xlsx_bytes,
)


def _code(excinfo) -> str:
    return excinfo.value.payload.error_code


# ------------------------------------------------------------------ local files


def test_a_file_inside_an_allowed_root_is_read(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source = write_csv(uploads)

    connection, result = ingest(
        tmp_path, spec(str(source)), allowed_local_roots=[uploads]
    )
    try:
        assert result.asset.raw_path.read_bytes() == source.read_bytes()
        assert result.asset.locator.startswith("file://")
        assert result.asset.fetched_at == FETCHED_AT
    finally:
        connection.close()


def test_a_connector_without_roots_cannot_read_local_files(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source = write_csv(uploads)

    with pytest.raises(LakehouseError) as excinfo:
        ingest(tmp_path, spec(str(source)))
    assert _code(excinfo) == "ACCESS_DENIED"


def test_traversal_out_of_the_allowed_root_is_refused(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    write_csv(uploads)
    outside = write_csv(tmp_path, name="secret.csv")

    with pytest.raises(LakehouseError) as excinfo:
        ingest(
            tmp_path,
            spec(str(uploads / ".." / outside.name)),
            allowed_local_roots=[uploads],
        )
    assert _code(excinfo) == "ACCESS_DENIED"


def test_a_symlink_pointing_outside_the_root_is_refused(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    outside = write_csv(tmp_path, name="secret.csv")
    link = uploads / "innocent.csv"
    link.symlink_to(outside)

    with pytest.raises(LakehouseError) as excinfo:
        ingest(tmp_path, spec(str(link)), allowed_local_roots=[uploads])
    assert _code(excinfo) == "ACCESS_DENIED"


def test_a_sibling_directory_sharing_a_prefix_is_not_inside_the_root(tmp_path: Path) -> None:
    """`/data-evil` must not count as being inside `/data`."""

    allowed = tmp_path / "data"
    allowed.mkdir()
    evil = tmp_path / "data-evil"
    evil.mkdir()
    source = write_csv(evil)

    with pytest.raises(LakehouseError) as excinfo:
        ingest(tmp_path, spec(str(source)), allowed_local_roots=[allowed])
    assert _code(excinfo) == "ACCESS_DENIED"


def test_a_directory_is_not_a_file(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    (uploads / "nested").mkdir(parents=True)

    with pytest.raises(LakehouseError) as excinfo:
        ingest(tmp_path, spec(str(uploads / "nested")), allowed_local_roots=[uploads])
    assert _code(excinfo) == "ACCESS_DENIED"


def test_a_fifo_is_not_a_regular_file(tmp_path: Path) -> None:
    import os

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    pipe = uploads / "pipe.csv"
    os.mkfifo(pipe)

    policy = LocalFilePolicy((uploads,))
    with pytest.raises(AccessDeniedError, match="regular file"):
        read_local_file(pipe, policy)


def test_an_oversized_local_file_is_refused(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    write_bytes(uploads, "big.csv", b"a,b\n" + b"1,2\n" * 5000)

    with pytest.raises(LakehouseError) as excinfo:
        ingest(
            tmp_path,
            spec(str(uploads / "big.csv")),
            allowed_local_roots=[uploads],
            max_bytes=128,
        )
    assert _code(excinfo) == "ACCESS_DENIED"


def test_a_file_that_grows_between_the_stat_and_the_read_is_still_bounded(
    tmp_path: Path, monkeypatch
) -> None:
    """The size check before the read is a guard; the check on the bytes is the guarantee.

    A file can grow after ``stat`` says it is small. Here the first check is made to pass on
    an already-oversized file, so the second one -- on the bytes actually read -- is the only
    thing standing between the caller and an unbounded read. It holds.
    """

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source = write_bytes(uploads, "grow.csv", b"a,b\n" + b"1,2\n" * 100)
    policy = LocalFilePolicy((uploads,), max_bytes=8)

    monkeypatch.setattr(
        "src.lakehouse.generic._access.resolve_local_file",
        lambda path, _policy: Path(path),
    )
    with pytest.raises(AccessDeniedError, match="while being read"):
        read_local_file(source, policy)


def test_an_already_oversized_file_is_caught_before_the_read(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source = write_bytes(uploads, "big.csv", b"a,b\n" + b"1,2\n" * 100)
    policy = LocalFilePolicy((uploads,), max_bytes=8)

    with pytest.raises(AccessDeniedError, match="over the 8 byte limit"):
        read_local_file(source, policy)


def test_a_policy_without_roots_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        LocalFilePolicy(())


# -------------------------------------------------------------------------- URLs


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/data.csv",
        "http://127.0.0.1/data.csv",
        "https://[::1]/data.csv",
        "http://10.0.0.5/data.csv",
        "http://192.168.1.1/data.csv",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://224.0.0.1/data.csv",
        "http://something.localhost/data.csv",
        "http://box.internal/data.csv",
    ],
)
def test_dangerous_urls_are_refused(url: str) -> None:
    with pytest.raises(AccessDeniedError):
        assert_url_is_allowed(url)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/data.csv",
        "gopher://example.com/",
        "data:text/csv;base64,YQ==",
    ],
)
def test_only_http_and_https_are_fetched(url: str) -> None:
    with pytest.raises(AccessDeniedError, match="URLs are fetched"):
        assert_url_is_allowed(url)


def test_url_credentials_are_refused() -> None:
    with pytest.raises(AccessDeniedError, match="credentials"):
        assert_url_is_allowed("https://user:secret@example.com/data.csv")


def test_a_host_resolving_to_a_private_address_is_refused() -> None:
    def resolver(_host: str) -> list:
        return [ipaddress.ip_address("93.184.216.34"), ipaddress.ip_address("10.1.2.3")]

    with pytest.raises(AccessDeniedError, match="private"):
        assert_url_is_allowed("https://example.com/data.csv", resolver=resolver)


def test_an_ipv4_mapped_loopback_is_refused() -> None:
    def resolver(_host: str) -> list:
        return [ipaddress.ip_address("::ffff:127.0.0.1")]

    with pytest.raises(AccessDeniedError, match="loopback"):
        assert_url_is_allowed("https://example.com/data.csv", resolver=resolver)


def test_a_public_url_is_fetched_and_stored(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.lakehouse.generic.connector.assert_url_is_allowed", lambda url: None
    )
    session = FakeSession(
        [
            FakeResponse(
                content=SYNTHETIC_CSV.encode("utf-8"),
                headers={"Content-Type": "text/csv; charset=utf-8"},
            )
        ]
    )

    connection, result = ingest(
        tmp_path, spec("https://example.com/data/synthetic.csv"), session=session
    )
    try:
        assert result.asset.media_type == "text/csv"
        assert result.asset.http_status == 200
        assert result.asset.byte_size == len(SYNTHETIC_CSV.encode("utf-8"))
    finally:
        connection.close()


def test_a_redirect_target_is_validated_again(tmp_path: Path) -> None:
    """A public URL redirecting at the metadata service must not be followed."""

    session = FakeSession(
        [
            FakeResponse(
                status_code=302,
                headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            )
        ]
    )
    with pytest.raises(LakehouseError) as excinfo:
        ingest(
            tmp_path,
            spec("https://example.com/data.csv"),
            session=session,
            max_attempts=1,
        )
    assert _code(excinfo) == "ACCESS_DENIED"


def test_a_redirect_loop_is_bounded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.lakehouse.generic.connector.assert_url_is_allowed", lambda url: None
    )
    session = FakeSession(
        [
            FakeResponse(status_code=302, headers={"Location": "https://example.com/next"})
            for _ in range(10)
        ]
    )
    with pytest.raises(LakehouseError) as excinfo:
        ingest(
            tmp_path,
            spec("https://example.com/data.csv"),
            session=session,
            max_attempts=1,
            max_redirects=2,
        )
    assert _code(excinfo) == "ACCESS_DENIED"
    assert len(session.requests) == 3  # the original plus two hops


def test_an_oversized_streamed_response_is_abandoned(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.lakehouse.generic.connector.assert_url_is_allowed", lambda url: None
    )
    session = FakeSession(
        [FakeResponse(content=b"x" * 100_000, headers={"Content-Type": "text/csv"})]
    )
    with pytest.raises(LakehouseError) as excinfo:
        ingest(
            tmp_path,
            spec("https://example.com/big.csv"),
            session=session,
            max_attempts=1,
            max_bytes=1024,
        )
    assert _code(excinfo) == "ACCESS_DENIED"


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 422])
def test_client_errors_are_not_retried(tmp_path: Path, monkeypatch, status: int) -> None:
    monkeypatch.setattr(
        "src.lakehouse.generic.connector.assert_url_is_allowed", lambda url: None
    )
    session = FakeSession([FakeResponse(status_code=status) for _ in range(5)])
    with pytest.raises(LakehouseError) as excinfo:
        ingest(tmp_path, spec("https://example.com/x.csv"), session=session, max_attempts=3)
    assert _code(excinfo) == "HTTP_ERROR"
    assert len(session.requests) == 1


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_retryable_statuses_are_retried_and_then_give_up(
    tmp_path: Path, monkeypatch, status: int
) -> None:
    monkeypatch.setattr(
        "src.lakehouse.generic.connector.assert_url_is_allowed", lambda url: None
    )
    session = FakeSession([FakeResponse(status_code=status) for _ in range(5)])
    with pytest.raises(LakehouseError) as excinfo:
        ingest(
            tmp_path,
            spec("https://example.com/x.csv"),
            session=session,
            max_attempts=3,
            sleep=lambda _seconds: None,
        )
    assert _code(excinfo) == "HTTP_ERROR"
    assert len(session.requests) == 3


def test_a_timeout_is_retried_and_classified(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.lakehouse.generic.connector.assert_url_is_allowed", lambda url: None
    )
    session = FakeSession([requests.Timeout("slow") for _ in range(3)])
    with pytest.raises(LakehouseError) as excinfo:
        ingest(
            tmp_path,
            spec("https://example.com/x.csv"),
            session=session,
            max_attempts=2,
            sleep=lambda _seconds: None,
        )
    assert _code(excinfo) == "FETCH_TIMEOUT"
    assert len(session.requests) == 2


# ------------------------------------------------------------------- secrecy


def test_a_query_string_never_reaches_the_locator_or_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "src.lakehouse.generic.connector.assert_url_is_allowed", lambda url: None
    )
    session = FakeSession(
        [FakeResponse(content=SYNTHETIC_CSV.encode("utf-8"), headers={"Content-Type": "text/csv"})]
    )
    secret = "SUPER-SECRET-TOKEN-123"

    connection, result = ingest(
        tmp_path,
        spec(f"https://example.com/data.csv?api_key={secret}&x=1"),
        session=session,
    )
    try:
        assert secret not in result.asset.locator
        assert "<redacted>" in result.asset.locator
        assert secret not in repr(result.asset.metadata)

        stored = connection.execute(
            "SELECT locator, request_metadata_json FROM meta.artifact_request"
        ).fetchone()
        assert secret not in stored[0]
        assert secret not in stored[1]
    finally:
        connection.close()


def test_a_secret_in_the_spec_parameters_is_not_copied_into_metadata(
    tmp_path: Path,
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    write_csv(uploads)
    secret = "ANOTHER-SECRET-VALUE"

    with pytest.raises(LakehouseError) as excinfo:
        ingest(
            tmp_path,
            spec(str(uploads / "synthetic.csv"), parameters={"format": "csv", "auth_token": secret}),
            allowed_local_roots=[uploads],
        )
    assert secret not in str(excinfo.value)
    assert "unknown" in str(excinfo.value)


def test_an_http_error_message_never_quotes_the_body(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.lakehouse.generic.connector.assert_url_is_allowed", lambda url: None
    )
    session = FakeSession(
        [FakeResponse(status_code=403, content=b"token=LEAKED-SECRET expired")]
    )
    with pytest.raises(LakehouseError) as excinfo:
        ingest(tmp_path, spec("https://example.com/x.csv"), session=session, max_attempts=1)
    assert "LEAKED-SECRET" not in str(excinfo.value)
    assert "HTTP 403" in str(excinfo.value)


def test_safe_locator_strips_credentials_and_query() -> None:
    assert (
        _safe_locator("https://example.com:8443/a/b.csv?key=abc#frag")
        == "https://example.com:8443/a/b.csv?<redacted>"
    )


# ------------------------------------------------------------- format signals


def test_a_mislabelled_xlsx_is_caught_by_its_signature(tmp_path: Path) -> None:
    """Named .csv, served as text/csv, but the bytes are a workbook."""

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    write_bytes(uploads, "sneaky.csv", xlsx_bytes({"S1": [["a", "b"], [1, 2]]}))

    connection, result = ingest(
        tmp_path, spec(str(uploads / "sneaky.csv")), allowed_local_roots=[uploads]
    )
    try:
        assert result.asset.metadata["resolved_format"] == "xlsx"
        assert result.asset.media_type.endswith("spreadsheetml.sheet")
    finally:
        connection.close()


def test_an_explicit_format_contradicting_the_signature_is_refused(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    write_bytes(uploads, "book.xlsx", xlsx_bytes({"S1": [["a"], [1]]}))

    with pytest.raises(LakehouseError) as excinfo:
        ingest(
            tmp_path,
            spec(str(uploads / "book.xlsx"), parameters={"format": "csv"}),
            allowed_local_roots=[uploads],
        )
    assert _code(excinfo) == "UNSUPPORTED_FORMAT"
    assert "contradicts" in str(excinfo.value)


def test_extension_and_content_type_disagreement_is_refused(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "src.lakehouse.generic.connector.assert_url_is_allowed", lambda url: None
    )
    session = FakeSession(
        [FakeResponse(content=b"a,b\n1,2\n", headers={"Content-Type": "application/json"})]
    )
    with pytest.raises(LakehouseError) as excinfo:
        ingest(
            tmp_path,
            spec("https://example.com/data.csv"),
            session=session,
            max_attempts=1,
        )
    assert _code(excinfo) == "UNSUPPORTED_FORMAT"
    assert "disagree" in str(excinfo.value)


@pytest.mark.parametrize("name", ["report.pdf", "scan.png", "legacy.xls", "macro.xlsm"])
def test_unsupported_formats_are_refused_by_name_with_a_reason(
    tmp_path: Path, name: str
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    write_bytes(uploads, name, b"not really that format")

    with pytest.raises(LakehouseError) as excinfo:
        ingest(tmp_path, spec(str(uploads / name)), allowed_local_roots=[uploads])
    assert _code(excinfo) == "UNSUPPORTED_FORMAT"


def test_an_unknown_extension_without_content_type_is_refused(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    write_bytes(uploads, "mystery.dat", b"a,b\n1,2\n")

    with pytest.raises(LakehouseError) as excinfo:
        ingest(tmp_path, spec(str(uploads / "mystery.dat")), allowed_local_roots=[uploads])
    assert _code(excinfo) == "UNSUPPORTED_FORMAT"


def test_a_legacy_xls_signature_is_refused(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    write_bytes(uploads, "old.csv", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)

    with pytest.raises(LakehouseError) as excinfo:
        ingest(tmp_path, spec(str(uploads / "old.csv")), allowed_local_roots=[uploads])
    assert _code(excinfo) == "UNSUPPORTED_FORMAT"
    assert "OLE2" in str(excinfo.value) or ".xls" in str(excinfo.value)


def test_an_empty_source_is_refused(tmp_path: Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    write_bytes(uploads, "empty.csv", b"")

    with pytest.raises(LakehouseError) as excinfo:
        ingest(tmp_path, spec(str(uploads / "empty.csv")), allowed_local_roots=[uploads])
    assert _code(excinfo) == "EMPTY_DATASET"


def test_a_non_adhoc_source_id_is_refused(tmp_path: Path) -> None:
    from src.lakehouse.contracts.models import FetchSpec

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    source = write_csv(uploads)
    connector = GenericTabularConnector(
        RawStorage(tmp_path / "raw"), allowed_local_roots=[uploads]
    )
    with pytest.raises(LakehouseError) as excinfo:
        connector.fetch(
            FetchSpec(source_id="evds", dataset_id="evds_cpi", locator=str(source))
        )
    assert excinfo.value.payload.error_code == "UNSUPPORTED_FORMAT"
