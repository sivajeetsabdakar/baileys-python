from __future__ import annotations

import importlib.resources

import baileys as bpt
from baileys.client import DEFAULT_ORIGIN, WA_WEBSOCKET_URL, WhatsAppWebClient
from baileys.wabinary import BinaryNode


def test_public_api_exports_core_building_blocks():
    assert bpt.BinaryNode is BinaryNode
    assert bpt.WhatsAppWebClient is WhatsAppWebClient
    assert callable(bpt.build_text_message_node)
    assert callable(bpt.hkdf)
    assert callable(bpt.derive_media_keys)
    assert callable(bpt.expand_app_state_keys)
    assert callable(bpt.derive_pairing_code_key)
    assert callable(bpt.decompress_if_required)
    assert callable(bpt.areJidsSameUser)
    assert callable(bpt.transferDevice)
    assert callable(bpt.isJidMetaAI)
    assert callable(bpt.isHostedPnUser)
    assert callable(bpt.generate_pairing_code)
    assert callable(bpt.pairing_code_hello_node)
    assert callable(bpt.make_socket)
    assert callable(bpt.makeWASocket)
    assert callable(bpt.build_pairing_qr_data)
    assert callable(bpt.configure_successful_pairing)
    assert callable(bpt.pairing_code_request_node)
    assert bpt.QRPairingRequest
    assert bpt.WhatsAppClient
    assert bpt.EventEmitter
    assert bpt.DisconnectError
    assert bpt.DisconnectReason.loggedOut == 401
    assert bpt.NotificationInfo
    assert bpt.DirtyInfo
    assert bpt.OfflineInfo
    assert bpt.CallInfo
    assert bpt.MessageUpsert
    assert bpt.WAMessage
    assert bpt.QueryManager
    assert bpt.ReconnectPolicy
    assert bpt.ReceiptInfo
    assert bpt.RetryRequest
    assert bpt.RetryOutcome
    assert bpt.AppStateKeys
    assert bpt.MediaKeys
    assert bpt.PreKeyNodeResult
    assert bpt.PreKeyMaintenanceResult
    assert bpt.SignedPreKeyRotation
    assert hasattr(bpt.WhatsAppClient, "connectAndWait")
    assert hasattr(bpt.WhatsAppClient, "reconnect")
    assert hasattr(bpt.WhatsAppClient, "finalizePairSuccess")
    assert hasattr(bpt.WhatsAppClient, "connectForQRPairing")
    assert hasattr(bpt.WhatsAppClient, "digestKeyBundle")
    assert hasattr(bpt.WhatsAppClient, "countPreKeys")
    assert hasattr(bpt.WhatsAppClient, "uploadPreKeys")
    assert hasattr(bpt.WhatsAppClient, "maintainPreKeys")
    assert hasattr(bpt.WhatsAppClient, "rotateSignedPreKey")
    assert hasattr(bpt.WhatsAppClient, "logout")
    assert hasattr(bpt.WhatsAppClient, "ReconnectPolicy")
    assert hasattr(bpt.WhatsAppClient, "resendMessageForRetry")
    assert callable(bpt.parse_receipt_info)
    assert callable(bpt.parse_retry_request)
    assert callable(bpt.receipt_status_from_type)
    assert callable(bpt.parse_notification_info)
    assert callable(bpt.parse_dirty_info)
    assert callable(bpt.parse_offline_info)
    assert callable(bpt.parse_call_info)


def test_client_defaults_and_package_data_are_importable(tmp_path):
    client = WhatsAppWebClient(tmp_path / "missing.json")

    assert client.websocket_url == WA_WEBSOCKET_URL
    assert client.origin == DEFAULT_ORIGIN
    assert client.use_routing_info is True
    assert importlib.resources.files("baileys.generated").joinpath("wabinary_tokens.json").is_file()
