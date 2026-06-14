from __future__ import annotations

import importlib.resources

import baileys as bpt
from baileys.client import DEFAULT_ORIGIN, WA_WEBSOCKET_URL, WhatsAppWebClient
from baileys.wabinary import BinaryNode


def test_public_api_exports_core_building_blocks():
    assert bpt.BinaryNode is BinaryNode
    assert bpt.WhatsAppWebClient is WhatsAppWebClient
    assert callable(bpt.build_text_message_node)
    assert callable(bpt.generate_pairing_code)
    assert callable(bpt.pairing_code_hello_node)


def test_client_defaults_and_package_data_are_importable(tmp_path):
    client = WhatsAppWebClient(tmp_path / "missing.json")

    assert client.websocket_url == WA_WEBSOCKET_URL
    assert client.origin == DEFAULT_ORIGIN
    assert client.use_routing_info is True
    assert importlib.resources.files("baileys.generated").joinpath("wabinary_tokens.json").is_file()
