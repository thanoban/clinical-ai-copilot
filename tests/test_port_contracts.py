from __future__ import annotations

from aegis_dx.adapters import StubIngestionAdapter, StubTriageAdapter
from aegis_dx.composition import StubReportAdapter, StubRetrievalAdapter, StubSynthesisAdapter
from aegis_dx.specialists import StubChestXRaySpecialistAdapter
from aegis_dx.trust import StubGuardrailAdapter, StubVerificationAdapter

from tests.contracts.guardrail_contract import assert_guardrail_port_contract
from tests.contracts.ingestion_contract import assert_ingestion_port_contract
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


def test_stub_retrieval_adapter_satisfies_contract() -> None:
    assert_retrieval_port_contract(StubRetrievalAdapter())


def test_stub_synthesis_adapter_satisfies_contract() -> None:
    assert_synthesis_port_contract(StubSynthesisAdapter())


def test_stub_report_adapter_satisfies_contract() -> None:
    assert_report_port_contract(StubReportAdapter())


def test_stub_verification_adapter_satisfies_contract() -> None:
    assert_verification_port_contract(StubVerificationAdapter())


def test_stub_guardrail_adapter_satisfies_contract() -> None:
    assert_guardrail_port_contract(StubGuardrailAdapter())
