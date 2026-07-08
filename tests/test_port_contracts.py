from __future__ import annotations

from aegis_dx.adapters import StubIngestionAdapter, StubTriageAdapter
from aegis_dx.composition import StubReportAdapter, StubRetrievalAdapter, StubSynthesisAdapter
from aegis_dx.specialists import StubChestXRaySpecialistAdapter

from tests.contracts.ingestion_contract import assert_ingestion_port_contract
from tests.contracts.report_contract import assert_report_port_contract
from tests.contracts.retrieval_contract import assert_retrieval_port_contract
from tests.contracts.specialist_contract import assert_specialist_port_contract
from tests.contracts.synthesis_contract import assert_synthesis_port_contract
from tests.contracts.triage_contract import assert_triage_port_contract


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
