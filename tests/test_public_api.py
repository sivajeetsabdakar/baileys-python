from __future__ import annotations

import importlib.resources
import json
from pathlib import Path

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
    assert bpt.BusinessProfile
    assert bpt.CatalogResult
    assert bpt.Product
    assert bpt.MexError
    assert bpt.NewsletterMetadata
    assert bpt.HistorySyncResult
    assert bpt.HistoryChat
    assert bpt.HistoryContact
    assert bpt.LidPnMapping
    assert callable(bpt.process_history_sync)
    assert callable(bpt.get_history_sync_notification)
    assert bpt.MessageUpsert
    assert bpt.WAMessage
    assert bpt.QueryManager
    assert bpt.ReconnectPolicy
    assert bpt.ReceiptInfo
    assert bpt.RetryRequest
    assert bpt.RetryOutcome
    assert bpt.AppStateKeys
    assert bpt.AppStateCollectionSync
    assert bpt.AppliedAppStateSync
    assert bpt.DecodedAppStatePatch
    assert callable(bpt.extract_app_state_sync_data)
    assert callable(bpt.decode_syncd_patch)
    assert callable(bpt.apply_app_state_sync)
    assert bpt.MediaKeys
    assert bpt.MediaRetryEvent
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
    assert callable(bpt.business_profile_node)
    assert callable(bpt.parse_business_profile)
    assert callable(bpt.catalog_node)
    assert callable(bpt.group_get_invite_info_node)
    assert callable(bpt.group_toggle_ephemeral_node)
    assert callable(bpt.group_member_add_mode_node)
    assert callable(bpt.group_join_approval_mode_node)
    assert callable(bpt.cover_photo_update_node)
    assert callable(bpt.parse_catalog)
    assert callable(bpt.wmex_query_node)
    assert callable(bpt.parse_wmex_result)
    assert callable(bpt.newsletter_metadata_query)
    assert callable(bpt.parse_newsletter_metadata)
    assert callable(bpt.community_metadata_node)
    assert callable(bpt.community_create_node)
    assert callable(bpt.community_link_group_node)
    assert callable(bpt.parse_community_metadata)
    assert callable(bpt.get_message_reporting_token)
    assert callable(bpt.should_include_reporting_token)
    assert callable(bpt.build_tc_token_from_jid)
    assert callable(bpt.store_tc_tokens_from_iq_result)
    assert callable(bpt.load_wam_specs)
    assert hasattr(bpt.WhatsAppClient, "updateBusinessProfile")
    assert hasattr(bpt.WhatsAppClient, "getBusinessProfile")
    assert hasattr(bpt.WhatsAppClient, "updateCoverPhoto")
    assert hasattr(bpt.WhatsAppClient, "getCatalog")
    assert hasattr(bpt.WhatsAppClient, "productCreate")
    assert hasattr(bpt.WhatsAppClient, "executeWMexQuery")
    assert hasattr(bpt.WhatsAppClient, "newsletterMetadata")
    assert hasattr(bpt.WhatsAppClient, "newsletterUpdatePicture")
    assert hasattr(bpt.WhatsAppClient, "fetchStatus")
    assert hasattr(bpt.WhatsAppClient, "fetchDisappearingDuration")
    assert hasattr(bpt.WhatsAppClient, "communityMetadata")
    assert hasattr(bpt.WhatsAppClient, "communityAcceptInvite")
    assert hasattr(bpt.WhatsAppClient, "communityFetchLinkedGroups")
    assert hasattr(bpt.WhatsAppClient, "groupGetInviteInfo")
    assert hasattr(bpt.WhatsAppClient, "groupToggleEphemeral")
    assert hasattr(bpt.WhatsAppClient, "groupMemberAddMode")
    assert hasattr(bpt.WhatsAppClient, "groupJoinApprovalMode")
    assert hasattr(bpt.WhatsAppClient, "updateMessagesPrivacy")
    assert hasattr(bpt.WhatsAppClient, "updateCallPrivacy")
    assert hasattr(bpt.WhatsAppClient, "updateLastSeenPrivacy")
    assert hasattr(bpt.WhatsAppClient, "updateOnlinePrivacy")
    assert hasattr(bpt.WhatsAppClient, "updateProfilePicturePrivacy")
    assert hasattr(bpt.WhatsAppClient, "updateStatusPrivacy")
    assert hasattr(bpt.WhatsAppClient, "updateReadReceiptsPrivacy")
    assert hasattr(bpt.WhatsAppClient, "updateGroupsAddPrivacy")
    assert hasattr(bpt.WhatsAppClient, "rejectCall")
    assert hasattr(bpt.WhatsAppClient, "createCallLink")
    assert hasattr(bpt.WhatsAppClient, "addOrEditContact")
    assert hasattr(bpt.WhatsAppClient, "removeContact")
    assert hasattr(bpt.WhatsAppClient, "addOrEditQuickReply")
    assert hasattr(bpt.WhatsAppClient, "removeQuickReply")
    assert hasattr(bpt.WhatsAppClient, "addChatLabel")
    assert hasattr(bpt.WhatsAppClient, "sendReceipts")
    assert hasattr(bpt.WhatsAppClient, "presenceSubscribe")
    assert hasattr(bpt.WhatsAppClient, "cleanDirtyBits")
    assert hasattr(bpt.WhatsAppClient, "star")
    assert hasattr(bpt.WhatsAppClient, "updateDefaultDisappearingMode")
    assert hasattr(bpt.WhatsAppClient, "updateDisableLinkPreviewsPrivacy")
    assert hasattr(bpt.WhatsAppClient, "fetchNewChatMessageCap")
    assert hasattr(bpt.WhatsAppClient, "assertSessions")
    assert hasattr(bpt.WhatsAppClient, "executeUSyncQuery")
    assert hasattr(bpt.WhatsAppClient, "getBotListV2")
    assert hasattr(bpt.WhatsAppClient, "issuePrivacyTokens")
    assert hasattr(bpt.WhatsAppClient, "updateMemberLabel")
    assert hasattr(bpt.WhatsAppClient, "updateMediaMessage")
    assert hasattr(bpt.WhatsAppClient, "sendPeerDataOperationMessage")
    assert hasattr(bpt.WhatsAppClient, "resyncAppState")
    assert hasattr(bpt.WhatsAppClient, "refreshMediaConn")
    assert hasattr(bpt.WhatsAppClient, "getMediaHost")
    assert hasattr(bpt.WhatsAppClient, "waUploadToServer")
    assert hasattr(bpt.WhatsAppClient, "getUSyncDevices")
    assert hasattr(bpt.WhatsAppClient, "sendWAM")
    assert hasattr(bpt.WhatsAppClient, "sendWAMBuffer")


def test_client_defaults_and_package_data_are_importable(tmp_path):
    client = WhatsAppWebClient(tmp_path / "missing.json")

    assert client.websocket_url == WA_WEBSOCKET_URL
    assert client.origin == DEFAULT_ORIGIN
    assert client.use_routing_info is True
    assert importlib.resources.files("baileys.generated").joinpath("wabinary_tokens.json").is_file()


def test_public_api_parity_manifest_matches_client_surface():
    manifest = json.loads((Path(__file__).parent / "fixtures" / "public_api_parity.json").read_text(encoding="utf-8"))
    implemented = set(manifest["implemented_methods"])
    deferred = set(manifest["deferred_methods"])

    assert implemented
    assert not implemented & deferred
    missing = sorted(method for method in implemented if not hasattr(bpt.WhatsAppClient, method))
    assert missing == []
    assert all(manifest["deferred_methods"][method] for method in deferred)
