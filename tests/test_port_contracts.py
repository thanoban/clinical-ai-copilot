from __future__ import annotations

from aegis_dx.adapters import StubIngestionAdapter, StubTriageAdapter
from aegis_dx.audit import StoreAuditAdapter
from aegis_dx.composition import (
    ReflexiveSynthesisAdapter,
    StubReportAdapter,
    StubRetrievalAdapter,
    StubSynthesisAdapter,
)
from aegis_dx.ecg_specialists import StubECGSpecialistAdapter
from aegis_dx.identity import HeaderIdentityAdapter
from aegis_dx.specialists import StubChestXRaySpecialistAdapter
from aegis_dx.store import SQLiteCaseStore
from aegis_dx.trust import StubGuardrailAdapter, StubVerificationAdapter

from tests.contracts.audit_contract import assert_audit_port_contract
from tests.contracts.guardrail_contract import assert_guardrail_port_contract
from tests.contracts.ingestion_contract import assert_ingestion_port_contract
from tests.contracts.identity_contract import assert_identity_port_contract
from tests.contracts.report_contract import assert_report_port_contract
from tests.contracts.retrieval_contract import assert_retrieval_port_contract
from tests.contracts.specialist_contract import assert_specialist_port_contract
from tests.contracts.synthesis_contract import assert_synthesis_port_contract
from tests.contracts.triage_contract import assert_triage_port_contract
from tests.contracts.verification_contract import assert_verification_port_contract


def test_stub_ingestion_adapter_satisfies_contract() -> None:
    assert_ingestion_port_contract(StubIngestionAdapter())


def test_stub_triage_adapter_satisfies_contract() -> None:
    assert_triage_port_contract(StubTriageAdapter())


def test_stub_specialist_adapter_satisfies_contract() -> None:
    assert_specialist_port_contract(StubChestXRaySpecialistAdapter())


def test_stub_ecg_specialist_adapter_satisfies_contract() -> None:
    assert_specialist_port_contract(StubECGSpecialistAdapter())


def test_stub_retrieval_adapter_satisfies_contract() -> None:
    assert_retrieval_port_contract(StubRetrievalAdapter())


def test_stub_synthesis_adapter_satisfies_contract() -> None:
    assert_synthesis_port_contract(StubSynthesisAdapter())


def test_reflexive_synthesis_adapter_satisfies_contract() -> None:
    assert_synthesis_port_contract(ReflexiveSynthesisAdapter(StubSynthesisAdapter()))


def test_stub_report_adapter_satisfies_contract() -> None:
    assert_report_port_contract(StubReportAdapter())


def test_stub_verification_adapter_satisfies_contract() -> None:
    assert_verification_port_contract(StubVerificationAdapter())


def test_stub_guardrail_adapter_satisfies_contract() -> None:
    assert_guardrail_port_contract(StubGuardrailAdapter())


def test_header_identity_adapter_satisfies_contract() -> None:
    assert_identity_port_contract(HeaderIdentityAdapter())


def test_store_audit_adapter_satisfies_contract(tmp_path) -> None:
    store = SQLiteCaseStore(tmp_path / "aegis_dx_contracts.db")
    assert_audit_port_contract(StoreAuditAdapter(store))
