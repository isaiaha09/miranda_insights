from __future__ import annotations

import logging
from typing import Iterable

import requests
from django.apps import apps
from django.utils import timezone


logger = logging.getLogger(__name__)

EXPO_PUSH_API_URL = "https://exp.host/--/api/v2/push/send"
EXPO_MAX_BATCH_SIZE = 100


def get_mobile_push_device_model():
	return apps.get_model("accounts", "MobilePushDevice")


def normalize_push_token(token: str) -> str:
	return str(token or "").strip()


def register_mobile_push_device(user, *, token: str, platform: str = "", device_name: str = "") -> MobilePushDevice:
	MobilePushDevice = get_mobile_push_device_model()
	normalized_token = normalize_push_token(token)
	if not normalized_token:
		raise ValueError("Push token is required.")

	normalized_platform = str(platform or "").strip().lower()
	valid_platforms = {
		MobilePushDevice.PLATFORM_IOS,
		MobilePushDevice.PLATFORM_ANDROID,
	}
	if normalized_platform not in valid_platforms:
		normalized_platform = MobilePushDevice.PLATFORM_UNKNOWN

	device, created = MobilePushDevice.objects.get_or_create(
		token=normalized_token,
		defaults={
			"user": user,
			"platform": normalized_platform,
			"device_name": str(device_name or "").strip(),
			"is_active": True,
			"last_registered_at": timezone.now(),
		},
	)
	if created:
		return device

	updated_fields = []
	if device.user_id != user.pk:
		device.user = user
		updated_fields.append("user")
	if device.platform != normalized_platform:
		device.platform = normalized_platform
		updated_fields.append("platform")
	normalized_device_name = str(device_name or "").strip()
	if normalized_device_name != device.device_name:
		device.device_name = normalized_device_name
		updated_fields.append("device_name")
	if not device.is_active:
		device.is_active = True
		updated_fields.append("is_active")
	device.last_registered_at = timezone.now()
	updated_fields.append("last_registered_at")
	device.save(update_fields=updated_fields + ["updated_at"])
	return device


def unregister_mobile_push_device(user, *, token: str) -> int:
	MobilePushDevice = get_mobile_push_device_model()
	normalized_token = normalize_push_token(token)
	if not normalized_token:
		return 0
	return MobilePushDevice.objects.filter(user=user, token=normalized_token, is_active=True).update(
		is_active=False,
		updated_at=timezone.now(),
	)


def deactivate_mobile_push_tokens(tokens: Iterable[str]) -> int:
	MobilePushDevice = get_mobile_push_device_model()
	normalized_tokens = [normalize_push_token(token) for token in tokens if normalize_push_token(token)]
	if not normalized_tokens:
		return 0
	return MobilePushDevice.objects.filter(token__in=normalized_tokens, is_active=True).update(
		is_active=False,
		updated_at=timezone.now(),
	)


def _chunked(values: list[dict], size: int) -> Iterable[list[dict]]:
	for index in range(0, len(values), size):
		yield values[index:index + size]


def send_mobile_push_notification_to_user(user, *, title: str, body: str, data: dict | None = None) -> int:
	if user is None:
		return 0
	MobilePushDevice = get_mobile_push_device_model()
	devices = list(user.mobile_push_devices.filter(is_active=True).only("token"))
	if not devices:
		return 0

	message_data = dict(data or {})
	message_payloads = [
		{
			"to": device.token,
			"title": str(title or "").strip()[:200],
			"body": str(body or "").strip()[:500],
			"sound": "default",
			"priority": "high",
			"channelId": "default",
			"data": message_data,
		}
		for device in devices
	]
	if not message_payloads:
		return 0

	delivered_count = 0
	invalid_tokens = []
	for payload_batch in _chunked(message_payloads, EXPO_MAX_BATCH_SIZE):
		try:
			response = requests.post(
				EXPO_PUSH_API_URL,
				json=payload_batch,
				headers={
					"Accept": "application/json",
					"Accept-encoding": "gzip, deflate",
					"Content-Type": "application/json",
				},
				timeout=10,
			)
			response.raise_for_status()
			response_payload = response.json()
		except Exception:
			logger.exception("Unable to deliver mobile push notification batch.")
			continue

		for message, result in zip(payload_batch, response_payload.get("data", [])):
			if result.get("status") == "ok":
				delivered_count += 1
				continue
			details = result.get("details") or {}
			if details.get("error") == "DeviceNotRegistered":
				invalid_tokens.append(message.get("to", ""))

	if invalid_tokens:
		deactivate_mobile_push_tokens(invalid_tokens)

	return delivered_count