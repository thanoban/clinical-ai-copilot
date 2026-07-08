from __future__ import annotations

from aegis_dx.adapters import StubIngestionAdapter, StubTriageAdapter
from aegis_dx.specialists import StubChestXRaySpecialistAdapter

from tests.contracts.ingestion_contract import assert_ingestion_port_contract
from tests.contracts.specialist_contract import assert_specialist_port_contract
from tests.contracts.triage_contract import assert_triage_port_contract


def test_stub_ingestion_adapter_satisfies_contract() -> None:
    assert_ingestion_port_contract(StubIngestionAdapter())


def test_stub_triage_adapter_satisfies_contract() -> None:
    assert_triage_port_contract(StubTriageAdapter())


def test_stub_specialist_adapter_satisfies_contract() -> None:
    assert_specialist_port_contract(StubChestXRaySpecialistAdapter())
